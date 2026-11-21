# 版本化中心仓库与扩展测试

布局为 `extensions/<id>/metadata.json` 及 `extensions/<id>/<version>/`。每个版本都是完整、不可变的发布输入，原生 crate 使用独立 Cargo workspace 和自己的 Cargo.lock，因此可以同时保留多个版本。

```json
{
  "id": "native-math",
  "versions": ["0.1.0", "0.2.0"],
  "yanked_versions": {"0.1.0": "存在缺陷，请升级"},
  "maintainers": []
}
```

上面展示元数据格式，实际目录必须与 versions 完全一致。当前只接受稳定版本 `x.y.z`，没有预发布版本或版本范围解析。客户端不指定 `--version` 时选当前平台可用的最高版本；显式指定可下载未撤回的历史版本。已撤回版本从下一份签名索引移除，阻止新的安装和下载；既有安装可以离线运行。撤回不等于从磁盘删除。

每个版本的 `presubmit.yml` 是数据配置，不是 shell 脚本：

```yaml
matrix:
  platform: [linux-x64, linux-arm64, macos-arm64, windows-x64]
build:
  cargo_manifest: native/Cargo.toml
  artifacts:
    - from: '{library_prefix}foundry_native_math{library_suffix}'
      to: 'lib/{library_prefix}foundry_native_math{library_suffix}'
tasks:
  add:
    capability: add
    input: {a: 2, b: 3}
    expect: {result: 5}
```

纯 JS 省略 build。命令行扩展可用 `{exe}` 展开 Windows 的 `.exe` 后缀，动态库占位符按平台展开；产物必须匹配 manifest 中的运行路径。原生版本的测试矩阵必须覆盖 manifest 声明的全部平台。当前构建适配器为 Cargo，可接收任何提供 C ABI 的预编译动态库；其他语言的 CI 构建适配器尚未实现。最终用户只下载成品 ZIP，无须 Cargo 或编译器。

每个任务调用 manifest 中的一个 capability，比较 JSON 返回值。`input` 中字符串 `$fixture` 会替换为含 `abc` 的临时测试文件绝对路径。任务不支持任意 shell。构建脚本和运行文件仍属于不可信原生代码，安全边界见 [security.md](security.md)。

```sh
python3 -m pip install -r requirements-ci.txt
cargo build --workspace --locked
python3 scripts/test_extension.py --extension native-math --version 0.1.0 --platform linux-x64
python3 scripts/build_extensions.py --extension native-math --version 0.1.0 --out dist
```

版本产物暂存于 `dist/versions/<id>/<version>/`；`dist/dev/<id>/` 是本次构建的最新可用版本的开发便捷副本。包只包含 manifest、JS 和已编译产物，native 源码和 presubmit 不进入包。

新增版本时复制上一版本目录、修改 manifest.version、更新根 metadata.versions，并运行该版本 presubmit。PR CI 从基准提交加载可信规划器，只测试改动版本；修改共享运行时、打包工具或工作流则测试所有版本。根元数据变化测试对应扩展的全部版本，包括已撤回版本。扩展测试工作流仅在 PR 上运行。可用本页命令在本地指定扩展和版本。不受信任的配置不能选择 self-hosted runner。

版本目录一旦存在于基准提交便不能原地修改，连测试配置也保持不可变。修复旧版代码或测试应新增版本，撤回原因只改根元数据。维护者必须审核 metadata 与工作流变更；maintainers 字段目前记录联系人，不授予自动合并或签名权限。

## 第三方托管的 ZIP

扩展作者可以把成品 ZIP 托管在公开的 HTTPS 地址。仓库中保留 `metadata.json`、对应版本的 `manifest.json`、`presubmit.yml` 和 `packages.yaml`。纯 JS 使用 `any`，原生扩展按 manifest 声明的平台分别填写。

```yaml
any:
  url: https://downloads.example.org/my-extension-1.0.0-any.zip
  sha256: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
```

