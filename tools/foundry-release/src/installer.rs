use anyhow::{Context, Result, ensure};
use base64::{Engine, engine::general_purpose::STANDARD};
use ed25519_dalek::{Signer, SigningKey};
use foundry_store::TrustRoot;
use sha2::{Digest, Sha512};
use std::{
    fmt::Write,
    fs,
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

const NAMESPACE: &[u8] = b"foundry-install-v1";
const MAGIC: &[u8] = b"SSHSIG";
const ALGORITHM: &[u8] = b"ssh-ed25519";
const HASH: &[u8] = b"sha512";
const PLATFORMS: [&str; 4] = ["linux-x64", "linux-arm64", "macos-arm64", "windows-x64"];

pub fn sign(
    release: &Path,
    manifest: &Path,
    signature: &Path,
    allowed_signers: &Path,
    root: &TrustRoot,
    key: &SigningKey,
) -> Result<()> {
    root.validate(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs())?;
    let public_key = key.verifying_key().to_bytes();
    ensure!(
        root.threshold == 1
            && root
                .keys
                .values()
                .any(|value| value.eq_ignore_ascii_case(&hex::encode(public_key))),
        "installer signing key does not satisfy the trust root"
    );
    let release = foundry_core::parse_unique_json(&fs::read(release)?)?;
    ensure!(release["schemaVersion"] == 1, "invalid release schema");
    let version = release["version"]
        .as_str()
        .context("missing release version")?;
    let parsed = semver::Version::parse(version)?;
    ensure!(
        parsed.pre.is_empty() && parsed.build.is_empty(),
        "expected stable release version"
    );
    let mut list = format!("foundry-install-v1 {version} {}\n", root.expires_at);
    for platform in PLATFORMS {
        let name = format!("foundry-{version}-{platform}.zip");
        let asset = &release["assets"][&name];
        let digest = asset["sha256"].as_str().context("missing client digest")?;
        let size = asset["size"].as_u64().context("missing client size")?;
        ensure!(
            digest.len() == 64
                && digest.bytes().all(|b| b.is_ascii_hexdigit())
                && size > 0
                && size <= 128 * 1024 * 1024,
            "invalid client ZIP record"
        );
        writeln!(list, "{} {size} {name}", digest.to_ascii_lowercase())?;
    }

    let mut public_blob = Vec::new();
    ssh_string(&mut public_blob, ALGORITHM);
    ssh_string(&mut public_blob, &public_key);

    // OpenSSH PROTOCOL.sshsig defines this domain-separated payload and envelope.
    let mut payload = MAGIC.to_vec();
    ssh_string(&mut payload, NAMESPACE);
    ssh_string(&mut payload, b"");
    ssh_string(&mut payload, HASH);
    ssh_string(&mut payload, &Sha512::digest(list.as_bytes()));

    let mut signature_blob = Vec::new();
    ssh_string(&mut signature_blob, ALGORITHM);
    ssh_string(&mut signature_blob, &key.sign(&payload).to_bytes());

    let mut wire = MAGIC.to_vec();
    wire.extend(1u32.to_be_bytes());
    ssh_string(&mut wire, &public_blob);
    ssh_string(&mut wire, NAMESPACE);
    ssh_string(&mut wire, b"");
    ssh_string(&mut wire, HASH);
    ssh_string(&mut wire, &signature_blob);

    let mut armor = String::from("-----BEGIN SSH SIGNATURE-----\n");
    for line in STANDARD.encode(wire).as_bytes().chunks(70) {
        writeln!(armor, "{}", std::str::from_utf8(line)?)?;
    }
    armor.push_str("-----END SSH SIGNATURE-----\n");

    fs::write(manifest, list)?;
    fs::write(signature, armor)?;
    fs::write(
        allowed_signers,
        format!(
            "# foundry-install-v1 expires-at {}\nfoundry-release namespaces=\"foundry-install-v1\" ssh-ed25519 {}\n",
            root.expires_at,
            STANDARD.encode(public_blob)
        ),
    )?;
    Ok(())
}

fn ssh_string(output: &mut Vec<u8>, value: &[u8]) {
    output.extend((value.len() as u32).to_be_bytes());
    output.extend(value);
}
