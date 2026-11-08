use anyhow::{Context, Result, bail, ensure};
use clap::{Parser, Subcommand};
use foundry_store::*;
use serde_json::{Value, json};
use std::{
    collections::BTreeSet,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};
#[derive(Parser)]
#[command(version, about = "Install and run signed QuickJS extensions")]
struct Cli {
    #[arg(long, env = "FOUNDRY_DATA_DIR", global = true)]
    data_dir: Option<PathBuf>,
    #[arg(long, env = "FOUNDRY_INDEX", global = true)]
    index: Option<String>,
    #[arg(long, global = true)]
    trust_root: Option<PathBuf>,
    #[arg(long, global = true)]
    json: bool,
    #[arg(long, global=true, default_value_t=30000, value_parser=clap::value_parser!(u64).range(1..=30000))]
    timeout_ms: u64,
    #[command(subcommand)]
    command: Commands,
}
#[derive(Subcommand)]
enum Commands {
    Search {
        query: String,
    },
    Info {
        id: String,
    },
    List,
    Install {
        id: String,
        #[arg(long)]
        version: Option<String>,
        #[arg(long)]
        grant: Vec<String>,
    },
    #[command(alias = "get")]
    Download {
        id: String,
        #[arg(long)]
        version: Option<String>,
        #[arg(long)]
        output: Option<PathBuf>,
        #[arg(long)]
        force: bool,
    },
    Upgrade {
        id: String,
        #[arg(long)]
        grant: Vec<String>,
    },
    Uninstall {
        id: String,
    },
    Run {
        id: String,
        capability: String,
        #[arg(long, default_value = "{} ")]
        input: String,
    },
    Dev {
        #[command(subcommand)]
        command: DevCommands,
    },
    Trust {
        #[command(subcommand)]
        command: TrustCommands,
    },
}
#[derive(Subcommand)]
enum DevCommands {
    Run {
        path: PathBuf,
        capability: String,
        #[arg(long, default_value = "{} ")]
        input: String,
        #[arg(long)]
        grant: Vec<String>,
    },
}
#[derive(Subcommand)]
enum TrustCommands {
    Rotate { root: PathBuf, signatures: PathBuf },
}
fn main() {
    if let Err(e) = start() {
        eprintln!(
            "{}",
            json!({"code":"FOUNDRY_ERROR","message":format!("{e:#}")})
        );
        std::process::exit(1);
    }
}
fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}
fn read_root(cli: &Cli, store: &Store) -> Result<TrustRoot> {
    let p = cli
        .trust_root
        .clone()
        .unwrap_or_else(|| store.root.join("trust-root.json"));
    let root = serde_json::from_value(foundry_core::parse_unique_json(
        &std::fs::read(p).context("configure --trust-root from a trusted source")?,
    )?)?;
    Ok(root)
}
fn load_index(cli: &Cli, store: &Store) -> Result<VerifiedIndex> {
    let source = cli
        .index
        .as_deref()
        .or(option_env!("FOUNDRY_INDEX_URL"))
        .context("configure --index <HTTPS URL or signed local index>")?;
    let bytes = fetch(source, 16 * 1024 * 1024)?;
    let signature_bytes = fetch(&format!("{source}.sig"), 65536)?;
    let v = foundry_core::parse_unique_json(&signature_bytes)?;
    let sigs: Vec<Signature> = if v.is_array() {
        serde_json::from_value(v)?
    } else {
        vec![serde_json::from_value(v)?]
    };
    let index = verify_index_signatures(
        &bytes,
        &sigs,
        &read_root(cli, store)?,
        store.sequence()?,
        now(),
    )?;
    store.remember_index(&index)?;
    Ok(index)
}
fn start() -> Result<()> {
    let cli = Cli::parse();
    let data = cli.data_dir.clone().unwrap_or_else(|| {
        dirs::data_local_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join("foundry")
    });
    let store = Store::new(data)?;
    let output = match &cli.command {
        Commands::Search { query } => {
            let index = load_index(&cli, &store)?;
            json!(
                index
                    .index
                    .packages
                    .iter()
                    .filter(|p| p.id.contains(query))
                    .collect::<Vec<_>>()
            )
        }
        Commands::Info { id } => {
            let index = load_index(&cli, &store)?;
            json!(
                index
                    .index
                    .packages
                    .iter()
                    .filter(|p| &p.id == id)
                    .collect::<Vec<_>>()
            )
        }
        Commands::List => json!(store.list()?),
        Commands::Install { id, version, grant } => {
            install(&cli, &store, id, version.as_deref(), grant)?
        }
        Commands::Download {
            id,
            version,
            output,
            force,
        } => download(
            &cli,
            &store,
            id,
            version.as_deref(),
            output.as_deref(),
            *force,
        )?,
        Commands::Upgrade { id, grant } => {
            let mut grants = store
                .list()?
                .into_iter()
                .find(|p| &p.id == id)
                .context("extension not installed")?
                .grants;
            grants.extend(grant.iter().cloned());
            install(
                &cli,
                &store,
                id,
                None,
                &grants.into_iter().collect::<Vec<_>>(),
            )?
        }
        Commands::Uninstall { id } => {
            store.uninstall(id)?;
            json!({"uninstalled":id})
        }
        Commands::Run {
            id,
            capability,
            input,
        } => {
            ensure!(
                foundry_core::valid_id(id),
                "invalid installed extension id; local paths require dev run"
            );
            let (_temp, p, item) = store.snapshot(id)?;
            run(
                &store,
                &p.path,
                &p.manifest,
                capability,
                input,
                &item.grants,
                cli.timeout_ms,
            )?
        }
        Commands::Dev {
            command:
                DevCommands::Run {
                    path,
                    capability,
                    input,
                    grant,
                },
        } => {
            let root = path.canonicalize()?;
            let m = foundry_core::validate_manifest(&std::fs::read(root.join("manifest.json"))?)?;
            eprintln!(
                "Development mode: running explicitly trusted local source {}",
                root.display()
            );
            run(
                &store,
                &root,
                &m,
                capability,
                input,
                &grant.iter().cloned().collect(),
                cli.timeout_ms,
            )?
        }
        Commands::Trust {
            command: TrustCommands::Rotate { root, signatures },
        } => {
            ensure!(
                cli.trust_root.is_none(),
                "rotation updates the store trust-root.json, omit --trust-root"
            );
            let old = read_root(&cli, &store)?;
            let bytes = std::fs::read(root)?;
            let sigs: Vec<Signature> = serde_json::from_slice(&std::fs::read(signatures)?)?;
            let new = rotate_root(&old, &bytes, &sigs, now())?;
            let path = store.root.join("trust-root.json");
            let mut temp = tempfile::NamedTempFile::new_in(&store.root)?;
            std::io::Write::write_all(&mut temp, &bytes)?;
            temp.as_file().sync_all()?;
            temp.persist(&path)?;
            json!({"rootVersion":new.version})
        }
    };
    println!("{}", serde_json::to_string_pretty(&output)?);
    Ok(())
}
fn install(
    cli: &Cli,
    store: &Store,
    id: &str,
    version: Option<&str>,
    grant: &[String],
) -> Result<Value> {
    let index = load_index(cli, store)?;
    let platform = foundry_core::platform();
    let mut candidates = index
        .index
        .packages
        .iter()
        .filter(|p| {
            p.id == id
                && (p.platform == platform || p.platform == "any")
                && version.is_none_or(|v| v == p.version)
        })
        .collect::<Vec<_>>();
    candidates.sort_by_key(|p| semver::Version::parse(&p.version).ok());
    let package = candidates
        .last()
        .context("no compatible published extension")?;
    let bytes = fetch(&package.url, package.size)?;
    let mut grants: BTreeSet<_> = grant.iter().cloned().collect();
    // Prompt only after checking the signed archive hash and validated manifest.
    ensure!(
        bytes.len() as u64 == package.size && digest(&bytes) == package.sha256,
        "package integrity mismatch"
    );
    let temp = tempfile::tempdir()?;
    extract_zip(&bytes, temp.path())?;
    verify_files(temp.path())?;
    let m = foundry_core::validate_manifest(&std::fs::read(temp.path().join("manifest.json"))?)?;
    let missing = m
        .permissions
        .iter()
        .filter(|p| !grants.contains(*p))
        .cloned()
        .collect::<Vec<_>>();
    if !missing.is_empty() {
        use std::io::IsTerminal;
        if std::io::stdin().is_terminal() {
            eprintln!(
                "{} requests {:?}. Native execution is not an OS sandbox. Allow? [y/N]",
                id, missing
            );
            let mut line = String::new();
            std::io::stdin().read_line(&mut line)?;
            ensure!(line.trim().eq_ignore_ascii_case("y"), "permission denied");
            grants.extend(missing);
        } else {
            anyhow::bail!("explicit --grant required for {missing:?}");
        }
    }
    Ok(json!(store.install(package, &bytes, &grants)?))
}

