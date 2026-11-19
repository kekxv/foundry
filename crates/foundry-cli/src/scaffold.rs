use anyhow::{Context, Result, bail, ensure};
use clap::{Args, ValueEnum};
use serde_json::{Value, json};
use std::{
    fs::{self, File},
    io::{self, BufRead, IsTerminal, Write},
    path::{Path, PathBuf},
};

const DEFAULT_VERSION: &str = "0.1.0";
const DEFAULT_OUTPUT: &str = "extensions";
const PLATFORMS: &str = r#"["linux-x64", "linux-arm64", "macos-arm64", "windows-x64"]"#;
const JAVASCRIPT: &str = "export async function echo({value}) {\n  return {value};\n}\n";
const EXECUTABLE_JS: &str = r#"export async function echo({value}) {
  const result = await host.exec('echo', [String(value)]);
  if (result.exitCode !== 0) throw new Error(result.stderr);
  return {value: Number(result.stdout.trim())};
}
"#;
const LIBRARY_JS: &str = r#"export async function echo({value}) {
  return {value: await host.library('echo').call('echo', [value])};
}
"#;
const EXECUTABLE_RS: &str = r#"fn main() -> Result<(), Box<dyn std::error::Error>> {
    let value: i32 = std::env::args()
        .nth(1)
        .ok_or("expected an integer")?
        .parse()?;
    println!("{value}");
    Ok(())
}
"#;
const LIBRARY_RS: &str = r#"#[unsafe(no_mangle)]
pub extern "C" fn foundry_echo(value: i32) -> i32 {
    value
}
"#;
const EXECUTABLES: &str = r#",
  "executables": {
    "echo": {
      "linux-x64": "bin/foundry-extension",
      "linux-arm64": "bin/foundry-extension",
      "macos-arm64": "bin/foundry-extension",
      "windows-x64": "bin/foundry-extension.exe"
    }
  }"#;
const LIBRARIES: &str = r#",
  "libraries": {
    "echo": {
      "abi": "c",
      "paths": {
        "linux-x64": "lib/libfoundry_extension.so",
        "linux-arm64": "lib/libfoundry_extension.so",
        "macos-arm64": "lib/libfoundry_extension.dylib",
        "windows-x64": "lib/foundry_extension.dll"
      },
      "symbols": {
        "echo": {
          "symbol": "foundry_echo",
          "parameters": ["i32"],
          "returns": "i32"
        }
      }
    }
  }"#;

#[derive(Args)]
pub struct NewExtension {
    /// New extension ID (omit both ID forms in a terminal to open the wizard)
    id: Option<String>,
    /// New extension ID as a named option for scripts
    #[arg(long = "id", value_name = "ID", conflicts_with = "id")]
    named_id: Option<String>,
    /// Prompt for any settings not supplied on the command line
    #[arg(short, long)]
    interactive: bool,
    /// Runtime template (default: javascript)
    #[arg(long = "type", value_enum)]
    kind: Option<ExtensionType>,
    /// Initial stable version (default: 0.1.0)
    #[arg(long)]
    version: Option<semver::Version>,
    /// Parent directory for the new extension (default: extensions)
    #[arg(long)]
    output: Option<PathBuf>,
}

struct ExtensionSpec {
    id: String,
    kind: ExtensionType,
    version: semver::Version,
    output: PathBuf,
}

#[derive(Clone, Copy, Default, ValueEnum)]
enum ExtensionType {
    #[default]
    Javascript,
    Executable,
    NativeLibrary,
}

impl NewExtension {
    pub fn create(&self) -> Result<Value> {
        let id = self.id.as_deref().or(self.named_id.as_deref());
        if self.interactive
            || (id.is_none() && io::stdin().is_terminal() && io::stderr().is_terminal())
        {
            return self
                .wizard(id, &mut io::stdin().lock(), &mut io::stderr().lock())?
                .create();
        }
        let Some(id) = id else {
            bail!(
                "provide an extension ID with --id or as a positional argument, or pass --interactive"
            );
        };
        ExtensionSpec {
            id: id.to_owned(),
            kind: self.kind.unwrap_or_default(),
            version: self
                .version
                .clone()
                .unwrap_or_else(|| semver::Version::new(0, 1, 0)),
            output: self
                .output
                .clone()
                .unwrap_or_else(|| PathBuf::from(DEFAULT_OUTPUT)),
        }
        .create()
    }

