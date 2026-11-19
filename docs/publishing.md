# 发布与部署

## 一次性 GitHub 配置

1. 推送到真实 GitHub 仓库，默认分支使用 `main`（如更名，同步修改 CI/pages 的分支过滤）。
2. 保护主分支，要求 PR 审核和平台 CI；为工作流、签名工具、发布脚本、Cargo 依赖与公钥根设置维护者审核规则。
3. 按 `trust/README.md` 离线生成生产 key，将公钥根审核后提交为 `trust/root.json`；私钥 seed 的 hex 值仅放 GitHub `release-signing` Environment 的 `FOUNDRY_SIGNING_KEY` secret；同一环境变量 `FOUNDRY_KEY_ID` 指定 key ID。
4. 给 `release-signing` 设置 required reviewers、禁止自批并限制默认分支；`release-publishing` 也限制默认分支。环境规则需要管理员配置，YAML 无法替代这些设置。
5. GitHub Pages 的 Source 设为 Deploy from a branch，选择 gh-pages / root。仓库允许 Actions 对部署 job 使用 contents:write。

## PR 与正式发布

PR 自动执行 Rust 测试、真实签名仓库测试、libffi 崩溃测试和网站构建，并上传按平台生成的未签名候选包与摘要预览。PR 预览不会进入受保护签名步骤，正式发布必须重新核对合并提交。矩阵为 Windows 2022 x64、macOS 15 ARM64、Ubuntu 22.04 x64、Ubuntu 24.04 ARM64；托管 runner 的可用性受 GitHub 仓库类型/配额影响。没有对应 runner 结果时不能声称该平台已验证。

合并后手动触发 Signed release workflow，提供新的稳定版本号和严格递增 sequence。版本号需与 Cargo workspace 一致。流程拒绝已有版本，不覆盖资产，按 workflow 固定 sourceCommit 构建。首次发布需要 `trust/root.json`。

无密钥构建 job 为每平台生成客户端 ZIP、worker 及正式扩展；候选 job 合并索引并显示提交与 release-manifest SHA-256。维护者核对后批准 release-signing。签名 job 校验所有资产摘要、包 URL、提交及平台集合，仅签名元数据；发布 job 才拥有 Release 写权限，且没有签名私钥。30 天有效索引需要到期前发布新批次；旧版本已安装包离线运行不受索引过期影响。

客户端 ZIP 附 trust-root.json 便于使用，但首次引导仍需核对独立可信的公钥指纹。Release 提供 index.json、index.json.sig、release-manifest.json、release-manifest.json.sig，以及四个平台客户端和扩展包。原生依赖 libffi 静态链接到 worker。当前没有 `curl | sh` 安装入口。发布后可下载平台对应的客户端 ZIP，将 `foundry` 和 `foundry-worker` 解压到同一目录。

## 官网与索引

主分支更新自动构建 Astro 并推送 gh-pages。有生产根时，网站构建从最新正式 Release 下载并验证原始索引，再将它原样复制到 `registry/`，与页面一起部署；不会由页面代码重新序列化。校验失败会阻止部署，避免发布篡改索引。尚无生产根或 Release 时只发布文档并显示未发布状态。

发布完成调用同一 Pages 工作流。项目仓库自动使用 `/<repo>/` base，用户主页仓库使用 `/`。可用 `FOUNDRY_SITE`、`FOUNDRY_BASE` 在本地构建时覆盖。客户端索引地址最终是 `https://<owner>.github.io/<repo>/registry/index.json`。

## 本地验证（只用临时测试密钥）

```sh
python3 -m pip install -r requirements-ci.txt
cargo build --workspace --locked
python3 scripts/test_distribution.py
python3 scripts/test_device_plugins.py
python3 scripts/test_native_isolation.py
python3 scripts/test_host_files.py
python3 scripts/test_release_pipeline.py
```

测试会临时生成、签署并安装三类实现与四个设备/识别插件，不接触生产 secret。开发打包：

```sh
python3 scripts/build_extensions.py --out dist
./target/debug/foundry-release pack --source dist/dev/native-math --platform linux-x64 --output dist/native-math.zip
```

`pack` 结果是候选文件，不等于正式发布；必须由可信索引绑定。生产密钥不要写入命令参数、仓库、构建缓存或日志，使用受保护环境注入。根的轮换说明见 security.md。

## 历史版本发布

版本目录及独立测试配置见 [registry.md](registry.md)。发布前获取上一份正式索引并验证签名、递增序号；已验证历史索引以 SHA-256 绑定到构建、组装和签名任务。原有 `(id, version, platform)` 条目复用原始 URL 和摘要，只构建尚未发布的版本/平台。索引保留全部未撤回历史版本，因此旧 Release 资产不能删除。

扩展版本独立于客户端版本；目前正式流水线仍在一次新客户端 Release 中发布本批扩展和更新索引，触发参数 `version` 是客户端版本，不会要求所有扩展使用同一版本号。撤回版本也需要完成一次签名索引发布才会对客户端生效。

签名索引的 `withdrawnPackages` 保留已撤回包的原始记录，客户端只从 `packages` 选择安装。撤回后恢复发布会复用原来的包及 URL，不允许借撤回重写历史二进制。
