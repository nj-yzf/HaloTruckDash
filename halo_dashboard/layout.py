"""30 editable character cells between two fixed turn signals."""
from copy import deepcopy
from datetime import datetime

CELL_COUNT = 30
SPEED_UNITS = ('km/h', 'mph')

def convert_speed(kmh, speed_unit='km/h'):
    if speed_unit not in SPEED_UNITS:
        raise ValueError('请选择km/h或mph速度单位')
    return kmh / 1.609344 if speed_unit == 'mph' else kmh
FIELD_WIDTHS = {'speed': 3, 'limit': 3, 'fuel': 2, 'time': 5, 'gear': 3, 'rpm': 4,
                'real_time': 5, 'cruise_speed': 3, 'job_remaining': 5,
                'nav_time': 5, 'nav_distance': 4, 'rest_time': 5, 'fuel_liters': 4}
FIELD_LABELS = {'speed': '车速', 'limit': '限速', 'fuel': '油量%', 'time': '游戏时间', 'gear': '挡位', 'rpm': '转速',
                'real_time': '现实时间', 'cruise_speed': '巡航目标', 'job_remaining': '任务剩余',
                'nav_time': '导航用时', 'nav_distance': '导航公里', 'rest_time': '休息倒计时', 'fuel_liters': '燃油升数'}

def preset_layout(variant=1, speed_unit='km/h'):
    convert_speed(0, speed_unit)
    fields = [('gear', 1), ('speed', 6), ('limit', 10), ('time', 19), ('fuel', 26)] if variant == 1 else [
        ('gear', 1), ('limit', 7), ('speed', 11), ('time', 20), ('fuel', 26)]
    literals = {9: '/', 13: 'k', 14: 'm', 15: '/', 16: 'h', 28: '%'} if variant == 1 else {
        6: 'L', 14: 'k', 15: 'm', 16: '/', 17: 'h', 28: '%'}
    if speed_unit == 'mph':
        unit_start = 13 if variant == 1 else 14
        literals.pop(unit_start)
        literals.update({unit_start + 1: 'm', unit_start + 2: 'p', unit_start + 3: 'h'})
    return {'items': [{'start': start, 'type': 'field', 'field': name} for name, start in fields] +
                     [{'start': start, 'type': 'text', 'text': char} for start, char in literals.items()]}

DEFAULT_LAYOUT = {'items': []}

def item_width(item):
    return FIELD_WIDTHS[item['field']] if item['type'] == 'field' else len(item['text'])

def normalize(settings):
    if not isinstance(settings, dict) or not isinstance(settings.get('items'), list):
        raise ValueError('自由布局需要30格的控件配置')
    if len(settings['items']) > CELL_COUNT:
        raise ValueError('布局控件数量超过30格')
    occupied, items = set(), []
    for source in settings['items']:
        if not isinstance(source, dict) or type(source.get('start')) is not int:
            raise ValueError('控件位置无效')
        start, kind = source['start'], source.get('type')
        if kind == 'field' and isinstance(source.get('field'), str) and source['field'] in FIELD_WIDTHS:
            item = {'start': start, 'type': kind, 'field': source['field']}
        elif kind == 'text' and isinstance(source.get('text'), str) and source['text']:
            if any(not 32 <= ord(char) <= 126 for char in source['text']):
                raise ValueError('每格请输入可打印ASCII字符，可使用空格、[]、/、%等')
            item = {'start': start, 'type': kind, 'text': source['text']}
        else:
            raise ValueError('未知控件或文字类型')
        cells = set(range(start, start + item_width(item)))
        if not cells or min(cells) < 0 or max(cells) >= CELL_COUNT:
            raise ValueError('控件超出中间30格，请移动到更靠左的位置')
        if occupied & cells:
            raise ValueError('控件重叠，请先移走或删除已有内容')
        occupied |= cells
        items.append(item)
    return {'items': sorted(items, key=lambda item: item['start'])}

def validate(settings, width=32):
    return normalize(settings)

def owner_at(settings, cell):
    return next((item for item in settings['items'] if item['start'] <= cell < item['start'] + item_width(item)), None)

def remove_at(settings, cell):
    owner = owner_at(settings, cell)
    return normalize({'items': [deepcopy(item) for item in settings['items'] if item is not owner]})

def place_field(settings, cell, field, move_from=None):
    result = remove_at(settings, move_from) if move_from is not None else deepcopy(settings)
    result['items'].append({'start': cell, 'type': 'field', 'field': field})
    return normalize(result)

