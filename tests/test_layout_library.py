from pathlib import Path
import json
import struct
import shutil
import tempfile
import unittest
from unittest.mock import patch
from halo_dashboard.layout import preset_layout, normalize
from halo_dashboard.layout_library import LayoutLibrary, export_layout, import_layout, document, MAX_BYTES, atomic_json, LIBRARY_FORMAT
from halo_dashboard.telemetry import decode_snapshot
from test_core import fixture

class LibraryTests(unittest.TestCase):
    def temporary(self):
        return tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'research')

    def test_named_layouts_survive_restart_and_can_be_replaced_or_deleted(self):
        with self.temporary() as tmp:
            path = Path(tmp) / 'data' / 'layouts.json'
            library = LayoutLibrary(path)
            library.save(' 日间 ', preset_layout(1))
            library.save('夜间', preset_layout(2))
            restored = LayoutLibrary(path)
            self.assertEqual(set(restored.entries()), {'日间', '夜间'})
            self.assertEqual(restored.load('夜间'), normalize(preset_layout(2)))
            restored.save('日间', {'items': []})
            restored.delete('夜间')
            self.assertEqual(LayoutLibrary(path).entries(), {'日间': {'items': []}})

    def test_portable_roundtrip_is_data_only_and_independent(self):
        with self.temporary() as tmp:
            path = Path(tmp) / '分享.json'
            original = preset_layout(1)
            export_layout(path, '分享方案', original)
            exported = import_layout(path)
            other = LayoutLibrary()
            other.save(exported['name'], exported['layout'])
            self.assertEqual(other.load('分享方案'), normalize(original))
            exported['layout']['items'].clear()
            self.assertTrue(other.load('分享方案')['items'])

    def test_bad_files_and_future_versions_refused_without_touching_library(self):
        with self.temporary() as tmp:
            path = Path(tmp) / 'layouts.json'
            library = LayoutLibrary(path)
            library.save('已有', preset_layout(1))
            stored = next(library.directory.glob('*.json'))
            before = stored.read_bytes()
            imported = Path(tmp) / 'import.json'
            for bad in [[], {}, {'format': 'halo-truck-dash-layout', 'version': 2},
                        document('重叠', {'items': []}) | {'layout': {'items': [
                            {'start': 0, 'type': 'field', 'field': 'speed'},
                            {'start': 1, 'type': 'field', 'field': 'rpm'}]}},
                        document('未知', {'items': []}) | {'layout': {'items': [
                            {'start': 0, 'type': 'field', 'field': ['speed']}]}},
                        document('越界', {'items': []}) | {'layout': {'items': [
                            {'start': 29, 'type': 'field', 'field': 'speed'}]}}]:
                imported.write_text(json.dumps(bad), encoding='utf-8')
                with self.assertRaises(ValueError):
                    import_layout(imported)
                self.assertEqual(stored.read_bytes(), before)
            imported.write_bytes(b'x' * (MAX_BYTES + 1))
            with self.assertRaises(ValueError):
                import_layout(imported)
            path.write_text('broken', encoding='utf-8')
            with self.assertRaises(ValueError):
                library.save('新', preset_layout(2))
            self.assertEqual(path.read_text(), 'broken')

    def test_failed_atomic_write_keeps_previous_file(self):
        with self.temporary() as tmp:
            path = Path(tmp) / 'layouts.json'
            library = LayoutLibrary(path)
            library.save('原布局', preset_layout(1))
            stored = next(library.directory.glob('*.json'))
            before = stored.read_bytes()
            with patch('halo_dashboard.layout_library.Path.replace', side_effect=OSError('模拟写入失败')):
                with self.assertRaises(OSError):
                    library.save('原布局', preset_layout(2))
            self.assertEqual(stored.read_bytes(), before)
            self.assertEqual(list(library.directory.glob('*.tmp')), [])

    def test_legacy_library_migrates_once_without_resurrecting_deleted_files(self):
        with self.temporary() as tmp:
            old = Path(tmp) / 'layouts.json'
            atomic_json(old, {'format': LIBRARY_FORMAT, 'version': 1, 'layouts': [document('旧布局', preset_layout(1))]})
            backup = old.read_bytes()
            library = LayoutLibrary(old)
            self.assertEqual(library.load('旧布局'), normalize(preset_layout(1)))
            self.assertEqual(old.read_bytes(), backup)
            stored = next(library.storage_directory().glob('*.json'))
            self.assertEqual(import_layout(stored)['name'], '旧布局')
            library.delete('旧布局')
            self.assertEqual(LayoutLibrary(old).entries(), {})
            self.assertEqual(old.read_bytes(), backup)

    def test_individual_files_can_be_batch_copied_and_external_files_are_discovered(self):
        with self.temporary() as tmp:
            first, second = LayoutLibrary(Path(tmp) / 'one'), LayoutLibrary(Path(tmp) / 'two')
            for index in range(2):
                first.save(first.new_name(), preset_layout(index + 1))
            self.assertEqual(first.new_name(), '我的布局03')
            destination = second.storage_directory()
            for path in first.directory.glob('*.json'):
                shutil.copy2(path, destination / path.name)
            self.assertEqual(second.entries(), first.entries())
            (destination / 'broken.json').write_text('bad', encoding='utf-8')
            self.assertEqual(second.entries(), first.entries())
            self.assertTrue(second.warnings)
            first.save('CON / A:B?', {'items': []})
            self.assertEqual(first.load('CON / A:B?'), {'items': []})

    def test_extended_telemetry_deadline_is_not_navigation_time_or_event_toggle(self):
        data = fixture()
        for offset, fmt, value in [(88, 'I', 13000), (4300, '?', True), (4301, '?', True),
                                   (500, 'i', 220), (988, 'f', 20), (1589, '?', True),
                                   (1064, 'f', 7200), (1060, 'f', 128000)]:
            struct.pack_into('<' + fmt, data, offset, value)
        truck, _ = decode_snapshot(data)
        self.assertEqual(truck.job_remaining_minutes, 13000 - truck.game_minutes)
        self.assertEqual((truck.cruise_speed, truck.route_seconds, truck.rest_minutes), (72, 7200, 220))
        # Finished/delivered flags are event toggles, not current job state.
        data[4300] = 0
        truck, _ = decode_snapshot(data)
        self.assertIsNone(truck.job_remaining_minutes)

if __name__ == '__main__':
    unittest.main()
