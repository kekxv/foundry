mod ffi;
mod process;
use anyhow::{Context, Result, ensure};
pub use ffi::*;
use foundry_core::{Manifest, checked_path, platform};
pub use process::*;
use serde_json::{Value, json};
use std::{path::Path, time::Duration};
pub fn dispatch(root: &Path, m: &Manifest, v: &Value, timeout: Duration) -> Result<Value> {
    match v["op"].as_str() {
        Some("exec") => {
            ensure!(
                m.permissions.iter().any(|p| p == "process.spawn"),
                "execution not declared"
            );
            let id = v["id"].as_str().context("missing executable id")?;
            let relative = m
                .executables
                .get(id)
                .and_then(|p| p.get(&platform()))
                .context("undeclared executable")?;
            let path = checked_path(root, relative)?;
            let args = v["args"].as_array().context("arguments must be an array")?;
            ensure!(args.len() <= 256, "too many arguments");
            let mut cmd = std::process::Command::new(path);
            for arg in args {
                cmd.arg(arg.as_str().context("arguments must be strings")?);
            }
            cmd.current_dir(root);
            let limit = v["options"]["timeoutMs"]
                .as_u64()
                .map(Duration::from_millis)
                .unwrap_or(timeout)
                .min(timeout);
            let result = run_process(&mut cmd, None, limit, false)?;
            Ok(json!({"exitCode":result.exit_code,"stdout":result.stdout,"stderr":result.stderr}))
        }
        Some("ffi") => {
            ensure!(
                m.permissions.iter().any(|p| p == "native.call"),
                "native call not declared"
            );
            call_ffi(
                root,
                m,
                v["id"].as_str().context("missing library")?,
                v["symbol"].as_str().context("missing symbol")?,
                &v["args"],
            )
        }
        _ => anyhow::bail!("unsupported worker operation"),
    }
}

/// File IO is also isolated so special/slow files cannot block the QuickJS thread.
pub fn dispatch_fs(data: &Path, m: &Manifest, v: &Value) -> Result<Value> {
    use std::io::Read;
    let write = v["op"] == "writeText";
    let permission = if write {
        "filesystem.write"
    } else {
        "filesystem.read"
    };
    ensure!(
        m.permissions.iter().any(|p| p == permission),
        "file operation not declared"
    );
    let path = checked_path(data, v["path"].as_str().context("missing data path")?)?;
    if path.exists() {
        ensure!(
            path.metadata()?.is_file(),
            "data path must be a regular file"
        );
    }
    if write {
        let text = v["text"].as_str().context("text must be string")?;
        ensure!(text.len() <= 1024 * 1024, "file too large");
        std::fs::create_dir_all(path.parent().unwrap())?;
        std::fs::write(path, text)?;
        Ok(Value::Null)
    } else {
        let f = std::fs::File::open(path)?;
        ensure!(
            f.metadata()?.is_file() && f.metadata()?.len() <= 1024 * 1024,
            "file must be regular and at most 1 MiB"
        );
        let mut bytes = Vec::new();
        f.take(1024 * 1024 + 1).read_to_end(&mut bytes)?;
        ensure!(bytes.len() <= 1024 * 1024, "file too large");
        Ok(json!(String::from_utf8(bytes)?))
    }
}