fn download(
    cli: &Cli,
    store: &Store,
    id: &str,
    version: Option<&str>,
    output: Option<&Path>,
    force: bool,
) -> Result<Value> {
    ensure!(foundry_core::valid_id(id), "invalid extension id");
    let index = load_index(cli, store)?;
    let platform = foundry_core::platform();
    let mut candidates = index
        .index
        .packages
        .iter()
        .filter(|p| {
            p.id == id
                && (p.platform == platform || p.platform == "any")
                && version.is_none_or(|v| v == p.version)
        })
        .collect::<Vec<_>>();
    candidates.sort_by_key(|p| semver::Version::parse(&p.version).ok());
    let package = candidates
        .last()
        .context("no compatible published extension")?;
    let bytes = fetch(&package.url, package.size)?;
    ensure!(
        bytes.len() as u64 == package.size && digest(&bytes) == package.sha256,
        "package integrity mismatch"
    );
    let destination = output.map(Path::to_path_buf).unwrap_or_else(|| {
        PathBuf::from(format!(
            "{}-{}-{}.zip",
            package.id, package.version, package.platform
        ))
    });
    if destination.exists() && !force {
        bail!(
            "output already exists: {}; pass --force to replace it",
            destination.display()
        );
    }
    if let Some(parent) = destination.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let temporary =
        tempfile::NamedTempFile::new_in(destination.parent().unwrap_or(Path::new(".")))?;
    std::fs::write(temporary.path(), &bytes)?;
    temporary.as_file().sync_all()?;
    temporary.persist(&destination)?;
    Ok(
        json!({"downloaded":package.id,"version":package.version,"platform":package.platform,
        "path":destination,"sha256":package.sha256,"size":package.size,"installed":false}),
    )
}

