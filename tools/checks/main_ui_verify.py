"""Verify all main controls and the entire footer at 100/150/200% text scaling."""
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


class PreviewWorker:
    def __init__(self):
        self.settings, self.active = {}, False
        self.commands, self.events = queue.Queue(), queue.Queue()
        self.finished = threading.Event()
        self.finished.set()
    def start(self):
        pass


with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
    with patch('halo_dashboard.app.STATE', Path(temporary)), patch('halo_dashboard.app.Worker', PreviewWorker):
        for scaling in (4 / 3, 2, 8 / 3):
            root = tk.Tk()
            root.attributes('-alpha', 0)
            root.tk.call('tk', 'scaling', scaling)
            app = App(root)
            root.update()
            for width, height in [(root.winfo_width(), root.winfo_height()), root.minsize()]:
                root.geometry(f'{width}x{height}')
                root.update()
                def walk(widget):
                    for child in widget.winfo_children():
                        x = child.winfo_rootx() - root.winfo_rootx()
                        y = child.winfo_rooty() - root.winfo_rooty()
                        text = child.cget('text') if 'text' in child.keys() else ''
                        assert child.winfo_ismapped(), (scaling, text)
                        assert 0 <= x and x + child.winfo_width() <= root.winfo_width(), (scaling, text, x, child.winfo_width())
                        assert 0 <= y and y + child.winfo_height() <= root.winfo_height(), (scaling, text, y, child.winfo_height())
                        if isinstance(child, ttk.Label):
                            assert child.winfo_height() >= child.winfo_reqheight(), (scaling, text)
                            assert child.winfo_width() >= child.winfo_reqwidth(), (scaling, text)
                        walk(child)
                walk(root)
                assert int(app.footer.cget('wraplength')) <= app.footer.winfo_width()
            app.close()
print('Main window controls and complete footer fit at default/minimum sizes with 100/150/200% text scaling.')