    fn wizard(
        &self,
        id: Option<&str>,
        input: &mut impl BufRead,
        messages: &mut impl Write,
    ) -> Result<ExtensionSpec> {
        // Check supplied options before prompting for missing settings.
        if let Some(id) = id {
            validate_id(id)?;
        }
        if let Some(version) = &self.version {
            validate_version(version)?;
        }
        if let Some(output) = &self.output {
            validate_output(output)?;
        }

        let id = match id {
            Some(id) => id.to_owned(),
            None => prompt(input, messages, "Extension ID", None, |answer| {
                validate_id(answer)?;
                Ok(answer.to_owned())
            })?,
        };
        let kind = match self.kind {
            Some(kind) => kind,
            None => prompt(
                input,
                messages,
                "Template (javascript, executable, native-library)",
                Some("javascript"),
                |answer| ExtensionType::from_str(answer, true).map_err(anyhow::Error::msg),
            )?,
        };
        let version = match &self.version {
            Some(version) => version.clone(),
            None => prompt(
                input,
                messages,
                "Stable version",
                Some(DEFAULT_VERSION),
                |answer| {
                    let version = semver::Version::parse(answer)?;
                    validate_version(&version)?;
                    Ok(version)
                },
            )?,
        };
        let output = match &self.output {
            Some(output) => output.clone(),
            None => prompt(
                input,
                messages,
                "Parent directory",
                Some(DEFAULT_OUTPUT),
                |answer| {
                    let output = PathBuf::from(answer);
                    validate_output(&output)?;
                    Ok(output)
                },
            )?,
        };
        Ok(ExtensionSpec {
            id,
            kind,
            version,
            output,
        })
    }
}

fn prompt<T>(
    input: &mut impl BufRead,
    messages: &mut impl Write,
    label: &str,
    default: Option<&str>,
    parse: impl Fn(&str) -> Result<T>,
) -> Result<T> {
    loop {
        write!(messages, "{label}")?;
        if let Some(default) = default {
            write!(messages, " [{default}]")?;
        }
        write!(messages, ": ")?;
        messages.flush()?;
        let mut line = String::new();
        if input.read_line(&mut line)? == 0 {
            bail!("extension creation cancelled: end of input");
        }
        let answer = line.trim();
        let answer = if answer.is_empty() {
            default.unwrap_or("")
        } else {
            answer
        };
        match parse(answer) {
            Ok(value) => return Ok(value),
            Err(error) => writeln!(messages, "{error}")?,
        }
    }
}

fn validate_id(id: &str) -> Result<()> {
    ensure!(
        foundry_core::valid_id(id),
        "extension ID must start with a lowercase letter or digit and contain at most 64 lowercase letters, digits, or hyphens"
    );
    foundry_core::validate_path(id)
}

fn validate_version(version: &semver::Version) -> Result<()> {
    ensure!(
        version.pre.is_empty() && version.build.is_empty(),
        "registry requires stable SemVer x.y.z"
    );
    Ok(())
}

fn validate_output(output: &Path) -> Result<()> {
    ensure!(
        !output.as_os_str().is_empty(),
        "output path must not be empty"
    );
    ensure!(output.to_str().is_some(), "output path must be UTF-8");
    Ok(())
}

