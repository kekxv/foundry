use anyhow::{Context as _, Result, ensure};
use foundry_core::{Manifest, checked_path, validate_value};
use rquickjs::{
    Context, Ctx, Error, Function, Module, Promise, Runtime, Value as JsValue,
    loader::{Loader, Resolver},
    module::Declared,
};
use serde_json::Value;
use std::{
    collections::BTreeSet,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

#[derive(Clone, Copy)]
pub struct RuntimeLimits {
    pub memory: usize,
    pub stack: usize,
    pub timeout: Duration,
}
impl Default for RuntimeLimits {
    fn default() -> Self {
        Self {
            memory: 64 * 1024 * 1024,
            stack: 1024 * 1024,
            timeout: Duration::from_secs(30),
        }
    }
}
pub type HostBridge = Box<dyn Fn(Value, Duration) -> Result<Value>>;
struct PackageResolver;
impl Resolver for PackageResolver {
    fn resolve<'js>(
        &mut self,
        _ctx: &Ctx<'js>,
        base: &str,
        name: &str,
    ) -> rquickjs::Result<String> {
        if !name.starts_with("./") && !name.starts_with("../") {
            return Err(Error::new_resolving(base, name));
        }
        let mut parts: Vec<&str> = base.split('/').collect();
        parts.pop();
        for p in name.split('/') {
            match p {
                "." => {}
                ".." => {
                    if parts.pop().is_none() {
                        return Err(Error::new_resolving(base, name));
                    }
                }
                "" => return Err(Error::new_resolving(base, name)),
                x => parts.push(x),
            }
        }
        let path = parts.join("/");
        foundry_core::validate_path(&path).map_err(|_| Error::new_resolving(base, name))?;
        Ok(path)
    }
}
struct PackageLoader(PathBuf);
impl Loader for PackageLoader {
    fn load<'js>(&mut self, ctx: &Ctx<'js>, name: &str) -> rquickjs::Result<Module<'js, Declared>> {
        let p = checked_path(&self.0, name).map_err(|_| Error::new_loading(name))?;
        let meta = std::fs::metadata(&p).map_err(|_| Error::new_loading(name))?;
        if !meta.is_file() || meta.len() > 1024 * 1024 {
            return Err(Error::new_loading(name));
        }
        let bytes = std::fs::read(p).map_err(|_| Error::new_loading(name))?;
        Module::declare(ctx.clone(), name, bytes)
    }
}
fn js_error(ctx: &Ctx<'_>, e: Error) -> anyhow::Error {
    if matches!(e, Error::Exception) {
        let v = ctx.catch();
        anyhow::anyhow!("JavaScript exception: {v:?}")
    } else {
        anyhow::anyhow!("QuickJS: {e}")
    }
}
fn await_promise<'js>(ctx: &Ctx<'js>, p: Promise<'js>, deadline: Instant) -> Result<JsValue<'js>> {
    loop {
        ensure!(Instant::now() < deadline, "extension timed out");
        if let Some(v) = p.result::<JsValue>() {
            return v.map_err(|e| js_error(ctx, e));
        }
        if !ctx.execute_pending_job() {
            std::thread::sleep(Duration::from_millis(1));
        }
    }
}
pub fn run_extension(
    root: &Path,
    m: &Manifest,
    capability: &str,
    input: Value,
    limits: RuntimeLimits,
    grants: &BTreeSet<String>,
    bridge: Option<HostBridge>,
) -> Result<Value> {
    let cap = m
        .capabilities
        .get(capability)
        .context("unknown capability")?;
    validate_value(&cap.input, &input)?;
    let input_bytes = serde_json::to_vec(&input)?;
    ensure!(input_bytes.len() <= 1024 * 1024, "input too large");
    let deadline = Instant::now() + limits.timeout;
    let rt = Runtime::new().map_err(|e| anyhow::anyhow!("{e}"))?;
    rt.set_memory_limit(limits.memory);
    rt.set_max_stack_size(limits.stack);
    rt.set_interrupt_handler(Some(Box::new(move || Instant::now() >= deadline)));
    rt.set_loader(PackageResolver, PackageLoader(root.canonicalize()?));
    let ctx = Context::full(&rt).map_err(|e| anyhow::anyhow!("{e}"))?;
    let allowed: BTreeSet<_> = m
        .permissions
        .iter()
        .filter(|p| grants.contains(*p))
        .cloned()
        .collect();
    let out=ctx.with(|ctx|->Result<Value>{
  let bridge_fn=Function::new(ctx.clone(),move|request:String|->String{
   let response=(||->Result<Value>{ensure!(request.len()<=1024*1024,"host request too large");let v:Value=serde_json::from_str(&request)?;
    let permission=match v["op"].as_str(){Some("exec")=>"process.spawn",Some("ffi")=>"native.call",Some("readText")=>"filesystem.read",Some("writeText")=>"filesystem.write",_=>anyhow::bail!("unknown host operation")};
    ensure!(allowed.contains(permission),"permission denied: {permission}");let remaining=deadline.saturating_duration_since(Instant::now());ensure!(!remaining.is_zero(),"extension timed out");bridge.as_ref().context("host bridge unavailable")?(v,remaining)
   })();
   match response{Ok(v)=>serde_json::json!({"ok":true,"value":v}).to_string(),Err(e)=>serde_json::json!({"ok":false,"error":e.to_string()}).to_string()}
  }).map_err(|e|js_error(&ctx,e))?;
  ctx.globals().set("__foundryBridge",bridge_fn).map_err(|e|js_error(&ctx,e))?;
  ctx.eval::<(),_>(r#"(()=>{const bridge=globalThis.__foundryBridge;delete globalThis.__foundryBridge;
   const parse=JSON.parse,stringify=JSON.stringify,freeze=Object.freeze;
   function call(request){const r=parse(bridge(stringify(request)));if(!r.ok)throw new Error(r.error);return r.value;}
   Object.defineProperty(globalThis,'host',{value:freeze({
    exec:async(id,args,options={})=>call({op:'exec',id,args,options}),
    library:(id)=>freeze({call:async(symbol,args)=>call({op:'ffi',id,symbol,args})}),
    fs:freeze({readText:async(path)=>call({op:'readText',path}),writeText:async(path,text)=>call({op:'writeText',path,text})})
   }),writable:false,configurable:false});})()"#).map_err(|e|js_error(&ctx,e))?;
  // Capture builtins before untrusted module code can replace global JSON functions.
  let serialize:Function=ctx.eval(r#"(()=>{
   const stringify=JSON.stringify,finite=Number.isFinite,keys=Object.keys,isArray=Array.isArray;
   const descriptor=Object.getOwnPropertyDescriptor,prototype=Object.getPrototypeOf,create=Object.create;
   const objectPrototype=Object.prototype,arrayPrototype=Array.prototype,setPrototype=Object.setPrototypeOf,string=String;
   return function(value){const ancestors=[];
    function copy(v){if(v===null)return null;const t=typeof v;
     if(t==='number'){if(!finite(v))throw new Error('non-finite JSON number');return v;}
     if(t==='string'||t==='boolean')return v;
     if(t!=='object')throw new Error('not JSON');
     for(let i=0;i<ancestors.length;i++)if(ancestors[i]===v)throw new Error('cyclic JSON');
     const array=isArray(v),proto=prototype(v);
     if(proto!==(array?arrayPrototype:objectPrototype)&&proto!==null)throw new Error('not a plain JSON object');
     ancestors[ancestors.length]=v;const out=array?setPrototype([],null):create(null);
     if(array){const n=v.length;for(let i=0;i<n;i++){const d=descriptor(v,string(i));if(!d||!('value' in d))throw new Error('sparse/accessor array');out[i]=copy(d.value);}}
     else {const names=keys(v);for(let i=0;i<names.length;i++){const k=names[i],d=descriptor(v,k);if(!d||!('value' in d))throw new Error('JSON accessors forbidden');out[k]=copy(d.value);}}
     ancestors.length--;return out;
    }
    return stringify(copy(value));
   };
  })()"#).map_err(|e|js_error(&ctx,e))?;
  let entry=checked_path(root,&m.entry)?;ensure!(entry.metadata()?.is_file()&&entry.metadata()?.len()<=1024*1024,"module must be a regular file at most 1 MiB");
  let module=Module::declare(ctx.clone(),m.entry.clone(),std::fs::read(entry)?).map_err(|e|js_error(&ctx,e))?;
  let (module,p)=module.eval().map_err(|e|js_error(&ctx,e))?;await_promise(&ctx,p,deadline)?;
  let f:Function=module.get(cap.export.as_str()).map_err(|e|js_error(&ctx,e))?;let argument=ctx.json_parse(input_bytes).map_err(|e|js_error(&ctx,e))?;
  let mut result:JsValue=f.call((argument,)).map_err(|e|js_error(&ctx,e))?;
  if let Some(p)=result.as_promise(){result=await_promise(&ctx,p.clone(),deadline)?;}
  let serialized:String=serialize.call((result,)).map_err(|e|js_error(&ctx,e))?;ensure!(serialized.len()<=1024*1024,"output too large");let output=serde_json::from_str(&serialized)?;validate_value(&cap.output,&output)?;Ok(output)
 })?;
    Ok(out)
}
