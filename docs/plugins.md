# 设备、识别与接口插件

插件是普通的版本化、可签名扩展；`plugin.kind` 描述用途，`type` 描述执行方式，二者独立。因此同一身份证合同可以有纯 JS 模拟实现、已编译 CLI 适配器或 libffi 原生桥接实现，业务方始终调用能力并接收 JSON。

当前四个正式插件都是可安装、可测试的 **mock 模拟实现**，不连接真实硬件，也不运行 OCR 引擎。它们没有原生权限，支持四个官方目标平台。包、版本目录、签名校验和独立 presubmit 与其他扩展相同。

| 扩展           | plugin.kind    | 合同               | 能力               |
| -------------- | -------------- | ------------------ | ------------------ |
| id-card-reader | id-card-reader | foundry.id-card.v1 | devices、read-card |
| camera         | camera         | foundry.camera.v1  | devices、capture   |
| ocr            | ocr            | foundry.ocr.v1     | recognize          |
| serial-port    | serial         | foundry.serial.v1  | devices、exchange  |

打印机、扫码器、NFC、传感器、GPIO、HID 等也可以使用同样机制声明稳定的 kind 与独立合同；目前没有附带这些设备的具体适配器。kind 允许自定义小写标识，不会隐式添加系统权限。

## 身份证固定结构

```sh
./target/debug/foundry dev run extensions/id-card-reader/0.1.0 devices --input '{}'
./target/debug/foundry dev run extensions/id-card-reader/0.1.0 read-card --input '{}'
```

`read-card` 输出的字段固定，缺少字段或类型不匹配会由客户端拒绝：

```json
{
  "schemaVersion": 1,
  "pluginKind": "id-card-reader",
  "mode": "mock",
  "deviceId": "mock-id-card-reader-01",
  "data": {
    "documentType": "cn-resident-id",
    "name": "模拟测试人员",
    "gender": "unknown",
    "ethnicity": "测试民族",
    "birthDate": "1990-01-01",
    "address": "测试省测试市测试区示例路1号",
    "idNumber": "000000199001010000",
    "issuingAuthority": "模拟签发机关",
    "validFrom": "2020-01-01",
    "validTo": "2030-01-01",
    "photo": null
  }
}
```

证件号有意使用无效地区码，全部信息为虚构测试数据。`gender` 为 male/female/unknown；`validTo` 为日期或 long-term；`photo` 为 null，或包含 mimeType/base64/width/height 的图像对象。基础 Schema 只校验数据结构和证件号形式，不验证身份证真实性、签发有效性或号码校验码。

可传 `deviceId` 选择设备；未知设备会使调用失败，错误消息包含 DEVICE_NOT_FOUND。真实适配器必须把厂商字段转换为这个合同，并将 mode 设为 adapter。原始 SDK 结构不能直接透传成不稳定的业务接口。

## 摄像头与 OCR

camera 的 `devices` 枚举设备，`capture` 接收可选 deviceId 与 format（当前只接受 png）。模拟输出为有效的 1×1 白色 PNG，结构为：

```text
schemaVersion / pluginKind / mode / deviceId
└─ data.image: {mimeType, base64, width, height}
```

OCR 的 `recognize` 输入为 `{image: {mimeType: "image/png"|"image/jpeg", base64: "..."}}`。可选 width/height 接受图像尺寸，因此调用方可以把 camera 的 data.image 整体传给 OCR 的 input.image。Base64 字符串必须符合编码格式且有大小限制；当前模拟实现不解码/识别图片，固定返回 FOUNDRY MOCK TEXT。输出结构为：

```text
schemaVersion / pluginKind / mode / deviceId
└─ data: {text, language, blocks: [{text, confidence, boundingBox: {x,y,width,height}}]}
```

位置框以输入图像像素为单位，置信度范围 0～1；模拟数值不代表实际模型质量。真实 OCR 可通过已编译适配器对接本地识别引擎、厂商 SDK 或服务，仍返回同一合同。network transport 不会为 JS 增加 HTTP API，联网能力需由获得原生权限的适配器实现。

## 串口与其他硬件接口

```sh
./target/debug/foundry dev run extensions/serial-port/0.1.0 devices --input '{}'
./target/debug/foundry dev run extensions/serial-port/0.1.0 exchange --input '{"message":"PING"}'
```

模拟串口返回 PONG，其他非空消息返回 ECHO:消息。`data` 固定为 `{request,response,encoding:"utf8"}`，请求最多256个字符。真实适配器可在单次 exchange 内完成打开端口、配置、写入、读取与关闭，不把 OS 句柄暴露给 JavaScript。

## 真实设备适配器

示例元数据形状（需要另外提供真实的预编译程序及 capability 定义）：

```json
{
  "type": "executable",
  "permissions": ["process.spawn"],
  "plugin": {
    "kind": "id-card-reader",
    "mode": "adapter",
    "transport": "sdk",
    "contract": "foundry.id-card.v1"
  }
}
```

manifest.executables 按目标平台声明桥接程序；对应版本 presubmit 构建并打包这些成品。JS 接口可以这样调用：

```js
export async function readCard(input) {
  const result = await host.exec('reader', [
    'read-card',
    JSON.stringify(input),
  ]);
  if (result.exitCode !== 0) throw new Error('DEVICE_READ_FAILED');
  return JSON.parse(result.stdout);
}
```

CLI 适配器负责调用设备 SDK、转换编码、归一化字段及错误，并仅向 stdout 输出一次合同 JSON，诊断输出写 stderr。SDK、驱动、模型及再分发许可由适配器维护者处理；跨平台能力取决于实际厂商支持，不能仅靠修改 manifest 获得。

动态库适配器使用 type=native-library、native.call、transport=sdk/usb 等，并提供 manifest.libraries 与 C ABI 符号。现有 libffi 只支持 i32/u32/f64/void 返回和 cstring/buffer 输入；不能直接返回 SDK 的任意结构体、原生字符串指针或回调。复杂身份证信息和图片输出通常应采用上述 CLI JSON 桥接；见 [ffi.md](ffi.md)。

原生调用使用独立、有时限的 worker，不维护跨调用 DLL 状态或设备会话。首版合同采用单次读取、单帧采集和单次请求响应，不提供持续视频流/跨调用硬件句柄。原生输出合计最多1MiB，Base64 图像必须留出 JSON 开销并遵守限额；大图需适配器缩放或压缩。

适配器模式不会绕过签名、逐文件完整性校验和显式原生授权。真实业务数据不应成为 CI 固定样本，CI 使用 mock 插件或专用测试数据；实际硬件测试需要维护者另行准备设备与驱动。

## 数据合同与验证

规范文件在 `schemas/plugins/*.v1.schema.json`，同时内嵌在各插件 capability.output，避免运行时依赖远程引用。集成测试检查两者一致，并通过真实 QuickJS 调用、临时签名安装、错误输入和输出拒绝验证完整流程。

```sh
cargo build --workspace --locked
python3 scripts/test_device_plugins.py
python3 scripts/test_extension.py --extension id-card-reader --version 0.1.0 --platform linux-x64
python3 scripts/test_extension.py --extension camera --version 0.1.0 --platform linux-x64
python3 scripts/test_extension.py --extension ocr --version 0.1.0 --platform linux-x64
python3 scripts/test_extension.py --extension serial-port --version 0.1.0 --platform linux-x64
```

兼容性变化通过新增合同/版本发布，保持历史版本和下载摘要不变。mock→adapter 的切换必须发布新版本，并重新授权新增的原生权限；不是修改一个标记后直接沿用旧安装。
