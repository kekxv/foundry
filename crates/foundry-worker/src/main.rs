use anyhow::{Result, ensure};
use std::io::{Read, Write};
fn main() {
    if let Err(e) = main_inner() {
        eprintln!("{e:#}");
        std::process::exit(1);
    }
}
fn main_inner() -> Result<()> {
    let mut bytes = Vec::new();
    std::io::stdin()
        .take(1024 * 1024 + 1)
        .read_to_end(&mut bytes)?;
    ensure!(bytes.len() <= 1024 * 1024, "request too large");
    let v: serde_json::Value = serde_json::from_slice(&bytes)?;
    ensure!(v["version"] == 1, "unsupported worker protocol");
    let root = std::path::Path::new(
        v["root"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("missing root"))?,
    );
    let m = foundry_core::validate_manifest(&std::fs::read(root.join("manifest.json"))?)?;
    let ms = v["timeoutMs"].as_u64().unwrap_or(30000).min(30000);
    let result = if matches!(v["request"]["op"].as_str(), Some("readText" | "writeText")) {
        let data = std::path::Path::new(
            v["dataRoot"]
                .as_str()
                .ok_or_else(|| anyhow::anyhow!("missing data root"))?,
        );
        foundry_worker::dispatch_fs(data, &m, &v["request"])
    } else {
        foundry_worker::dispatch(
            root,
            &m,
            &v["request"],
            std::time::Duration::from_millis(ms),
        )
    };
    let response = match result {
        Ok(value) => {
            serde_json::json!({"version":1,"requestId":v["requestId"],"ok":true,"value":value})
        }
        Err(e) => {
            serde_json::json!({"version":1,"requestId":v["requestId"],"ok":false,"error":e.to_string()})
        }
    };
    let response_path = v["responsePath"]
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("missing response transport"))?;
    let bytes = serde_json::to_vec(&response)?;
    ensure!(bytes.len() <= 1024 * 1024, "worker response too large");
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(response_path)?;
    file.write_all(&bytes)?;
    Ok(())
}
