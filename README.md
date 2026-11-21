# Foundry

**用 JavaScript 描述能力，按需安装跨平台扩展。** Rust 客户端嵌入 QuickJS，统一调用纯 JS、命令行与 libffi 动态库扩展。

当前提供可本地构建和验证的首版实现。正式 GitHub 仓库、生产公钥和 Environment 审批规则尚需管理员配置；不包含生产私钥，也没有已上线的下载地址。已配置 Windows x64、macOS arm64、Linux x64/arm64 的 CI，实际支持状态以这些 runner 的结果为准。macOS 仅提供 arm64（Apple Silicon）客户端及原生扩展产物。Linux x64 发布基线为 Ubuntu 22.04 / glibc 2.35；ARM64 为 Ubuntu 24.04 / glibc 2.39。

## 本地开始

准备 Rust（版本由 rust-toolchain.toml 固定）、Python 3.11+ 及平台 C/C++ 构建工具。Unix 需要 make；libffi 使用随 crate 构建的静态库。Windows 使用 Visual Studio Build Tools 的 MSVC 环境。

```sh
python3 -m pip install -r requirements-ci.txt
cargo build --workspace --locked
python3 scripts/build_extensions.py

./target/debug/foundry dev run extensions/text-utils/0.1.0 normalize --input '{"text":"  hello\r\nworld  "}'
./target/debug/foundry dev run dist/dev/file-digest digest --grant process.spawn --input '{"path":"/absolute/path/to/file"}'
./target/debug/foundry dev run dist/dev/native-math add --grant native.call --input '{"a":2,"b":3}'
```

Windows 使用 `python` 和 `target/debug/foundry.exe`。以上命令使用 POSIX shell 引号；PowerShell 下根据版本可能需要对传给原生程序的 JSON 双引号转义。`dev run` 明确表示信任本地源码，不绕过正式安装的验签。

## 正式安装与调用

官网构建生成 `install.sh` 和 `install.ps1`。安装前通过可信渠道取得 Release 的 `allowed_signers` 公钥文件。脚本使用系统 OpenSSH 验证安装清单的 Ed25519 签名，核对对应平台 ZIP 的大小和 SHA-256，再把客户端与 worker 安装到同一目录。

Linux x64/arm64 和 macOS arm64 可在官网部署后运行：

```sh
curl -fsSL --proto '=https' --proto-redir '=https' https://OWNER.github.io/REPO/install.sh \
  | sh -s -- --allowed-signers ./allowed_signers --install-dir "$HOME/.local/share/foundry-client"
```

Windows x64 使用 PowerShell。保存脚本后，按本机执行策略运行。

```powershell
Invoke-WebRequest https://OWNER.github.io/REPO/install.ps1 -OutFile install.ps1
.\install.ps1 -AllowedSigners .\allowed_signers
```

把示例 URL 换成实际官网地址。安装器默认选择最新正式 Release，也可用 `--version` 或 `-Version` 指定版本。安装路径会在成功后显示，可将该目录加入 PATH。Linux 和 macOS 使用 `curl`、`unzip`、系统 SHA-256 命令和支持 `-Y verify` 的 OpenSSH。Windows 需要启用支持该命令的系统 OpenSSH Client。[安装与发布](docs/publishing.md)

从可信来源获取公钥根文件，配置签名索引：

```sh
foundry --trust-root ./trust-root.json --index https://YOUR-TRUSTED-HOST/registry/index.json install text-utils
foundry --trust-root ./trust-root.json --index https://YOUR-TRUSTED-HOST/registry/index.json download native-math --output ./native-math.zip
# get 是 download 的别名
foundry --trust-root ./trust-root.json --index https://YOUR-TRUSTED-HOST/registry/index.json get text-utils
foundry run text-utils normalize --input '{"text":"  hello  "}'
foundry list
foundry uninstall text-utils
```

`YOUR-TRUSTED-HOST` 是待部署的真实地址，不是现成服务。可将公共根文件放在用户数据目录的 `trust-root.json`，使用 `FOUNDRY_INDEX` 配置索引。显式本地索引文件用于签名离线镜像，仍必须通过验签。

```text
search / info / install / download (get) / run / list / upgrade / uninstall
--data-dir <path>  --index <source>  --trust-root <path>
--timeout-ms <1..30000>  --json
```

默认输出均为 JSON，错误写 stderr。新增原生执行权限必须使用 `--grant process.spawn` 或 `--grant native.call` 授权；交互安装可确认，非交互默认拒绝。`foundry-worker` 必须与客户端放在同一目录。

