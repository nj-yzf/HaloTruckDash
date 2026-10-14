"""Exercise candidate listing and explicit validation controls without real HID."""
from pathlib import Path
import queue
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from halo_dashboard.app import App
from halo_dashboard.hardware import DeviceRegistry, device_rows, device_key
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


devices = [dict(vendor_id=0x2D99, product_id=pid, product_string='花再 Halo PixelBar',
                interface_number=interface, usage_page=page, usage=1, release_number=256,
                serial_number=f'private-{index}', path=f'private-{index}'.encode())
           for index, (pid, interface, page) in enumerate([(0xA160, 4, 0xFF14), (0xB100, 5, 0xFF14), (0xB100, 0, 12)])]

with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
    state = Path(temporary)
    registry = DeviceRegistry(state / 'validated-devices.json')
    with patch('halo_dashboard.app.STATE', state), patch('halo_dashboard.app.Worker', PreviewWorker):
        root = tk.Tk()
        root.attributes('-alpha', 0)
        app = App(root)
        panel = app.open_device_dialog()
        panel.window.attributes('-alpha', 0)
        root.update()
        assert app.worker.commands.get_nowait() == ('hardware_scan', None)
        app.worker.events.put(('hardware', {'rows': device_rows(registry, devices, include_keys=True), 'active': False}))
        app.worker.events.put(('hardware_notice', {'text': '扫描完成', 'error': False}))
        app.poll()
        assert len(panel.rows) == 3
        panel.tree.selection_set('d2')
        root.update()
        assert str(panel.verify_button.cget('state')) == 'disabled'
        panel.tree.selection_set('d1')
        root.update()
        assert str(panel.verify_button.cget('state')) == 'normal'
        panel.verify_button.invoke()
        assert app.worker.commands.get_nowait() == ('hardware_verify', device_key(devices[1]))
        assert panel.busy and str(panel.verify_button.cget('state')) == 'disabled'
        registry.select(devices[1], verified=True)
        app.worker.events.put(('hardware', {'rows': device_rows(registry, devices, include_keys=True), 'active': False}))
        app.worker.events.put(('hardware_notice', {'text': '基础协议验证通过', 'error': False}))
        app.poll()
        assert not panel.busy and '用户验证通过' in panel.tree.item('d1', 'values')[-1]
        app.worker.events.put(('active', True))
        truck = Truck(connected=True, speed=88, gear=12)
        app.worker.events.put(('frame', (truck, format_frame(truck))))
        app.poll()
        assert '88 km/h' in app.values.cget('text')
        assert str(panel.verify_button.cget('state')) == 'disabled'
        assert str(panel.export_button.cget('state')) == 'normal'
        panel.export_button.invoke()
        assert app.worker.commands.get_nowait()[0] == 'hardware_export'
        panel.notice('诊断已导出')
        with patch('halo_dashboard.device_dialog.os.startfile') as opened:
            panel.open_folder()
        opened.assert_called_once_with(state)
        app.worker.events.put(('hardware', {'rows': [], 'active': False}))
        app.poll()
        assert not panel.tree.selection() and str(panel.verify_button.cget('state')) == 'disabled'
        app.close()

        for scaling in (4 / 3, 2, 8 / 3):
            root = tk.Tk()
            root.attributes('-alpha', 0)
            root.tk.call('tk', 'scaling', scaling)
            app = App(root)
            panel = app.open_device_dialog(scan=False)
            panel.window.attributes('-alpha', 0)
            panel.set_state({'rows': device_rows(registry, devices, include_keys=True), 'active': False})
            root.update()
            window = panel.window
            def walk(widget):
                for child in widget.winfo_children():
                    x, y = child.winfo_rootx() - window.winfo_rootx(), child.winfo_rooty() - window.winfo_rooty()
                    text = child.cget('text') if 'text' in child.keys() else ''
                    assert child.winfo_ismapped(), (scaling, text)
                    assert 0 <= x and x + child.winfo_width() <= window.winfo_width(), (scaling, text)
                    assert 0 <= y and y + child.winfo_height() <= window.winfo_height(), (scaling, text)
                    if isinstance(child, ttk.Label):
                        assert child.winfo_height() >= child.winfo_reqheight(), (scaling, text)
                    walk(child)
            walk(window)
            app.close()
print('Hardware UI: unknown candidates, validation commands, active-session lock, diagnostics export, live telemetry and 100/150/200% window fit passed.')
