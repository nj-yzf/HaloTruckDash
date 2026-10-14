import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from halo_dashboard.device import Halo
from halo_dashboard.display import Frame
from halo_dashboard.app import Worker
from halo_dashboard.telemetry import Truck
from halo_dashboard.hardware import (VID, DeviceRegistry, device_key, discover_candidates,
    known_device, eligible_device, device_rows, diagnostics_document)
from test_reliability import Firmware, Clock


def info(**changes):
    result = dict(vendor_id=VID, product_id=0xB100, product_string='花再 Halo PixelBar',
                  manufacturer_string='EDIFIER', serial_number='PRIVATE_SERIAL', path=b'PRIVATE_PATH',
                  interface_number=4, usage_page=0xFF14, usage=1, release_number=0x0100)
    result.update(changes)
    return result


class Board(Firmware):
    def __init__(self):
        super().__init__()
        self.paths = []
    def open_path(self, path):
        self.paths.append(path)


class HardwareTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.directory = Path(self.temporary.name)
        self.board = Board()
        self.clock = Clock()
        self.patch_clock = patch('halo_dashboard.device.time', self.clock)
        self.patch_clock.start()
        self.patch_board = patch('halo_dashboard.device.hid.device', return_value=self.board)
        self.factory = self.patch_board.start()
        self.halo = Halo(self.directory / 'screen-recovery.json')
    def tearDown(self):
        self.halo.close()
        self.patch_board.stop()
        self.patch_clock.stop()
        self.temporary.cleanup()

    def test_unknown_pid_and_other_interfaces_are_discovered_without_opening(self):
        devices = [info(), info(interface_number=1, usage_page=12, path=b'consumer'),
                   info(vendor_id=0x9999, path=b'new-vendor'),
                   info(vendor_id=0x9999, product_string='Other keyboard', path=b'keyboard')]
        with patch('halo_dashboard.hardware.hid.enumerate', return_value=devices + [devices[0]]):
            found = discover_candidates()
            self.assertEqual(found, devices[:3])
            rows = device_rows(self.halo.registry, found)
            self.assertEqual([row['status'] for row in rows], ['待验证', '仅供诊断', '待验证'])
        self.factory.assert_not_called()
        self.assertEqual(self.board.writes, [])

    def test_unverified_unknown_device_is_not_opened_automatically(self):
        with patch('halo_dashboard.device.hid.enumerate', return_value=[info()]):
            with self.assertRaisesRegex(RuntimeError, '设备与诊断'):
                self.halo.open()
        self.factory.assert_not_called()

    def test_manual_verification_sends_only_two_queries_and_no_recovery_write(self):
        self.halo.verify_candidate(info())
        self.assertEqual([command for command, _ in self.board.writes], [0xEE, 0xE7])
        self.assertEqual(self.board.text, 'original')
        self.assertTrue(self.halo.registry.approved(info()))
        self.assertIsNone(self.halo.device)
        self.assertFalse(self.halo.recovery_path.exists())
        self.assertEqual(DeviceRegistry(self.halo.registry.path).selected, device_key(info()))

    def test_approved_unknown_revalidates_after_restart_and_can_restore(self):
        self.halo.verify_candidate(info())
        halo = Halo(self.halo.recovery_path)
        self.board.writes.clear()
        try:
            with patch('halo_dashboard.device.discover_candidates', return_value=[info()]):
                halo.open()
            self.assertEqual([command for command, _ in self.board.writes], [0xEE, 0xE7])
            halo.capture()
            halo.show(Frame('080km/h', (102, 175, 255)), verify=True)
            self.assertEqual(self.board.text, '080km/h')
            halo.restore()
            self.assertEqual(self.board.text, 'original')
            self.assertFalse(halo.recovery_path.exists())
        finally:
            halo.close()

    def test_wrong_state_or_text_response_does_not_enable_device(self):
        self.board.state = bytes([1, *self.board.state[1:]])
        with self.assertRaises(ValueError):
            self.halo.verify_candidate(info())
        self.assertFalse(self.halo.registry.path.exists())
        self.board.state = bytes([0, *self.board.state[1:]])
        with patch('halo_dashboard.device.read_text', side_effect=ValueError('unsupported format')):
            with self.assertRaises(ValueError):
                self.halo.verify_candidate(info())
        self.assertFalse(self.halo.registry.path.exists())
        self.assertTrue(all(command in (0xEE, 0xE7) for command, _ in self.board.writes))

    def test_non_control_interface_cannot_be_probed(self):
        for device in (info(usage_page=12), info(product_string='Other speaker'), info(usage=3)):
            with self.subTest(device=device), self.assertRaises(ValueError):
                self.halo.verify_candidate(device)
        self.factory.assert_not_called()

    def test_setting_commands_are_blocked_in_verification_mode(self):
        self.halo.device = self.board
        self.halo.query_only = True
        with self.assertRaisesRegex(RuntimeError, '只允许查询'):
            self.halo.write(0xE8, b'bad')
        self.assertEqual(self.board.writes, [])

    def test_approval_is_not_global_for_pid_or_firmware_or_another_unit(self):
        self.halo.verify_candidate(info())
        for changes in ({'product_id': 0xB101}, {'release_number': 0x0200},
                        {'interface_number': 5}, {'serial_number': 'OTHER_SERIAL'}):
            with self.subTest(changes=changes):
                self.assertFalse(self.halo.registry.approved(info(**changes)))
        self.assertTrue(self.halo.registry.approved(info(product_string='')))
        anonymous = info(serial_number=None)
        self.halo.registry.select(anonymous, verified=True)
        self.assertFalse(self.halo.registry.approved(info(serial_number=None, path=b'other-port')))

    def test_failed_preference_save_cannot_leave_in_memory_approval(self):
        with patch('halo_dashboard.hardware.atomic_json', side_effect=PermissionError()):
            with self.assertRaises(PermissionError):
                self.halo.verify_candidate(info())
        self.assertFalse(self.halo.registry.approved(info()))
        self.assertIsNone(self.halo.registry.selected)

    def test_diagnostics_include_unknown_interfaces_but_omit_private_identifiers(self):
        self.halo.verify_candidate(info())
        self.board.writes.clear()
        document = diagnostics_document(self.halo.registry, [info(), info(usage_page=12)])
        encoded = json.dumps(document)
        self.assertEqual(len(document['devices']), 2)
        self.assertFalse(document['hid_queries_sent'])
        for private in ('PRIVATE_SERIAL', 'PRIVATE_PATH', device_key(info()), 'serial_number', '"path"'):
            self.assertNotIn(private, encoded)
        self.assertEqual(self.board.writes, [])

    def test_selected_device_is_not_replaced_by_another_connected_unit(self):
        self.halo.verify_candidate(info())
        with patch('halo_dashboard.device.discover_candidates', return_value=[info(serial_number='OTHER_SERIAL')]):
            with self.assertRaises(RuntimeError):
                self.halo.open()
        self.assertEqual(self.board.paths, [info()['path']])

    def test_cross_device_recovery_is_refused_before_setting_commands(self):
        self.halo.info, self.halo.device = info(product_id=0xA160), self.board
        self.halo.capture()
        original = self.halo.recovery_path.read_bytes()
        self.halo.info = info(product_id=0xA160, serial_number='OTHER_SERIAL')
        self.board.writes.clear()
        with self.assertRaisesRegex(ValueError, '另一台'):
            self.halo.capture()
        with self.assertRaisesRegex(ValueError, '不匹配'):
            self.halo.restore()
        self.assertEqual(self.halo.recovery_path.read_bytes(), original)
        self.assertTrue(all(command in (0xEE, 0xE7) for command, _ in self.board.writes))

    def test_legacy_recovery_can_bind_known_device_but_not_unknown(self):
        legacy = {'state': list(self.board.state[:9]), 'text': 'original'}
        self.halo.recovery_path.write_text(json.dumps(legacy), encoding='utf-8')
        self.halo.info, self.halo.device = info(), self.board
        with self.assertRaisesRegex(ValueError, '未绑定'):
            self.halo.capture()
        self.halo.info = info(product_id=0xA160)
        self.halo.capture()
        self.assertEqual(self.halo.saved['device_key'], device_key(self.halo.info))
        self.assertEqual(self.halo.saved['text'], 'original')

    def test_missing_metadata_is_diagnosable_and_malformed_registry_is_not_trusted(self):
        rows = device_rows(self.halo.registry, [info(vendor_id=None, product_id=None, interface_number=None)])
        self.assertEqual((rows[0]['vid'], rows[0]['pid'], rows[0]['status']), ('未知', '未知', '仅供诊断'))
        self.halo.registry.path.write_text('{bad json', encoding='utf-8')
        registry = DeviceRegistry(self.halo.registry.path)
        self.assertEqual(registry.records, {})
        self.assertFalse(registry.usable(info()))

    def test_worker_verifies_then_syncs_blocks_reverification_and_exports_without_queries(self):
        class Reader:
            def read(self):
                return Truck(connected=True, speed=80, gear=12)
            def close(self):
                pass

        def receive(worker, kind, predicate=lambda value: True):
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                event, value = worker.events.get(timeout=max(.01, deadline - time.monotonic()))
                if event == kind and predicate(value):
                    return value
            self.fail(f'Worker event not received: {kind}')

        with patch('halo_dashboard.app.STATE', self.directory), \
             patch('halo_dashboard.app.Telemetry', Reader), \
             patch('halo_dashboard.hardware.hid.enumerate', return_value=[info()]):
            worker = Worker()
            worker.start()
            try:
                worker.commands.put(('hardware_verify', device_key(info())))
                notice = receive(worker, 'hardware_notice')
                self.assertFalse(notice['error'], notice)
                self.assertEqual([command for command, _ in self.board.writes], [0xEE, 0xE7])
                worker.commands.put(('hardware_export', None))
                self.assertFalse(receive(worker, 'hardware_notice')['error'])
                self.assertEqual(len(self.board.writes), 2)
                document = json.loads((self.directory / 'diagnostics.json').read_text(encoding='utf-8'))
                self.assertEqual(document['devices'][0]['status'], '用户验证通过')
                self.assertFalse(document['hid_queries_sent'])
                worker.commands.put('start')
                receive(worker, 'device', lambda value: '正在同步' in value)
                worker.commands.put(('hardware_verify', device_key(info())))
                notice = receive(worker, 'hardware_notice')
                self.assertTrue(notice['error'])
                self.assertIn('先停止同步', notice['text'])
                self.assertTrue(worker.active)
                self.assertNotEqual(self.board.text, 'original')
                worker.commands.put('stop')
                receive(worker, 'device', lambda value: '已停止同步' in value)
                self.assertEqual(self.board.text, 'original')
                self.assertFalse((self.directory / 'screen-recovery.json').exists())
            finally:
                worker.commands.put('quit')
                self.assertTrue(worker.finished.wait(3))


if __name__ == '__main__':
    unittest.main()
