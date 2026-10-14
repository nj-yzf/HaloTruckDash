"""Named-layout editor integration; no real worker or USB accesses."""
from pathlib import Path
import json
import queue
import sys
import tempfile
import threading
from unittest.mock import patch
import tkinter as tk
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from halo_dashboard.app import App
from halo_dashboard.layout import normalize, preset_layout, place_field
from halo_dashboard.layout_library import atomic_json, export_layout, import_layout

class PreviewWorker:
    def __init__(self):
        self.settings = {}
        self.commands, self.events = queue.Queue(), queue.Queue()
        self.finished = threading.Event()
        self.finished.set()
        self.active = False
    def start(self):
        pass

with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
    state = Path(temporary)
    atomic_json(state / 'settings.json', {'mode': '布局2', 'custom': {'items': []}, 'color': '白色'})
    with patch('halo_dashboard.app.STATE', state), patch('halo_dashboard.app.Worker', PreviewWorker):
        root = tk.Tk()
        root.attributes('-alpha', 0)
        app = App(root)
        root.update()
        assert app.mode.get() == '默认布局2'
        assert '自由布局' not in app.layout_choices
        editor = app.edit_layout()
        editor.window.attributes('-alpha', 0)
        root.update()
        assert editor.model == normalize(preset_layout(2))
        assert list(app.mode_combo.cget('values')) == list(editor.saved_names.cget('values'))
        first = place_field({'items': []}, 0, 'speed')
        second = place_field({'items': []}, 7, 'rpm')
        for name, model in [('白天', first), ('夜间', second)]:
            editor.load_model(model)
            editor.layout_name.set(name)
            editor.save_named()
        assert list(app.mode_combo.cget('values')) == list(editor.saved_names.cget('values'))
        app.mode_combo.set('夜间')
        app.mode_combo.event_generate('<<ComboboxSelected>>')
        root.update()
        assert app.worker.settings['custom'] == second
        # Even an existing editor reloads the main selection when opened again.
        assert app.edit_layout() is editor
        assert editor.layout_name.get() == '夜间' and editor.model == second
        editor.select_choice('默认布局1')
        editor.save_named()
        assert editor.layout_name.get() == '默认布局1（副本）'
        editor.select_choice('白天')
        editor.apply()
        assert app.mode.get() == '白天'
        # New drafts have numbered names and do not appear in main until saved.
        editor = app.edit_layout()
        editor.window.attributes('-alpha', 0)
        editor.new_layout()
        assert editor.layout_name.get() == '我的布局01' and editor.model == {'items': []}
        assert '我的布局01' not in app.layout_choices
        editor.load_model(place_field(first, 20, 'fuel'))
        editor.apply()
        assert app.mode.get() == '我的布局01'
        assert app.layout_library.load('我的布局01') == app.custom_layout
        editor = app.edit_layout()
        editor.window.attributes('-alpha', 0)
        assert editor.model == app.custom_layout
        editor.new_layout()
        assert editor.layout_name.get() == '我的布局02'
        assert app.mode.get() == '我的布局01'
        editor.save_named()
        assert '我的布局02' in app.layout_choices
        # Folder button opens the authoritative individual-JSON directory.
        with patch('halo_dashboard.grid_editor.os.startfile') as opened:
            editor.open_layout_folder()
        opened.assert_called_once_with(str((state / 'layouts').resolve()))
        assert all(import_layout(path)['layout'] is not None for path in (state / 'layouts').glob('*.json'))
        # Import supports multiple files and preserves colliding stored names.
        shared1, shared2 = state / 'share1.json', state / 'share2.json'
        export_layout(shared1, '白天', first)
        export_layout(shared2, '分享二', second)
        with patch('halo_dashboard.grid_editor.filedialog.askopenfilenames', return_value=(str(shared1), str(shared2))):
            editor.import_file()
        assert app.layout_library.load('白天') == first
        assert app.layout_library.load('白天（导入）') == first
        assert app.layout_library.load('分享二') == second
        before = app.layout_library.entries()
        (state / 'bad.json').write_text('bad', encoding='utf-8')
        with patch('halo_dashboard.grid_editor.filedialog.askopenfilenames', return_value=(str(shared1), str(state / 'bad.json'))):
            editor.import_file()
        assert app.layout_library.entries() == before
        assert set(app.mode_combo.cget('values')) == set(editor.saved_names.cget('values'))
        # Deleting an active named layout falls back to a default, never a free entry.
        app.mode.set('白天')
        app.select_layout()
        app.edit_layout()
        with patch('halo_dashboard.grid_editor.messagebox.askyesno', return_value=True):
            editor.delete_named()
        assert app.mode.get() == '默认布局1'
        assert '自由布局' not in app.layout_choices
        app.mode.set('夜间')
        app.select_layout()
        app.close()
        root = tk.Tk()
        root.attributes('-alpha', 0)
        restored = App(root)
        assert restored.mode.get() == '夜间' and restored.custom_layout == second
        restored.close()
        # A legacy active free draft migrates once into a numbered saved layout.
        atomic_json(state / 'settings.json', {'mode': '自由布局', 'custom': first, 'draft': first})
        root = tk.Tk()
        root.attributes('-alpha', 0)
        migrated = App(root)
        assert migrated.mode.get().startswith('我的布局')
        assert migrated.custom_layout == first
        count = len(migrated.layout_library.entries())
        migrated.close()
        root = tk.Tk()
        root.attributes('-alpha', 0)
        migrated = App(root)
        assert len(migrated.layout_library.entries()) == count
        migrated.close()
print('Current selection reload, numbered new layouts, folder access, batch import, removal and legacy migration passed.')