用 `foundry-release pack` 生成 ZIP 和对应的 SHA-256 与字节数。ZIP 包内的 `manifest.json` 必须与仓库声明一致。使用外部 ZIP 时，`presubmit.yml` 保留平台和测试任务，省略 `build`。各平台 CI 使用 Foundry 的下载和校验代码，核对大小、SHA-256、文件清单及 manifest 后运行测试。

GitHub Pages 托管的自建扩展 ZIP 单文件最多 100 MiB。第三方 ZIP 的下载上限为 250 MiB（262144000 字节）。下载第三方 ZIP 前，CI 用 `curl --head` 获取最终 HTTPS 地址的 `Content-Length`，并据此限制下载。下载后严格核对字节数和 SHA-256。配置中的 `size` 可省略，填写时仅作字节数参考。旧版 `packages.json` 仍可读取，每个版本只使用一种格式。

正式发布把 URL、SHA-256 和大小写入 GitHub Pages 的签名索引。客户端执行 `foundry download <id>` 或 `foundry install <id>` 时直接从配置的 HTTPS 地址下载，并按索引核对包的大小和摘要。URL、大小或摘要变化时，请发布新的扩展版本。

签名索引的 `withdrawnPackages` 保留已撤回包的原始记录，客户端只从 `packages` 选择安装。撤回后恢复发布会复用原来的包及 URL，不允许借撤回重写历史二进制。

## PR 审查 diff 与平台结果

`Extension review diff` 在每个 PR 中独立运行，向 Actions Summary 写入报告，并上传 `extension-review-diff-<PR号>` artifact，包含 report.md 和 report.json。它与规划/测试任务并行，因此违规修改历史版本时，审查者仍能看到修改内容。

新增版本对比 PR 基准提交中最近的较低版本；同一 PR 添加多个版本时，每个版本仍对比基准提交，不拿 PR 自己新增的版本冒充可信历史。历史版本的原地修改/删除对比基准中的同版本，并标明不可变性违规。元数据撤回、恢复和文档修改单独展示。报告包含语义变化以及 manifest、JS、原生源文件、presubmit 和其他版本文件的 unified diff。

报告仅从 Git 中读取基准和 HEAD 的已提交对象，不读取或执行候选扩展。拒绝符号链接和子模块；二进制/超大文件只报告 Git blob ID 和大小。文本、文件数量和报告总量有限额，达到上限会明确提示 omitted/truncated，不会假装已展示全部内容。不存在的基准直接失败。

本地已有提交时可以运行（BASE_SHA 替换为完整基准提交哈希）：

```sh
python3 scripts/extension_diff.py --base BASE_SHA --output dist/pr-diff.md --json-output dist/pr-diff.json
```

当前正式扩展的独立测试矩阵：

| 平台        | GitHub 托管 runner |
| ----------- | ------------------ |
| Linux x64   | ubuntu-22.04       |
| Linux arm64 | ubuntu-24.04-arm   |
| macOS arm64 | macos-15           |
| Windows x64 | windows-2022       |

每个版本的任务显示为 `<id>@<version> / <platform>`，将测试输出上传为 `extension-test-<id>-<version>-<platform>`，并在该任务 Summary 记录测试状态。准备/构建阶段失败时可能没有测试 artifact，此时查看 job 日志；失败仍会阻止整体检查通过。客户端 Rust、真实签名分发和报告回归测试也在四个平台矩阵运行。

建议将 **Extension checks** 设置为必需检查。它会在上游失败或跳过时仍然运行：规划失败、PR diff 失败、任一平台失败/取消都会失败；确实没有受影响版本时允许跳过平台测试。不要仅把某个动态矩阵任务设为唯一的必需检查。

首次启用需先将可信 diff 工具合入基准分支，PR 不会回退执行自己提供的报告脚本。将提交推送至真实仓库并创建 PR 后，才会产生对应的 PR diff 和托管平台运行结果。

扩展检查工作流不对 PR 事件设置路径过滤：纯文档/网站 PR 也会完成固定检查，规划器返回空矩阵后跳过原生平台测试，避免必需检查永久停留 Pending。
