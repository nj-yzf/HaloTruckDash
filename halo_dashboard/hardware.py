"""Discover related HID interfaces and keep explicit, device-bound approvals."""
import hashlib
import json
from pathlib import Path
import re
import hid

from .layout_library import atomic_json
from .support import remember_devices

VID = 0x2D99
PIDS = (0xA160, 0xA106)


def family_name(info):
    name = str(info.get('product_string') or '').casefold()
    return 'pixelbar' in name and ('halo' in name or '花再' in name)


def known_device(info):
    name = str(info.get('product_string') or '').casefold()
    return (info.get('vendor_id') == VID and info.get('product_id') in PIDS
            and info.get('interface_number') == 4 and info.get('usage_page') == 0xFF14
            and info.get('usage') == 1 and (not name or 'halo' in name or 'pixelbar' in name))


def eligible_device(info):
    identity = family_name(info) or (info.get('vendor_id') == VID and info.get('product_id') in PIDS)
    return bool(identity and info.get('usage_page') == 0xFF14 and info.get('usage') == 1
                and type(info.get('interface_number')) is int and 0 <= info['interface_number'] <= 255
                and info.get('path'))


def discover_candidates():
    # Enumerate metadata only. Do not open devices or send any HID reports.
    result, seen = [], set()
    inventory = hid.enumerate()
    remember_devices(inventory)
    for info in inventory:
        if info.get('vendor_id') != VID and not family_name(info):
            continue
        path = info.get('path')
        if not path or path in seen:
            continue
        seen.add(path)
        result.append(info)
    return result


def device_profile(info):
    return {field: info.get(field) for field in
            ('vendor_id', 'product_id', 'interface_number', 'usage_page', 'usage', 'release_number')}


def device_key(info):
    serial = info.get('serial_number')
    path = info.get('path', b'')
    if isinstance(path, bytes):
        path = path.hex()
    identity = {'profile': device_profile(info), 'serial' if serial else 'path': serial or path}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


class DeviceRegistry:
    def __init__(self, path):
        self.path = Path(path)
        self.records, self.selected = {}, None
        try:
            if self.path.stat().st_size > 128 * 1024:
                return
            data = json.loads(self.path.read_text(encoding='utf-8-sig'))
            if data.get('format') != 'halo-truck-dash-devices' or type(data.get('version')) is not int or data['version'] != 1:
                return
            records = data.get('verified', {})
            if isinstance(records, dict) and len(records) <= 100:
                self.records = {key: profile for key, profile in records.items()
                                if re.fullmatch(r'[0-9a-f]{64}', key) and isinstance(profile, dict)}
            selected = data.get('selected')
            if isinstance(selected, str) and re.fullmatch(r'[0-9a-f]{64}', selected):
                self.selected = selected
        except (OSError, ValueError, AttributeError, RecursionError):
            pass

    def approved(self, info):
        return self.records.get(device_key(info)) == device_profile(info)

    def usable(self, info):
        return known_device(info) or self.approved(info)

    def select(self, info, verified=False):
        if not self.usable(info) and not (verified and eligible_device(info)):
            raise ValueError('该接口尚未通过基础协议验证')
        key = device_key(info)
        records = self.records.copy()
        if not known_device(info):
            if key not in records and len(records) >= 100:
                raise ValueError('已验证设备记录超过100个，请整理设备记录后重试')
            records[key] = device_profile(info)
        atomic_json(self.path, {'format': 'halo-truck-dash-devices', 'version': 1,
                               'selected': key, 'verified': records})
        self.records, self.selected = records, key


def device_rows(registry, devices=None, include_keys=False):
    rows = []
    for info in discover_candidates() if devices is None else devices:
        known, verified = known_device(info), registry.approved(info)
        eligible = eligible_device(info) or verified or known
        status = '已知设备' if known else '用户验证通过' if verified else '待验证' if eligible else '仅供诊断'
        vid, pid = info.get('vendor_id'), info.get('product_id')
        row = {'vid': f'{vid:04X}' if isinstance(vid, int) else '未知',
               'pid': f'{pid:04X}' if isinstance(pid, int) else '未知',
               'product': ' '.join(str(info.get('product_string') or '名称未提供').split())[:100],
               'manufacturer': ' '.join(str(info.get('manufacturer_string') or '').split())[:100],
               'interface': info.get('interface_number'), 'usage_page': info.get('usage_page'),
               'usage': info.get('usage'), 'release_number': info.get('release_number'),
               'status': status, 'known': known, 'verified': verified, 'can_verify': eligible,
               'usable': known or verified, 'selected': registry.selected == device_key(info),
               'reason': '可执行屏幕状态和文字查询，不改变显示内容' if eligible else '名称或控制接口信息不足，仅枚举信息，不发送查询'}
        if include_keys:
            row['key'] = device_key(info)
        rows.append(row)
    return rows


def diagnostics_document(registry, devices=None, truck=None):
    import platform
    import struct
    from .version import VERSION
    result = {'application': 'HaloTruckDash', 'version': VERSION, 'windows': platform.platform(),
              'process_bits': struct.calcsize('P') * 8, 'devices': device_rows(registry, devices),
              'hid_queries_sent': False, 'note': '本诊断仅枚举USB信息，不发送HID查询或屏幕设置；序列号和设备路径不导出。'}
    if truck is not None:
        result['telemetry'] = vars(truck)
    return result
