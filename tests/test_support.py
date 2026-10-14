import json
import logging
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from halo_dashboard.app import Worker
from halo_dashboard.support import (RuntimeStatus, configure_logging, remember_devices, redact_text,
    export_feedback, collect_diagnostics, install_exception_hooks, record_ui_exception, plugin_information)
from halo_dashboard.telemetry import Truck


class SupportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.state = Path(self.temporary.name)
        self.logger = logging.getLogger()
        self.handlers, self.level = self.logger.handlers[:], self.logger.level
        self.logger.handlers.clear()

    def tearDown(self):
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
            handler.close()
        self.logger.handlers[:] = self.handlers
        self.logger.setLevel(self.level)
        self.temporary.cleanup()

    def test_rotation_bounds_disk_use_and_retains_recent_context(self):
        handler = configure_logging(self.state)
        handler.maxBytes, handler.backupCount = 1024, 2
        for index in range(100):
            logging.info('Record index=%s %s', index, 'x' * 100)
        handler.flush()
        files = list(self.state.glob('dashboard.log*'))
        self.assertEqual(len(files), 3)
        self.assertTrue(all(path.stat().st_size <= 1024 for path in files))
        self.assertIn('index=99', (self.state / 'dashboard.log').read_text(encoding='utf-8'))

    def test_paths_known_device_ids_and_legacy_screen_text_are_redacted(self):
        remember_devices([{'serial_number': 'SECRET-UNIT-123', 'path': b'PRIVATE-HID-PATH'}])
        raw = ('problem C:\\Users\\Alice\\Desktop\\app.py\n'
               'File "D:\\游戏目录\\plugin.dll", line 15\n'
               'network \\\\myserver\\private\\share\n'
               'SECRET-UNIT-123 PRIVATE-HID-PATH\n'
               "text='private \\' words' expected='other private text'\n"
               'hid \\\\?\\hid#vid_2d99&pid_b100#private-unit\n')
        result = redact_text(raw)
        for secret in ('Alice', '游戏目录', 'myserver', 'SECRET-UNIT-123', 'PRIVATE-HID-PATH', 'other private text', 'private-unit'):
            self.assertNotIn(secret, result)
        self.assertIn('line 15', result)
        self.assertEqual(redact_text('HID connected'), 'HID connected')

    def test_feedback_zip_is_allowlisted_bounded_private_and_valid_json(self):
        (self.state / 'settings.json').write_text('PRIVATE CONFIG')
        (self.state / 'screen-recovery.json').write_text('PRIVATE SCREEN')
        (self.state / 'validated-devices.json').write_text('PRIVATE REGISTRY')
        (self.state / 'dashboard.log').write_text('x' * 300000 + '\nrecent error\n', encoding='utf-8')
        (self.state / 'dashboard.log.1').write_text('File "C:\\Users\\Alice\\file.py"\n', encoding='utf-8')
        document = {'error': 'C:\\Users\\Alice\\failure "quoted"', 'devices': []}
        path = export_feedback(self.state, document, {'sync_failures': 1},
                               {'mode': 'custom', 'game_dir': 'PRIVATE GAME', 'custom': {'text': 'PRIVATE LAYOUT'}})
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(set(archive.namelist()), {'README.txt', 'report.json', 'logs/dashboard.log', 'logs/dashboard.log.1'})
            report = json.loads(archive.read('report.json'))
            self.assertEqual(report['runtime']['sync_failures'], 1)
            self.assertEqual(report['options'], {'mode': 'custom'})
            combined = b'\n'.join(archive.read(name) for name in archive.namelist()).decode()
            for secret in ('Alice', 'PRIVATE CONFIG', 'PRIVATE SCREEN', 'PRIVATE GAME', 'PRIVATE REGISTRY', 'PRIVATE LAYOUT'):
                self.assertNotIn(secret, combined)
            self.assertEqual(archive.read('logs/dashboard.log').decode().splitlines(), ['recent error'])
        self.assertFalse(list(path.parent.glob('*.tmp')))

    def test_partial_export_does_not_leave_a_broken_zip(self):
        with patch('halo_dashboard.support.zipfile.ZipFile', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                export_feedback(self.state, {})
        self.assertEqual(list((self.state / 'feedback').iterdir()), [])

    def test_python_thread_and_tk_exceptions_reach_private_log(self):
        old_sys, old_thread = sys.excepthook, threading.excepthook
        handler = configure_logging(self.state)
        try:
            install_exception_hooks()
            try:
                raise RuntimeError('bad file C:\\Users\\Alice\\data.json')
            except RuntimeError:
                exc_type, value, trace = sys.exc_info()
                sys.excepthook(exc_type, value, trace)
                threading.excepthook(SimpleNamespace(thread=threading.current_thread(),
                    exc_type=exc_type, exc_value=value, exc_traceback=trace))
                record_ui_exception(exc_type, value, trace)
            handler.flush()
            log = (self.state / 'dashboard.log').read_text(encoding='utf-8')
            for label in ('main-thread exception', 'thread exception', 'UI callback exception', 'Traceback'):
                self.assertIn(label, log)
            self.assertNotIn('Alice', log)
        finally:
            sys.excepthook, threading.excepthook = old_sys, old_thread

    def test_runtime_can_be_snapshotted_during_pending_usb_operation(self):
        runtime = RuntimeStatus()
        with self.assertRaises(OSError):
            with runtime.operation('sync_frame'):
                snapshot = runtime.snapshot()
                self.assertEqual(snapshot['operation'], 'sync_frame')
                self.assertGreaterEqual(snapshot['operation_seconds'], 0)
                raise OSError('disconnect')
        self.assertEqual(runtime.snapshot()['operation'], 'idle')
        runtime.increment('sync_failures')
        runtime.increment('sync_cycles')
        self.assertEqual(runtime.snapshot()['sync_failures'], 1)
        self.assertIsNotNone(runtime.snapshot()['last_success_elapsed_seconds'])

    def test_diagnostic_enumeration_failure_still_exports_telemetry_without_hid_open(self):
        class Reader:
            def read(self):
                return Truck(connected=True, speed=80)
            def close(self):
                pass
        with patch('halo_dashboard.hardware.hid.enumerate', side_effect=OSError('USB failure')), \
             patch('halo_dashboard.telemetry.Telemetry', Reader), \
             patch('halo_dashboard.device.hid.device') as opened:
            document = collect_diagnostics(self.state)
        self.assertTrue(document['collection_errors'])
        self.assertEqual(document['telemetry']['speed'], 80)
        self.assertFalse(document['hid_queries_sent'])
        opened.assert_not_called()

    def test_worker_initialization_failure_finishes_and_can_be_reported(self):
        with patch('halo_dashboard.app.Telemetry', side_effect=OSError('initialization failure')):
            worker = Worker()
            worker.start()
            self.assertTrue(worker.finished.wait(2))
        worker.join(2)
        self.assertEqual(worker.events.get_nowait()[0], 'error')
        self.assertTrue(worker.runtime.snapshot()['worker_finished'])

    def test_plugin_report_checks_hashes_without_disclosing_or_modifying_paths(self):
        plugin = self.state / '游戏' / 'bin' / 'win_x64' / 'plugins' / 'scs-telemetry.dll'
        plugin.parent.mkdir(parents=True)
        plugin.write_bytes(b'OTHER PLUGIN')
        result = plugin_information(self.state, {'ets2': str(self.state / '游戏')})
        self.assertFalse(result['installed']['ets2']['matches_bundled_version'])
        self.assertEqual(plugin.read_bytes(), b'OTHER PLUGIN')
        self.assertNotIn(str(self.state), json.dumps(result))


if __name__ == '__main__':
    unittest.main()
