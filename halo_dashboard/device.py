"""Halo screen-only HID driver. No volume, firmware or ambient-light commands."""
import json
import logging
from pathlib import Path
import time
import hid
from .hardware import (VID, PIDS, known_device, eligible_device, discover_candidates,
                       device_key, DeviceRegistry)
from .layout_library import atomic_json

def packet(command, payload=b""):
    body = bytes(payload)
    if len(body) > 57:
        raise ValueError("HID 数据包过长")
    data = bytearray([0x2E, 0xAA, 0xED, command, len(body) >> 8, len(body) & 255])
    data.extend(body)
    data.append(sum(data[1:]) & 255)
    return bytes(data).ljust(64, b"\0")

def text_payload(text):
    encoded = text.encode("utf-8")
    if not text or len(encoded) > 48:
        raise ValueError("屏幕文字必须为 1–48 个 UTF-8 字节")
    return bytes([0, len(encoded)]) + encoded

def parse_response(data, command):
    data = bytes(data)
    if len(data) < 7 or data[:4] != bytes([0x2F, 0xBB, 0xEC, command]):
        raise ValueError("音响返回了不匹配的响应")
    length = int.from_bytes(data[4:6], "big")
    end = 6 + length
    if end >= len(data) or data[end] != sum(data[1:end]) & 255:
        raise ValueError("音响响应校验失败")
    return data[6:end]

def read_text(payload):
    # A160 query: slot, two metadata bytes, current_byte_length, UTF-8.
    # Metadata byte 0x10 is not assumed to be an ASCII character limit.
    if len(payload) >= 4 and payload[0] == 0 and len(payload) == 4 + payload[3]:
        return payload[4:].decode("utf-8")
    # Community protocol variant: slot, current_byte_length, UTF-8.
    if len(payload) >= 2 and payload[0] == 0 and len(payload) == 2 + payload[1]:
        return payload[2:].decode("utf-8")
    raise ValueError("无法解析音响的文字读回格式")

def enumerate_devices():
    return [d for d in hid.enumerate(VID, 0) if known_device(d)]