fn run(
    store: &Store,
    root: &Path,
    m: &foundry_core::Manifest,
    capability: &str,
    input: &str,
    grants: &BTreeSet<String>,
    timeout_ms: u64,
) -> Result<Value> {
    ensure!(
        m.permissions.iter().all(|p| grants.contains(p)),
        "extension permissions require explicit authorization"
    );
    let data = store.root.join("data").join(&m.id);
    std::fs::create_dir_all(&data)?;
    let bridge_root = root.to_path_buf();
    let bridge: foundry_runtime::HostBridge = Box::new(move |request, timeout| {
        let worker = std::env::current_exe()?.with_file_name(if cfg!(windows) {
            "foundry-worker.exe"
        } else {
            "foundry-worker"
        });
        ensure!(
            worker.is_file(),
            "foundry-worker must be installed beside foundry"
        );
        let transport = tempfile::tempdir()?;
        let response_path = transport.path().join("response.json");
        let envelope = json!({"version":1,"requestId":1,"root":bridge_root,"dataRoot":data,"responsePath":response_path,"request":request,"timeoutMs":timeout.as_millis().min(30000) as u64});
        let mut bytes = serde_json::to_vec(&envelope)?;
        bytes.push(b'\n');
        ensure!(bytes.len() <= 1024 * 1024, "worker request too large");
        let output = foundry_worker::run_process(
            &mut std::process::Command::new(worker),
            Some(bytes),
            timeout,
            true,
        )?;
        ensure!(output.exit_code == 0, "worker failed: {}", output.stderr);
        // Native stdout/stderr are diagnostic streams, never the protocol channel.
        if !output.stdout.is_empty() {
            eprint!("{}", output.stdout);
        }
        if !output.stderr.is_empty() {
            eprint!("{}", output.stderr);
        }
        let response_file = foundry_core::checked_path(transport.path(), "response.json")?;
        ensure!(
            response_file.metadata()?.is_file() && response_file.metadata()?.len() <= 1024 * 1024,
            "invalid worker response size"
        );
        let response: Value = serde_json::from_slice(&std::fs::read(response_file)?)?;
        ensure!(
            response["version"] == 1 && response["requestId"] == 1,
            "worker protocol mismatch"
        );
        ensure!(response["ok"] == true, "{}", response["error"]);
        Ok(response["value"].clone())
    });
    foundry_runtime::run_extension(
        root,
        m,
        capability,
        serde_json::from_str(input)?,
        foundry_runtime::RuntimeLimits {
            timeout: std::time::Duration::from_millis(timeout_ms),
            ..Default::default()
        },
        grants,
        Some(bridge),
    )
}
