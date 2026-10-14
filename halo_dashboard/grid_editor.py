"""Native Tk editor: drag data widgets into one horizontal row of 30 cells."""
from copy import deepcopy
import os
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk, messagebox, filedialog
from .layout import (CELL_COUNT, FIELD_WIDTHS, FIELD_LABELS, normalize, render,
                     field_values, owner_at, item_width, place_field, write_text,
                     remove_at, selected_between, move_items, remove_items, preset_layout, SPEED_UNITS)
from .telemetry import Truck
from .layout_library import LayoutLibrary, import_layout, export_layout
from .window_geometry import fit_editor
from .layout_catalog import LayoutCatalog, DEFAULT_NAMES

SAMPLE = Truck(connected=True, speed=80, limit=90, gear=12, rpm=1500, fuel=66,
               capacity=100, game_minutes=585, left=True, right=True, shifter_type='automatic',
               cruise=True, cruise_speed=80, on_job=True, delivery_minutes=1440,
               route_seconds=8460, distance=128, rest_minutes=310)
PALETTE = list(FIELD_WIDTHS)
COLORS = {'speed': '#22577a', 'limit': '#59488d', 'fuel': '#276448',
          'time': '#826326', 'gear': '#914d58', 'rpm': '#475a73',
          'real_time': '#216c78', 'cruise_speed': '#475f9a', 'job_remaining': '#994e27',
          'nav_time': '#7b397c', 'nav_distance': '#647029', 'rest_time': '#875d3b',
          'fuel_liters': '#376d67'}
GRID_TOP, GRID_BOTTOM, CANVAS_HEIGHT = 44, 103, 142

