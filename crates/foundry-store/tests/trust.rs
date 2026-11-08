use ed25519_dalek::{Signer, SigningKey};
use foundry_store::*;
use serde_json::json;
#[test]
fn rejects_wrong_signature_expiry_and_rollback() {
    let key = SigningKey::from_bytes(&[7; 32]);
    let bytes=serde_json::to_vec(&json!({"schemaVersion":1,"sequence":4,"expiresAt":2000,"sourceCommit":"abc","packages":[]})).unwrap();
    let mut msg = INDEX_DOMAIN.to_vec();
    msg.extend(&bytes);
    let sig = hex::encode(key.sign(&msg).to_bytes());
    let root = TrustRoot::single("test", &hex::encode(key.verifying_key().as_bytes()));
    assert!(
        verify_index(
            &bytes,
            &Signature {
                key_id: "test".into(),
                signature: sig.clone()
            },
            &root,
            3,
            1000
        )
        .is_ok()
    );
    assert!(
        verify_index(
            &bytes,
            &Signature {
                key_id: "test".into(),
                signature: sig.clone()
            },
            &root,
            5,
            1000
        )
        .is_err()
    );
    assert!(
        verify_index(
            &bytes,
            &Signature {
                key_id: "test".into(),
                signature: sig.clone()
            },
            &root,
            3,
            3000
        )
        .is_err()
    );
    assert!(
        verify_index(
            &bytes,
            &Signature {
                key_id: "test".into(),
                signature: "00".repeat(64)
            },
            &root,
            3,
            1000
        )
        .is_err()
    );
}
#[test]
fn package_integrity_detects_changes() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("main.js"), "export const x=1").unwrap();
    write_file_list(dir.path()).unwrap();
    verify_files(dir.path()).unwrap();
    std::fs::write(dir.path().join("main.js"), "evil").unwrap();
    assert!(verify_files(dir.path()).is_err());
}
#[test]
fn rejects_archive_escape_and_duplicates() {
    use std::io::Write;
    for names in [
        vec!["../evil"],
        vec!["same", "samo"],
        vec!["A", "a"],
        vec!["CON"],
        vec!["link"],
    ] {
        let mut w = zip::ZipWriter::new(std::io::Cursor::new(Vec::new()));
        let label = format!("{names:?}");
        for n in names {
            if n == "link" {
                w.add_symlink(n, "/etc/passwd", zip::write::SimpleFileOptions::default())
                    .unwrap();
            } else {
                w.start_file(n, zip::write::SimpleFileOptions::default())
                    .unwrap();
                w.write_all(b"x").unwrap();
            }
        }
        let mut bytes = w.finish().unwrap().into_inner();
        for i in 0..bytes.len().saturating_sub(3) {
            if &bytes[i..i + 4] == b"samo" {
                bytes[i + 3] = b'e';
            }
        }
        let d = tempfile::tempdir().unwrap();
        assert!(extract_zip(&bytes, d.path()).is_err(), "{label}");
    }
}

#[test]
fn rejects_reused_content_directory_with_forged_file_list() {
    use std::collections::BTreeSet;
    let d = tempfile::tempdir().unwrap();
    let source = d.path().join("source");
    std::fs::create_dir(&source).unwrap();
    std::fs::write(
        source.join("manifest.json"),
        include_bytes!("../../../extensions/text-utils/0.1.0/manifest.json"),
    )
    .unwrap();
    std::fs::write(
        source.join("main.js"),
        "export async function normalize(){return {text:'safe'}}",
    )
    .unwrap();
    write_file_list(&source).unwrap();
    let bytes = pack_zip(&source).unwrap();
    let p = Package {
        id: "text-utils".into(),
        version: "0.1.0".into(),
        platform: "any".into(),
        url: "test".into(),
        sha256: digest(&bytes),
        size: bytes.len() as u64,
    };
    let store = Store::new(d.path().join("store")).unwrap();
    store.install(&p, &bytes, &BTreeSet::new()).unwrap();
    let installed = store.root.join("packages").join(&p.sha256);
    std::fs::write(installed.join("main.js"), "evil").unwrap();
    write_file_list(&installed).unwrap();
    assert!(store.install(&p, &bytes, &BTreeSet::new()).is_err());
}
#[test]
fn root_rotation_requires_old_and_new_signatures() {
    let old = SigningKey::from_bytes(&[11; 32]);
    let new = SigningKey::from_bytes(&[12; 32]);
    let root = TrustRoot::single("old", &hex::encode(old.verifying_key().as_bytes()));
    let mut next = TrustRoot::single("new", &hex::encode(new.verifying_key().as_bytes()));
    next.version = 2;
    let bytes = serde_json::to_vec(&next).unwrap();
    let mut msg = ROOT_DOMAIN.to_vec();
    msg.extend(&bytes);
    let a = Signature {
        key_id: "old".into(),
        signature: hex::encode(old.sign(&msg).to_bytes()),
    };
    let b = Signature {
        key_id: "new".into(),
        signature: hex::encode(new.sign(&msg).to_bytes()),
    };
    assert!(rotate_root(&root, &bytes, std::slice::from_ref(&a), 1000).is_err());
    assert!(rotate_root(&root, &bytes, std::slice::from_ref(&b), 1000).is_err());
    assert_eq!(
        rotate_root(&root, &bytes, &[a, b], 1000).unwrap().version,
        2
    );
}

