"""Candidate device discovery, explicit query-only verification and diagnostics."""
import os
import logging
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from .window_geometry import work_area
from .support import feedback_url


class DeviceDialog:
    def __init__(self, root, send, state, on_feedback=None):
        self.send, self.state = send, Path(state)
        self.on_feedback = on_feedback
        self.rows, self.active, self.busy = {}, False, False
        self.window = tk.Toplevel(root)
        self.window.title('设备与诊断 · HaloTruckDash')
        self.window.configure(bg='#101722')
        self.window.transient(root)
        shell = ttk.Frame(self.window, padding=16)
        shell.pack(fill='both', expand=True)
        footer = ttk.Frame(shell)
        footer.pack(side='bottom', fill='x', pady=(10, 0))
        support = ttk.Frame(shell)
        support.pack(side='bottom', fill='x', pady=(10, 0))
        self.feedback_button = ttk.Button(support, text='导出反馈包', command=self.export_feedback)
        self.feedback_button.pack(side='left')
        self.issue_button = ttk.Button(support, text='反馈问题…', command=self.open_issue)
        self.issue_button.pack(side='left', padx=8)
        ttk.Label(support, text='反馈包仅保存在本机，需自行上传。', style='Muted.TLabel').pack(side='left')
        self.refresh_button = ttk.Button(footer, text='刷新列表', command=self.refresh)
        self.refresh_button.pack(side='left')
        self.verify_button = ttk.Button(footer, text='验证并选用', command=self.verify)
        self.verify_button.pack(side='left', padx=8)
        self.export_button = ttk.Button(footer, text='导出诊断', command=self.export)
        self.export_button.pack(side='left')
        ttk.Button(footer, text='打开数据目录', command=self.open_folder).pack(side='right')
        body = ttk.Frame(shell)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='发现设备 · 验证协议', font=('Microsoft YaHei UI', 15, 'bold')).pack(anchor='w')
        ttk.Label(body, text='未知PID不会自动连接。选中候选接口后验证，只查询屏幕状态和文字，不改动显示。\n'
                  '请先停止同步；验证通过仅代表基础协议兼容，显示效果仍需实际观察。',
                  style='Muted.TLabel', wraplength=820).pack(fill='x', pady=(5, 10))
        table = ttk.Frame(body)
        style = ttk.Style(self.window)
        style.configure('Hardware.Treeview', rowheight=max(26, round(26 * float(root.tk.call('tk', 'scaling')) / (4 / 3))))
        self.tree = ttk.Treeview(table, columns=('product', 'usb', 'interface', 'status'), show='headings', height=6, style='Hardware.Treeview')
        for column, title, width in [('product', '设备名称', 320), ('usb', 'VID : PID', 140),
                                      ('interface', '接口', 80), ('status', '识别状态', 150)]:
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, minwidth=60, stretch=column == 'product')
        scrollbar = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', lambda event: self.update_controls())
        self.details = ttk.Label(body, text='选择接口查看详情。', wraplength=820, justify='left')
        self.status = ttk.Label(body, text='点击刷新获取相关接口；列表和导出诊断均不发送HID查询。', wraplength=820, justify='left')
        # Reserve variable-height status/details before the resizable table.
        # Long validation errors must not disappear at large text scaling.
        self.status.pack(side='bottom', fill='x', pady=3)
        self.details.pack(side='bottom', fill='x', pady=(10, 3))
        table.pack(fill='both', expand=True)
        self.status.bind('<Configure>', lambda event: self.status.configure(wraplength=max(1, event.width - 4)))
        self.update_controls()
        self.window.update_idletasks()
        left, top, right, bottom = work_area(self.window)
        width = min(max(900, self.window.winfo_reqwidth()), right - left - 32)
        height = min(max(500, self.window.winfo_reqheight()), bottom - top - 64)
        self.window.minsize(width, height)
        self.window.geometry(f'{width}x{height}')

    def export_feedback(self):
        if self.on_feedback is not None:
            self.on_feedback()

    def open_issue(self):
        try:
            if not webbrowser.open(feedback_url()):
                raise OSError('无法打开浏览器，请手动访问GitHub仓库的Issues页面')
            self.status.configure(text='请在浏览器填写问题，附上导出的反馈ZIP；程序不会自动提交或上传。')
        except Exception as exc:
            logging.exception('Feedback browser launch failed')
            self.notice(str(exc), True)

    def exists(self):
        return self.window.winfo_exists()

    def selected(self):
        selection = self.tree.selection()
        return self.rows.get(selection[0]) if selection else None

    def set_state(self, state):
        previous = self.selected()
        key = previous['key'] if previous else None
        self.active = state['active']
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        for index, row in enumerate(state['rows']):
            iid = f'd{index}'
            self.rows[iid] = row
            label = row['status'] + (' · 已选用' if row['selected'] else '')
            self.tree.insert('', 'end', iid=iid, values=(row['product'], f'{row["vid"]} : {row["pid"]}', row['interface'], label))
            if row['key'] == key or (not key and row['selected']):
                self.tree.selection_set(iid)
        self.update_controls()

    def update_controls(self):
        row = self.selected()
        state = 'disabled' if self.busy else 'normal'
        self.refresh_button.configure(state=state)
        self.export_button.configure(state=state)
        can_verify = bool(row and row['can_verify'] and not self.active and not self.busy)
        self.verify_button.configure(state='normal' if can_verify else 'disabled')
        if row:
            usage_page = row['usage_page']
            page = f'{usage_page:04X}' if isinstance(usage_page, int) else '未知'
            details = f'Usage Page {page} · Usage {row["usage"]} · USB修订 {row["release_number"]}。{row["reason"]}'
            self.details.configure(text='请先停止同步，再验证设备。' if self.active else details)
        else:
            self.details.configure(text='选择接口查看详情；未知或非控制接口仍可导出诊断。')

    def operation(self, name):
        if self.busy:
            return
        row = self.selected()
        if name == 'hardware_verify' and (self.active or not row or not row['can_verify']):
            return
        self.busy = True
        self.status.configure(text='正在查询基础协议；未发送屏幕设置…' if name == 'hardware_verify' else '正在枚举设备信息…')
        self.update_controls()
        self.send((name, row['key'] if row else None))

    def refresh(self):
        self.operation('hardware_scan')

    def verify(self):
        self.operation('hardware_verify')

    def export(self):
        self.operation('hardware_export')

    def notice(self, text, error=False):
        self.busy = False
        self.status.configure(text=text, foreground='#ff8175' if error else '#a8dfc9')
        self.update_controls()

    def open_folder(self):
        try:
            self.state.mkdir(parents=True, exist_ok=True)
            os.startfile(self.state)
        except OSError as exc:
            self.notice(f'无法打开目录：{exc}', True)
