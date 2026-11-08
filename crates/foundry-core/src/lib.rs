use anyhow::{Result, bail, ensure};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Manifest {
    pub schema_version: u32,
    pub id: String,
    pub version: String,
    pub description: String,
    #[serde(rename = "type")]
    pub kind: String,
    pub entry: String,
    pub platforms: Vec<String>,
    pub permissions: Vec<String>,
    #[serde(
        default,
        deserialize_with = "deserialize_plugin",
        skip_serializing_if = "Option::is_none"
    )]
    pub plugin: Option<Plugin>,
    pub capabilities: BTreeMap<String, Capability>,
    #[serde(default)]
    pub executables: BTreeMap<String, BTreeMap<String, String>>,
    #[serde(default)]
    pub libraries: BTreeMap<String, Library>,
}
/// Plugin purpose and integration metadata, independent of implementation type.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Plugin {
    pub kind: String,
    pub mode: String,
    pub transport: String,
    pub contract: String,
}
fn deserialize_plugin<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> std::result::Result<Option<Plugin>, D::Error> {
    // Absence is compatible with legacy extensions; explicit null is malformed metadata.
    Plugin::deserialize(deserializer).map(Some)
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Capability {
    pub description: String,
    pub export: String,
    pub input: Value,
    pub output: Value,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Library {
    pub abi: String,
    pub paths: BTreeMap<String, String>,
    pub symbols: BTreeMap<String, Symbol>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Symbol {
    pub symbol: String,
    pub parameters: Vec<String>,
    pub returns: String,
}

pub fn valid_id(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 64
        && s.as_bytes()[0].is_ascii_alphanumeric()
        && s.bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}
pub fn validate_path(s: &str) -> Result<()> {
    ensure!(
        !s.is_empty() && s.len() <= 512 && !s.contains(['\\', ':', '\0']),
        "invalid package path: {s}"
    );
    for part in s.split('/') {
        ensure!(
            !part.is_empty() && part != "." && part != ".." && !part.ends_with(['.', ' ']),
            "invalid path component"
        );
        ensure!(
            !part
                .chars()
                .any(|c| c.is_control() || "<>\"|?*".contains(c)),
            "invalid path character"
        );
        let stem = part.split('.').next().unwrap_or("").to_ascii_uppercase();
        ensure!(
            ![
                "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7",
                "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8",
                "LPT9"
            ]
            .contains(&stem.as_str()),
            "reserved path"
        );
    }
    Ok(())
}
pub fn checked_path(root: &Path, relative: &str) -> Result<PathBuf> {
    validate_path(relative)?;
    let base = root.canonicalize()?;
    let p = base.join(relative);
    let mut current = base.clone();
    for part in relative.split('/') {
        current.push(part);
        if current.exists() || current.symlink_metadata().is_ok() {
            ensure!(
                !current.symlink_metadata()?.file_type().is_symlink(),
                "symlinks forbidden"
            );
        }
    }
    if p.exists() {
        ensure!(p.canonicalize()?.starts_with(&base), "path escapes package");
    }
    Ok(p)
}
pub fn platform() -> String {
    let os = match std::env::consts::OS {
        "windows" => "windows",
        "macos" => "macos",
        _ => "linux",
    };
    let arch = match std::env::consts::ARCH {
        "x86_64" => "x64",
        "aarch64" => "arm64",
        x => x,
    };
    format!("{os}-{arch}")
}
fn check_schema(s: &Value, depth: usize) -> Result<()> {
    ensure!(depth <= 32, "schema nesting exceeds limit");
    match s {
        Value::Object(m) => {
            for (k, v) in m {
                ensure!(
                    !["$ref", "$dynamicRef", "$recursiveRef"].contains(&k.as_str()),
                    "schema references are unsupported"
                );
                check_schema(v, depth + 1)?;
            }
        }
        Value::Array(a) => {
            for v in a {
                check_schema(v, depth + 1)?;
            }
        }
        _ => {}
    }
    Ok(())
}
pub fn validate_value(schema: &Value, value: &Value) -> Result<()> {
    let validator = jsonschema::validator_for(schema)?;
    if let Err(e) = validator.validate(value) {
        bail!("schema validation: {e}");
    }
    Ok(())
}
pub fn validate_manifest(bytes: &[u8]) -> Result<Manifest> {
    ensure!(bytes.len() <= 1024 * 1024, "manifest too large");
    let value = parse_unique_json(bytes)?;
    let m: Manifest = serde_json::from_value(value)?;
    ensure!(m.schema_version == 1, "unsupported manifest version");
    ensure!(valid_id(&m.id), "invalid extension id");
    semver::Version::parse(&m.version)?;
    validate_path(&m.entry)?;
    ensure!(
        ["javascript", "executable", "native-library"].contains(&m.kind.as_str()),
        "unknown extension type"
    );
    ensure!(
        !m.platforms.is_empty()
            && m.platforms.iter().all(|p| [
                "any",
                "windows-x64",
                "macos-arm64",
                "linux-x64",
                "linux-arm64"
            ]
            .contains(&p.as_str())),
        "unsupported platform"
    );
    ensure!(
        m.permissions.iter().all(|p| [
            "process.spawn",
            "native.call",
            "filesystem.read",
            "filesystem.write"
        ]
        .contains(&p.as_str())),
        "unknown permission"
    );
    if let Some(plugin) = &m.plugin {
        ensure!(valid_id(&plugin.kind), "invalid plugin kind");
        ensure!(
            plugin.contract.len() <= 128
                && plugin.contract.split('.').count() >= 2
                && plugin.contract.split('.').all(valid_id),
            "invalid plugin contract"
        );
        match plugin.mode.as_str() {
            "mock" => ensure!(
                plugin.transport == "mock",
                "mock plugin requires mock transport"
            ),
            "adapter" => {
                ensure!(
                    ["usb", "serial", "hid", "network", "system", "sdk"]
                        .contains(&plugin.transport.as_str()),
                    "invalid adapter transport"
                );
                let required = match m.kind.as_str() {
                    "executable" => "process.spawn",
                    "native-library" => "native.call",
                    _ => bail!(
                        "adapter plugins require an executable or native-library implementation"
                    ),
                };
                ensure!(
                    m.permissions.iter().any(|p| p == required),
                    "adapter plugin requires explicit native permission"
                );
            }
            _ => bail!("unsupported plugin mode"),
        }
    }
    ensure!(!m.capabilities.is_empty(), "no capabilities");
    for (name, c) in &m.capabilities {
        ensure!(valid_id(name), "invalid capability name");
        ensure!(!c.export.is_empty(), "empty export");
        for s in [&c.input, &c.output] {
            check_schema(s, 0)?;
            jsonschema::validator_for(s)?;
        }
    }
    for paths in m.executables.values() {
        for p in paths.values() {
            validate_path(p)?;
        }
    }
    for l in m.libraries.values() {
        ensure!(l.abi == "c", "unsupported ABI");
        for p in l.paths.values() {
            validate_path(p)?;
        }
        for s in l.symbols.values() {
            ensure!(
                !s.symbol.is_empty() && !s.symbol.contains('\0'),
                "invalid symbol"
            );
            ensure!(
                ["void", "i32", "u32", "f64"].contains(&s.returns.as_str()),
                "unsupported return type"
            );
            ensure!(
                s.parameters.len() <= 32
                    && s.parameters
                        .iter()
                        .all(|p| ["i32", "u32", "f64", "cstring", "buffer"].contains(&p.as_str())),
                "unsupported parameter type"
            );
        }
    }
    Ok(m)
}

// A recursive visitor rejects duplicate fields before typed deserialization.
pub fn parse_unique_json(bytes: &[u8]) -> Result<Value> {
    struct Unique(Value);
    impl<'de> Deserialize<'de> for Unique {
        fn deserialize<D: serde::Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
            struct Visitor;
            impl<'de> serde::de::Visitor<'de> for Visitor {
                type Value = Unique;
                fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                    f.write_str("JSON without duplicate keys")
                }
                fn visit_map<A: serde::de::MapAccess<'de>>(
                    self,
                    mut a: A,
                ) -> std::result::Result<Unique, A::Error> {
                    let mut m = serde_json::Map::new();
                    while let Some((k, v)) = a.next_entry::<String, Unique>()? {
                        if m.insert(k, v.0).is_some() {
                            return Err(serde::de::Error::custom("duplicate JSON key"));
                        }
                    }
                    Ok(Unique(Value::Object(m)))
                }
                fn visit_seq<A: serde::de::SeqAccess<'de>>(
                    self,
                    mut a: A,
                ) -> std::result::Result<Unique, A::Error> {
                    let mut v = Vec::new();
                    while let Some(x) = a.next_element::<Unique>()? {
                        v.push(x.0);
                    }
                    Ok(Unique(Value::Array(v)))
                }
                fn visit_str<E: serde::de::Error>(self, v: &str) -> std::result::Result<Unique, E> {
                    Ok(Unique(Value::String(v.into())))
                }
                fn visit_bool<E: serde::de::Error>(
                    self,
                    v: bool,
                ) -> std::result::Result<Unique, E> {
                    Ok(Unique(Value::Bool(v)))
                }
                fn visit_i64<E: serde::de::Error>(self, v: i64) -> std::result::Result<Unique, E> {
                    Ok(Unique(v.into()))
                }
                fn visit_u64<E: serde::de::Error>(self, v: u64) -> std::result::Result<Unique, E> {
                    Ok(Unique(v.into()))
                }
                fn visit_f64<E: serde::de::Error>(self, v: f64) -> std::result::Result<Unique, E> {
                    Ok(Unique(
                        serde_json::Number::from_f64(v)
                            .ok_or_else(|| E::custom("non-finite"))?
                            .into(),
                    ))
                }
                fn visit_unit<E: serde::de::Error>(self) -> std::result::Result<Unique, E> {
                    Ok(Unique(Value::Null))
                }
            }
            d.deserialize_any(Visitor)
        }
    }
    let mut d = serde_json::Deserializer::from_slice(bytes);
    let v = Unique::deserialize(&mut d)?.0;
    d.end()?;
    Ok(v)
}

/// Validate all runtime resources before a package can become the active version.
pub fn validate_package_resources(
    root: &Path,
    m: &Manifest,
    selected_platform: &str,
) -> Result<()> {
    ensure!(
        m.platforms.iter().any(|p| p == selected_platform),
        "package does not support selected platform"
    );
    let require_file = |relative: &str| -> Result<()> {
        let p = checked_path(root, relative)?;
        ensure!(
            p.metadata()?.is_file(),
            "runtime resource must be a regular file: {relative}"
        );
        Ok(())
    };
    require_file(&m.entry)?;
    ensure!(
        m.kind != "executable" || !m.executables.is_empty(),
        "executable extension declares no programs"
    );
    ensure!(
        m.kind != "native-library" || !m.libraries.is_empty(),
        "native extension declares no libraries"
    );
    for paths in m.executables.values() {
        require_file(
            paths
                .get(selected_platform)
                .ok_or_else(|| anyhow::anyhow!("missing selected-platform executable mapping"))?,
        )?;
    }
    for library in m.libraries.values() {
        require_file(
            library
                .paths
                .get(selected_platform)
                .ok_or_else(|| anyhow::anyhow!("missing selected-platform library mapping"))?,
        )?;
    }
    Ok(())
}
