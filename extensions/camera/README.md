# camera

摄像头插件：模拟设备枚举与单帧图像采集。这是正式的 `mock` 插件包，不连接真实设备，不执行真实 OCR。遵循 `foundry.camera.v1` 数据合同，走正常的签名/版本/下载流程。

```sh
foundry dev run extensions/camera/0.1.0 capture --input '{}'
```

结构及真实 SDK 适配见 [设备插件指南](../../docs/plugins.md)。四个平台 presubmit 使用同一 QuickJS 实现。真实设备适配器应通过 executable 或 native-library 实现，使用新的版本和显式原生权限；不能仅把 mode 改为 adapter。