class Halo:
    def __init__(self, recovery_path: Path):
        self.device = None
        self.info = None
        self.saved = None
        self.last_text = None
        self.last_color = None
        self.recovery_path = recovery_path
        self.registry = DeviceRegistry(recovery_path.parent / 'validated-devices.json')
        self.query_only = False
        self.last_text_write = 0.0
        self.last_layout_write = 0.0
        self.last_health_check = 0.0
        self.last_write = 0.0

    def drain(self):
        """Consume write acknowledgements instead of letting HID input accumulate."""
        self.device.set_nonblocking(True)
        for _ in range(128):
            if not self.device.read(64):
                break

    def layout(self, color):
        self.write(0xEF, bytes([1, *color, 0, 2, 0, 1, 255]))
        self.write(0xEF, bytes([3, *color, 0, 0, 255, 255, 255]))
        self.last_layout_write = time.monotonic()

    def open(self):
        if self.registry.records or self.registry.selected:
            devices = [info for info in discover_candidates() if self.registry.usable(info)]
            target = self.saved.get('device_key') if isinstance(self.saved, dict) else None
            target = target or self.registry.selected
            if target:
                devices = [info for info in devices if device_key(info) == target]
        else:
            devices = enumerate_devices()
        if not devices:
            raise RuntimeError("未找到可用的Halo控制接口；请检查USB数据线，或在“设备与诊断”中验证候选设备")
        if len(devices) > 1:
            raise RuntimeError('检测到多个Halo控制接口，请在“设备与诊断”中验证并选用其中一台')
        self.info = devices[0]
        self.device = hid.device()
        try:
            self.device.open_path(self.info["path"])
            if known_device(self.info):
                self.query(0xEE)  # Validate framing before any settings are changed.
            else:
                self.query_only = True
                self.protocol_snapshot()  # Recheck an approved variant on every connection.
                self.query_only = False
        except Exception:
            self.query_only = False
            self.close()
            raise

    def protocol_snapshot(self):
        state = self.query(0xEE)
        if len(state) < 9 or state[0] != 0:
            raise ValueError('屏幕状态响应格式或状态码不兼容')
        original = read_text(self.query(0xE7, b'\0'))
        if len(original.encode('utf-8')) > 48:
            raise ValueError('原文字超过可恢复范围，未启用此设备')
        return state, original

    def verify_candidate(self, info):
        if self.device:
            raise RuntimeError('请先停止同步，再验证设备')
        if not (eligible_device(info) or self.registry.usable(info)):
            raise ValueError('该接口仅供诊断，名称或屏幕控制接口信息不足')
        pending = self.saved.get('device_key') if isinstance(self.saved, dict) else None
        if pending and pending != device_key(info):
            raise ValueError('原音响仍有待恢复记录，请先连接原音响恢复屏幕')
        self.info = info
        self.device = hid.device()
        self.query_only = True
        try:
            self.device.open_path(info['path'])
            self.protocol_snapshot()
            self.registry.select(info, verified=True)
        finally:
            self.query_only = False
            self.close()

    def write(self, command, payload):
        if self.query_only and command not in (0xEE, 0xE7):
            raise RuntimeError('验证阶段只允许查询屏幕状态和文字')
        self.drain()
        # Space consecutive commands; firmware applies settings asynchronously.
        remaining = .03 - (time.monotonic() - self.last_write)
        if remaining > 0:
            time.sleep(remaining)
        count = self.device.write(packet(command, payload))
        if count != 64:
            raise OSError(f"HID 发送失败：只写入 {count}/64 字节")
        self.last_write = time.monotonic()

    def query(self, command, payload=b""):
        self.write(command, payload)
        self.device.set_nonblocking(False)
        deadline = time.monotonic() + 1.2
        while time.monotonic() < deadline:
            data = self.device.read(64, 200)
            if data and bytes(data)[:4] == bytes([0x2F, 0xBB, 0xEC, command]):
                return parse_response(data, command)
        raise TimeoutError("音响查询超时，请关闭其他程序对音响屏幕的控制后重试")

    def capture(self):
        state, original = self.protocol_snapshot()
        key = device_key(self.info) if self.info else None
        saved = {"state": list(state[:9]), "text": original, 'device_key': key}
        # A previous recovery record must survive a crash/reconnect.
        if self.recovery_path.exists():
            saved = json.loads(self.recovery_path.read_text(encoding="utf-8"))
            previous = saved.get('device_key')
            if previous and previous != key:
                raise ValueError('恢复记录属于另一台音响，请先连接原音响恢复，或备份并移走旧恢复记录')
            if not previous and self.info:
                if not known_device(self.info):
                    raise ValueError('旧版恢复记录未绑定设备，不能用于未知型号；请先用原音响恢复')
                saved['device_key'] = key
                atomic_json(self.recovery_path, saved)
        else:
            self.recovery_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(self.recovery_path, saved)
        self.saved = saved

    def show(self, frame, verify=False):
        now = time.monotonic()
        if frame.text != self.last_text or now - self.last_text_write >= 2:
            self.write(0xE8, text_payload(frame.text))
            self.last_text = frame.text
            self.last_text_write = time.monotonic()
        if frame.color != self.last_color or now - self.last_layout_write >= 3:
            self.layout(frame.color)
            self.last_color = frame.color
        if verify:
            self.wait_for(lambda: read_text(self.query(0xE7, b"\0")) == frame.text,
                          "文字读回不一致，可能有其他控制软件同时写入屏幕")
            expected = bytes([*frame.color, 0, 2, 0, 1, 255])
            self.wait_for(lambda: self.query(0xEE)[1:9] == expected,
                          "屏幕模式/颜色读回不一致，请暂停其他软件的屏幕同步")
        elif now - self.last_health_check >= 5:
            expected = bytes([*frame.color, 0, 2, 0, 1, 255])
            state = self.query(0xEE)
            text = read_text(self.query(0xE7, b"\0"))
            if state[1:9] != expected or text != frame.text:
                logging.warning("屏幕状态偏离仪表：state=%s text=%r expected=%r，重新应用", state.hex(), text, frame.text)
                self.write(0xE8, text_payload(frame.text))
                self.layout(frame.color)
                self.wait_for(lambda: read_text(self.query(0xE7, b"\0")) == frame.text,
                              "其他控制软件持续覆盖屏幕，请暂停其屏幕同步")
                self.wait_for(lambda: self.query(0xEE)[1:9] == expected,
                              "屏幕模式无法保持，请暂停其他控制软件的屏幕同步")
            self.last_health_check = time.monotonic()
        self.drain()

    @staticmethod
    def wait_for(check, message):
        # Firmware applies settings asynchronously after acknowledging the write.
        for _ in range(8):
            time.sleep(.06)
            if check():
                return
        raise RuntimeError(message)

    def restore(self):
        if not self.saved:
            return
        key = self.saved.get('device_key')
        if key and (not self.info or key != device_key(self.info)):
            raise ValueError('当前音响与恢复记录不匹配，已保留记录且未修改屏幕')
        original = self.saved["text"]
        if original:
            self.write(0xE8, text_payload(original))
        # Query byte 0 is status; setting action 1 reapplies mode/color/layout.
        setting = bytes([1, *self.saved["state"][1:9]])
        self.write(0xEF, setting)
        time.sleep(.03)
        self.write(0xEF, bytes([3, *self.saved["state"][1:4], 0, 0, 255, 255, 255]))
        self.wait_for(lambda: self.query(0xEE)[1:9] == setting[1:9],
                      "屏幕恢复校验失败，已保留恢复记录")
        if original:
            self.wait_for(lambda: read_text(self.query(0xE7, b"\0")) == original,
                          "原文字恢复校验失败，已保留恢复记录")
        self.recovery_path.unlink(missing_ok=True)
        self.saved = None

    def close(self):
        if self.device:
            self.device.close()
        self.device = None
        self.last_text = self.last_color = None
        self.last_text_write = self.last_layout_write = self.last_health_check = 0.0
