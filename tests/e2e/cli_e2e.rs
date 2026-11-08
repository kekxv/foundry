use std::process::Command;
#[test]
fn dev_runs_pure_js_and_rejects_permissionless_native() {
    let d = tempfile::tempdir().unwrap();
    let binary = env!("CARGO_BIN_EXE_foundry");
    let base = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let out = Command::new(binary)
        .args([
            "--data-dir",
            d.path().to_str().unwrap(),
            "dev",
            "run",
            base.join("extensions/text-utils/0.1.0").to_str().unwrap(),
            "normalize",
            "--input",
            "{\"text\":\"  hello\\r\\nworld  \"}",
        ])
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&out.stdout).unwrap(),
        serde_json::json!({"text":"hello\nworld"})
    );
    let bad = Command::new(binary)
        .args([
            "--data-dir",
            d.path().to_str().unwrap(),
            "dev",
            "run",
            base.join("extensions/native-math/0.1.0").to_str().unwrap(),
            "add",
            "--input",
            "{\"a\":1,\"b\":2}",
        ])
        .output()
        .unwrap();
    assert!(!bad.status.success());
    let wrong = Command::new(binary)
        .args([
            "--data-dir",
            d.path().to_str().unwrap(),
            "run",
            base.join("extensions/text-utils/0.1.0").to_str().unwrap(),
            "normalize",
            "--input",
            "{\"text\":\"x\"}",
        ])
        .output()
        .unwrap();
    assert!(!wrong.status.success());
}
