"""Audit the stable ZIP, embedded runtime/icons/version, and isolated EXE startup."""
import argparse
import hashlib
import os
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import CodeType
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pefile
from PyInstaller.archive.readers import CArchiveReader
from halo_dashboard.installer import PLUGIN_SHA256
from halo_dashboard.version import VERSION, PRODUCT_NAME


def strings(code):
    for value in code.co_consts:
        if isinstance(value, str):
            yield value
        elif isinstance(value, CodeType):
            yield from strings(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ui-smoke', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    release = root / 'dist' / f'v{VERSION}'
    exe = release / 'HaloTruckDash.exe'
    archive = root / 'dist' / f'HaloTruckDash-v{VERSION}-win-x64.zip'
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
        names = [name.replace('\\', '/') for name in package.namelist()]
        assert all(not name.startswith(('data/', 'research/', '.git/')) and '/data/' not in name for name in names)
        assert all(name in names for name in ['HaloTruckDash.exe', 'LICENSE', 'README.md', 'THIRD_PARTY_NOTICES.md', 'docs/COMPATIBILITY.md', 'docs/SUPPORT.md'])
        assert package.read('HaloTruckDash.exe') == exe.read_bytes()
    for line in (release / 'SHA256SUMS.txt').read_text(encoding='ascii').splitlines():
        digest, name = line.split('  ', 1)
        path = exe if name == exe.name else archive
        assert name == path.name and hashlib.sha256(path.read_bytes()).hexdigest() == digest
    pe = pefile.PE(str(exe))
    assert pe.FILE_HEADER.Machine == 0x8664 and pe.OPTIONAL_HEADER.Subsystem == 2
    assert {3, 14, 16}.issubset({entry.id for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries})
    metadata = {}
    for entries in pe.FileInfo:
        for entry in entries:
            for table in getattr(entry, 'StringTable', []):
                metadata.update(table.entries)
    assert metadata[b'ProductName'].decode() == PRODUCT_NAME
    assert metadata[b'FileVersion'].decode() == VERSION
    bundled = CArchiveReader(str(exe))
    names = {name.replace('\\', '/') for name in bundled.toc}
    for suffix in ('python311.dll', '_tkinter.pyd', '_ctypes.pyd', 'VCRUNTIME140.dll'):
        assert any(name.lower().endswith(suffix.lower()) for name in names), suffix
    assert 'assets/HaloTruckDash.ico' in names
    plugin = next(name for name in bundled.toc if name.replace('\\', '/') == 'assets/scs-telemetry.dll')
    assert hashlib.sha256(bundled.extract(plugin)).hexdigest() == PLUGIN_SHA256
    pyz = bundled.open_embedded_archive('PYZ.pyz')
    assert {'halo_dashboard.hardware', 'halo_dashboard.device_dialog', 'halo_dashboard.support'}.issubset(pyz.toc)
    assert 'halo_dashboard.updates' not in pyz.toc and 'halo_dashboard.update_ui' not in pyz.toc
    for name in pyz.toc:
        if name.startswith('halo_dashboard.'):
            assert not any('Halo Truck Dash' in value or 'HALO / TRUCK DASH' in value for value in strings(pyz.extract(name))), name
    if args.ui_smoke:
        # A copy with no adjacent Python, config, or assets must run on its own.
        # Also exercise non-ASCII paths and remove Python's environment hints.
        with tempfile.TemporaryDirectory(prefix='HaloTruckDash 兼容性 ', dir=root / 'build') as temporary:
            standalone = Path(temporary) / exe.name
            shutil.copy2(exe, standalone)
            environment = os.environ.copy()
            for key in ('PYTHONHOME', 'PYTHONPATH'):
                environment.pop(key, None)
            environment['PATH'] = str(Path(environment.get('SystemRoot', r'C:\Windows')) / 'System32')
            result = subprocess.run([str(standalone), '--ui-smoke'], env=environment, timeout=40)
            assert result.returncode == 0
            result = subprocess.run([str(standalone), '--feedback'], env=environment, timeout=40)
            assert result.returncode == 0
            feedback = list((standalone.parent / 'data' / 'feedback').glob('*.zip'))
            assert len(feedback) == 1
            with zipfile.ZipFile(feedback[0]) as package:
                assert package.testzip() is None
                assert set(package.namelist()).issubset({'report.json', 'README.txt', 'logs/dashboard.log',
                    'logs/dashboard.log.1', 'logs/dashboard.log.2', 'logs/dashboard.log.3'})
                report = json.loads(package.read('report.json'))
                assert report['format'] == 'HaloTruckDash-feedback'
                assert report['diagnostics']['version'] == VERSION
                assert report['diagnostics']['hid_queries_sent'] is False
                assert report['plugins']['bundled']['matches_bundled_version']
                assert 'serial_number' not in package.read('report.json').decode()
    print(f'{PRODUCT_NAME} {VERSION}: x64 ZIP, licenses, icons, bundled runtime, no updater, isolated UI and local feedback export checks passed.')


if __name__ == '__main__':
    main()
