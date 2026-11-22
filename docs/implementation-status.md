# 首版实施记录

日期：2026-11-07，2026-11-08 更新。项目已实现并本地验证；尚未连接远程 GitHub 仓库，也未进行生产发布。

## 已交付

| 计划任务        | 本地交付                                                                                         |
| --------------- | ------------------------------------------------------------------------------------------------ |
| 1. 扩展格式     | Rust workspace、严格 manifest 验证、JSON Schema、正式扩展声明                                    |
| 2. 可信存储     | Ed25519 根与索引验证、过期/回滚检查、安全 ZIP、逐文件校验、根轮换                                |
| 3. QuickJS      | ES Modules、async/Promise、包内导入、堆/栈/时限、严格 JSON 输出                                  |
| 4. 命令行扩展   | 隔离 worker、不经过 shell 的有界执行、正式 file-digest                                           |
| 5. 动态库扩展   | 静态链接 libffi 的 worker、C ABI、标量/cstring/buffer、正式 native-math                          |
| 6. 客户端       | 搜索、信息、安装、下载（`download`/`get`）、调用、列表、升级、卸载、显式授权、本地开发、运行快照 |
| 7. 发布         | 四平台 CI、PR 未签名候选、固定提交与摘要审批绑定、分离签名/发布、密钥轮换接口                    |
| 8. 官网         | Astro 7 首页、目录、详情、编写指南；gh-pages 自动部署及原始签名索引一起发布                      |
| 设备与识别插件  | 可选 plugin 元数据、四个正式 mock 插件、固定 JSON 合同、摄像头→OCR 数据兼容、独立原生适配器接口  |
| 扩展中心仓库 CI | 每个扩展的 `metadata.json` / `presubmit.yml`、变更检测、平台矩阵和单扩展实际产物测试             |

七个正式扩展源码在 `extensions/`；本机调试构建和 ZIP 产物已在 `target/debug/` 与 `dist/` 生成，没有 examples 子项目。

## 验证证据

- `cargo test --workspace --locked`：27 个 Rust 测试通过。
- `cargo fmt --all -- --check`、workspace clippy `-D warnings`：通过。
- `python3 scripts/test_device_plugins.py`：身份字段、有效 PNG、摄像头→OCR、串口响应、无效输入/输出拒绝、临时签名下载与安装通过。
- `python3 scripts/test_distribution.py`：真实临时签名索引、三类扩展安装/调用/更新/卸载、并发安装、权限升级、错误签名、过期/回滚、包和运行文件篡改均通过。
- `python3 scripts/test_native_isolation.py`：真实 libffi 字符串/缓冲区/空缓冲区、非法参数、原生日志、崩溃、死循环超时及随后调用通过。测试崩溃库只在临时目录生成。
- `python3 scripts/test_host_files.py`：读写权限、越界路径、符号链接、FIFO 超时回归通过。
- `python3 scripts/test_release_pipeline.py`：候选提交、清单摘要、额外文件和错误发布来源的拒绝测试通过。
- `cargo clippy -p foundry-worker --all-targets --target x86_64-pc-windows-gnu --features libffi/system -- -D warnings`：Windows 分支类型检查通过；此项仅交叉检查 Rust 代码，不是 Windows 原生执行，也不验证 bundled libffi 在 Windows 的完整链接。
- `actionlint v1.7.11`：全部 GitHub 工作流检查通过。
- Astro check：0 错误、0 警告；十个静态页面构建及 `/foundry/` 项目子路径内部链接检查通过。
- 网站正式发布状态随 registry 数据切换已本地核对；Chromium 已检查八类页面在 1440/768/390/320px 的32组布局，锚点、页面宽度、控制台与可访问性审计通过。
- 网站依赖已升级至 Astro 7.4.7，npm audit：0 已报告漏洞。

## 独立审查与修正

执行了一次独立、只读的完整代码审查。发现并修正：阻塞文件 IO 绕过时限、动态库 stdout 污染响应、Windows 条件编译警告、Windows Job 初始化失败泄漏、缺失入口/原生文件仍可安装、访问器不稳定序列化、祖先目录大小写碰撞，以及审批回归测试未进入 CI。可复现问题均先观察失败，再以对应测试确认修正；Windows 执行路径只交叉检查，须由 Windows runner 实测。

## 实施裁定

- 这是用户指定的全新目录，直接初始化开发分支；没有既有仓库或改动需要另建 worktree。本次整理纳入首次本地提交，未推送或创建远程仓库。
- 首版能力 Schema 拒绝所有引用，要求自包含；暂不支持任意资源打包、扩展依赖求解、隐式共享库依赖。
- 宿主接口返回 Promise，首版同步等待有时限的独立 worker；不保证 Promise.all 原生调用并发。
- 每次原生请求使用新 worker，只支持标量/void 返回，不暴露裸指针或跨请求动态库状态。
- 对 JSON 访问器、路径大小写和审批测试覆盖按契约及平台影响作为必要修正处理，没有遗留已知审查项。
- 原生进程隔离用于故障清理，签名用于授权与完整性；均不等于原生代码强沙箱。

## 上线前仍需外部配置与验证

1. 真实 GitHub 仓库和默认分支 main。
2. 受保护签名环境中的生产私钥 secret。发布流程生成并发布公钥根。
3. GitHub 分支保护、必需审核人、签名环境审批与默认分支限制。
4. 在对应 runner 实际运行 Windows、macOS、Linux ARM64 构建与调用；本机只有 Linux x64 执行证据。
5. 预发布签名、Release 上传、gh-pages 远端部署与下载验收。

这些步骤没有在本地伪造成功。完整操作见 publishing.md 和 trust/README.md。根到期或旧私钥丢失需要独立可信渠道恢复；不能自动相信下载的新根。
