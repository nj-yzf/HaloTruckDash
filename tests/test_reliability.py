from collections import deque
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import time

from halo_dashboard.device import Halo
from halo_dashboard.display import Frame
from halo_dashboard.telemetry import Truck
from halo_dashboard.app import Worker

class Clock:
    def __init__(self):
        self.now = 100.0
    def monotonic(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds

class Firmware:
    def __init__(self):
        self.state = bytes([0, 240, 180, 200, 0, 1, 0, 9, 255])
        self.text = 'original'
        self.queue = deque()
        self.writes = []
        self.maximum_pending = 0
    def set_nonblocking(self, flag):
        pass
    def read(self, length, timeout=0):
        return list(self.queue.popleft()) if self.queue else []
    def response(self, command, payload):
        data = bytearray([0x2f, 0xbb, 0xec, command, 0, len(payload)])
        data.extend(payload)
        data.append(sum(data[1:]) & 255)
        self.queue.append(bytes(data).ljust(64, b'\0'))
        self.maximum_pending = max(self.maximum_pending, len(self.queue))
    def write(self, data):
        command = data[3]
        payload = data[6:6+data[5]]
        self.writes.append((command, bytes(payload)))
        if command == 0xe8:
            self.text = payload[2:].decode()
        elif command == 0xef:
            if payload[0] == 1:
                self.state = bytes([0, *self.state[1:4], *payload[4:9]])
            elif payload[0] == 3:
                self.state = bytes([0, *payload[1:4], *self.state[4:9]])
        if command == 0xee:
            self.response(command, self.state)
        elif command == 0xe7:
            encoded = self.text.encode()
            self.response(command, bytes([0, 16, 50, len(encoded)]) + encoded)
        else:
            self.response(command, b'\0')  # setter acknowledgement
        return 64
    def close(self):
        pass

class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.halo = Halo(Path(self.tmp.name) / 'recovery.json')
        self.firmware = Firmware()
        self.halo.device = self.firmware
        self.clock = Clock()
        self.clock_patch = patch('halo_dashboard.device.time', self.clock)
        self.clock_patch.start()
        self.halo.capture()
    def tearDown(self):
        self.clock_patch.stop()
        self.tmp.cleanup()

    def test_three_minute_changing_stream_consumes_acknowledgements(self):
        for index in range(900):
            frame = Frame(f'{index % 100:03d} 12', (102, 175, 255))
            self.halo.show(frame, verify=index == 0)
            self.clock.sleep(.2)
        self.assertLessEqual(self.firmware.maximum_pending, 1)
        self.assertEqual(len(self.firmware.queue), 0)
        self.assertGreater(self.clock.now, 280)
        self.halo.restore()
        self.assertEqual(self.firmware.text, 'original')

    def test_unchanged_text_has_heartbeat_and_mode_refresh(self):
        frame = Frame('PAUSED', (102, 175, 255))
        for index in range(500):
            self.halo.show(frame, verify=index == 0)
            self.clock.sleep(.2)
        text_writes = [p for c, p in self.firmware.writes if c == 0xe8]
        layout_writes = [p for c, p in self.firmware.writes if c == 0xef and p[0] == 1]
        self.assertGreater(len(text_writes), 40)
        self.assertGreater(len(layout_writes), 25)

    def test_health_check_repairs_external_screen_change(self):
        frame = Frame('080 12', (102, 175, 255))
        self.halo.show(frame, verify=True)
        self.firmware.text = 'external'
        self.firmware.state = bytes([0, 240, 180, 200, 0, 1, 0, 9, 255])
        self.halo.show(frame)
        self.assertEqual(self.firmware.text, frame.text)
        self.assertEqual(self.firmware.state[1:9], bytes([102, 175, 255, 0, 2, 0, 1, 255]))

    def test_reconnect_keeps_original_recovery_record(self):
        frame = Frame('080 12', (102, 175, 255))
        self.halo.show(frame)
        saved = self.halo.saved.copy()
        self.halo.close()
        self.halo.device = self.firmware
        self.halo.capture()
        self.assertEqual(self.halo.saved, saved)
        self.halo.restore()
        self.assertEqual(self.firmware.text, 'original')

class WorkerTests(unittest.TestCase):
    def test_write_failure_reconnects_and_stop_restores_original(self):
        class Reader:
            def read(self):
                return Truck(connected=True, speed=80, gear=12)
            def close(self):
                pass
        class Transport:
            instance = None
            def __init__(self, path):
                Transport.instance = self
                self.recovery_path = path
                self.device = None
                self.saved = None
                self.info = {'product_id': 0xa160}
                self.opens = self.failures = self.successes = self.restores = 0
            def open(self):
                self.opens += 1
                self.device = True
            def capture(self):
                if self.saved is None:
                    self.saved = 'original'
            def show(self, frame, verify=False):
                if not self.failures:
                    self.failures += 1
                    raise OSError('simulated USB disconnect')
                self.successes += 1
            def restore(self):
                if self.saved is not None:
                    self.restores += 1
                    self.saved = None
            def close(self):
                self.device = None
        with patch('halo_dashboard.app.Telemetry', Reader), patch('halo_dashboard.app.Halo', Transport):
            worker = Worker()
            worker.start()
            worker.commands.put('start')
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and not (Transport.instance and Transport.instance.successes):
                    time.sleep(.05)
                transport = Transport.instance
                self.assertGreaterEqual(transport.opens, 2)
                self.assertGreater(transport.successes, 0)
                self.assertTrue(worker.active)
                worker.commands.put('stop')
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline and worker.active:
                    time.sleep(.05)
                self.assertFalse(worker.active)
                self.assertEqual(transport.restores, 1)
            finally:
                worker.commands.put('quit')
                self.assertTrue(worker.finished.wait(3))

if __name__ == '__main__':
    unittest.main()
