import hashlib
from pathlib import Path
import shutil
from .games import default_game_dir, detect_game

PLUGIN_SHA256 = "1d03dbc7a975e72203c60a7b9998021ceb8800b836bf28a131279979ad386cd4"
DEFAULT_GAME = default_game_dir('ets2')

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def install_plugin(game_dir, bundled_dll, expected_game=None):
    root = Path(game_dir).resolve()
    game = detect_game(root, expected_game)
    binary = root / "bin" / "win_x64" / game.executable
    source = Path(bundled_dll)
    if sha256(source) != PLUGIN_SHA256:
        raise ValueError("附带插件校验失败，请重新获取软件")
    directory = binary.parent / "plugins"
    directory.mkdir(exist_ok=True)
    destination = directory / "scs-telemetry.dll"
    if destination.exists():
        if sha256(destination) == PLUGIN_SHA256:
            return f"{game.label}兼容插件已安装；如尚未重启该游戏，请重启后进入驾驶"
        raise FileExistsError("已有不同版本 scs-telemetry.dll，本程序未覆盖它。\n"
                              "它可能供其他仪表软件使用，请保留现有插件并先核对兼容性；"
                              "不要直接删除、改名或替换。详见使用说明及 README 的兼容性说明。")
    # Exclusive create avoids overwriting a concurrent installer or existing plugin.
    with destination.open("xb") as target, source.open("rb") as origin:
        shutil.copyfileobj(origin, target)
    return f"{game.label}插件已安装。请完全退出并重新启动该游戏，接受 SDK 提示后进入驾驶"
