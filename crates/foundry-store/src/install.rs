use crate::*;
use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet},
    io::Read,
    path::PathBuf,
};
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InstalledPackage {
    pub id: String,
    pub version: String,
    pub platform: String,
    pub archive_sha256: String,
    pub file_list_sha256: String,
    pub grants: BTreeSet<String>,
}
#[derive(Debug)]
pub struct VerifiedPackage {
    pub path: PathBuf,
    pub manifest: foundry_core::Manifest,
}
pub struct Store {
    pub root: PathBuf,
}
#[derive(Default, Serialize, Deserialize)]
struct State {
    #[serde(default)]
    sequence: u64,
    #[serde(default)]
    installed: BTreeMap<String, InstalledPackage>,
}
impl Store {
    pub fn new(root: PathBuf) -> Result<Self> {
        std::fs::create_dir_all(&root)?;
        Ok(Self { root })
    }
    fn lock(&self) -> Result<std::fs::File> {
        let f = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(self.root.join("lock"))?;
        fs2::FileExt::lock_exclusive(&f)?;
        Ok(f)
    }
    fn state(&self) -> Result<State> {
        let p = self.root.join("state.json");
        if p.exists() {
            Ok(serde_json::from_slice(&std::fs::read(p)?)?)
        } else {
            Ok(State::default())
        }
    }
    fn save(&self, state: &State) -> Result<()> {
        let mut t = tempfile::NamedTempFile::new_in(&self.root)?;
        std::io::Write::write_all(&mut t, &serde_json::to_vec_pretty(state)?)?;
        t.as_file().sync_all()?;
        t.persist(self.root.join("state.json"))?;
        Ok(())
    }
    pub fn list(&self) -> Result<Vec<InstalledPackage>> {
        let _lock = self.lock()?;
        Ok(self.state()?.installed.into_values().collect())
    }
    pub fn sequence(&self) -> Result<u64> {
        Ok(self.state()?.sequence)
    }
    pub fn remember_index(&self, index: &VerifiedIndex) -> Result<()> {
        let _lock = self.lock()?;
        let mut s = self.state()?;
        ensure!(index.index.sequence >= s.sequence, "index rollback");
        s.sequence = index.index.sequence;
        self.save(&s)
    }
    pub fn install(
        &self,
        p: &Package,
        bytes: &[u8],
        grants: &BTreeSet<String>,
    ) -> Result<InstalledPackage> {
        ensure!(
            bytes.len() as u64 == p.size && digest(bytes) == p.sha256,
            "archive digest/size mismatch"
        );
        ensure!(foundry_core::valid_id(&p.id), "invalid id");
        let _lock = self.lock()?;
        let temp = tempfile::tempdir_in(&self.root)?;
        extract_zip(bytes, temp.path())?;
        verify_files(temp.path())?;
        let m =
            foundry_core::validate_manifest(&std::fs::read(temp.path().join("manifest.json"))?)?;
        ensure!(
            m.id == p.id && m.version == p.version && m.platforms.contains(&p.platform),
            "manifest does not match index"
        );
        ensure!(
            p.platform == "any" || p.platform == foundry_core::platform(),
            "wrong platform"
        );
        ensure!(
            m.permissions.iter().all(|x| grants.contains(x)),
            "required permissions not granted: {:?}",
            m.permissions
        );
        foundry_core::validate_package_resources(temp.path(), &m, &p.platform)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            for paths in m.executables.values() {
                if let Some(path) = paths.get(&p.platform) {
                    let executable = foundry_core::checked_path(temp.path(), path)?;
                    std::fs::set_permissions(executable, std::fs::Permissions::from_mode(0o755))?;
                }
            }
        }
        // A content-addressed immutable directory allows updates without overwriting running files.
        let destination = self.root.join("packages").join(&p.sha256);
        std::fs::create_dir_all(destination.parent().unwrap())?;
        let expected_file_list = digest(&std::fs::read(temp.path().join("files.json"))?);
        if destination.exists() {
            verify_files(&destination)?;
            ensure!(
                digest(&std::fs::read(destination.join("files.json"))?) == expected_file_list,
                "existing content directory was modified"
            );
        }
        if !destination.exists() {
            std::fs::rename(temp.path(), &destination)?;
        }
        let item = InstalledPackage {
            id: p.id.clone(),
            version: p.version.clone(),
            platform: p.platform.clone(),
            archive_sha256: p.sha256.clone(),
            file_list_sha256: expected_file_list,
            grants: m.permissions.into_iter().collect(),
        };
        let mut state = self.state()?;
        state.installed.insert(p.id.clone(), item.clone());
        self.save(&state)?;
        Ok(item)
    }
    pub fn snapshot(
        &self,
        id: &str,
    ) -> Result<(tempfile::TempDir, VerifiedPackage, InstalledPackage)> {
        let _lock = self.lock()?;
        let item = self
            .state()?
            .installed
            .get(id)
            .context("extension not installed")?
            .clone();
        let source = self.root.join("packages").join(&item.archive_sha256);
        ensure!(
            digest(&std::fs::read(source.join("files.json"))?) == item.file_list_sha256,
            "file list tampered"
        );
        verify_files(&source)?;
        let temp = tempfile::tempdir_in(&self.root)?;
        for e in walkdir::WalkDir::new(&source)
            .min_depth(1)
            .follow_links(false)
        {
            let e = e?;
            ensure!(!e.file_type().is_symlink(), "symlink forbidden");
            let p = temp.path().join(e.path().strip_prefix(&source)?);
            if e.file_type().is_dir() {
                std::fs::create_dir_all(p)?;
            } else {
                std::fs::create_dir_all(p.parent().unwrap())?;
                std::fs::copy(e.path(), p)?;
            }
        }
        verify_files(temp.path())?;
        ensure!(
            digest(&std::fs::read(temp.path().join("files.json"))?) == item.file_list_sha256,
            "snapshot integrity mismatch"
        );
        let manifest =
            foundry_core::validate_manifest(&std::fs::read(temp.path().join("manifest.json"))?)?;
        let path = temp.path().to_path_buf();
        Ok((temp, VerifiedPackage { path, manifest }, item))
    }
    pub fn uninstall(&self, id: &str) -> Result<()> {
        let _lock = self.lock()?;
        let mut s = self.state()?;
        ensure!(s.installed.remove(id).is_some(), "extension not installed");
        self.save(&s)
    }
}
// Signed local mirrors are accepted explicitly; remote transport always requires HTTPS.
pub fn fetch(source: &str, limit: u64) -> Result<Vec<u8>> {
    if !source.contains("://") {
        let f = std::fs::File::open(source)?;
        ensure!(f.metadata()?.len() <= limit, "file too large");
        let mut b = Vec::new();
        f.take(limit + 1).read_to_end(&mut b)?;
        ensure!(b.len() as u64 <= limit, "file too large");
        return Ok(b);
    }
    ensure!(source.starts_with("https://"), "remote URLs must use HTTPS");
    let client = reqwest::blocking::Client::builder()
        .https_only(true)
        .timeout(std::time::Duration::from_secs(60))
        .redirect(reqwest::redirect::Policy::limited(5))
        .build()?;
    let response = client.get(source).send()?.error_for_status()?;
    if let Some(n) = response.content_length() {
        ensure!(n <= limit, "download too large");
    }
    let mut b = Vec::new();
    response.take(limit + 1).read_to_end(&mut b)?;
    ensure!(b.len() as u64 <= limit, "download too large");
    Ok(b)
}
