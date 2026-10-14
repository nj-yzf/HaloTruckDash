# 开发与构建

使用Windows 10/11、Python 3.11 x64及PowerShell。在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe main.py
.\build.ps1
.\.venv\Scripts\python.exe tools/verify_release.py --ui-smoke
```

`build.ps1`运行单元测试和原生窗口检查、生成Windows文件版本信息、嵌入图标，并构建便携EXE、ZIP与SHA256SUMS.txt。输出位于dist；用户数据不会加入ZIP。版本号统一来自halo_dashboard/version.py。

`docs/windows-workflow.yml`为Windows云端构建模板，包含构建和隔离EXE检查，不连接真实音响。当前发布账号缺少GitHub Actions的workflow权限，因此模板未启用。取得权限后可将其放到 `.github/workflows/windows.yml` 再推送。正式版当前的验证结果来自本地测试，不代表已在第二台实体电脑或云端完成实测。

`main`为不含在线更新的稳定版。`online-updates`保存0.5.0实验功能，与正式版独立维护。

原生窗口检查位于tools/checks，均使用模拟后台或隔离状态目录，不写USB。`--diagnose`只枚举设备及读取遥测，不输出USB序列号、设备路径，不修改游戏文件。不要将data、日志、个人配置或本地研究材料提交到仓库。

## 图标

assets/HaloTruckDash.svg为原创可编辑矢量图标，同时提供256px PNG及包含16–256px九种尺寸的ICO。EXE使用ICO，Tk窗口及任务栏使用同一图标，Windows AppUserModelID为HaloTruckDash.Desktop。图标采用项目MIT许可。

若需重新生成图标，额外安装Pillow后运行 `python tools/make_icon.py`。Pillow仅用于开发生成资源，不是运行时依赖。

## 发布

构建并验证后提交源码，在该提交上创建v版本号标签。将dist/HaloTruckDash-v版本号-win-x64.zip及对应版本目录的SHA256SUMS.txt上传到GitHub Release；源码由GitHub标签提供。保留第三方组件许可。发布包不要包含开发机data目录。
