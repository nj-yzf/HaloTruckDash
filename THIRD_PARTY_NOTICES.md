# 第三方资料与组件

- **SCS 官方 Telemetry SDK**：欧洲卡车模拟2和美国卡车模拟外接仪表的数据来源。文档：https://modding.scssoft.com/wiki/Documentation/Engine/SDK/Telemetry 。本程序通过下述社区桥接插件读取数据。
- **RenCloud/scs-sdk-plugin V.1.12.1**：MIT；附带 Win64 `scs-telemetry.dll`，原始发布 https://github.com/RenCloud/scs-sdk-plugin/releases/tag/V.1.12.1 。共享内存布局参考 V.1.12 `scs-telemetry/inc/scs-telemetry-common.hpp`，修订号 12；许可证见 `licenses/scs-sdk-plugin-LICENSE.txt`（源码目录下为 `assets/licenses/`）。
- **Seraph310/halo-pixelbar-mcp**：MIT；公开的 Halo 帧格式、HID 接口筛选、查询、文字和屏幕设置说明作为协议参考，本程序驱动独立实现并在本机 A160 验证。https://github.com/Seraph310/halo-pixelbar-mcp 。参考项目许可证见 `licenses/halo-pixelbar-mcp-LICENSE.txt`。
- **XFEstudio/HaloPixelToolBox**：MIT；对照其公开的 `HidPacketBuilder.cs` / `HaloPixelDevice.cs` 核对自定义文字模式与 USB HID 通信。https://github.com/XFEstudio/HaloPixelToolBox 。没有直接复制该项目代码。
- **truck-telemetry 0.0.3**：MIT；开发时用于独立核对 revision 12 的字段偏移。https://pypi.org/project/truck-telemetry/ 。没有打包进发布 exe。
- **hidapi 0.15.0 Python binding / HIDAPI**：按 wheel 随附许可分发，见 `licenses/hidapi/`。
- **Python 3.11 / Tcl/Tk**：发布 exe 内包含运行时及 Tk 窗口库。原始许可证见 `licenses/python-LICENSE.txt` 与 `licenses/tcltk-LICENSE.txt`。
- **PyInstaller 6.16.0**：GPL 2.0-or-later，包含允许分发打包应用的 bootloader exception；许可证见 `licenses/pyinstaller-LICENSE.txt`。