impl ExtensionSpec {
    fn create(&self) -> Result<Value> {
        validate_id(&self.id)?;
        validate_version(&self.version)?;
        validate_output(&self.output)?;

        let id = &self.id;
        let version = self.version.to_string();
        let kind = self.kind.to_possible_value().unwrap();
        let kind = kind.get_name();
        let (entry, platforms, permissions, resources) = match self.kind {
            ExtensionType::Javascript => (JAVASCRIPT, r#"["any"]"#, "[]", ""),
            ExtensionType::Executable => (
                EXECUTABLE_JS,
                PLATFORMS,
                r#"["process.spawn"]"#,
                EXECUTABLES,
            ),
            ExtensionType::NativeLibrary => {
                (LIBRARY_JS, PLATFORMS, r#"["native.call"]"#, LIBRARIES)
            }
        };

        let manifest = format!(
            r#"{{
  "schemaVersion": 1,
  "id": "{id}",
  "version": "{version}",
  "description": "Echo an integer",
  "type": "{kind}",
  "entry": "main.js",
  "platforms": {platforms},
  "permissions": {permissions},
  "capabilities": {{
    "echo": {{
      "description": "Echo an integer",
      "export": "echo",
      "input": {{
        "type": "object",
        "additionalProperties": false,
        "properties": {{
          "value": {{
            "type": "integer",
            "minimum": -2147483648,
            "maximum": 2147483647
          }}
        }},
        "required": ["value"]
      }},
      "output": {{
        "type": "object",
        "additionalProperties": false,
        "properties": {{"value": {{"type": "integer"}}}},
        "required": ["value"]
      }}
    }}
  }}{resources}
}}
"#
        );
        foundry_core::validate_manifest(manifest.as_bytes())?;
        let metadata = format!(
            r#"{{
  "id": "{id}",
  "versions": ["{version}"],
  "yanked_versions": {{}},
  "maintainers": []
}}
"#
        );

        let mut files = vec![
            (PathBuf::from("metadata.json"), metadata),
            (Path::new(&version).join("manifest.json"), manifest),
            (Path::new(&version).join("main.js"), entry.to_owned()),
        ];
        let mut presubmit = String::from(
            "matrix:\n  platform: [linux-x64, linux-arm64, macos-arm64, windows-x64]\n",
        );
        if let Some(native) = match self.kind {
            ExtensionType::Javascript => None,
            ExtensionType::Executable => Some((
                "",
                "main.rs",
                EXECUTABLE_RS,
                "foundry-extension{exe}",
                "bin/foundry-extension{exe}",
            )),
            ExtensionType::NativeLibrary => Some((
                "\n[lib]\ncrate-type = [\"cdylib\"]\n",
                "lib.rs",
                LIBRARY_RS,
                "{library_prefix}foundry_extension{library_suffix}",
                "lib/{library_prefix}foundry_extension{library_suffix}",
            )),
        } {
            let (lib, file, source, artifact, target) = native;
            let dir = Path::new(&version).join("native");
            files.extend([
                (
                    dir.join("Cargo.toml"),
                    format!(
                        "[package]\nname = \"foundry-extension\"\nversion = \"{version}\"\nedition = \"2024\"\n{lib}\n[workspace]\n"
                    ),
                ),
                (
                    dir.join("Cargo.lock"),
                    format!(
                        "# This file is automatically @generated by Cargo.\n# It is not intended for manual editing.\nversion = 4\n\n[[package]]\nname = \"foundry-extension\"\nversion = \"{version}\"\n"
                    ),
                ),
                (dir.join("src").join(file), source.to_owned()),
            ]);
            presubmit.push_str(&format!(
                "build:\n  cargo_manifest: native/Cargo.toml\n  artifacts:\n    - from: '{artifact}'\n      to: '{target}'\n"
            ));
        }
        presubmit.push_str(
            "tasks:\n  echo:\n    capability: echo\n    input: {value: 42}\n    expect: {value: 42}\n",
        );
        files.push((Path::new(&version).join("presubmit.yml"), presubmit));

        fs::create_dir_all(&self.output)
            .with_context(|| format!("create parent directory {}", self.output.display()))?;
        let directory = self.output.join(id);
        fs::create_dir(&directory)
            .with_context(|| format!("create new extension directory {}", directory.display()))?;
        if let Err(error) = write_files(&directory, files) {
            if let Err(cleanup) = fs::remove_dir_all(&directory) {
                return Err(error.context(format!(
                    "could not clean up {}: {cleanup}",
                    directory.display()
                )));
            }
            return Err(error);
        }
        Ok(json!({
            "id": id,
            "version": version,
            "type": kind,
            "directory": directory,
            "source": directory.join(version),
        }))
    }
}

fn write_files(directory: &Path, files: Vec<(PathBuf, String)>) -> Result<()> {
    for (relative, contents) in files {
        let path = directory.join(relative);
        fs::create_dir_all(path.parent().unwrap())?;
        File::create_new(&path)
            .and_then(|mut file| file.write_all(contents.as_bytes()))
            .with_context(|| format!("write {}", path.display()))?;
    }
    Ok(())
}
