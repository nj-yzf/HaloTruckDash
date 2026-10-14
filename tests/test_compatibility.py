"""Exercise concurrent read-only clients without opening the real game's map."""
from concurrent.futures import ThreadPoolExecutor
import json
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
import struct
import subprocess
import sys
import time
import unittest
import uuid

from test_core import fixture
from halo_dashboard.telemetry import SNAPSHOT_SIZE, Telemetry


class CompatibilityTests(unittest.TestCase):
    def test_independent_readers_share_map_without_modifying_or_owning_it(self):
        name = 'Local\\HaloCoexistTest_' + uuid.uuid4().hex
        memory = SharedMemory(name=name, create=True, size=SNAPSHOT_SIZE)
        reader = Telemetry(name)
        script = '''
import json, sys, time
from halo_dashboard.telemetry import Telemetry
reader = Telemetry(sys.argv[1])
values = []
try:
    for _ in range(60):
        truck = reader.read()
        assert truck.connected, truck.reason
        values.append(truck.speed)
        time.sleep(.01)
finally:
    reader.close()
print(json.dumps(values))
'''
        try:
            original = fixture()
            memory.buf[:] = original
            with ThreadPoolExecutor(max_workers=1) as pool:
                other = pool.submit(subprocess.run, [sys.executable, '-c', script, name],
                                    cwd=Path(__file__).resolve().parents[1],
                                    text=True, capture_output=True, timeout=10)
                for index in range(100):
                    # The producer alone updates the map; readers must neither
                    # alter its bytes nor prevent it from updating.
                    struct.pack_into('<Q', original, 8, index + 100)
                    memory.buf[:] = original
                    self.assertTrue(reader.read().connected)
                    self.assertEqual(bytes(memory.buf), original)
                    time.sleep(.01)
                result = other.result()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(json.loads(result.stdout)), 60)
            self.assertEqual(bytes(memory.buf), original)
            reader.close()
            # The producer and another client survive one client's exit.
            survivor = Telemetry(name)
            try:
                self.assertTrue(survivor.read().connected)
            finally:
                survivor.close()
        finally:
            reader.close()
            memory.close()


if __name__ == '__main__':
    unittest.main()
