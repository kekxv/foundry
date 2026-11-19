use std::{
    io::Write,
    path::Path,
    process::{Command, Output, Stdio},
};

fn run_wizard(directory: &Path, args: &[&str], answers: &str) -> Output {
    let mut child = Command::new(env!("CARGO_BIN_EXE_foundry"))
        .current_dir(directory)
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(answers.as_bytes())
        .unwrap();
    child.wait_with_output().unwrap()
}

#[test]
fn interactive_new_retries_invalid_answers_and_uses_defaults() {
    let temp = tempfile::tempdir().unwrap();
    let output = run_wizard(
        temp.path(),
        &["new", "--interactive"],
        "Invalid ID\nmy-extension\nunknown-type\n\n0.1.0-rc.1\n\n\n",
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let result: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(result["type"], "javascript");
    assert_eq!(result["version"], "0.1.0");
    assert!(
        temp.path()
            .join("extensions/my-extension/0.1.0/main.js")
            .is_file()
    );
}

#[test]
fn interactive_new_stops_at_eof_without_writing_and_accepts_explicit_options() {
    let temp = tempfile::tempdir().unwrap();
    let output = run_wizard(temp.path(), &["new", "--interactive"], "cancelled\n");
    assert!(!output.status.success());
    assert!(!temp.path().join("extensions").exists());

    let output = run_wizard(
        temp.path(),
        &[
            "new",
            "my-library",
            "-i",
            "--version",
            "1.2.3",
            "--output",
            "custom parent",
        ],
        "native-library\n",
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let result: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(result["type"], "native-library");
    assert!(
        temp.path()
            .join("custom parent/my-library/1.2.3/native/src/lib.rs")
            .is_file()
    );
}

#[test]
fn new_without_an_id_or_terminal_reports_how_to_proceed() {
    let temp = tempfile::tempdir().unwrap();
    let output = run_wizard(temp.path(), &["new"], "");
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("--interactive"));
    assert!(!temp.path().join("extensions").exists());
}

#[test]
fn new_accepts_all_named_options_without_reading_stdin() {
    let temp = tempfile::tempdir().unwrap();
    let args = [
        "new",
        "--id",
        "automation",
        "--type",
        "executable",
        "--version",
        "2.3.4",
        "--output",
        "custom parent",
    ];
    let output = run_wizard(temp.path(), &args, "");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stderr.is_empty());
    let result: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(result["id"], "automation");
    assert_eq!(result["type"], "executable");
    assert_eq!(result["version"], "2.3.4");
    assert!(
        temp.path()
            .join("custom parent/automation/2.3.4/native/src/main.rs")
            .is_file()
    );
    assert!(!temp.path().join("extensions").exists());
}

#[test]
fn new_rejects_positional_and_named_ids_together() {
    let temp = tempfile::tempdir().unwrap();
    let output = run_wizard(temp.path(), &["new", "first", "--id", "second"], "");
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("cannot be used with"));
    assert!(!temp.path().join("extensions").exists());
}

#[test]
fn new_creates_a_runnable_extension_offline() {
    let temp = tempfile::tempdir().unwrap();
    let state = temp.path().join("state");
    let binary = env!("CARGO_BIN_EXE_foundry");
    let output = Command::new(binary)
        .current_dir(temp.path())
        .arg("--data-dir")
        .arg(&state)
        .args(["new", "hello"])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(!state.exists());
    let extension = temp.path().join("extensions/hello");
    let metadata: serde_json::Value =
        serde_json::from_slice(&std::fs::read(extension.join("metadata.json")).unwrap()).unwrap();
    assert_eq!(metadata["id"], "hello");
    assert_eq!(metadata["versions"], serde_json::json!(["0.1.0"]));

    let source = extension.join("0.1.0");
    let output = Command::new(binary)
        .arg("--data-dir")
        .arg(&state)
        .args(["dev", "run"])
        .arg(source)
        .args(["echo", "--input", r#"{"value":17}"#])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&output.stdout).unwrap(),
        serde_json::json!({"value":17})
    );
}

#[test]
fn new_preserves_existing_extensions_and_rejects_invalid_names_and_versions() {
    let temp = tempfile::tempdir().unwrap();
    let directory = temp.path().join("extension source");
    let binary = env!("CARGO_BIN_EXE_foundry");
    let create = |id: &str, version: &str| {
        Command::new(binary)
            .current_dir(temp.path())
            .args(["new", id, "--version", version, "--output"])
            .arg(&directory)
            .output()
            .unwrap()
    };
    for (id, version) in [
        ("../outside", "0.1.0"),
        ("con", "0.1.0"),
        ("hello", "1.2.3-rc.1"),
        ("hello", "1.2.3+build"),
    ] {
        assert!(!create(id, version).status.success());
    }
    assert!(!directory.exists());
    let output = create("hello", "1.2.3");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let source = directory.join("hello/1.2.3/main.js");
    std::fs::write(&source, "// my code\n").unwrap();
    assert!(!create("hello", "1.2.3").status.success());
    assert!(!create("hello", "2.0.0").status.success());
    assert_eq!(std::fs::read_to_string(source).unwrap(), "// my code\n");
    assert!(!directory.join("hello/2.0.0").exists());
}

#[cfg(unix)]
#[test]
fn new_rejects_non_utf8_output_before_writing_files() {
    use std::{ffi::OsStr, os::unix::ffi::OsStrExt};

    let temp = tempfile::tempdir().unwrap();
    let directory = temp.path().join(OsStr::from_bytes(b"extensions-\xff"));
    let output = Command::new(env!("CARGO_BIN_EXE_foundry"))
        .args(["new", "hello", "--output"])
        .arg(&directory)
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert!(!directory.exists());
}

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
