# HaloTruckDash

<img src="assets/HaloTruckDash.png" width="88" alt="HaloTruckDash icon">

将欧洲卡车模拟2（ETS2）和美国卡车模拟（ATS）的仪表信息显示到花再 Halo PixelBar 点阵屏。支持 Windows 10/11 x64，解压运行，无需安装 Python。正式版以0.4.1为基础，不含在线更新；0.5.0保留在 `online-updates` 开发分支。

## 开始使用

1. 从 [Releases](https://github.com/nj-yzf/HaloTruckDash/releases) 下载 `win-x64.zip`，解压到可写目录，运行 `HaloTruckDash.exe`。
2. 用可传输数据的 USB 线连接 Halo PixelBar。仅连接蓝牙无法控制点阵屏。
3. 首次使用，为对应游戏选择根目录并点击“安装遥测插件”；程序会尝试检测 Steam 游戏库，也支持手动选择。欧卡和美卡需分别安装一次。
4. 完全重启游戏，接受 SDK 提示并进入驾驶。选择布局、颜色、速度单位及挡位模式，点击“开始同步到音响”。

未运行游戏时可使用“模拟演示数据”。停止同步或正常退出会恢复原屏幕；异常退出后可点击“恢复原屏幕”。同步时仅由本程序控制音响屏幕。切换欧卡和美卡前先退出上一款游戏。

## 显示和自定义

```text
默认布局1：< A12  080/090km/h  09:45  67% >
默认布局2：< A12  L090 080km/h  09:45 67% >
```

两端为转向灯，中间30格可编辑。自动挡显示 A/N/R，手动挡显示数字；支持 km/h 和 mph。自定义布局中手写的单位文字需自行修改，导航距离和燃油量仍为公里、升。

- 打开“布局编辑器…”编辑当前方案，或“新建”空白方案。
- 拖入彩色信息控件，直接在格子中键入单位、空格和符号。
- Shift拖动框选，Ctrl点击增减选择；拖动选中内容整体移动。Delete删除，Ctrl+Z/Y撤销、重做。
- 命名并“保存并应用”，即可在主界面切换。支持多套方案、JSON导入/导出，以及打开布局文件夹批量复制分享。

控件包括车速、限速、挡位、油量、转速、游戏/现实时间、巡航目标、任务剩余、导航用时/距离、休息倒计时和燃油升数。自定义油量最高显示99；默认布局保留100%。时长≤24小时显示HH:MM，超过后显示如2d11h。

## 兼容性和数据

- 本项目已实测 A160、欧卡、美卡；用户已确认与 SimHub 协同工作正常。A106 有公开协议依据，尚待本项目实机验证；其他型号或品牌音响不在支持范围。详见 [兼容性说明](docs/COMPATIBILITY.md)。
- 如游戏无遥测，请确认安装路径、接受SDK提示，并安装微软官方 [Visual C++ v14 x64运行库](https://aka.ms/vc14/vc_redist.x64.exe)。安装器不会覆盖不同版本的同名插件。
- 设置、布局、日志位于程序旁的 `data/`；目录不可写时改用 `%LOCALAPPDATA%/HaloTruckDash/data/`，在“使用说明”中可查看实际位置。
- 升级前关闭旧版，再将整个 `data` 目录复制到新版旁即可保留配置。诊断命令 `HaloTruckDash.exe --diagnose` 生成 `diagnostics.json`，不会写音响。

## 开源与构建

原创代码和图标采用 [MIT](LICENSE) 许可；第三方组件保留各自许可，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。开发构建方法见 [BUILDING.md](docs/BUILDING.md)。
