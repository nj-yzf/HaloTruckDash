"""Portable preferences, with a per-user fallback for read-only installations."""
import os
from pathlib import Path
import tempfile


def writable_directory(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=path) as stream:
        stream.write(b'HaloTruckDash')
    return path


def data_directory(base, local_app_data=None):
    try:
        return writable_directory(Path(base) / 'data')
    except OSError:
        local = local_app_data or os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local'
        return writable_directory(Path(local) / 'HaloTruckDash' / 'data')
