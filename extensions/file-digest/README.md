# file-digest

命令行扩展，digest 读取指定文件并返回 SHA-256；需要 process.spawn，允许原生程序按当前用户权限读取文件。

这是正式扩展，与项目一同发布；同时作为开发相应类型扩展的参考。接口和平台声明见 manifest.json，QuickJS 包装见 main.js，原生实现（如有）见 native/。

先在仓库根目录运行 `cargo build --workspace` 和 `python3 scripts/build_extensions.py`。纯 JS 可直接 dev run 本目录；原生扩展请 dev run 打包脚本生成的 `dist/dev/file-digest`，并显式授权权限。

发布通过正式签名索引，不能把本地开发加载当作验签。详细调用命令见根 README 和 docs/。
