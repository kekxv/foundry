use foundry_core::{validate_manifest, validate_value};
use serde_json::{Value, json};
fn sample(kind: &str) -> Value {
    json!({"schemaVersion":1,"id":"test-ext","version":"1.0.0","description":"test",
        "type":kind,"entry":"main.js","platforms":["any"],"permissions":[],
        "capabilities":{"greet":{"description":"greet","export":"greet","input":{"type":"object","required":["name"],"properties":{"name":{"type":"string"}}},"output":{"type":"string"}}}})
}
#[test]
fn manifest_accepts_three_types() {
    for kind in ["javascript", "executable", "native-library"] {
        assert!(validate_manifest(&serde_json::to_vec(&sample(kind)).unwrap()).is_ok());
    }
}
#[test]
fn manifest_rejects_invalid_paths() {
    for path in [
        "../evil.js",
        "/evil.js",
        "C:/evil.js",
        "a\\b.js",
        "./main.js",
        "CON",
        "a//b",
        "a/../b",
    ] {
        let mut m = sample("javascript");
        m["entry"] = json!(path);
        assert!(
            validate_manifest(&serde_json::to_vec(&m).unwrap()).is_err(),
            "{path}"
        );
    }
}
#[test]
fn capability_rejects_invalid_input() {
    let m = validate_manifest(&serde_json::to_vec(&sample("javascript")).unwrap()).unwrap();
    assert!(validate_value(&m.capabilities["greet"].input, &json!({"name":"world"})).is_ok());
    assert!(validate_value(&m.capabilities["greet"].input, &json!({"name":12})).is_err());
}
#[test]
fn rejects_unknown_version_type_remote_ref_and_duplicate_keys() {
    for (key, value) in [
        ("schemaVersion", json!(2)),
        ("type", json!("unknown")),
        ("id", json!("../oops")),
    ] {
        let mut m = sample("javascript");
        m[key] = value;
        assert!(validate_manifest(&serde_json::to_vec(&m).unwrap()).is_err());
    }
    let mut m = sample("javascript");
    m["capabilities"]["greet"]["input"] = json!({"$ref":"https://evil.test/schema"});
    assert!(validate_manifest(&serde_json::to_vec(&m).unwrap()).is_err());
    let s = serde_json::to_string(&sample("javascript"))
        .unwrap()
        .replacen("{", "{\"id\":\"other\",", 1);
    assert!(validate_manifest(s.as_bytes()).is_err());
}

#[test]
fn official_manifests_follow_published_schema() {
    let schema: Value =
        serde_json::from_slice(include_bytes!("../../../schemas/manifest.schema.json")).unwrap();
    for data in [
        include_bytes!("../../../extensions/text-utils/0.1.0/manifest.json").as_slice(),
        include_bytes!("../../../extensions/file-digest/0.1.0/manifest.json").as_slice(),
        include_bytes!("../../../extensions/native-math/0.1.0/manifest.json").as_slice(),
        include_bytes!("../../../extensions/id-card-reader/0.1.0/manifest.json").as_slice(),
        include_bytes!("../../../extensions/camera/0.1.0/manifest.json").as_slice(),
        include_bytes!("../../../extensions/ocr/0.1.0/manifest.json").as_slice(),
        include_bytes!("../../../extensions/serial-port/0.1.0/manifest.json").as_slice(),
    ] {
        let v: Value = serde_json::from_slice(data).unwrap();
        validate_value(&schema, &v).unwrap();
        validate_manifest(data).unwrap();
    }
}

#[test]
fn plugin_contract_is_optional_and_strict() {
    let schema: Value =
        serde_json::from_slice(include_bytes!("../../../schemas/manifest.schema.json")).unwrap();
    let mut m = sample("javascript");
    m["plugin"] = json!({"kind":"id-card-reader","mode":"mock","transport":"mock","contract":"foundry.id-card.v1"});
    validate_value(&schema, &m).unwrap();
    validate_manifest(&serde_json::to_vec(&m).unwrap()).unwrap();
    for (field, value) in [
        ("kind", "../camera"),
        ("mode", "live"),
        ("transport", "usb"),
        ("contract", "bad contract"),
    ] {
        let mut invalid = m.clone();
        invalid["plugin"][field] = json!(value);
        assert!(
            validate_manifest(&serde_json::to_vec(&invalid).unwrap()).is_err(),
            "{field}"
        );
        assert!(validate_value(&schema, &invalid).is_err());
    }
    let mut invalid_null = m.clone();
    invalid_null["plugin"] = Value::Null;
    assert!(validate_manifest(&serde_json::to_vec(&invalid_null).unwrap()).is_err());
    assert!(validate_value(&schema, &invalid_null).is_err());
    let mut adapter = m.clone();
    adapter["plugin"]["mode"] = json!("adapter");
    adapter["plugin"]["transport"] = json!("sdk");
    assert!(validate_manifest(&serde_json::to_vec(&adapter).unwrap()).is_err());
    adapter["type"] = json!("native-library");
    adapter["permissions"] = json!(["native.call"]);
    validate_manifest(&serde_json::to_vec(&adapter).unwrap()).unwrap();
    validate_value(&schema, &adapter).unwrap();
}
