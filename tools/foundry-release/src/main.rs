use anyhow::{Context, Result, ensure};
use clap::{Parser, Subcommand};
use ed25519_dalek::{Signer, SigningKey};
use foundry_store::*;
use std::{collections::BTreeSet, path::PathBuf};
#[derive(Parser)]
#[command(about = "Reproducible Foundry packaging and detached signing")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}
#[derive(Subcommand)]
enum Commands {
    Pack {
        #[arg(long)]
        source: PathBuf,
        #[arg(long)]
        output: PathBuf,
        #[arg(long)]
        platform: String,
    },
    BuildIndex {
        #[arg(long)]
        candidates: PathBuf,
        #[arg(long)]
        sequence: u64,
        #[arg(long)]
        expires_at: u64,
        #[arg(long)]
        source_commit: String,
        #[arg(long)]
        output: PathBuf,
    },
    Sign {
        #[arg(long)]
        input: PathBuf,
        #[arg(long)]
        output: PathBuf,
        #[arg(long)]
        key_id: String,
        #[arg(long, default_value = "index")]
        domain: String,
    },
    Verify {
        #[arg(long)]
        input: PathBuf,
        #[arg(long)]
        signature: PathBuf,
        #[arg(long)]
        root: PathBuf,
        #[arg(long)]
        allow_expired: bool,
    },
    Keygen {
        #[arg(long)]
        private_output: PathBuf,
        #[arg(long)]
        root_output: PathBuf,
        #[arg(long)]
        key_id: String,
    },
}
fn main() {
    if let Err(e) = run() {
        eprintln!("{e:#}");
        std::process::exit(1);
    }
}
fn run() -> Result<()> {
    match Cli::parse().command {
        Commands::Pack {
            source,
            output,
            platform,
        } => {
            let m = foundry_core::validate_manifest(&std::fs::read(source.join("manifest.json"))?)?;
            ensure!(
                m.platforms.contains(&platform),
                "unsupported package platform"
            );
            foundry_core::validate_package_resources(&source, &m, &platform)?;
            let temp = tempfile::tempdir()?;
            // Pack only runtime resources: JS files, manifest and declared native files. Native source stays in git.
            copy_js(&source, &source, temp.path())?;
            std::fs::copy(
                source.join("manifest.json"),
                temp.path().join("manifest.json"),
            )?;
            let mut resources = BTreeSet::new();
            for paths in m.executables.values() {
                if let Some(p) = paths.get(&platform) {
                    resources.insert(p);
                }
            }
            for lib in m.libraries.values() {
                if let Some(p) = lib.paths.get(&platform) {
                    resources.insert(p);
                }
            }
            for relative in resources {
                let p = foundry_core::checked_path(&source, relative)?;
                let dest = temp.path().join(relative);
                std::fs::create_dir_all(dest.parent().unwrap())?;
                std::fs::copy(p, dest)?;
            }
            write_file_list(temp.path())?;
            let bytes = pack_zip(temp.path())?;
            if let Some(p) = output.parent() {
                std::fs::create_dir_all(p)?;
            }
            std::fs::write(&output, &bytes)?;
            println!(
                "{}",
                serde_json::json!({"id":m.id,"version":m.version,"platform":platform,"sha256":digest(&bytes),"size":bytes.len(),"file":output})
            );
        }
        Commands::BuildIndex {
            candidates,
            sequence,
            expires_at,
            source_commit,
            output,
        } => {
            let packages: Vec<Package> = serde_json::from_value(foundry_core::parse_unique_json(
                &std::fs::read(candidates)?,
            )?)?;
            ensure!(
                sequence > 0
                    && source_commit.len() == 40
                    && source_commit.bytes().all(|b| b.is_ascii_hexdigit()),
                "invalid sequence or source commit"
            );
            let index = Index {
                schema_version: 1,
                sequence,
                expires_at,
                source_commit,
                packages,
                withdrawn_packages: Vec::new(),
            };
            std::fs::write(output, serde_json::to_vec_pretty(&index)?)?;
        }
        Commands::Sign {
            input,
            output,
            key_id,
            domain,
        } => {
            let key = std::env::var("FOUNDRY_SIGNING_KEY")
                .context("FOUNDRY_SIGNING_KEY must contain a 32-byte hex seed")?;
            let bytes: [u8; 32] = hex::decode(key)
                .map_err(|_| anyhow::anyhow!("invalid signing key encoding"))?
                .try_into()
                .map_err(|_| anyhow::anyhow!("invalid signing key length"))?;
            let domain = match domain.as_str() {
                "index" => INDEX_DOMAIN,
                "root" => ROOT_DOMAIN,
                "release" => b"foundry:release:v1\n",
                _ => anyhow::bail!("unknown signing domain"),
            };
            let mut data = domain.to_vec();
            data.extend(std::fs::read(input)?);
            let signature = SigningKey::from_bytes(&bytes).sign(&data);
            std::fs::write(
                output,
                serde_json::to_vec_pretty(&Signature {
                    key_id,
                    signature: hex::encode(signature.to_bytes()),
                })?,
            )?;
        }
        Commands::Verify {
            input,
            signature,
            root,
            allow_expired,
        } => {
            let root: TrustRoot =
                serde_json::from_value(foundry_core::parse_unique_json(&std::fs::read(root)?)?)?;
            let bytes = std::fs::read(input)?;
            let sig: Signature = serde_json::from_slice(&std::fs::read(signature)?)?;
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)?
                .as_secs();
            root.validate(now)?;
            verify_index(&bytes, &sig, &root, 0, if allow_expired { 0 } else { now })?;
            println!("verified");
        }
        Commands::Keygen {
            private_output,
            root_output,
            key_id,
        } => {
            ensure!(
                !private_output.exists() && !root_output.exists(),
                "refusing to overwrite keys"
            );
            let mut seed = [0u8; 32];
            getrandom::fill(&mut seed).map_err(|e| anyhow::anyhow!("OS randomness: {e}"))?;
            let key = SigningKey::from_bytes(&seed);
            let mut options = std::fs::OpenOptions::new();
            options.write(true).create_new(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            let mut file = options.open(private_output)?;
            use std::io::Write;
            file.write_all(hex::encode(seed).as_bytes())?;
            let mut root = TrustRoot::single(&key_id, &hex::encode(key.verifying_key().as_bytes()));
            root.expires_at = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)?
                .as_secs()
                + 365 * 86400;
            std::fs::write(root_output, serde_json::to_vec_pretty(&root)?)?;
        }
    }
    Ok(())
}
fn copy_js(base: &std::path::Path, dir: &std::path::Path, out: &std::path::Path) -> Result<()> {
    for e in std::fs::read_dir(dir)? {
        let e = e?;
        let kind = e.file_type()?;
        ensure!(!kind.is_symlink(), "source symlinks forbidden");
        let name = e.file_name();
        if kind.is_dir() {
            if ["native", "bin", "lib", "target", "node_modules", ".git"]
                .iter()
                .any(|s| name == *s)
            {
                continue;
            }
            copy_js(base, &e.path(), out)?;
        } else if e.path().extension().is_some_and(|s| s == "js") {
            ensure!(kind.is_file(), "JS resource must be a regular file");
            let rel = e.path().strip_prefix(base)?.to_path_buf();
            let p = out.join(rel);
            std::fs::create_dir_all(p.parent().unwrap())?;
            std::fs::copy(e.path(), p)?;
        }
    }
    Ok(())
}
