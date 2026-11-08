# QuickJS 宿主接口

客户端使用 rquickjs，支持 ES Modules、`export async function`、Promise 和包内相对模块。没有 Node.js 或 QuickJS std/os API。

运行默认限额：JS 堆 64 MiB、栈 1 MiB、总执行时间 30 秒；CLI `--timeout-ms` 可降低至 1 ms。总时限包含模块求值、Promise 和宿主等待。原生进程输出合计最多 1 MiB；JS 限额不能约束原生代码的全部内存分配。

## 命令行

```js
const {exitCode, stdout, stderr} = await host.exec('digest', [path], {
  timeoutMs: 1000,
});
```

需要 `process.spawn`。只运行 manifest 声明的程序，不经过 shell，不搜索 PATH；参数必须为字符串数组，最多 256 项。超时不超过本次剩余运行时间。stdout/stderr 必须是 UTF-8。文件摘要正式扩展展示完整用法。

## 动态库

```js
const result = await host.library('math').call('add', [2, 3]);
```

需要 `native.call`。只解析已声明库与符号，严格校验实参数量、类型和范围；通过 worker/libffi 调用默认 C ABI。指针不暴露给 JS，见 [ffi.md](ffi.md)。

## 扩展数据目录

```js
const text = await host.fs.readText('cache/result.txt');
await host.fs.writeText('cache/result.txt', 'value');
```

分别需要 `filesystem.read`、`filesystem.write`。路径相对于客户端用户数据目录下 `data/<extension-id>/`，不接受任意系统路径；禁止链接逃逸，单文件最多 1 MiB。原生程序可绕过这类 JS 访问限制，因此原生执行权限是单独的信任授权。

所有接口返回 Promise。首版桥接在 QuickJS 线程上同步等待有界 worker 的结果；不要假设 `Promise.all` 能使多个原生调用并行。每次 native 请求使用独立 worker，不保存跨调用的动态库状态。

正式 `run` 使用完整性校验后的临时快照；`dev run` 接受显式可信本地源码，二者均执行输入输出校验、权限检查和时限控制。错误导致 CLI 非零退出，stderr 为 `{code,message}`，stdout 为 JSON 结果；`--json` 为兼容明确的脚本调用保留，默认已经是 JSON。

worker 请求使用有界 JSON 输入，响应写入本次调用私有临时目录内的独立响应文件；原生 stdout/stderr 仅作为有界诊断转发到客户端 stderr，不参与协议解析。文件接口也在有超时的 worker 中执行，并拒绝 FIFO、设备等特殊文件。