def write_text(settings, cell, text):
    if any(not 32 <= ord(char) <= 126 for char in text):
        raise ValueError('请使用单行ASCII字符，包括空格和[]等符号')
    if cell < 0 or cell + len(text) > CELL_COUNT:
        raise ValueError('输入文字超出30格，内容未写入')
    result = deepcopy(settings)
    for position, char in enumerate(text, cell):
        owner = owner_at(result, position)
        if owner and owner['type'] == 'field':
            raise ValueError('该位置被信息控件占用；请先移走或删除控件')
        result = remove_at(result, position)
        if char != ' ':
            result['items'].append({'start': position, 'type': 'text', 'text': char})
    return normalize(result)

def selected_between(settings, first, last):
    """Touching any cell of an item selects the whole item."""
    low, high = sorted((first, last))
    return {item['start'] for item in settings['items']
            if item['start'] <= high and item['start'] + item_width(item) > low}

def move_items(settings, starts, delta):
    result = deepcopy(settings)
    for item in result['items']:
        if item['start'] in starts:
            item['start'] += delta
    return normalize(result)

def remove_items(settings, starts):
    return normalize({'items': [deepcopy(item) for item in settings['items'] if item['start'] not in starts]})

def gear_text(truck, mode='auto'):
    manual = mode == 'manual' or (mode == 'auto' and truck.shifter_type in ('manual', 'hshifter'))
    if manual:
        return str(max(-99, min(99, truck.gear)))
    if truck.gear == 0:
        return 'N'
    if truck.gear < 0:
        return f'R{min(99, abs(truck.gear))}'
    return f'A{min(99, truck.gear)}'

def duration(minutes):
    if minutes is None:
        return '--:--'
    minutes = max(0, minutes)
    if minutes <= 24 * 60:
        whole = int(minutes)
        return f'{whole // 60:02d}:{whole % 60:02d}'
    hours = int(minutes // 60)
    days, hour = divmod(hours, 24)
    if days < 10:
        return f'{days}d{hour:02d}h'
    # Two-digit days plus two-digit hours and both suffixes cannot fit five
    # cells. Indicate whole days and a remainder instead of truncating a value.
    return f'{min(999, days):03d}d+'

def field_values(truck, gear_mode='auto', now=None, speed_unit='km/h'):
    percent = truck.fuel_percent
    speed, limit = convert_speed(abs(truck.speed), speed_unit), convert_speed(truck.limit, speed_unit)
    return {'speed': f'{min(999, round(speed)):03d}',
            'limit': f'{min(999, round(limit)):03d}' if truck.limit > 0 else '---',
            'fuel': '--' if percent is None else f'{min(99, round(percent)):02d}',
            'time': '--:--' if truck.game_minutes is None else f'{(truck.game_minutes // 60) % 24:02d}:{truck.game_minutes % 60:02d}',
            'gear': gear_text(truck, gear_mode).ljust(3),
            'rpm': f'{min(9999, max(0, round(truck.rpm))):04d}',
            'real_time': (now or datetime.now()).strftime('%H:%M'),
            'cruise_speed': f'{min(999, max(0, round(convert_speed(truck.cruise_speed, speed_unit)))):03d}' if truck.cruise and truck.cruise_speed > 0 else '---',
            'job_remaining': duration(truck.job_remaining_minutes),
            'nav_time': duration(truck.route_seconds / 60) if truck.distance > 0 else '--:--',
            'nav_distance': f'{min(9999, max(0, round(truck.distance))):04d}' if truck.distance > 0 else '----',
            'rest_time': duration(truck.rest_minutes),
            'fuel_liters': f'{min(9999, max(0, round(truck.fuel))):04d}' if truck.capacity > 0 else '----'}

def render(truck, width=32, settings=None, gear_mode='auto', speed_unit='km/h'):
    settings = normalize(settings if settings is not None else DEFAULT_LAYOUT)
    values, cells = field_values(truck, gear_mode, speed_unit=speed_unit), [' '] * CELL_COUNT
    for item in settings['items']:
        text = values[item['field']] if item['type'] == 'field' else item['text']
        start = item['start']
        cells[start:start + len(text)] = text
    return ('<' if truck.left else '-') + ''.join(cells) + ('>' if truck.right else '-')

def render_preset(truck, variant=1, gear_mode='auto', speed_unit='km/h'):
    text = render(truck, settings=preset_layout(variant, speed_unit), gear_mode=gear_mode, speed_unit=speed_unit)
    percent = truck.fuel_percent
    if percent is None:
        text = text[:27] + '---%' + text[31:]
    elif round(percent) >= 100:
        text = text[:27] + '100%' + text[31:]
    return text
