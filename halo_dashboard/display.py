from dataclasses import dataclass
from .telemetry import Truck
from .layout import render, render_preset

MODES = {'默认布局1': 'preset1', '默认布局2': 'preset2'}
COLORS = {'冰蓝': (102, 175, 255), '白色': (235, 240, 255), '绿色': (80, 230, 130),
          '琥珀': (255, 185, 65), '粉色': (240, 180, 200)}
GEAR_MODES = {'跟随游戏': 'auto', '强制自动': 'automatic', '强制手动': 'manual'}

@dataclass(frozen=True)
class Frame:
    text: str
    color: tuple[int, int, int]
    detail: str = ''

def format_frame(truck: Truck, mode='preset1', seconds=0.0, cycle_seconds=3.0,
                 color=(102, 175, 255), alerts=True, width=32, custom=None, gear_mode='auto', speed_unit='km/h'):
    if mode not in ('preset1', 'preset2', 'custom'):
        raise ValueError('请选择默认布局1、默认布局2或自定义布局')
    if not truck.connected:
        waiting = {1: 'WAIT ETS2', 2: 'WAIT ATS'}.get(truck.game_id, 'WAIT ETS2/ATS')
        return Frame('-' + waiting.center(30) + '-', color, truck.reason)
    text = (render(truck, settings=custom, gear_mode=gear_mode, speed_unit=speed_unit) if mode == 'custom'
            else render_preset(truck, 1 if mode == 'preset1' else 2, gear_mode, speed_unit))
    overspeed = truck.limit > 0 and abs(truck.speed) > truck.limit + 3
    status = '低油量' if truck.low_fuel else '驻车制动已启用' if truck.parking else '超速' if overspeed else truck.reason
    if truck.paused:
        return Frame(text, (143, 162, 184), '游戏已暂停，保留仪表读数')
    warning = (255, 170, 30) if truck.low_fuel or truck.parking else (255, 80, 70) if overspeed else color
    return Frame(text, warning if alerts else color, status)
