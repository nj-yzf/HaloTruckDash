"""ETS2/ATS installation selector and unit preferences; no real game/USB writes."""
from pathlib import Path
import queue
import sys
import tempfile
import threading
from unittest.mock import patch
import tkinter as tk
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from halo_dashboard.app import App
from halo_dashboard.games import GAMES
from halo_dashboard.installer import PLUGIN_SHA256, sha256
from halo_dashboard.telemetry import Truck
from halo_dashboard.display import format_frame
from halo_dashboard.layout import normalize, preset_layout
from halo_dashboard.layout_library import atomic_json

class PreviewWorker:
    def __init__(self):
        self.settings, self.active = {}, False
        self.commands, self.events = queue.Queue(), queue.Queue()
        self.finished = threading.Event()
        self.finished.set()
    def start(self):
        pass

with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
    state = Path(temporary) / 'data'
    state.mkdir()
    legacy_ets = str(Path(temporary) / 'Custom ETS2 Folder')
    atomic_json(state / 'settings.json', {'mode': '默认布局1', 'game_dir': legacy_ets, 'custom': {'items': []}})
    ats = Path(temporary) / 'American Truck Simulator'
    (ats / 'bin' / 'win_x64').mkdir(parents=True)
    (ats / 'bin' / 'win_x64' / 'amtrucks.exe').write_bytes(b'test')
    with patch('halo_dashboard.app.STATE', state), patch('halo_dashboard.app.Worker', PreviewWorker):
        root = tk.Tk()
        root.attributes('-alpha', 0)
        app = App(root)
        root.update()
        original_ets_path = app.game_dir.get()
        assert original_ets_path == legacy_ets and app.speed_unit.get() == 'km/h'
        app.target_combo.set(GAMES['ats'].label)
        app.target_combo.event_generate('<<ComboboxSelected>>')
        assert app._install_key == 'ats'
        app.game_dir.set(str(ats))
        app.target_combo.set(GAMES['ets2'].label)
        app.target_combo.event_generate('<<ComboboxSelected>>')
        assert app.game_dir.get() == original_ets_path
        assert app.game_dirs['ats'] == str(ats)
        with patch('halo_dashboard.app.filedialog.askdirectory', return_value=str(ats)):
            app.browse()
        assert app._install_key == 'ats' and app.install_target.get() == GAMES['ats'].label
        with patch('halo_dashboard.app.messagebox.showinfo') as installed:
            app.install()
        assert installed.called and '美卡' in installed.call_args.args[1]
        assert sha256(ats / 'bin' / 'win_x64' / 'plugins' / 'scs-telemetry.dll') == PLUGIN_SHA256
        editor = app.edit_layout()
        editor.window.attributes('-alpha', 0)
        root.update()
        app.unit_combo.set('mph')
        app.unit_combo.event_generate('<<ComboboxSelected>>')
        root.update()
        assert editor.speed_unit == 'mph'
        assert editor.model == normalize(preset_layout(1, 'mph'))
        assert editor.current_choice() == '默认布局1'
        assert editor.cards['speed'].winfo_children()[1].cget('text') == '050'
        app.target_combo.set(GAMES['ets2'].label)
        app.target_combo.event_generate('<<ComboboxSelected>>')
        truck = Truck(connected=True, game_id=2, speed=80.4672, gear=18, reason='美卡 / ATS：实时遥测已连接')
        app.worker.events.put(('frame', (truck, format_frame(truck, speed_unit='mph'))))
        app.poll()
        assert '50 mph' in app.values.cget('text')
        assert '美卡' in app.telemetry_status.cget('text')
        # Extra controls must fit both normal and minimum main-window sizes.
        for width, height in [(780, 660), (730, 650)]:
            root.geometry(f'{width}x{height}')
            root.update()
            # A mapped rectangle can still contain clipped text: verify the
            # footer has its full requested height after width-based wrapping.
            assert app.footer.winfo_height() >= app.footer.winfo_reqheight()
            assert int(app.footer.cget('wraplength')) <= app.footer.winfo_width()
            def walk(widget):
                for child in widget.winfo_children():
                    if isinstance(child, tk.Toplevel):
                        continue
                    x, y = child.winfo_rootx() - root.winfo_rootx(), child.winfo_rooty() - root.winfo_rooty()
                    assert child.winfo_ismapped(), (width, height, child.winfo_class(), child.cget('text') if 'text' in child.keys() else '')
                    assert 0 <= x and x + child.winfo_width() <= root.winfo_width(), child.winfo_class()
                    assert 0 <= y and y + child.winfo_height() <= root.winfo_height(), child.winfo_class()
                    walk(child)
            walk(root)
        app.close()
        root = tk.Tk()
        root.attributes('-alpha', 0)
        restored = App(root)
        assert restored.speed_unit.get() == 'mph'
        assert restored.game_dirs['ats'] == str(ats)
        assert restored.game_dirs['ets2'] == original_ets_path
        restored.close()
print('Dual-game paths, ATS installation, automatic source text, mph editor and preference persistence passed.')
