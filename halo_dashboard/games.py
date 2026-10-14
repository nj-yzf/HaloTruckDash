"""Supported SCS games and installation targets; telemetry selection is automatic."""
from dataclasses import dataclass
from pathlib import Path

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

def default_game_dir(key='ets2'):
    return Path(r'E:\SteamLibrary\steamapps\common') / GAMES[key].folder

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
