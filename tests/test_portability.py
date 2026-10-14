from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from halo_dashboard.device import enumerate_devices, Halo, VID, PIDS
from halo_dashboard.games import default_game_dir, steam_libraries, GAMES
from halo_dashboard.storage import data_directory


class PortabilityTests(unittest.TestCase):
    def test_steam_library_discovery_unicode_spaces_and_multiple_drives(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            steam = base / 'Steam'
            library = base / '游戏库 with spaces'
            (steam / 'steamapps').mkdir(parents=True)
            escaped = str(library).replace('\\', '\\\\')
            (steam / 'steamapps' / 'libraryfolders.vdf').write_text(
                f'"libraryfolders" {{ "1" {{ "path" "{escaped}" "apps" {{ "227300" "12345" }} }} }}', encoding='utf-8')
            for game in GAMES.values():
                binary = library / 'steamapps' / 'common' / game.folder / 'bin' / 'win_x64' / game.executable
                binary.parent.mkdir(parents=True)
                binary.write_bytes(b'test')
            with patch('halo_dashboard.games.steam_install_dirs', return_value=[steam]):
                self.assertIn(library, steam_libraries())
                self.assertEqual(steam_libraries(), [steam, library])
                for key, game in GAMES.items():
                    self.assertEqual(default_game_dir(key), library / 'steamapps' / 'common' / game.folder)

    def test_missing_steam_configuration_has_a_portable_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'Steam'
            with patch('halo_dashboard.games.steam_install_dirs', return_value=[root]):
                self.assertEqual(default_game_dir('ets2'), root / 'steamapps' / 'common' / GAMES['ets2'].folder)

    def test_legacy_vdf_and_malformed_utf8_do_not_break_startup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, library = Path(temporary) / 'Steam', Path(temporary) / 'Other Library'
            (root / 'steamapps').mkdir(parents=True)
            config = root / 'steamapps' / 'libraryfolders.vdf'
            with patch('halo_dashboard.games.steam_install_dirs', return_value=[root]):
                escaped = str(library).replace('\\', '\\\\')
                config.write_text(f'"1" "{escaped}"', encoding='utf-8')
                self.assertIn(library, steam_libraries())
                config.write_bytes(b'\xff\xfe')
                self.assertEqual(steam_libraries(), [root])

    def test_portable_data_and_read_only_installation_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, local = Path(temporary) / 'app', Path(temporary) / 'local'
            self.assertEqual(data_directory(base, local), base / 'data')
            with patch('halo_dashboard.storage.writable_directory', side_effect=[PermissionError(), local / 'HaloTruckDash' / 'data']):
                self.assertEqual(data_directory(base, local), local / 'HaloTruckDash' / 'data')

    def test_known_devices_without_product_strings_and_wrong_interfaces(self):
        devices = [dict(vendor_id=VID, product_id=pid, interface_number=4, usage_page=0xFF14,
                        usage=1, product_string=name, path=f'{pid}-{name}'.encode())
                   for pid in PIDS for name in ('EDIFIER Halo', 'PixelBar', '', None)]
        wrong = [dict(devices[0], vendor_id=0xFFFF), dict(devices[0], product_id=0xFFFF), dict(devices[0], interface_number=1),
                 dict(devices[0], usage_page=1), dict(devices[0], usage=2),
                 dict(devices[0], product_string='Unrelated Speaker')]
        with patch('halo_dashboard.device.hid.enumerate', return_value=devices + wrong):
            self.assertEqual(enumerate_devices(), devices)

    def test_multiple_speakers_are_not_arbitrarily_selected(self):
        with patch('halo_dashboard.device.enumerate_devices', return_value=[{}, {}]), patch('halo_dashboard.device.hid.device') as opened:
            with self.assertRaisesRegex(RuntimeError, '多个'):
                Halo(Path('unused.json')).open()
            opened.assert_not_called()


if __name__ == '__main__':
    unittest.main()
