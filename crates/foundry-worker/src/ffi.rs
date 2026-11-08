use anyhow::{Context, Result, ensure};
use foundry_core::{Manifest, Symbol, checked_path, platform};
use libffi::middle::{Arg, Cif, CodePtr, Type};
use serde_json::{Value, json};
use std::{
    ffi::{CString, c_void},
    path::Path,
};
pub fn validate_ffi<'a>(
    m: &'a Manifest,
    lib: &str,
    symbol: &str,
    args: &Value,
) -> Result<&'a Symbol> {
    let s = m
        .libraries
        .get(lib)
        .context("undeclared library")?
        .symbols
        .get(symbol)
        .context("undeclared symbol")?;
    let a = args.as_array().context("FFI arguments must be array")?;
    ensure!(a.len() == s.parameters.len(), "wrong FFI argument count");
    for (t, v) in s.parameters.iter().zip(a) {
        match t.as_str() {
            "i32" => {
                ensure!(
                    v.as_i64().and_then(|n| i32::try_from(n).ok()).is_some(),
                    "i32 out of range"
                );
            }
            "u32" => {
                ensure!(
                    v.as_u64().and_then(|n| u32::try_from(n).ok()).is_some(),
                    "u32 out of range"
                );
            }
            "f64" => {
                ensure!(v.as_f64().is_some_and(f64::is_finite), "invalid f64");
            }
            "cstring" => {
                let s = v.as_str().context("cstring must be string")?;
                ensure!(
                    s.len() <= 1024 * 1024 && !s.contains('\0'),
                    "invalid cstring"
                );
            }
            "buffer" => {
                let b = v.as_array().context("buffer must be byte array")?;
                ensure!(
                    b.len() <= 1024 * 1024
                        && b.iter().all(|n| n.as_u64().is_some_and(|n| n <= 255)),
                    "invalid byte buffer"
                );
            }
            _ => anyhow::bail!("unsupported FFI type"),
        }
    }
    Ok(s)
}
enum Stored {
    I32(i32),
    U32(u32),
    F64(f64),
    Pointer(*const c_void),
    Size(usize),
}
impl Stored {
    fn arg(&self) -> Arg {
        match self {
            Self::I32(v) => Arg::new(v),
            Self::U32(v) => Arg::new(v),
            Self::F64(v) => Arg::new(v),
            Self::Pointer(v) => Arg::new(v),
            Self::Size(v) => Arg::new(v),
        }
    }
}
pub fn call_ffi(root: &Path, m: &Manifest, id: &str, symbol: &str, args: &Value) -> Result<Value> {
    let s = validate_ffi(m, id, symbol, args)?;
    let l = &m.libraries[id];
    let p = checked_path(
        root,
        l.paths
            .get(&platform())
            .context("library not available on this platform")?,
    )?;
    let mut stored = Vec::new();
    let mut types = Vec::new();
    let mut strings = Vec::new();
    let mut buffers = Vec::new();
    for (t, v) in s.parameters.iter().zip(args.as_array().unwrap()) {
        match t.as_str() {
            "i32" => {
                stored.push(Stored::I32(v.as_i64().unwrap() as i32));
                types.push(Type::i32());
            }
            "u32" => {
                stored.push(Stored::U32(v.as_u64().unwrap() as u32));
                types.push(Type::u32());
            }
            "f64" => {
                stored.push(Stored::F64(v.as_f64().unwrap()));
                types.push(Type::f64());
            }
            "cstring" => {
                strings.push(CString::new(v.as_str().unwrap())?);
                stored.push(Stored::Pointer(strings.last().unwrap().as_ptr().cast()));
                types.push(Type::pointer());
            }
            "buffer" => {
                let b: Vec<u8> = v
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|n| n.as_u64().unwrap() as u8)
                    .collect();
                let len = b.len();
                buffers.push(b);
                stored.push(Stored::Pointer(buffers.last().unwrap().as_ptr().cast()));
                stored.push(Stored::Size(len));
                types.push(Type::pointer());
                types.push(Type::usize());
            }
            _ => unreachable!(),
        }
    }
    let ret = match s.returns.as_str() {
        "i32" => Type::i32(),
        "u32" => Type::u32(),
        "f64" => Type::f64(),
        "void" => Type::void(),
        _ => anyhow::bail!("unsupported return type"),
    };
    let cif = Cif::new(types, ret);
    let args: Vec<_> = stored.iter().map(Stored::arg).collect();
    // SAFETY: untrusted ABI declarations cannot be proven correct. Only the isolated worker calls this.
    // Rust owns all parameter storage until call returns; no native pointers cross IPC.
    unsafe {
        #[cfg(windows)]
        let library: libloading::Library =
            libloading::os::windows::Library::load_with_flags(&p, 0x00000100 | 0x00001000)?.into();
        #[cfg(not(windows))]
        let library = libloading::Library::new(&p)?;
        let function: libloading::Symbol<unsafe extern "C" fn()> =
            library.get(s.symbol.as_bytes())?;
        let code = CodePtr::from_ptr(*function as *const c_void);
        Ok(match s.returns.as_str() {
            "i32" => json!(cif.call::<i32>(code, &args)),
            "u32" => json!(cif.call::<u32>(code, &args)),
            "f64" => {
                let n = cif.call::<f64>(code, &args);
                ensure!(n.is_finite(), "nonfinite native result");
                json!(n)
            }
            "void" => {
                cif.call::<()>(code, &args);
                Value::Null
            }
            _ => unreachable!(),
        })
    }
}
