use anyhow::{Result, ensure};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    io::{Cursor, Read, Write},
    path::Path,
};
pub const MAX_ARCHIVE_SIZE: u64 = 128 * 1024 * 1024;
const MAX_EXPANDED: u64 = 512 * 1024 * 1024;
#[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct FileRecord {
    pub size: u64,
    pub sha256: String,
}
pub fn digest(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}
fn files(root: &Path) -> Result<BTreeMap<String, FileRecord>> {
    let mut result = BTreeMap::new();
    let mut case = BTreeMap::new();
    let mut total = 0u64;
    for e in walkdir::WalkDir::new(root).min_depth(1).follow_links(false) {
        let e = e?;
        ensure!(!e.file_type().is_symlink(), "package symlinks forbidden");
        let name = e
            .path()
            .strip_prefix(root)?
            .to_str()
            .ok_or_else(|| anyhow::anyhow!("non UTF-8 path"))?
            .replace('\\', "/");
        foundry_core::validate_path(&name)?;
        check_case_components(&name, &mut case)?;
        if e.file_type().is_dir() {
            continue;
        }
        ensure!(e.file_type().is_file(), "nonregular file");
        if name == "files.json" {
            continue;
        }
        let size = e.metadata()?.len();
        total = total
            .checked_add(size)
            .ok_or_else(|| anyhow::anyhow!("size overflow"))?;
        ensure!(total <= MAX_EXPANDED, "package too large");
        result.insert(
            name,
            FileRecord {
                size,
                sha256: digest(&std::fs::read(e.path())?),
            },
        );
    }
    Ok(result)
}
pub fn write_file_list(root: &Path) -> Result<()> {
    let data = serde_json::to_vec_pretty(&files(root)?)?;
    std::fs::write(root.join("files.json"), data)?;
    Ok(())
}
pub fn verify_files(root: &Path) -> Result<()> {
    let p = foundry_core::checked_path(root, "files.json")?;
    ensure!(p.metadata()?.len() <= 1024 * 1024, "file list too large");
    let expected: BTreeMap<String, FileRecord> =
        serde_json::from_value(foundry_core::parse_unique_json(&std::fs::read(p)?)?)?;
    ensure!(files(root)? == expected, "package integrity mismatch");
    Ok(())
}
pub fn extract_zip(bytes: &[u8], root: &Path) -> Result<()> {
    ensure!(bytes.len() as u64 <= MAX_ARCHIVE_SIZE, "archive too large");
    let mut z = zip::ZipArchive::new(Cursor::new(bytes))?;
    ensure!(z.len() <= 4096, "too many archive entries");
    let mut seen = BTreeSet::new();
    let mut components = BTreeMap::new();
    let mut total = 0u64;
    // zip's name index can hide duplicate central-directory entries; inspect raw names too.
    let mut offset = z.central_directory_start() as usize;
    let mut raw_names = BTreeSet::new();
    let mut raw_count = 0;
    while bytes.get(offset..offset + 4) == Some(b"PK\x01\x02") {
        ensure!(offset + 46 <= bytes.len(), "truncated central directory");
        let word =
            |i: usize| u16::from_le_bytes([bytes[offset + i], bytes[offset + i + 1]]) as usize;
        let n = word(28);
        let extra = word(30);
        let comment = word(32);
        ensure!(
            offset + 46 + n + extra + comment <= bytes.len(),
            "truncated name"
        );
        ensure!(
            raw_names.insert(bytes[offset + 46..offset + 46 + n].to_vec()),
            "duplicate ZIP filename"
        );
        raw_count += 1;
        offset += 46 + n + extra + comment;
    }
    ensure!(raw_count == z.len(), "inconsistent central directory");
    for i in 0..z.len() {
        let mut f = z.by_index(i)?;
        let name = f.name().trim_end_matches('/').to_string();
        foundry_core::validate_path(&name)?;
        check_case_components(&name, &mut components)?;
        ensure!(seen.insert(name.to_lowercase()), "duplicate archive entry");
        if let Some(mode) = f.unix_mode() {
            let kind = mode & 0o170000;
            ensure!(
                kind == 0 || kind == 0o100000 || kind == 0o040000,
                "links/devices forbidden"
            );
        }
        total = total
            .checked_add(f.size())
            .ok_or_else(|| anyhow::anyhow!("size overflow"))?;
        ensure!(
            total <= MAX_EXPANDED && f.size() <= MAX_ARCHIVE_SIZE,
            "expanded archive too large"
        );
        ensure!(
            f.size()
                <= f.compressed_size()
                    .saturating_mul(1000)
                    .saturating_add(1024 * 1024),
            "compression ratio exceeded"
        );
        let p = foundry_core::checked_path(root, &name)?;
        if f.is_dir() {
            std::fs::create_dir_all(p)?;
            continue;
        }
        std::fs::create_dir_all(p.parent().unwrap())?;
        let mut out = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(p)?;
        let expected = f.size();
        let n = std::io::copy(&mut (&mut f).take(expected + 1), &mut out)?;
        ensure!(n == expected, "entry size mismatch");
        out.flush()?;
    }
    Ok(())
}
pub fn pack_zip(root: &Path) -> Result<Vec<u8>> {
    verify_files(root)?;
    let mut names = files(root)?.into_keys().collect::<Vec<_>>();
    names.push("files.json".into());
    names.sort();
    let mut z = zip::ZipWriter::new(Cursor::new(Vec::new()));
    for name in names {
        z.start_file(
            &name,
            zip::write::SimpleFileOptions::default()
                .compression_method(zip::CompressionMethod::Deflated)
                .unix_permissions(0o644),
        )?;
        z.write_all(&std::fs::read(root.join(name))?)?;
    }
    Ok(z.finish()?.into_inner())
}

fn check_case_components(name: &str, seen: &mut BTreeMap<String, String>) -> Result<()> {
    let mut current = String::new();
    for part in name.split('/') {
        if !current.is_empty() {
            current.push('/');
        }
        current.push_str(part);
        let lower = current.to_lowercase();
        if let Some(previous) = seen.get(&lower) {
            ensure!(previous == &current, "case collision in path components");
        } else {
            seen.insert(lower, current.clone());
        }
    }
    Ok(())
}
