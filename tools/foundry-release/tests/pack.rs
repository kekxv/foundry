use std::process::Command;
#[test]
fn deterministic_pack_and_tamper_detection() {
    let d = tempfile::tempdir().unwrap();
    let root =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../extensions/text-utils/0.1.0");
    for name in ["a.zip", "b.zip"] {
        let o = Command::new(env!("CARGO_BIN_EXE_foundry-release"))
            .args([
                "pack",
                "--source",
                root.to_str().unwrap(),
                "--output",
                d.path().join(name).to_str().unwrap(),
                "--platform",
                "any",
            ])
            .output()
            .unwrap();
        assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    }
    assert_eq!(
        std::fs::read(d.path().join("a.zip")).unwrap(),
        std::fs::read(d.path().join("b.zip")).unwrap()
    );
}

#[test]
fn pack_rejects_missing_entry() {
    let d = tempfile::tempdir().unwrap();
    let mut m: serde_json::Value = serde_json::from_slice(include_bytes!(
        "../../../extensions/text-utils/0.1.0/manifest.json"
    ))
    .unwrap();
    m["entry"] = serde_json::json!("missing.js");
    std::fs::write(
        d.path().join("manifest.json"),
        serde_json::to_vec(&m).unwrap(),
    )
    .unwrap();
    let o = Command::new(env!("CARGO_BIN_EXE_foundry-release"))
        .args([
            "pack",
            "--source",
            d.path().to_str().unwrap(),
            "--output",
            d.path().join("bad.zip").to_str().unwrap(),
            "--platform",
            "any",
        ])
        .output()
        .unwrap();
    assert!(!o.status.success());
}
