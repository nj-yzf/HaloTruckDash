from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
import struct
import tempfile
import time
import unittest
import uuid
from test_core import fixture
from halo_dashboard.games import detect_game
from halo_dashboard.installer import install_plugin, sha256, PLUGIN_SHA256
from halo_dashboard.telemetry import Truck, Telemetry, decode_snapshot, SNAPSHOT_SIZE
from halo_dashboard.layout import render_preset, field_values, place_field, write_text, render
from halo_dashboard.display import format_frame

class AtsTests(unittest.TestCase):
    def test_ats_and_ets2_decode_same_common_fields_and_identify_source(self):
        data = fixture()
        ets, _ = decode_snapshot(data)
        struct.pack_into('<I', data, 52, 2)
        ats, _ = decode_snapshot(data)
        self.assertEqual((ets.game_id, ats.game_id), (1, 2))
        self.assertIn('美卡', ats.reason)
        for key, value in vars(ets).items():
            if key not in ('game_id', 'reason'):
                self.assertEqual(getattr(ats, key), value, key)
        struct.pack_into('<i', data, 508, 18)
        self.assertEqual(field_values(decode_snapshot(data)[0])['gear'], 'A18')
        data[0] = 0
        ats, _ = decode_snapshot(data)
        self.assertFalse(ats.connected)
        self.assertEqual(format_frame(ats).text.strip('- '), 'WAIT ATS')

    def test_mph_converts_all_speed_fields_and_presets_remain_32_cells(self):
        truck = Truck(connected=True, game_id=2, speed=80.4672, limit=96.56064,
                      cruise=True, cruise_speed=88.51392, gear=18, fuel=67, capacity=100,
                      game_minutes=585, left=True, right=True)
        values = field_values(truck, speed_unit='mph')
        self.assertEqual((values['speed'], values['limit'], values['cruise_speed']), ('050', '060', '055'))
        self.assertEqual(render_preset(truck, 1, speed_unit='mph'), '< A18  050/060 mph  09:45  67% >')
        self.assertEqual(render_preset(truck, 2, speed_unit='mph'), '< A18  L060 050 mph  09:45 67% >')
        for mode in ('preset1', 'preset2', 'custom'):
            for unit in ('mph', 'km/h'):
                frame = format_frame(truck, mode, speed_unit=unit)
                self.assertEqual(len(frame.text), 32)
        # Manual unit text remains under user control; numeric fields still convert.
        custom = write_text(place_field({'items': []}, 0, 'speed'), 3, 'km/h')
        self.assertEqual(render(truck, settings=custom, speed_unit='mph')[1:8], '050km/h')
        truck.speed = 120
        self.assertEqual(format_frame(truck, speed_unit='mph').color, format_frame(truck, speed_unit='km/h').color)

    def test_ats_installs_same_plugin_and_refuses_wrong_target_or_overwrite(self):
        source = Path(__file__).resolve().parents[1] / 'assets' / 'scs-telemetry.dll'
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'research') as temporary:
            root = Path(temporary) / 'American Truck Simulator'
            binary = root / 'bin' / 'win_x64' / 'amtrucks.exe'
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b'test')
            self.assertEqual(detect_game(root).key, 'ats')
            with self.assertRaisesRegex(ValueError, '当前选择'):
                install_plugin(root, source, expected_game='ets2')
            self.assertFalse((binary.parent / 'plugins').exists())
            self.assertIn('美卡', install_plugin(root, source, expected_game='ats'))
            plugin = binary.parent / 'plugins' / 'scs-telemetry.dll'
            self.assertEqual(sha256(plugin), PLUGIN_SHA256)
            self.assertIn('已安装', install_plugin(root, source))
            unrelated = plugin.parent / 'other.dll'
            unrelated.write_bytes(b'other')
            plugin.write_bytes(b'existing')
            with self.assertRaises(FileExistsError):
                install_plugin(root, source)
            self.assertEqual((plugin.read_bytes(), unrelated.read_bytes()), (b'existing', b'other'))

    def test_switching_game_id_with_same_timestamp_resets_stale_detection(self):
        name = 'Local\\HaloAtsTest_' + uuid.uuid4().hex
        memory = SharedMemory(name=name, create=True, size=SNAPSHOT_SIZE)
        reader = Telemetry(name)
        try:
            memory.buf[:] = fixture()
            self.assertEqual(reader.read().game_id, 1)
            reader.last_change = time.monotonic() - 4
            struct.pack_into('<I', memory.buf, 52, 2)
            ats = reader.read()
            self.assertTrue(ats.connected)
            self.assertEqual(ats.game_id, 2)
        finally:
            reader.close()
            memory.close()

    def test_unsupported_game_and_units_are_not_misinterpreted(self):
        data = fixture()
        struct.pack_into('<I', data, 52, 99)
        self.assertFalse(decode_snapshot(data)[0].connected)
        with self.assertRaises(ValueError):
            field_values(Truck(), speed_unit='knots')

if __name__ == '__main__':
    unittest.main()