#[test]
fn invalid_update_missing_resources_preserves_installed_version() {
    use std::collections::BTreeSet;
    let d = tempfile::tempdir().unwrap();
    let source = d.path().join("source");
    std::fs::create_dir(&source).unwrap();
    let mut m: serde_json::Value = serde_json::from_slice(include_bytes!(
        "../../../extensions/text-utils/0.1.0/manifest.json"
    ))
    .unwrap();
    std::fs::write(
        source.join("manifest.json"),
        serde_json::to_vec(&m).unwrap(),
    )
    .unwrap();
    std::fs::write(
        source.join("main.js"),
        "export async function normalize(){return {text:'safe'}}",
    )
    .unwrap();
    write_file_list(&source).unwrap();
    let bytes = pack_zip(&source).unwrap();
    let mut p = Package {
        id: "text-utils".into(),
        version: "0.1.0".into(),
        platform: "any".into(),
        url: "test".into(),
        sha256: digest(&bytes),
        size: bytes.len() as u64,
    };
    let store = Store::new(d.path().join("store")).unwrap();
    store.install(&p, &bytes, &BTreeSet::new()).unwrap();
    m["version"] = json!("0.2.0");
    m["entry"] = json!("missing.js");
    std::fs::write(
        source.join("manifest.json"),
        serde_json::to_vec(&m).unwrap(),
    )
    .unwrap();
    write_file_list(&source).unwrap();
    let bad = pack_zip(&source).unwrap();
    p.version = "0.2.0".into();
    p.sha256 = digest(&bad);
    p.size = bad.len() as u64;
    assert!(store.install(&p, &bad, &BTreeSet::new()).is_err());
    assert_eq!(store.list().unwrap()[0].version, "0.1.0");
}
#[test]
fn rejects_case_collisions_in_ancestor_directories() {
    use std::io::Write;
    let mut w = zip::ZipWriter::new(std::io::Cursor::new(Vec::new()));
    for name in ["A/x.js", "a/y.js"] {
        w.start_file(name, zip::write::SimpleFileOptions::default())
            .unwrap();
        w.write_all(b"x").unwrap();
    }
    let bytes = w.finish().unwrap().into_inner();
    let d = tempfile::tempdir().unwrap();
    assert!(extract_zip(&bytes, d.path()).is_err());
}

#[test]
fn withdrawn_packages_are_authenticated_but_not_installable() {
    let key = SigningKey::from_bytes(&[7; 32]);
    let bytes = serde_json::to_vec(&json!({"schemaVersion":1,"sequence":4,"expiresAt":2000,"sourceCommit":"abc","packages":[],"withdrawnPackages":[{"id":"demo","version":"1.0.0","platform":"any","url":"https://example.com/old.zip","sha256":"ab".repeat(32),"size":123}]})).unwrap();
    let mut msg = INDEX_DOMAIN.to_vec();
    msg.extend(&bytes);
    let sig = Signature {
        key_id: "test".into(),
        signature: hex::encode(key.sign(&msg).to_bytes()),
    };
    let root = TrustRoot::single("test", &hex::encode(key.verifying_key().as_bytes()));
    let verified = verify_index(&bytes, &sig, &root, 3, 1000).unwrap();
    assert!(verified.index.packages.is_empty());
    assert_eq!(verified.index.withdrawn_packages.len(), 1);
}
