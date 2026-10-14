"""Read-only subset of RenCloud SCSTelemetry revision 12 (V.1.12/1.12.1).

Offsets checked against scs-telemetry-common.hpp and the truck-telemetry schema.
OpenFileMapping is used so waiting for a game never creates a phantom mapping.
"""
from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import math
import struct
import time
from .games import GAMES_BY_ID

SNAPSHOT_SIZE = 4304

@dataclass
class Truck:
    connected: bool = False
    paused: bool = False
    speed: float = 0.0  # km/h; signed, negative means reversing
    limit: float = 0.0  # km/h
    gear: int = 0
    rpm: float = 0.0
    fuel: float = 0.0
    capacity: float = 0.0
    left: bool = False
    right: bool = False
    parking: bool = False
    low_fuel: bool = False
    cruise: bool = False
    cruise_speed: float = 0.0
    engine: bool = False
    distance: float = 0.0  # remaining navigation distance, km
    game_minutes: int | None = None  # SCS absolute in-game minutes, not PC time
    shifter_type: str = ''  # arcade / automatic / manual / hshifter
    on_job: bool = False
    delivery_minutes: int | None = None  # absolute in-game deadline
    route_seconds: float = 0.0  # navigation estimate, game seconds
    rest_minutes: int = 0
    reason: str = "等待游戏遥测"
    game_id: int = 0

    @property
    def game_name(self):
        game = GAMES_BY_ID.get(self.game_id)
        return game.label if game else '卡车模拟游戏'

    @property
    def fuel_percent(self):
        return max(0, min(100, self.fuel / self.capacity * 100)) if self.capacity > 0 else None

    @property
    def job_remaining_minutes(self):
        if not self.on_job or not self.delivery_minutes or self.game_minutes is None:
            return None
        return max(0, self.delivery_minutes - self.game_minutes)


def decode_snapshot(data: bytes) -> tuple[Truck, int]:
    if len(data) < SNAPSHOT_SIZE:
        raise ValueError("遥测数据长度不足")
    def val(fmt, offset):
        return struct.unpack_from("<" + fmt, data, offset)[0]
    revision = val("I", 40)
    if revision != 12:
        raise ValueError(f"不支持共享内存修订 {revision}；需要 V.1.12.1 / 修订12，请核对插件兼容性，勿直接覆盖其他软件的插件")
    game_id = val('I', 52)
    if game_id not in GAMES_BY_ID:
        return Truck(reason="插件已加载，等待进入游戏"), val("Q", 8)
    if not val("?", 0):
        return Truck(game_id=game_id, reason=f"{GAMES_BY_ID[game_id].label}：遥测未激活，等待进入驾驶"), val("Q", 8)
    def number(offset):
        n = val("f", offset)
        if not math.isfinite(n):
            raise ValueError("遥测包含无效数值，等待下一帧")
        return n
    return Truck(
        connected=True, game_id=game_id, paused=val("?", 4), speed=number(948) * 3.6,
        limit=number(1068) * 3.6, gear=val("i", 508), rpm=number(952),
        fuel=number(1000), capacity=number(704), parking=val("?", 1566),
        low_fuel=val("?", 1570), engine=val("?", 1576),
        left=val("?", 1580), right=val("?", 1581), cruise=val("?", 1589),
        cruise_speed=number(988) * 3.6, distance=number(1060) / 1000,
        game_minutes=val("I", 64),
        on_job=val('?', 4300), delivery_minutes=val('I', 88) or None,
        route_seconds=number(1064), rest_minutes=val('i', 500),
        shifter_type=data[3196:3212].split(b'\0', 1)[0].decode('ascii', errors='replace'),
        reason=GAMES_BY_ID[game_id].label + ('：游戏已暂停' if val('?', 4) else '：实时遥测已连接'),
    ), val("Q", 8)


class Telemetry:
    def __init__(self, mapping_name="Local\\SCSTelemetry"):
        self.mapping_name = mapping_name
        self.handle = None
        self.view = None
        self.timestamp = None
        self.last_game_id = None
        self.last_change = time.monotonic()
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.OpenFileMappingW.restype = wintypes.HANDLE
        self.kernel.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
        self.kernel.MapViewOfFile.restype = ctypes.c_void_p
        self.kernel.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]

    def read(self):
        if not self.handle:
            self.handle = self.kernel.OpenFileMappingW(4, False, self.mapping_name)
            if not self.handle:
                self.timestamp = None
                self.last_game_id = None
                self.last_change = time.monotonic()
                return Truck(reason="等待欧卡2 / 美卡：在对应游戏安装插件、重启并进入驾驶")
            self.view = self.kernel.MapViewOfFile(self.handle, 4, 0, 0, SNAPSHOT_SIZE)
            if not self.view:
                self.close()
                return Truck(reason="无法读取遥测共享内存")
        try:
            truck, timestamp = decode_snapshot(ctypes.string_at(self.view, SNAPSHOT_SIZE))
            now = time.monotonic()
            if timestamp != self.timestamp or truck.game_id != self.last_game_id:
                self.timestamp = timestamp
                self.last_game_id = truck.game_id
                self.last_change = now
            if now - self.last_change > 3 and not truck.paused:
                return Truck(game_id=truck.game_id, reason=f"{truck.game_name}：遥测已停止，等待游戏重新连接")
            return truck
        except ValueError as exc:
            return Truck(reason=str(exc))
        finally:
            # Release every sample so our handle cannot keep a dead game's
            # paused mapping alive. Opening/mapping is cheap at 10 samples/sec.
            self.close()

    def close(self):
        if self.view:
            self.kernel.UnmapViewOfFile(self.view)
        if self.handle:
            self.kernel.CloseHandle(self.handle)
        self.view = self.handle = None


def demo(seconds):
    speed = 65 + math.sin(seconds / 8) * 30
    return Truck(connected=True, speed=speed, limit=80, gear=10 if speed < 75 else 12,
                 rpm=1200 + math.sin(seconds / 3) * 400, fuel=265, capacity=600,
                 left=int(seconds) % 14 < 2, engine=True, distance=128.4,
                 game_minutes=8 * 60 + 40 + int(seconds / 10), shifter_type='automatic',
                 on_job=True, delivery_minutes=2 * 1440, route_seconds=8400,
                 rest_minutes=310, cruise=True, cruise_speed=80,
                 reason="模拟演示（并非游戏数据）")
