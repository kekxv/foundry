# libffi 与 C ABI

正式扩展 `extensions/native-math/` 提供 Rust cdylib、JS 包装和完整 manifest。C++ 库必须增加 `extern "C"` 包装，ABI 统一为默认平台 C ABI；不会解析 C++ 名称修饰或自动推断签名。

```json
{
  "math": {
    "abi": "c",
    "paths": {"linux-x64": "lib/libfoundry_native_math.so"},
    "symbols": {
      "add": {
        "symbol": "foundry_add",
        "parameters": ["i32", "i32"],
        "returns": "i32"
      }
    }
  }
}
```

| 声明    | 参数表示                        | ABI 映射                          |
| ------- | ------------------------------- | --------------------------------- |
| i32     | 有范围校验的 JSON 整数          | int32_t                           |
| u32     | 0..4294967295 JSON 整数         | uint32_t                          |
| f64     | 有限 JSON number                | double                            |
| cstring | 不含 NUL 的 UTF-8 字符串        | const char*，只读、调用期间有效   |
| buffer  | 0..255 的 JSON 数组，最多 1 MiB | const uint8_t* 和 size_t 两个实参 |
| void    | 仅返回类型                      | 返回 JSON null                    |

cstring/buffer 仅用于输入。Rust 持有存储至调用结束，库不得保留或释放它；空 buffer 的长度是零，库不得解引用它的地址。没有原生分配的字符串/缓冲区返回、裸指针、变参、回调、按值结构体和跨请求句柄。需要这些能力时先定义所有权和释放协议。

动态库按规范绝对路径加载。Windows 使用 `LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS`；Unix 清除常见动态加载环境覆盖变量，推荐扩展静态链接除系统库以外的依赖。macOS/Linux 使用平台加载器，因此不能宣称完全禁止库自身声明的 RPATH/依赖加载；原生执行本身属于可信代码权限。

libffi 静态链接到 Rust worker，扩展的 `.dll/.dylib/.so` 单独分发。发布构建默认本机 runner，Windows MSVC，macOS 两种架构分别构建，Linux 使用 glibc。FFI 声明不正确可能崩溃或破坏 worker 的内存，libffi 无法证明 ABI 声明真实。

客户端每次调用启动独立 worker。父进程限制超时、IPC 和输出；Unix 用独立进程组清理，Windows 将子进程挂起创建，加入 kill-on-close Job Object 后恢复执行；初始化失败会终止并回收子进程。崩溃只影响本次调用；恶意原生代码仍可能逃逸故障清理机制，这不是 OS 安全沙箱。测试专用崩溃库只在临时目录生成，不进入正式 native-math 包。
