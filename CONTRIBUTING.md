# 开发与代码风格

客户端用户只需要发布的可执行文件；以下工具仅用于维护仓库。

## 格式约定

| 文件                                 | 工具与配置                                                    |
| ------------------------------------ | ------------------------------------------------------------- |
| Python                               | YAPF 的 Google 配置，isort 的 Google profile，80 列、4 空格   |
| JavaScript / TypeScript              | Prettier，复用 Google GTS 7.0.0 的四项格式选项，80 列、2 空格 |
| Astro / CSS / JSON / YAML / Markdown | Prettier 与 Astro 插件，统一2空格和LF换行                     |
| Rust                                 | 标准 rustfmt，100 列、4 空格；包括独立 native 扩展工作区      |

Google GTS 选项是 `bracketSpacing: false`、`singleQuote: true`、`trailingComma: all`、`arrowParens: avoid`。Google 没有覆盖本仓库全部语言的单一格式工具，因此 Rust 和 Astro 等使用上述明确约定；不将其称为 Google 官方样式。

格式化工具固定在 requirements-dev.txt 与 website/package-lock.json。编辑器遵循 .editorconfig；文本产物使用 .gitattributes 中的 LF 约定，确保跨平台 JS 包摘要稳定。

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm ci --prefix website

# 格式化所有维护的源码、配置与文档
python3 scripts/format_code.py

# CI 使用的只读格式检查
python3 scripts/format_code.py --check
```

Windows 使用 python 创建虚拟环境，并通过 `.venv\Scripts\Activate.ps1` 激活。格式工具不会处理 target、dist、node_modules、临时密钥和缓存；生成的 Cargo.lock/package-lock.json 保留各自包管理器格式。

## 本地验证

```sh
cargo test --workspace --locked
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo build --workspace --locked
python3 scripts/test_registry.py
python3 scripts/test_extension_diff.py
python3 scripts/test_release_pipeline.py
python3 scripts/test_device_plugins.py
python3 scripts/test_distribution.py
python3 scripts/test_native_isolation.py
python3 scripts/test_host_files.py
npm run check --prefix website
FOUNDRY_BASE=/foundry/ npm run build --prefix website
```

CI 的 **Code style** 检查会阻止未格式化的修改。PR 同时运行版本 diff、独立扩展测试，以及 Windows x64、macOS arm64、Linux x64/arm64 的客户端/分发测试；实际平台结果以对应 runner 为准。

## 目录与提交

- crates/：客户端、QuickJS、worker、可信存储与公共格式。
- tools/：维护者签名及打包工具。
- extensions/&lt;id&gt;/&lt;version&gt;/：正式版本输入与独立 presubmit。
- scripts/：构建、验证、PR 报告及格式入口。
- schemas/：manifest、索引与设备插件合同。
- website/：官网与扩展目录。
- docs/：格式、安全边界、设备接入、发布说明及设计记录。

首次提交前可以统一格式；版本进入基准分支后，不原地重写已存在版本的文件，后续修改应新增版本，遵循 [版本规则](docs/registry.md)。不要提交 target/dist、依赖目录、真实业务数据或签名私钥。生产密钥仅由受保护的签名 Environment 注入。