`download` 只下载并验证签名索引中的当前平台 ZIP，不解压、不安装、不执行扩展；默认写入 `<id>-<version>-<platform>.zip`，覆盖已有文件需要显式 `--force`。`install` 内部也会执行同样的下载和完整性校验。

## 基础扩展与设备插件

| 扩展           | 类型                    | 能力                              | 源码                                                    |
| -------------- | ----------------------- | --------------------------------- | ------------------------------------------------------- |
| text-utils     | javascript              | normalize                         | [extensions/text-utils](extensions/text-utils/)         |
| file-digest    | executable              | digest（SHA-256）                 | [extensions/file-digest](extensions/file-digest/)       |
| native-math    | native-library          | add、hypot                        | [extensions/native-math](extensions/native-math/)       |
| id-card-reader | javascript / 读卡器插件 | devices、read-card（模拟身份证）  | [extensions/id-card-reader](extensions/id-card-reader/) |
| camera         | javascript / 摄像头插件 | devices、capture（模拟单帧 PNG）  | [extensions/camera](extensions/camera/)                 |
| ocr            | javascript / OCR 插件   | recognize（固定模拟识别结构）     | [extensions/ocr](extensions/ocr/)                       |
| serial-port    | javascript / 串口插件   | devices、exchange（模拟请求响应） | [extensions/serial-port](extensions/serial-port/)       |

它们使用同一发布流程和正式索引，不是单独的示例项目。发布产物只包含运行文件，原生源码留在仓库供开发者参考。

## 设备、识别与接口插件

插件用途由可选的 `plugin` 字段描述，与 JS/命令行/动态库实现类型独立。例如身份证读卡器使用 `plugin.kind: id-card-reader` 和 `contract: foundry.id-card.v1`，返回固定字段的 JSON。更换 SDK 适配器时保持同一个数据合同。

```sh
./target/debug/foundry dev run extensions/id-card-reader/0.1.0 read-card --input '{}'
./target/debug/foundry dev run extensions/camera/0.1.0 capture --input '{}'
./target/debug/foundry dev run extensions/serial-port/0.1.0 exchange --input '{"message":"PING"}'
python3 scripts/test_device_plugins.py
```

四个设备/识别插件当前均为 `mode: mock`，不访问真实硬件，也不运行真实 OCR 引擎。身份证数据使用明确的虚构信息和无效地区码，照片为 null。真实设备需要独立的已编译 CLI 或 libffi SDK 桥接适配器，并显式授权原生执行；本项目不附带任何厂商 SDK。详情与固定数据结构见 [插件指南](docs/plugins.md)。

## 快速创建扩展

从 Foundry 仓库根目录运行以下命令，生成的扩展即可交给仓库的构建和 CI。示例假设 `foundry` 已加入 PATH，也可以使用 `./target/debug/foundry`。

```sh
foundry new
```

在终端直接运行 `foundry new` 会打开向导，依次填写扩展 ID、类型、初始版本和输出父目录。带默认值的选项可直接回车。用 `-i` 或 `--interactive` 可显式打开向导，命令行已提供的选项会跳过。

自动化脚本可以一次传入全部参数。命令无需读取标准输入，成功时在标准输出返回 JSON。

```sh
foundry new --id my-library --type native-library --version 1.0.0 --output extensions
```

也可以把扩展 ID 写成位置参数，并省略使用默认值的选项。

```sh
foundry new my-extension
foundry dev run extensions/my-extension/0.1.0 echo --input '{"value":42}'
foundry new my-command --type executable
```

`new` 默认创建 `extensions/<id>/0.1.0/`，生成版本元数据、manifest、QuickJS 入口和四平台的 `presubmit.yml`。两种原生模板还附带独立的 Rust crate 和锁文件，由仓库的构建流程编译并随扩展分发成品。

`--output <目录>` 可以指定扩展的父目录。已有的扩展目录会保留，命令会报错退出。原生模板可以用下文的 `scripts/test_extension.py` 构建并测试，例如在 Linux x64 上运行 `python3 scripts/test_extension.py --extension my-library --version 1.0.0 --platform linux-x64`。

`foundry new` 在任意目录都可离线创建扩展。默认输出到当前目录下的 `extensions/`，也可以用 `--output` 指定相对或绝对路径。命令不初始化 Git，也不会切换或创建分支。在其他 Git 仓库或普通目录生成的纯 JS 扩展可以直接用 `foundry dev run` 试跑。需要使用中心仓库的构建和 CI 时，把生成的整个扩展目录放到 Foundry 仓库的 `extensions/` 下。

