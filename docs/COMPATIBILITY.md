# 兼容性说明

| 项目 | 范围与验证情况 |
| --- | --- |
| 正式发布程序 | Windows 10/11 x64；包含Python、Tcl/Tk及HID运行组件，无需安装Python |
| Windows ARM64 | 没有原生ARM64发布包；x64模拟运行尚未实测 |
| Windows 7/8、32位Windows、macOS、Linux | 不支持当前Windows x64发布包 |
| 游戏 | ETS2和ATS的64位版本，用户已确认两者真实驾驶和音响同步正常 |
| 遥测插件 | RenCloud V.1.12.1，共享内存修订12；依赖Visual C++ v14 x64运行库 |
| SimHub | 用户已确认与当前测试组合协同工作正常；不同插件版本仍需核对 |

程序检测Steam注册表位置及libraryfolders.vdf中的其他游戏库，支持不同盘符、中文和空格路径；非Steam安装可手动选择。程序目录不可写时，设置回退到用户LOCALAPPDATA目录。单元、原生窗口及便携EXE检查不等同于在所有电脑型号上实测。

SCS插件导入MSVCP140.dll、VCRUNTIME140.dll及Windows Universal CRT。如果插件未载入，可安装[微软官方Visual C++ v14 x64运行库](https://aka.ms/vc14/vc_redist.x64.exe)。程序不会自动安装运行库或更换其他仪表的软件插件。

## 音响

| USB型号 | 适配状态 |
| --- | --- |
| VID 2D99 / PID A160 | 本项目实机验证；32字符布局、同步与恢复已经用户测试 |
| VID 2D99 / PID A106 | 有公开Halo PixelBar协议依据，并已加入筛选；尚待本项目实机验证 |
| 其他PID、其他型号/品牌 | 未适配，不向未知USB接口发送控制命令 |

除VID/PID外，还校验HID接口4、usage page FF14及usage 1；系统能提供产品名称时还校验Halo/PixelBar名称。产品字符串缺失时仍可识别已知硬件ID。发送设置前查询并检查响应格式。一次仅支持一台匹配音响，多台连接时会提示处理。

同型号的另一台音响预计可使用相同协议，但不同固件可能改变读回格式或可显示空间；A106及其他实体设备仍需验证。USB线、转接器和扩展坞需能正确枚举数据接口。设备更新后如识别失败，可用 `--diagnose` 生成诊断文件反馈VID/PID及接口信息；诊断不包含USB序列号和设备路径。

## 与其他程序共存

本程序只读Local\SCSTelemetry，不监听遥测网络端口，不改变游戏输入。多个读取程序可共享匹配插件；不同插件若覆盖同名DLL或同一共享内存仍可能冲突。安装器拒绝覆盖不同内容的scs-telemetry.dll，保留其他DLL。音响屏幕仅由一个程序控制。

SimHub的用户共存实测反馈已记录；[其官方排障说明](https://github.com/SHWotever/SimHub/wiki/SimHub-Basics----Games-config-and-troubleshooting#ets2--ats)仍提示部分遥测插件分支存在冲突，因此此结果不代表所有历史和未来版本组合都已验证。

[公开A106协议依据](https://github.com/Seraph310/halo-pixelbar-mcp) · [SCS官方遥测SDK](https://modding.scssoft.com/wiki/Documentation/Engine/SDK/Telemetry)
