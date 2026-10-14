"""Exercise native editor callbacks and geometry without writing to the speaker."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont
from halo_dashboard.grid_editor import GridEditor, PALETTE, COLORS
from halo_dashboard.window_geometry import fit_editor
from halo_dashboard.layout import owner_at, render, preset_layout, normalize
from halo_dashboard.telemetry import Truck
from halo_dashboard.layout_library import LayoutLibrary, import_layout

root = tk.Tk()
root.attributes('-alpha', 0)
style = ttk.Style()
style.theme_use('clam')
style.configure('TButton', font=('Microsoft YaHei UI', 10), padding=(12, 8))
style.configure('TLabel', font=('Microsoft YaHei UI', 10))
style.configure('TCheckbutton', font=('Microsoft YaHei UI', 10))
applied = []
temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
editor = GridEditor(root, {'items': []}, applied.append, library=LayoutLibrary(Path(temporary.name) / 'layouts.json'))
editor.window.attributes('-alpha', 0)
root.update()

def event(cell, state=0, y=90):
    left, size = editor.geometry()
    return SimpleNamespace(x_root=editor.canvas.winfo_rootx() + left + (cell + .5) * size,
                           y_root=editor.canvas.winfo_rooty() + y, state=state)

for field in PALETTE:
    editor.load_model({'items': []})
    editor.palette_down(event(0), field)
    editor.drag_motion(event(0))
    editor.drag_release(event(0))
    assert owner_at(editor.model, 0)['field'] == field
    editor.cell_down(event(1))
    editor.drag_motion(event(25))
    editor.drag_release(event(25))
    assert owner_at(editor.model, 24)['field'] == field
    assert owner_at(editor.model, 0) is None

editor.load_model({'items': []})
editor.palette_down(event(0), 'speed')
editor.drag_release(event(0))
editor.selected = 4
editor.insert('km/h')
original = deepcopy(editor.model)
editor.cell_down(event(1, state=1))
editor.drag_motion(event(7, state=1))
editor.drag_release(event(7, state=1))
assert editor.selection == {0, 4, 5, 6, 7}
editor.cell_down(event(1))
editor.drag_motion(event(11))
editor.drag_release(event(11))
assert editor.selection == {10, 14, 15, 16, 17}
assert owner_at(editor.model, 0) is None
assert render(Truck(), settings=editor.model)[11:19] == '000 km/h'
editor.undo()
assert editor.model == original
editor.redo()
moved = deepcopy(editor.model)
editor.select_all()
editor.cell_down(event(11))
editor.drag_motion(event(29))
editor.drag_release(event(29))
assert editor.model == moved
editor.delete()
assert not editor.model['items']
editor.undo()
assert editor.model == moved
editor.cell_down(event(14, state=4))
assert editor.selection == {14}
editor.cell_down(event(14, state=4))
assert not editor.selection
editor.cell_down(event(9))
editor.drag_motion(event(17))
editor.drag_release(event(17))
assert editor.selection == {10, 14, 15, 16, 17}
editor.marquee_mode.set(True)
editor.clear_selection()
editor.cell_down(event(11))
editor.drag_motion(event(17))
editor.drag_release(event(17))
assert len(editor.selection) == 5
editor.marquee_mode.set(False)
editor.layout_name.set('方案一')
editor.save_named()
editor.load_model(preset_layout(2))
editor.layout_name.set('方案二')
editor.save_named()
editor.layout_name.set('方案一')
editor.load_named()
assert editor.model == moved
shared = str(Path(temporary.name) / 'share.json')
with patch('halo_dashboard.grid_editor.filedialog.asksaveasfilename', return_value=shared):
    editor.export_file()
assert import_layout(shared)['layout'] == moved
editor.load_model({'items': []})
with patch('halo_dashboard.grid_editor.filedialog.askopenfilenames', return_value=(shared,)):
    editor.import_file()
assert editor.model == moved
editor.undo()
assert editor.model == {'items': []}
editor.redo()
assert editor.model == moved
assert len(LayoutLibrary(Path(temporary.name) / 'layouts.json').entries()) == 3

def check_geometry(width, height):
    editor.window.geometry(f'{width}x{height}')
    root.update()
    assert not hasattr(editor, 'vscroll') and not hasattr(editor, 'hscroll'), 'Scrollbars still consume space'
    assert editor.viewport.winfo_width() == editor.viewport.master.winfo_width(), 'Viewport loses right-side space'
    for button in editor.footer.winfo_children():
        assert button.winfo_ismapped()
        x = button.winfo_rootx() - editor.window.winfo_rootx()
        y = button.winfo_rooty() - editor.window.winfo_rooty()
        assert 0 <= x and x + button.winfo_width() <= editor.window.winfo_width()
        assert 0 <= y and y + button.winfo_height() <= editor.window.winfo_height(), 'Footer button clipped'
    assert len(editor.cards) == len(PALETTE) == len(set(COLORS.values())) == 13
    assert len({card.winfo_y() for card in editor.cards.values()}) == 1, 'Palette is not a single row'
    for card in editor.cards.values():
        assert card.winfo_height() > card.winfo_width(), 'Cards should be vertical rectangles'
        assert len(card.winfo_children()) == 3
        for label in card.winfo_children():
            font = tkfont.Font(root=root, font=label.cget('font'))
            assert font.measure(label.cget('text')) <= label.winfo_width() - 4, ('Card text clipped', label.cget('text'))
            assert label.winfo_y() + label.winfo_height() <= card.winfo_height(), 'Card line clipped'
    editor.viewport.yview_moveto(1)
    root.update()
    assert editor.viewport.yview()[1] == 1.0, 'Bottom of editor is unreachable'
    editor.mouse_wheel(SimpleNamespace(widget=editor.canvas, delta=120, state=0))
    editor.viewport.yview_moveto(0)
    root.update()
    print({'window': (editor.window.winfo_width(), editor.window.winfo_height()),
           'footer_visible': True, 'single_row_cards': 13, 'content_scrollable': True})

assert not hasattr(editor, 'literal'), 'Obsolete text entry remains'
assert set(editor.saved_names.cget('values')) == {'默认布局1', '默认布局2', '方案一', '方案二', '方案一（导入）'}
editor.saved_names.set('默认布局2')
editor.saved_names.event_generate('<<ComboboxSelected>>')
root.update()
assert editor.model == normalize(preset_layout(2))
editor.load_model(moved)
texts = [editor.canvas.itemcget(item, 'text') for item in editor.canvas.find_all() if editor.canvas.type(item) == 'text']
assert '左转向灯' in texts and '右转向灯' in texts and '固定' not in texts
check_geometry(1320, 660)
check_geometry(1100, 600)
check_geometry(1100, 480)
# The default bounds must also fit a short usable desktop (taskbar excluded).
with patch('halo_dashboard.window_geometry.work_area', return_value=(0, 0, 1280, 720)):
    fit_editor(editor.window)
    root.update()
    assert editor.window.winfo_height() <= 656
    assert editor.window.winfo_y() + editor.window.winfo_height() + 32 <= 720
check_geometry(1100, 660)
# All three lines must remain inside cards under enlarged Windows text scaling.
previous_scaling = root.tk.call('tk', 'scaling')
root.tk.call('tk', 'scaling', 2.0)
probe = GridEditor(root, {'items': []}, lambda model: None)
probe.window.attributes('-alpha', 0)
root.update()
old_editor, editor = editor, probe
check_geometry(1100, 480)
probe.window.destroy()
editor = old_editor
root.tk.call('tk', 'scaling', previous_scaling)
root.update()
# Direct keyboard entry and the card's three child mouse bindings remain usable.
editor.load_model({'items': []})
editor.selected = 0
for char in '[] km/h':
    editor.key(SimpleNamespace(keysym=char, char=char, state=0))
assert render(Truck(), settings=editor.model)[1:8] == '[] km/h'
editor.load_model({'items': []})
editor.selected = 0
label = editor.cards['speed'].winfo_children()[0]
label.event_generate('<ButtonPress-1>', x=5, y=5)
label.event_generate('<ButtonRelease-1>', x=5, y=5)
root.update()
assert owner_at(editor.model, 0)['field'] == 'speed'
editor.load_model(moved)
editor.apply()
assert applied == [moved]
root.destroy()
temporary.cleanup()
print('All 13 widgets, marquee/group drag, atomic rejection, undo/redo, named library and import/export passed.')
