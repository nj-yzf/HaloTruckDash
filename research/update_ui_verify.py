"""Exercise threaded update UI and ensure dashboard frames remain responsive."""
import hashlib
import io
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch
from urllib.error import URLError
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from halo_dashboard.app import App
from halo_dashboard.update_ui import UpdateController
from halo_dashboard.updates import Release, download_release, UpdateCancelled
from halo_dashboard.telemetry import Truck
from halo_dashboard.display import format_frame


class PreviewWorker:
    def __init__(self):
        self.settings, self.active = {}, False
        self.commands, self.events = queue.Queue(), queue.Queue()
        self.finished = threading.Event()
        self.finished.set()
    def start(self):
        pass


class Response(io.BytesIO):
    headers = {}
    def geturl(self):
        return 'https://updates.invalid/test.zip'


def wait(root, condition):
    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        root.update()
        time.sleep(.01)
    assert condition(), 'UI operation did not finish'
    root.update()


output = io.BytesIO()
with zipfile.ZipFile(output, 'w') as package:
    package.writestr('HaloTruckDash.exe', b'MZ test')
content = output.getvalue()
release = Release('0.6.0', 'https://updates.invalid/test.zip', len(content), hashlib.sha256(content).hexdigest(), '新增测试功能\n更新说明')

with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
    state = Path(temporary)
    with patch('halo_dashboard.app.STATE', state), patch('halo_dashboard.app.Worker', PreviewWorker):
        root = tk.Tk()
        root.attributes('-alpha', 0)
        app = App(root)
        updater = app.updater
        updater.check()
        updater.window.attributes('-alpha', 0)
        assert '尚未配置' in updater.status
        saved_before = updater.preferences.read_bytes()
        updater.url_var.set('http://updates.invalid/latest.json')
        assert not updater.save() and updater.preferences.read_bytes() == saved_before
        updater.url_var.set('https://updates.invalid/latest.json')
        updater.auto_var.set(True)
        assert updater.save()
        gate = threading.Event()
        def delayed_check(url, cancel):
            assert gate.wait(4)
            return release
        with patch('halo_dashboard.update_ui.fetch_release', delayed_check):
            updater.check()
            root.update()
            assert updater.busy and str(updater.check_button.cget('state')) == 'disabled'
            # The game's data path continues while the network thread is blocked.
            truck = Truck(connected=True, speed=88, gear=12)
            app.worker.events.put(('frame', (truck, format_frame(truck))))
            app.poll()
            assert '88 km/h' in app.values.cget('text')
            gate.set()
            wait(root, lambda: not updater.busy)
        assert '发现新版' in updater.status and '新增测试功能' in updater.notes.get('1.0', 'end')
        assert str(updater.download_button.cget('state')) == 'normal'
        def real_download(release, directory, cancel, progress):
            return download_release(release, directory, cancel, progress, opener=lambda *args: Response(content))
        with patch('halo_dashboard.update_ui.download_release', real_download):
            updater.download()
            wait(root, lambda: not updater.busy)
        assert updater.downloaded.read_bytes() == content
        assert '校验通过' in updater.status and updater.progress.cget('value') == 100
        with patch('halo_dashboard.update_ui.os.startfile') as opened:
            updater.open_directory()
        opened.assert_called_once_with(state / 'updates')
        def cancelled_download(release, directory, cancel, progress):
            assert cancel.wait(4)
            raise UpdateCancelled()
        with patch('halo_dashboard.update_ui.download_release', cancelled_download):
            updater.download()
            updater.cancel()
            wait(root, lambda: not updater.busy)
        assert '已取消' in updater.status
        with patch('halo_dashboard.update_ui.fetch_release', side_effect=URLError('offline')):
            updater.check()
            wait(root, lambda: not updater.busy)
        assert '失败' in updater.status and 'offline' in updater.status
        updater.hide()
        updater.shutdown()
        # Background checks only open a dialog when a newer stable release exists.
        quiet = UpdateController(root, state, enabled=False)
        assert quiet.auto and quiet.source == 'https://updates.invalid/latest.json'
        older = Release('0.4.1', release.url, release.size, release.sha256, '旧版')
        with patch('halo_dashboard.update_ui.fetch_release', return_value=older):
            quiet.check(automatic=True)
            wait(root, lambda: not quiet.busy)
        assert quiet.window is None and '最新版本' in quiet.status
        with patch('halo_dashboard.update_ui.fetch_release', return_value=release):
            quiet.check(automatic=True)
            wait(root, lambda: not quiet.busy)
        assert quiet.visible()
        quiet.window.attributes('-alpha', 0)
        quiet.hide()
        quiet.shutdown()
        app.close()
        for scaling in (4 / 3, 2, 8 / 3):
            root = tk.Tk()
            root.attributes('-alpha', 0)
            root.tk.call('tk', 'scaling', scaling)
            app = App(root, updates_enabled=False)
            window = app.updater.show()
            window.attributes('-alpha', 0)
            root.update()
            def walk(widget):
                for child in widget.winfo_children():
                    x, y = child.winfo_rootx() - window.winfo_rootx(), child.winfo_rooty() - window.winfo_rooty()
                    text = child.cget('text') if 'text' in child.keys() else ''
                    assert child.winfo_ismapped(), (scaling, text)
                    assert x >= 0 and x + child.winfo_width() <= window.winfo_width(), (scaling, text)
                    assert y >= 0 and y + child.winfo_height() <= window.winfo_height(), (scaling, text)
                    if isinstance(child, ttk.Label):
                        assert child.winfo_height() >= child.winfo_reqheight(), (scaling, text)
                    walk(child)
            walk(window)
            app.close()
print('Update UI: settings, async checks/downloads, uninterrupted telemetry, cancellation, offline errors, silent startup and 100/150/200% dialog fit passed.')
