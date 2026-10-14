"""Supported SCS games and installation targets; telemetry selection is automatic."""
from dataclasses import dataclass
from pathlib import Path
import os
import re

@dataclass(frozen=True)
class Game:
    key: str
    telemetry_id: int
    label: str
    folder: str
    executable: str

GAMES = {
    'ets2': Game('ets2', 1, '欧卡2 / ETS2', 'Euro Truck Simulator 2', 'eurotrucks2.exe'),
    'ats': Game('ats', 2, '美卡 / ATS', 'American Truck Simulator', 'amtrucks.exe'),
}
GAME_CHOICES = {game.label: key for key, game in GAMES.items()}
GAMES_BY_ID = {game.telemetry_id: game for game in GAMES.values()}

def steam_install_dirs():
    roots = []
    try:
        import winreg
        for hive, key, field in [(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
                                  (winreg.HKEY_LOCAL_MACHINE, r'Software\Valve\Steam', 'InstallPath')]:
            for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
                try:
                    with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                        value, _ = winreg.QueryValueEx(handle, field)
                        if isinstance(value, str) and value:
                            roots.append(Path(value))
                except OSError:
                    pass
    except ImportError:
        pass
    roots.extend(Path(os.environ.get(variable, fallback)) / 'Steam' for variable, fallback in
                 [('ProgramFiles(x86)', r'C:\Program Files (x86)'), ('ProgramFiles', r'C:\Program Files')])
    return unique_paths(roots)


def unique_paths(paths):
    result, seen = [], set()
    for path in paths:
        key = str(path).replace('/', '\\').casefold().rstrip('\\')
        if key not in seen:
            seen.add(key)
            result.append(Path(path))
    return result


def steam_libraries():
    roots = steam_install_dirs()
    libraries = list(roots)
    for root in roots:
        configuration = root / 'steamapps' / 'libraryfolders.vdf'
        try:
            if configuration.stat().st_size > 1024 * 1024:
                continue
            text = configuration.read_text(encoding='utf-8-sig')
            # Both modern "path" records and the legacy numeric-key format.
            for value in re.findall(r'"(?:path|\d+)"\s*"((?:\\.|[^"\\])*)"', text):
                value = value.replace('\\\\', '\\').replace('\\"', '"')
                if value and Path(value).is_absolute():
                    libraries.append(Path(value))
        except (OSError, UnicodeError):
            pass
    return unique_paths(libraries)


def default_game_dir(key='ets2'):
    candidates = [root / 'steamapps' / 'common' / GAMES[key].folder for root in steam_libraries()]
    for candidate in candidates:
        if (candidate / 'bin' / 'win_x64' / GAMES[key].executable).is_file():
            return candidate
    return candidates[0] if candidates else Path.home() / GAMES[key].folder

def detect_game(game_dir, expected_game=None):
    root = Path(game_dir)
    found = [game for game in GAMES.values() if (root / 'bin' / 'win_x64' / game.executable).is_file()]
    if expected_game is not None:
        if expected_game not in GAMES:
            raise ValueError('请选择欧卡2或美卡作为插件安装目标')
        selected = GAMES[expected_game]
        if selected in found:
            return selected
        if found:
            raise ValueError(f'此目录属于{found[0].label}，当前选择的是{selected.label}；请切换安装目标或重新选择目录')
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        raise ValueError('目录中同时存在两款游戏，请明确选择插件安装目标')
    raise ValueError('请选择游戏根目录，其中应包含 bin/win_x64/eurotrucks2.exe（欧卡2）或 amtrucks.exe（美卡）')
