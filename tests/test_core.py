import json
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
import struct
import tempfile
import time
import unittest
import uuid

from halo_dashboard.device import packet, parse_response, read_text, text_payload
from halo_dashboard.display import format_frame, COLORS
from halo_dashboard.installer import install_plugin, PLUGIN_SHA256, sha256
from halo_dashboard.telemetry import Truck, Telemetry, decode_snapshot, SNAPSHOT_SIZE

def fixture():
    data = bytearray(SNAPSHOT_SIZE)
    for offset, fmt, value in [(0, '?', True), (40, 'I', 12), (52, 'I', 1), (8, 'Q', 100),
                               (508, 'i', -2), (704, 'f', 600), (948, 'f', -20),
                               (952, 'f', 1500), (1000, 'f', 300), (1068, 'f', 25),
                               (1580, '?', True), (64, 'I', 7 * 1440 + 18 * 60 + 45)]:
        struct.pack_into('<' + fmt, data, offset, value)
    data[3196:3205] = b'automatic'
    return data

class CoreTests(unittest.TestCase):
    def test_units_and_dashboard_gear(self):
        truck, timestamp = decode_snapshot(fixture())
        self.assertTrue(truck.connected)
        self.assertEqual((truck.speed, truck.limit, truck.gear, truck.fuel_percent, timestamp), (-72, 90, -2, 50, 100))
        self.assertEqual(truck.game_minutes % 1440, 18 * 60 + 45)
        self.assertIn('072/090km/h', format_frame(truck).text)
        self.assertIn('R2', format_frame(truck).text)
        self.assertEqual(truck.shifter_type, 'automatic')

    def test_unknown_revision_refused(self):
        data = fixture()
        struct.pack_into('<I', data, 40, 999)
        with self.assertRaisesRegex(ValueError, '999'):
            decode_snapshot(data)

    def test_mapping_lifecycle_and_stale_data(self):
        name = 'Local\\HaloDashTest_' + uuid.uuid4().hex
        memory = SharedMemory(name=name, create=True, size=SNAPSHOT_SIZE)
        reader = Telemetry(name)
        try:
            memory.buf[:] = fixture()
            self.assertTrue(reader.read().connected)
            reader.last_change = time.monotonic() - 4
            self.assertFalse(reader.read().connected)
            memory.buf[4] = 1
            self.assertTrue(reader.read().paused)
            memory.close()
            self.assertFalse(reader.read().connected)
        finally:
            reader.close()
            memory.close()

    def test_short_frames_and_alert_priority(self):
        truck = Truck(connected=True, speed=110, gear=12, rpm=1500, fuel=300, capacity=600, limit=80)
        for mode in ('preset1', 'preset2', 'custom'):
            for seconds in (0, 3, 6, 9):
                frame = format_frame(truck, mode, seconds)
                self.assertEqual(len(frame.text), 32)
                self.assertLessEqual(len(frame.text.encode()), 48)
                self.assertEqual(frame.color, (255, 80, 70))
        truck.low_fuel = True
        self.assertEqual(format_frame(truck).color, (255, 170, 30))
        truck.paused = True
        self.assertIn('110/080km/h', format_frame(truck).text)
        truck.connected = False
        self.assertEqual(format_frame(truck).text.strip('- '), 'WAIT ETS2/ATS')

    def test_unknown_fuel_and_reverse(self):
        truck = Truck(connected=True, gear=-1, speed=-5)
        self.assertIn('---%', format_frame(truck).text)
        self.assertIn('005/---km/h', format_frame(truck).text)
        self.assertIn('R1', format_frame(truck).text)

    def test_known_hardware_response_and_checksum(self):
        response = bytes.fromhex('2fbbecee000c00f0b4c800010009ff01000017').ljust(64, b'\0')
        self.assertEqual(parse_response(response, 0xee)[1:4], bytes([240, 180, 200]))
        invalid = bytearray(response)
        invalid[7] ^= 1
        with self.assertRaises(ValueError):
            parse_response(invalid, 0xee)

    def test_text_encoding_and_constraints(self):
        text = '仪表正常'
        encoded = text.encode()
        self.assertEqual(read_text(bytes([0, 16, 50, len(encoded)]) + encoded), text)
        self.assertEqual(read_text(bytes([0, len(encoded)]) + encoded), text)
        payload = text_payload(text)
        frame = packet(0xe8, payload)
        self.assertEqual(len(frame), 64)
        self.assertEqual(frame[6:6+len(payload)], payload)
        self.assertEqual(frame[6+len(payload)], sum(frame[1:6+len(payload)]) & 255)
        with self.assertRaises(ValueError):
            text_payload('a' * 49)

    def test_installer_preserves_existing_plugin(self):
        source = Path(__file__).resolve().parents[1] / 'assets' / 'scs-telemetry.dll'
        self.assertEqual(sha256(source), PLUGIN_SHA256)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / 'bin' / 'win_x64' / 'eurotrucks2.exe'
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b'test')
            install_plugin(root, source)
            target = binary.parent / 'plugins' / 'scs-telemetry.dll'
            self.assertEqual(sha256(target), PLUGIN_SHA256)
            target.write_bytes(b'existing plugin')
            with self.assertRaises(FileExistsError):
                install_plugin(root, source)
            self.assertEqual(target.read_bytes(), b'existing plugin')

if __name__ == '__main__':
    unittest.main()
