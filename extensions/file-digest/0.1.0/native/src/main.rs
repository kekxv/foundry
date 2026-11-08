use sha2::{Digest, Sha256};
use std::io::Read;
fn main() {
    if let Err(e) = digest() {
        eprintln!("{e:#}");
        std::process::exit(1);
    }
}
fn digest() -> anyhow::Result<()> {
    let path = std::env::args_os()
        .nth(1)
        .ok_or_else(|| anyhow::anyhow!("usage: file-digest <path>"))?;
    let mut f = std::fs::File::open(path)?;
    let mut h = Sha256::new();
    let mut buf = [0u8; 65536];
    loop {
        let n = f.read(&mut buf)?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    println!(
        "{}",
        serde_json::json!({"sha256":hex::encode(h.finalize())})
    );
    Ok(())
}