客户端 CI 在四个平台上实际生成三种模板，使用仓库构建流程编译并打包，再从用临时测试密钥签名的本地索引安装 ZIP 并运行生成的测试任务。在 Linux x64 上可用 `python3 scripts/test_scaffold.py --platform linux-x64` 复现。

## 中心仓库式扩展 CI

扩展按 `extensions/<id>/<version>/` 保存。根目录的 `metadata.json` 列出所有版本及撤回原因；每个版本自带 `manifest.json`、JS 接口、原生构建源码和 `presubmit.yml`。版本号独立于客户端版本，当前支持稳定 SemVer `x.y.z`。

成品 ZIP 也可托管在第三方 HTTPS 地址。在 `packages.yaml` 中按平台填写 URL 和 SHA-256，文件大小由 CI 自动获取。[第三方托管的 ZIP](docs/registry.md#第三方托管的-zip)

```text
extensions/native-math/
  metadata.json                 # versions、yanked_versions
  0.1.0/
    manifest.json               # 类型、能力、权限和平台
    main.js
    native/                     # 仅供 CI 构建，不进入下载包
    presubmit.yml               # 该版本的平台、构建产物和测试断言
```

`.github/workflows/extensions.yml` 按 PR 修改的扩展和版本生成独立矩阵，共享运行时变动会测试全部版本。规划器使用 PR 基准提交中的可信代码解析配置。平台只允许预设的 GitHub 托管 runner，不接受自托管 runner 或任意 shell 测试命令。配置中的 `tasks` 通过客户端调用能力并检查 JSON 结果，原生扩展测试打包后的二进制。PR 构建不接触生产密钥；详见 [安全模型](docs/security.md)。

```sh
python3 scripts/test_extension.py --extension native-math --version 0.1.0 --platform linux-x64
python3 scripts/extension_matrix.py --extension native-math --version 0.1.0
# 已配置索引和公钥根后，也可指定历史版本
foundry install native-math --version 0.1.0 --grant native.call
foundry get native-math --version 0.1.0 --output native-math.zip
```

PR 会生成独立的 **Extension review diff**：在 Actions Summary 展示版本、类型、权限、能力及平台变化，附带 manifest、JS、原生源码、测试配置和元数据的文件 diff；同时上传 Markdown/JSON 报告。新增版本与基准分支中最近的较低版本比较，已有版本与基准提交中的同版本比较，即使不可变性校验失败也会独立展示 diff。

每个受影响版本按声明分别运行 Linux x64/arm64、macOS arm64、Windows x64 的测试；当前七个正式扩展均声明全部四个平台。任务名称包含扩展、版本、平台，运行日志保存在对应 artifact。稳定的 **Extension checks** 检查汇总 diff、规划和平台测试结果，适合设置为分支保护的必需检查；客户端与分发测试另有四平台矩阵。

已合并的版本目录不可修改或删除，修复必须新增版本；可在 `yanked_versions` 中撤回有问题版本。新索引不再提供已撤回版本的新安装或下载，不删除用户已安装版本。发布保留历史包的原始 URL、大小和哈希，不重新编译覆盖旧包。完整配置见 [版本与独立测试](docs/registry.md)。

## 测试与官网

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
cargo build --workspace --locked
python3 scripts/test_distribution.py
python3 scripts/test_device_plugins.py
python3 scripts/test_native_isolation.py
python3 scripts/test_host_files.py
python3 scripts/test_release_pipeline.py
python3 scripts/test_registry.py
python3 scripts/test_extension_diff.py
npm ci --prefix website
npm run check --prefix website
npm run build --prefix website
npm run dev --prefix website
```

网站是 Astro 静态站。主分支更新自动编译并推送 `gh-pages`；GitHub Pages 设置为从该分支根目录发布。没有正式签名索引时页面明确展示尚未发布状态。所有 GitHub Actions 固定到提交 SHA。

## 开发与安全

代码格式及贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。运行 `python3 scripts/format_code.py` 统一格式，CI 使用 `--check` 校验。

- [扩展格式](docs/extension-format.md)
- [设备插件与数据合同](docs/plugins.md)
- [宿主 API](docs/host-api.md)
- [libffi / C ABI](docs/ffi.md)
- [安全边界与密钥轮换](docs/security.md)
- [发布与 GitHub 配置](docs/publishing.md)
- [实施计划](docs/superpowers/plans/2026-11-07-foundry.md)

签名证明授权和完整性，不能证明扩展没有恶意。原生代码在独立进程运行；这用于故障隔离，不提供 OS 强沙箱。授权原生代码意味着信任它以当前用户权限运行。
