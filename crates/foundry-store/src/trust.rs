use anyhow::{Context, Result, ensure};
use ed25519_dalek::{Signature as DalekSignature, VerifyingKey};
use foundry_core::parse_unique_json;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
pub const INDEX_DOMAIN: &[u8] = b"foundry:index:v1\n";
pub const ROOT_DOMAIN: &[u8] = b"foundry:root:v1\n";
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Signature {
    pub key_id: String,
    pub signature: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TrustRoot {
    pub version: u64,
    pub expires_at: u64,
    pub threshold: usize,
    pub keys: BTreeMap<String, String>,
}
impl TrustRoot {
    pub fn single(id: &str, key: &str) -> Self {
        Self {
            version: 1,
            expires_at: u64::MAX,
            threshold: 1,
            keys: BTreeMap::from([(id.into(), key.into())]),
        }
    }
    pub fn validate(&self, now: u64) -> Result<()> {
        ensure!(
            self.version > 0
                && self.expires_at > now
                && self.threshold > 0
                && self.threshold <= self.keys.len(),
            "invalid/expired trust root"
        );
        for key in self.keys.values() {
            let _: [u8; 32] = hex::decode(key)?
                .try_into()
                .map_err(|_| anyhow::anyhow!("bad public key"))?;
        }
        Ok(())
    }
}
fn verify_signature(bytes: &[u8], sig: &Signature, root: &TrustRoot, domain: &[u8]) -> Result<()> {
    let key = root.keys.get(&sig.key_id).context("unknown signing key")?;
    let key: [u8; 32] = hex::decode(key)?
        .try_into()
        .map_err(|_| anyhow::anyhow!("bad key size"))?;
    let signature = DalekSignature::from_slice(&hex::decode(&sig.signature)?)?;
    let mut msg = domain.to_vec();
    msg.extend(bytes);
    VerifyingKey::from_bytes(&key)?.verify_strict(&msg, &signature)?;
    Ok(())
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Index {
    pub schema_version: u32,
    pub sequence: u64,
    pub expires_at: u64,
    pub source_commit: String,
    pub packages: Vec<Package>,
    #[serde(default)]
    pub withdrawn_packages: Vec<Package>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Package {
    pub id: String,
    pub version: String,
    pub platform: String,
    pub url: String,
    pub sha256: String,
    pub size: u64,
}
#[derive(Debug, Clone)]
pub struct VerifiedIndex {
    pub index: Index,
}
pub fn verify_index(
    bytes: &[u8],
    sig: &Signature,
    root: &TrustRoot,
    min_sequence: u64,
    now: u64,
) -> Result<VerifiedIndex> {
    verify_index_signatures(bytes, std::slice::from_ref(sig), root, min_sequence, now)
}
pub fn verify_index_signatures(
    bytes: &[u8],
    sigs: &[Signature],
    root: &TrustRoot,
    min_sequence: u64,
    now: u64,
) -> Result<VerifiedIndex> {
    root.validate(now)?;
    ensure!(bytes.len() <= 16 * 1024 * 1024, "index too large");
    verify_threshold(bytes, sigs, root, INDEX_DOMAIN)?;
    let index: Index = serde_json::from_value(parse_unique_json(bytes)?)?;
    ensure!(
        index.schema_version == 1 && index.sequence >= min_sequence && index.sequence > 0,
        "unsupported/rolled back index"
    );
    ensure!(index.expires_at > now, "expired index");
    let mut seen = std::collections::BTreeSet::new();
    for p in index.packages.iter().chain(&index.withdrawn_packages) {
        ensure!(foundry_core::valid_id(&p.id), "invalid id");
        semver_check(&p.version)?;
        ensure!(
            hex::decode(&p.sha256)?.len() == 32 && p.size <= MAX_ARCHIVE_SIZE,
            "bad package digest/size"
        );
        ensure!(
            seen.insert((&p.id, &p.version, &p.platform)),
            "duplicate package entry"
        );
    }
    Ok(VerifiedIndex { index })
}
fn semver_check(v: &str) -> Result<()> {
    ensure!(
        !v.is_empty()
            && v.len() < 128
            && !v.contains(['/', '\\', ':'])
            && v.bytes()
                .all(|b| b.is_ascii_alphanumeric() || b".-+".contains(&b)),
        "invalid version"
    );
    Ok(())
}
fn verify_threshold(
    bytes: &[u8],
    sigs: &[Signature],
    root: &TrustRoot,
    domain: &[u8],
) -> Result<()> {
    let mut valid = std::collections::BTreeSet::new();
    for sig in sigs {
        if verify_signature(bytes, sig, root, domain).is_ok() {
            valid.insert(&sig.key_id);
        }
    }
    ensure!(valid.len() >= root.threshold, "signature threshold not met");
    Ok(())
}
pub fn rotate_root(
    old: &TrustRoot,
    bytes: &[u8],
    sigs: &[Signature],
    now: u64,
) -> Result<TrustRoot> {
    old.validate(now)?;
    verify_threshold(bytes, sigs, old, ROOT_DOMAIN)?;
    let next: TrustRoot = serde_json::from_value(parse_unique_json(bytes)?)?;
    next.validate(now)?;
    ensure!(
        next.version == old.version + 1,
        "root version must increment by one"
    );
    verify_threshold(bytes, sigs, &next, ROOT_DOMAIN)?;
    Ok(next)
}
use crate::MAX_ARCHIVE_SIZE;
