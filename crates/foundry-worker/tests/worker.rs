use foundry_worker::*;
use serde_json::json;
use std::time::Duration;
#[test]
fn rejects_undeclared_symbols_and_bad_arguments() {
    let m = foundry_core::validate_manifest(include_bytes!(
        "../../../extensions/native-math/0.1.0/manifest.json"
    ))
    .unwrap();
    assert!(validate_ffi(&m, "math", "unknown", &json!([])).is_err());
    for args in [
        json!([2147483648i64, 1]),
        json!([1.5, 1]),
        json!([1]),
        json!(["ptr", 2]),
    ] {
        assert!(validate_ffi(&m, "math", "add", &args).is_err());
    }
}
#[test]
fn rejects_unknown_program_and_shell_arguments_are_literal() {
    let d = tempfile::tempdir().unwrap();
    let m = foundry_core::validate_manifest(include_bytes!(
        "../../../extensions/file-digest/0.1.0/manifest.json"
    ))
    .unwrap();
    assert!(
        dispatch(
            d.path(),
            &m,
            &json!({"op":"exec","id":"unknown","args":[]}),
            Duration::from_secs(1)
        )
        .is_err()
    );
}
#[test]
fn process_times_out_and_limits_output() {
    #[cfg(unix)]
    {
        assert!(
            run_process(
                std::process::Command::new("/bin/sh").args(["-c", "sleep 5"]),
                None,
                Duration::from_millis(50),
                true
            )
            .is_err()
        );
        assert!(
            run_process(
                std::process::Command::new("/bin/sh").args(["-c", "yes x"]),
                None,
                Duration::from_secs(2),
                true
            )
            .is_err()
        );
    }
}