class GridEditor:
    def __init__(self, root, model, on_apply, gear_mode='auto', library=None,
                 on_library_change=None, current_name=None, speed_unit='km/h'):
        self.window = tk.Toplevel(root)
        self.window.title('布局编辑器 · 中间30格')
        fit_editor(self.window)
        self.window.configure(bg='#101722')
        self.window.transient(root)
        self.model = normalize(deepcopy(model))
        self.on_apply, self.gear_mode = on_apply, gear_mode
        if speed_unit not in SPEED_UNITS:
            raise ValueError('请选择km/h或mph速度单位')
        self.speed_unit = speed_unit
        self.selected, self.drag = 0, None
        self.selection = set()
        self.marquee_mode = tk.BooleanVar(value=False)
        self.library = library if library is not None else LayoutLibrary()
        self.catalog = LayoutCatalog(self.library)
        self.on_library_change = on_library_change or (lambda: None)
        self.layout_name = tk.StringVar(value=current_name or self.library.new_name())
        self.history, self.future = [], []
        shell = ttk.Frame(self.window, padding=12)
        shell.pack(fill='both', expand=True)
        # Reserve the footer before allocating the scrollable content. It stays
        # reachable even when the desktop is shorter than the requested height.
        self.footer = ttk.Frame(shell, padding=(0, 8, 0, 0))
        self.footer.pack(side='bottom', fill='x')
        content = ttk.Frame(shell)
        content.pack(fill='both', expand=True)
        content.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)
        self.viewport = tk.Canvas(content, bg='#101722', highlightthickness=0,
                                  yscrollincrement=24, xscrollincrement=24)
        self.viewport.grid(row=0, column=0, sticky='nsew')
        self.box = ttk.Frame(self.viewport)
        self.content_window = self.viewport.create_window(0, 0, anchor='nw', window=self.box)
        self.box.bind('<Configure>', self.content_resized)
        self.viewport.bind('<Configure>', self.viewport_resized)
        self.window.bind('<MouseWheel>', self.mouse_wheel)
        ttk.Label(self.box, text='30个字符格，自由摆放信息', font=('Microsoft YaHei UI', 16, 'bold')).pack(anchor='w')
        ttk.Label(self.box, text='左右转向灯固定。拖入控件，选格后输入文字；Shift拖动框选，拖动选中内容可整体移动。',
                  style='Muted.TLabel').pack(anchor='w', pady=(2, 8))
        library_row = ttk.Frame(self.box)
        library_row.pack(fill='x', pady=(0, 8))
        ttk.Label(library_row, text='布局名称：').pack(side='left')
        self.saved_names = ttk.Combobox(library_row, textvariable=self.layout_name, width=20, postcommand=self.refresh_names)
        self.saved_names.pack(side='left', padx=(0, 8))
        self.saved_names.bind('<<ComboboxSelected>>', lambda event: self.load_named())
        for title, command in [('新建', self.new_layout), ('保存', self.save_named),
                ('删除', self.delete_named), ('布局文件夹', self.open_layout_folder),
                ('导入…', self.import_file), ('导出…', self.export_file)]:
            ttk.Button(library_row, text=title, command=command).pack(side='left', padx=(0, 6))
        self.palette = ttk.Frame(self.box)
        self.palette.pack(fill='x')
        self.cards = {}
        samples = field_values(SAMPLE, gear_mode, speed_unit=self.speed_unit)
        for position, field in enumerate(PALETTE):
            color = COLORS[field]
            card = tk.Frame(self.palette, bg=color, height=106, cursor='hand2',
                            highlightthickness=1, highlightbackground='#718499')
            card.grid(row=0, column=position, sticky='nsew', padx=(0, 4 if position < len(PALETTE) - 1 else 0))
            card.pack_propagate(False)
            self.cards[field] = card
            for line, font, padding in [(FIELD_LABELS[field], ('Microsoft YaHei UI', 9), (9, 2)),
                    (samples[field].strip(), ('Consolas', 14, 'bold'), (2, 3)),
                    (f'{FIELD_WIDTHS[field]}格', ('Microsoft YaHei UI', 9), (3, 7))]:
                label = tk.Label(card, text=line, bg=color, fg='white', cursor='hand2', font=font)
                label.base_font = font
                label.pack(fill='x', padx=2, pady=padding)
            card.bind('<Configure>', self.fit_card)
            for widget in (card, *card.winfo_children()):
                widget.bind('<ButtonPress-1>', lambda event, key=field: self.palette_down(event, key))
                widget.bind('<B1-Motion>', self.drag_motion)
                widget.bind('<ButtonRelease-1>', self.drag_release)
            self.palette.columnconfigure(position, weight=1, uniform='palette', minsize=68)
        selection_row = ttk.Frame(self.box)
        selection_row.pack(fill='x', pady=(6, 0))
        ttk.Checkbutton(selection_row, text='框选模式', variable=self.marquee_mode).pack(side='left')
        ttk.Button(selection_row, text='全选', command=self.select_all).pack(side='left', padx=8)
        ttk.Button(selection_row, text='取消选择', command=self.clear_selection).pack(side='left')
        ttk.Button(selection_row, text='删除所选', command=self.delete).pack(side='left', padx=8)
        self.scroll_hint = ttk.Label(selection_row, text='', style='Muted.TLabel')
        self.scroll_hint.pack(side='right')
        self.canvas = tk.Canvas(self.box, height=CANVAS_HEIGHT, bg='#080e18', highlightthickness=1, highlightbackground='#34475f')
        self.canvas.pack(fill='x', pady=(8, 6))
        self.canvas.bind('<Configure>', lambda event: self.draw())
        self.canvas.bind('<ButtonPress-1>', self.cell_down)
        self.canvas.bind('<B1-Motion>', self.drag_motion)
        self.canvas.bind('<ButtonRelease-1>', self.drag_release)
        self.canvas.bind('<KeyPress>', self.key)
        self.canvas.bind('<Control-v>', self.paste)
        self.canvas.bind('<Control-z>', lambda event: self.undo())
        self.canvas.bind('<Control-y>', lambda event: self.redo())
        self.canvas.bind('<Control-a>', self.select_all)
        self.window.bind('<Control-z>', lambda event: self.undo())
        self.window.bind('<Control-y>', lambda event: self.redo())
        self.status = ttk.Label(self.box, text='每个控件占固定格数，不含单位。自由布局油量最大显示99。', wraplength=1160)
        self.status.pack(anchor='w', pady=3)
        self.preview = ttk.Label(self.box, text='', font=('Consolas', 18, 'bold'))
        self.preview.pack(anchor='center', pady=4)
        self.unit_note = ttk.Label(self.box, text=f'速度数值单位：{self.speed_unit}；自定义布局中的km/h或mph文字请自行对应修改。', style='Muted.TLabel')
        self.unit_note.pack(anchor='w', pady=(2, 0))
        self.hint = ttk.Label(self.box, text='时长≤24小时：HH:MM；超过24小时：2d11h。任务剩余取交货时限，导航用时取预计行驶时间。\n'
                  '选格后直接键入；Shift拖动框选，Ctrl点击增减选择，Delete删除，Ctrl+Z/Y撤销/重做。',
                  style='Muted.TLabel', wraplength=1000)
        self.hint.pack(anchor='w', pady=4)
        controls = self.footer
        ttk.Button(controls, text='默认布局1', command=lambda: self.select_choice('默认布局1')).pack(side='left', padx=(0, 8))
        ttk.Button(controls, text='默认布局2', command=lambda: self.select_choice('默认布局2')).pack(side='left', padx=(0, 8))
        ttk.Button(controls, text='清空30格', command=lambda: self.load_model({'items': []})).pack(side='left', padx=(0, 8))
        ttk.Button(controls, text='撤销', command=self.undo).pack(side='left', padx=(0, 8))
        ttk.Button(controls, text='重做', command=self.redo).pack(side='left')
        ttk.Button(controls, text='保存并应用', command=self.apply).pack(side='right')
        ttk.Button(controls, text='取消', command=self.window.destroy).pack(side='right', padx=8)
        self.window.after_idle(self.draw)
        self.window.after_idle(self.refresh_names)

    def viewport_resized(self, event):
        self.viewport.itemconfigure(self.content_window, width=max(1020, event.width))
        self.content_resized()

    def content_resized(self, event=None):
        self.viewport.configure(scrollregion=self.viewport.bbox('all'))
        if hasattr(self, 'scroll_hint'):
            hints = []
            if self.box.winfo_height() > self.viewport.winfo_height() + 1:
                hints.append('滚轮上下浏览')
            if self.viewport.winfo_width() < 1020:
                hints.append('Shift+滚轮左右浏览')
            self.scroll_hint.configure(text=' · '.join(hints))
        if event is not None and hasattr(self, 'status'):
            width = max(200, event.width - 8)
            if self.status.cget('wraplength') != width:
                self.status.configure(wraplength=width)
                self.hint.configure(wraplength=width)

    def mouse_wheel(self, event):
        if not isinstance(event.widget, ttk.Combobox):
            scroll = self.viewport.xview_scroll if getattr(event, 'state', 0) & 1 else self.viewport.yview_scroll
            scroll(-int(event.delta / 120), 'units')
            return 'break'

    def set_speed_unit(self, speed_unit):
        if speed_unit not in SPEED_UNITS or speed_unit == self.speed_unit:
            return
        label = self.layout_name.get()
        default = label in DEFAULT_NAMES and self.model == normalize(preset_layout(DEFAULT_NAMES[label], self.speed_unit))
        self.speed_unit = speed_unit
        if default:
            self.load_model(preset_layout(DEFAULT_NAMES[label], speed_unit))
        for field, value in field_values(SAMPLE, self.gear_mode, speed_unit=speed_unit).items():
            self.cards[field].winfo_children()[1].configure(text=value.strip())
        self.unit_note.configure(text=f'速度数值单位：{speed_unit}；自定义布局中的km/h或mph文字请自行对应修改。')
        self.draw()

    def fit_card(self, event):
        """Keep all three lines legible without widening or wrapping the row."""
        labels = event.widget.winfo_children()
        fonts = [tkfont.Font(root=self.window, font=label.base_font) for label in labels]
        for label, font in zip(labels, fonts):
            while font.measure(label.cget('text')) > event.width - 12 and font.cget('size') > 6:
                font.configure(size=font.cget('size') - 1)
        while sum(font.metrics('linespace') for font in fonts) > event.height - 34:
            choices = [font for font in fonts if font.cget('size') > 6]
            if not choices:
                break
            font = max(choices, key=lambda candidate: candidate.metrics('linespace'))
            font.configure(size=font.cget('size') - 1)
        for label, font in zip(labels, fonts):
            label.configure(font=(font.cget('family'), font.cget('size'), font.cget('weight')))

    def geometry(self):
        return 64, max(1, (self.canvas.winfo_width() - 128) / CELL_COUNT)

    def index_at(self, event):
        if not (self.viewport.winfo_rootx() <= event.x_root < self.viewport.winfo_rootx() + self.viewport.winfo_width()
                and self.viewport.winfo_rooty() <= event.y_root < self.viewport.winfo_rooty() + self.viewport.winfo_height()):
            return None
        x = event.x_root - self.canvas.winfo_rootx()
        y = event.y_root - self.canvas.winfo_rooty()
        left, size = self.geometry()
        if GRID_TOP - 12 <= y <= GRID_BOTTOM + 10 and left <= x < left + size * CELL_COUNT:
            return int((x - left) / size)
        return None

    def draw(self):
        if not self.canvas.winfo_exists():
            return
        self.canvas.delete('all')
        left, size = self.geometry()
        text = render(SAMPLE, settings=self.model, gear_mode=self.gear_mode, speed_unit=self.speed_unit)
        center_y = (GRID_TOP + GRID_BOTTOM) / 2
        for x, symbol, label in [(left / 2, '<', '左转向灯'), (self.canvas.winfo_width() - left / 2, '>', '右转向灯')]:
            self.canvas.create_text(x, center_y, text=symbol, fill='#66afff', font=('Consolas', 21, 'bold'))
            self.canvas.create_text(x, 125, text=label, fill='#718499', font=('Microsoft YaHei UI', 8))
        for index in range(CELL_COUNT):
            item = owner_at(self.model, index)
            fill = COLORS[item['field']] if item and item['type'] == 'field' else '#182232'
            x0 = left + index * size
            self.canvas.create_rectangle(x0, GRID_TOP, x0 + size, GRID_BOTTOM, fill=fill, outline='#405166')
            self.canvas.create_text(x0 + size / 2, 125, text=str(index + 1), fill='#8495ab', font=('Consolas', 9))
            self.canvas.create_text(x0 + size / 2, center_y, text=text[index + 1] if text[index + 1] != ' ' else '·',
                                    fill='white' if text[index + 1] != ' ' else '#708098', font=('Consolas', 17, 'bold'))
        for item in self.model['items']:
            if item['type'] == 'field':
                x = left + item['start'] * size
                self.canvas.create_rectangle(x + 1, GRID_TOP - 1, x + item_width(item) * size - 1, GRID_BOTTOM + 1,
                                             outline='#99bfde', width=2)
                self.canvas.create_text(x + item_width(item) * size / 2, 24, text=FIELD_LABELS[item['field']],
                                        fill='#d2e5f5', font=('Microsoft YaHei UI', 9))
            if item['start'] in self.selection:
                x = left + item['start'] * size
                self.canvas.create_rectangle(x + 2, GRID_TOP + 2, x + item_width(item) * size - 2, GRID_BOTTOM - 2,
                                             fill='#ffcd66', stipple='gray25', outline='#ffcd66', width=3)
        x = left + self.selected * size
        self.canvas.create_rectangle(x + 2, GRID_TOP + 2, x + size - 2, GRID_BOTTOM - 2, outline='#ffcd66', width=3)
        self.preview.configure(text=text)

    def say(self, text, error=False):
        self.status.configure(text=text, foreground='#ff9b87' if error else '#9eceb3')

    def change(self, model):
        try:
            model = normalize(model)
        except ValueError as exc:
            self.say(str(exc), True)
            return False
        if model != self.model:
            self.history.append(deepcopy(self.model))
            self.history = self.history[-60:]
            self.future.clear()
            self.model = model
        self.draw()
        self.say(f'当前选中第{self.selected + 1}格；点击应用布局后显示到仪表。')
        return True

    def palette_down(self, event, field):
        self.drag = {'kind': 'field', 'field': field, 'moved': False}

    def load_model(self, model):
        self.selection.clear()
        return self.change(model)

    def select_all(self, event=None):
        self.selection = {item['start'] for item in self.model['items']}
        self.draw()
        return 'break'

    def clear_selection(self):
        self.selection.clear()
        self.draw()

    def point(self, event):
        return event.x_root - self.canvas.winfo_rootx(), event.y_root - self.canvas.winfo_rooty()

    def cell_down(self, event):
        index = self.index_at(event)
        if index is None:
            # The margin above/below the row is also a useful marquee origin.
            x, y = self.point(event)
            left, size = self.geometry()
            if not (left <= x < left + size * CELL_COUNT and 0 <= y <= CANVAS_HEIGHT):
                return
            index = int((x - left) / size)
        self.selected = index
        self.canvas.focus_set()
        item = owner_at(self.model, index)
        state = getattr(event, 'state', 0)
        shift, control = bool(state & 1), bool(state & 4)
        if control and not shift and item:
            self.selection.symmetric_difference_update({item['start']})
            self.drag = None
        elif shift or not item or (self.marquee_mode.get() and item['start'] not in self.selection):
            base = self.selection.copy() if control else set()
            self.selection = base.copy()
            self.drag = {'kind': 'marquee', 'origin': index, 'point': self.point(event),
                         'base': base, 'moved': False}
        else:
            if item['start'] not in self.selection:
                self.selection = {item['start']}
            self.drag = {'kind': 'items', 'origin': index, 'starts': self.selection.copy(), 'moved': False}
        self.draw()
        self.say(f'第{index + 1}格；已选{len(self.selection)}项。Shift拖动框选，Ctrl点击增减选择。')

    def drag_motion(self, event):
        if not self.drag:
            return
        if self.drag['kind'] != 'marquee':
            y = event.y_root - self.viewport.winfo_rooty()
            if y < 18 or y > self.viewport.winfo_height() - 18:
                self.viewport.yview_scroll(-1 if y < 18 else 1, 'units')
                self.window.update_idletasks()
        self.drag['moved'] = True
        self.canvas.delete('ghost')
        index = self.index_at(event)
        if self.drag['kind'] == 'marquee':
            left, size = self.geometry()
            x, y = self.point(event)
            end = max(0, min(29, int((x - left) / size)))
            x0, y0 = self.drag['point']
            if max(y0, y) >= GRID_TOP and min(y0, y) <= GRID_BOTTOM:
                self.selection = self.drag['base'] | selected_between(self.model, self.drag['origin'], end)
            else:
                self.selection = self.drag['base'].copy()
            self.draw()
            self.canvas.create_rectangle(x0, y0, x, y, outline='#ffcd66', dash=(4, 3), width=2, tags='ghost')
            self.say(f'已框选{len(self.selection)}项。松开后从选中内容上拖动，可整体移动。')
            return
        if index is not None:
            left, size = self.geometry()
            if self.drag['kind'] == 'field':
                spans = [(index, FIELD_WIDTHS[self.drag['field']])]
            else:
                delta = index - self.drag['origin']
                spans = [(item['start'] + delta, item_width(item)) for item in self.model['items']
                         if item['start'] in self.drag['starts']]
            valid = True
            try:
                if self.drag['kind'] == 'field':
                    place_field(self.model, index, self.drag['field'])
                else:
                    move_items(self.model, self.drag['starts'], delta)
            except ValueError:
                valid = False
            for start, width in spans:
                self.canvas.create_rectangle(left + start * size, GRID_TOP - 3, left + (start + width) * size, GRID_BOTTOM + 3,
                    outline='#81edaa' if valid else '#ff786b', width=4, tags='ghost')

    def drag_release(self, event):
        if not self.drag:
            return
        drag, self.drag = self.drag, None
        if drag['kind'] == 'marquee':
            self.canvas.delete('ghost')
            return
        index = self.index_at(event)
        if index is None and not drag['moved'] and drag['kind'] == 'field':
            index = self.selected
        if index is not None:
            try:
                if drag['kind'] == 'field':
                    model = place_field(self.model, index, drag['field'])
                    self.selection = {index}
                else:
                    delta = index - drag['origin']
                    model = move_items(self.model, drag['starts'], delta)
                    self.selection = {start + delta for start in drag['starts']}
                self.selected = index
                self.change(model)
            except ValueError as exc:
                self.say(str(exc), True)
        self.canvas.delete('ghost')

    def delete(self):
        model = remove_items(self.model, self.selection) if self.selection else remove_at(self.model, self.selected)
        self.selection.clear()
        self.change(model)

    def insert(self, text):
        try:
            model = write_text(self.model, self.selected, text)
            self.selection.clear()
            self.change(model)
            self.selected = min(CELL_COUNT - 1, self.selected + len(text))
            self.draw()
        except ValueError as exc:
            self.say(str(exc), True)

    def paste(self, event=None):
        try:
            self.insert(self.window.clipboard_get())
        except tk.TclError:
            pass
        return 'break'

    def key(self, event):
        if event.keysym in ('Left', 'Right', 'Home', 'End'):
            self.selection.clear()
            self.selected = (0 if event.keysym == 'Home' else 29 if event.keysym == 'End' else
                             max(0, min(29, self.selected + (-1 if event.keysym == 'Left' else 1))))
            self.draw()
        elif event.keysym == 'Delete':
            self.delete()
        elif event.keysym == 'BackSpace':
            self.selected = max(0, self.selected - 1)
            self.delete()
        elif event.char and not event.state & 4:
            self.insert(event.char)
        return 'break'

    def undo(self):
        if self.history:
            self.future.append(deepcopy(self.model))
            self.model = self.history.pop()
            self.selection.clear()
            self.draw()
        return 'break'

    def redo(self):
        if self.future:
            self.history.append(deepcopy(self.model))
            self.model = self.future.pop()
            self.selection.clear()
            self.draw()
        return 'break'

    def refresh_names(self):
        try:
            self.saved_names.configure(values=list(self.catalog.choices()))
            if self.library.warnings:
                self.say(f'已忽略{len(self.library.warnings)}个无效或重名文件，可打开布局文件夹检查：{self.library.warnings[0]}', True)
        except (OSError, ValueError) as exc:
            self.say(f'布局库无法读取：{exc}', True)

    def save_named(self):
        try:
            label = self.layout_name.get()
            kind, key = self.catalog.choices().get(label, ('new', label))
            name = key if kind == 'saved' else label
            if kind == 'preset':
                name = self.catalog.copy_name(label + '（副本）')
            name = self.library.save(name, self.model)
            self.layout_name.set(self.catalog.label_for_saved(name))
            self.refresh_names()
            self.on_library_change()
            self.say(f'已保存“{name}”。换个名称再保存即可创建另一套布局。')
            return True
        except (OSError, ValueError) as exc:
            self.say(str(exc), True)
            return False

    def new_layout(self):
        try:
            name = self.library.new_name()
            self.load_model({'items': []})
            self.layout_name.set(name)
            self.selected = 0
            self.canvas.focus_set()
            self.draw()
            self.say(f'已新建“{name}”；点击保存或保存并应用后加入布局列表。')
        except (OSError, ValueError) as exc:
            self.say(str(exc), True)

    def open_layout_folder(self):
        try:
            os.startfile(str(self.library.storage_directory()))
        except (OSError, ValueError) as exc:
            self.say(f'无法打开布局文件夹：{exc}', True)

    def load_named(self):
        try:
            _, model = self.catalog.resolve(self.layout_name.get(), self.speed_unit)
            self.selection.clear()
            self.change(model)
            self.say('已读取到编辑器；点击保存并应用后显示到仪表。可撤销读取操作。')
        except (OSError, ValueError) as exc:
            self.say(str(exc), True)

    def delete_named(self):
        try:
            kind, name = self.catalog.choices().get(self.layout_name.get(), ('new', None))
            if kind != 'saved':
                raise ValueError('请选择已保存的自定义布局；默认布局不能删除')
            self.library.load(name)
            if messagebox.askyesno('删除已保存布局', f'删除“{name}”？编辑器中的内容仍会保留。', parent=self.window):
                self.library.delete(name)
                self.refresh_names()
                self.on_library_change()
                self.say('已从布局库删除；当前编辑内容仍在。')
        except (OSError, ValueError) as exc:
            self.say(str(exc), True)

    def import_file(self):
        paths = filedialog.askopenfilenames(parent=self.window, title='导入Halo布局（可多选）',
                    filetypes=[('Halo布局文件', '*.json'), ('所有文件', '*.*')])
        if not paths:
            return
        try:
            entries = [import_layout(path) for path in paths]
            if len(self.library.entries()) + len(entries) > 200:
                raise ValueError('导入后超过200套布局，请先整理布局文件夹')
            for entry in entries:
                name = entry['name']
                if name in self.library.entries() or name in DEFAULT_NAMES:
                    name = self.catalog.copy_name(name + '（导入）')
                self.library.save(name, entry['layout'])
            self.refresh_names()
            self.on_library_change()
            self.selection.clear()
            self.change(entries[-1]['layout'])
            self.layout_name.set(self.catalog.label_for_saved(name))
            self.say(f'已导入{len(entries)}套布局，原有同名方案保留；当前打开最后一套，保存并应用后启用。')
        except (OSError, ValueError) as exc:
            self.refresh_names()
            self.on_library_change()
            self.say(f'导入失败：{exc}', True)

    def export_file(self):
        path = filedialog.asksaveasfilename(parent=self.window, title='导出当前编辑布局',
                    initialfile='Halo-layout.json', defaultextension='.json', filetypes=[('Halo布局文件', '*.json')])
        if not path:
            return
        try:
            export_layout(path, self.layout_name.get(), self.model)
            self.say('当前编辑布局已导出；将此JSON文件发给其他用户即可导入。')
        except (OSError, ValueError) as exc:
            self.say(f'导出失败：{exc}', True)

    def select_choice(self, label):
        self.layout_name.set(label)
        self.load_named()

    def current_choice(self):
        """Return a choice only when it exactly matches the stored model."""
        label = self.layout_name.get()
        try:
            _, saved = self.catalog.resolve(label, self.speed_unit)
            if saved == normalize(self.model):
                return label
        except (OSError, ValueError):
            pass
        return None

    def apply(self):
        try:
            model = normalize(self.model)
            if self.current_choice() is None and not self.save_named():
                return
            self.on_apply(deepcopy(model))
            self.window.destroy()
        except ValueError as exc:
            messagebox.showerror('布局无法应用', str(exc), parent=self.window)
