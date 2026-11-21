use std::{
    fs,
    io::Write,
    process::{Command, Stdio},
};

#[test]
fn installer_signature_interoperates_with_openssh() {
    let dir = tempfile::tempdir().unwrap();
    let manifest = dir.path().join("install-manifest.txt");
    let signature = dir.path().join("install-manifest.txt.sig");
    let root = dir.path().join("root.json");
    let key = dir.path().join("seed");
    let signers = dir.path().join("allowed_signers");
    let release = env!("CARGO_BIN_EXE_foundry-release");
    let approved = dir.path().join("release-manifest.json");
    let mut assets = serde_json::Map::new();
    for platform in ["linux-x64", "linux-arm64", "macos-arm64", "windows-x64"] {
        assets.insert(
            format!("foundry-0.1.0-{platform}.zip"),
            serde_json::json!({
                "sha256": "a".repeat(64), "size": 5,
            }),
        );
    }
    fs::write(
        &approved,
        serde_json::to_vec(&serde_json::json!({
            "schemaVersion": 1, "version": "0.1.0", "assets": assets,
        }))
        .unwrap(),
    )
    .unwrap();

    let output = Command::new(release)
        .args(["keygen", "--key-id", "test", "--private-output"])
        .arg(&key)
        .arg("--root-output")
        .arg(&root)
        .output()
        .unwrap();
    assert!(output.status.success(), "{output:?}");
    let output = Command::new(release)
        .args(["sign-installer", "--input"])
        .arg(&approved)
        .arg("--manifest")
        .arg(&manifest)
        .arg("--output")
        .arg(&signature)
        .arg("--root")
        .arg(&root)
        .arg("--allowed-signers")
        .arg(&signers)
        .env("FOUNDRY_SIGNING_KEY", fs::read_to_string(&key).unwrap())
        .output()
        .unwrap();
    assert!(output.status.success(), "{output:?}");

    let verify = |namespace: &str, message: &[u8]| {
        let mut child = Command::new("ssh-keygen")
            .args([
                "-Y",
                "verify",
                "-I",
                "foundry-release",
                "-n",
                namespace,
                "-f",
            ])
            .arg(&signers)
            .arg("-s")
            .arg(&signature)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        child.stdin.take().unwrap().write_all(message).unwrap();
        child.wait().unwrap().success()
    };
    let message = fs::read(manifest).unwrap();
    assert!(verify("foundry-install-v1", &message));
    assert!(!verify("foundry-install-v1", b"changed"));
    assert!(!verify("foundry-release", &message));
}
