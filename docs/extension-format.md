# 扩展格式 v1

扩展发布为按平台区分的 ZIP，以 `manifest.json` 为入口描述。正式实现位于 `extensions/`，用于学习和复用，不另设 examples。

必填字段：`schemaVersion: 1`、`id`（小写字母/数字/连字符，最多 64 字符）、SemVer `version`、`description`、`type`、`entry`、`platforms`、`permissions`、`capabilities`。未知字段、重复 JSON 键、未知版本和权限被拒绝。结构定义见 `schemas/manifest.schema.json`，运行时 Rust 验证器是执行边界。

`type` 为 `javascript`、`executable`、`native-library`。纯 JS 使用 `platforms: ["any"]`；原生扩展按 windows-x64、macos-arm64、linux-x64、linux-arm64 分发。平台标识不承诺不同 glibc 版本兼容，发布者须记录构建基线。

每项能力形如：

```json
{
  "normalize": {
    "description": "Normalize whitespace",
    "export": "normalize",
    "input": {
      "type": "object",
      "properties": {"text": {"type": "string"}},
      "required": ["text"]
    },
    "output": {
      "type": "object",
      "properties": {"text": {"type": "string"}},
      "required": ["text"]
    }
  }
}
```

`input/output` 使用 JSON Schema Draft 2020-12，首版拒绝所有 `$ref`、`$dynamicRef`、`$recursiveRef`。Schema 嵌套不超过 32 层，整个 manifest 不超过 1 MiB；JSON 输入输出各不超过 1 MiB。能力接收一个 JSON 值，返回 JSON 值或 Promise。禁止 undefined、BigInt、非有限数字、循环对象和自定义 toJSON；对象应为普通 JSON 对象；拒绝访问器和自定义原型，序列化经过验证的单次快照。

包内路径是 UTF-8、用 `/` 分隔的规范相对路径。禁绝对路径、空路径段、`..`、反斜杠、驱动器名、控制字符、Windows 保留名、符号链接和大小写冲突。主模块与依赖只允许包内相对导入，不允许 URL、Node 内置模块或 QuickJS std/os。

命令行扩展的 `executables` 是程序 ID → 平台 → 相对文件名的映射；动态库 `libraries` 的格式见 [ffi.md](ffi.md)。宿主调用必须同时满足 manifest 声明和调用者授权。

`files.json` 由打包器生成，键为文件相对路径，值为 `{size, sha256}`，覆盖除清单自身之外的全部运行文件。已签名索引绑定 ZIP SHA-256 和大小；安装时检查 ZIP 与逐文件清单，运行前复查，并校验安装时记录的清单摘要。额外文件、修改文件和链接均会拒绝。

当前打包器包含 manifest、所有运行 JS 文件、所选平台声明的程序和库；不会自动包含任意资源、原生源码、README 或隐式动态库依赖。原生扩展应静态链接非系统依赖；若需要任意资源或额外共享库，先扩展资源声明规范，再使用这些能力，不能依赖目录碰巧被打包。

`search/info` 首版展示签名索引中的 ID、版本、平台和摘要；完整能力与权限可在官网和安装授权时查看。暂不做依赖求解、自动按能力安装或任意 JS 包解析。

## 设备/功能插件元数据

可选 `plugin` 对象独立于 `type`：`kind` 为稳定的小写标识（例如 id-card-reader、camera、ocr、serial），`mode` 为 mock 或 adapter，`transport` 为 mock、usb、serial、hid、network、system 或 sdk，`contract` 为带命名空间的数据合同标识（例如 foundry.id-card.v1）。不允许未知字段。

mock 模式必须使用 mock transport；adapter 模式使用 executable/process.spawn 或 native-library/native.call 组合并显式声明权限。`transport` 只是适配器说明，不会自动开放 USB、网络或其他宿主能力。合同通过 capability.output 内嵌的 JSON Schema 强制校验，不依赖远程引用。具体字段和厂商接入方式见 [plugins.md](plugins.md)。
