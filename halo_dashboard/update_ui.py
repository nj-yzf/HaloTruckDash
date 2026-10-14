"""Tk update dialog; network and disk work never run on the UI/telemetry thread."""
import json
import logging
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from urllib.error import HTTPError, URLError

from .layout_library import atomic_json
from .updates import fetch_release, download_release, https_url, UpdateCancelled
from .version import VERSION, DEFAULT_UPDATE_URL
from .window_geometry import work_area


def error_text(exc):
    if isinstance(exc, HTTPError):
        return f'服务器返回HTTP {exc.code}，请核对更新源或稍后重试'
    if isinstance(exc, URLError):
        return f'无法连接更新服务器：{exc.reason}'
    if isinstance(exc, TimeoutError):
        return '连接或下载超时，请稍后重试'
    if isinstance(exc, PermissionError):
        return '无法保存更新文件，请检查程序data目录的写入权限'
    return str(exc) or type(exc).__name__


class UpdateController:
    def __init__(self, root, state, enabled=True):
        self.root, self.state, self.enabled = root, Path(state), enabled
        self.preferences = self.state / 'update-settings.json'
        self.directory = self.state / 'updates'
        self.source, self.auto = DEFAULT_UPDATE_URL, False
        try:
            if self.preferences.stat().st_size <= 16384:
                saved = json.loads(self.preferences.read_text(encoding='utf-8-sig'))
                source = saved.get('manifest_url') or DEFAULT_UPDATE_URL
                self.source = https_url(source) if source else ''
                self.auto = saved.get('auto_check') is True
        except (OSError, ValueError, AttributeError, RecursionError):
            pass
        self.window = None
        self.release, self.downloaded = None, None
        self.busy, self.closed = False, False
        self.cancel_event = threading.Event()
        self.events = queue.Queue()
        self.status = '尚未检查更新' if self.source else '尚未配置发布地址，请填写更新清单的HTTPS地址。'
        self.after_id = root.after(80, self.poll)
        self.auto_id = None
        if enabled and self.auto and self.source:
            self.auto_id = root.after(2000, self.automatic_check)

    def automatic_check(self):
        self.auto_id = None
        if not self.closed and not self.busy:
            self.check(automatic=True)

    def show(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            return self.window
        self.window = tk.Toplevel(self.root)
        window = self.window
        window.title('在线更新 · Halo Truck Dash')
        window.configure(bg='#101722')
        window.transient(self.root)
        window.protocol('WM_DELETE_WINDOW', self.hide)
        shell = ttk.Frame(window, padding=16)
        shell.pack(fill='both', expand=True)
        footer = ttk.Frame(shell)
        footer.pack(side='bottom', fill='x', pady=(12, 0))
        self.check_button = ttk.Button(footer, text='检查更新', command=self.check)
        self.check_button.pack(side='left')
        self.download_button = ttk.Button(footer, text='下载更新包', command=self.download)
        self.download_button.pack(side='left', padx=8)
        self.cancel_button = ttk.Button(footer, text='取消', command=self.cancel)
        self.cancel_button.pack(side='left')
        ttk.Button(footer, text='打开下载目录', command=self.open_directory).pack(side='right')
        body = ttk.Frame(shell)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=f'当前版本  {VERSION}', font=('Microsoft YaHei UI', 15, 'bold')).pack(anchor='w')
        self.latest = ttk.Label(body, text='', style='Muted.TLabel')
        self.latest.pack(anchor='w', pady=(3, 12))
        ttk.Label(body, text='更新源（latest.json 的 HTTPS 地址）').pack(anchor='w')
        source_row = ttk.Frame(body)
        source_row.pack(fill='x', pady=5)
        self.url_var = tk.StringVar(value=self.source)
        self.source_entry = ttk.Entry(source_row, textvariable=self.url_var)
        self.source_entry.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.save_button = ttk.Button(source_row, text='保存设置', command=self.save)
        self.save_button.pack(side='right')
        self.auto_var = tk.BooleanVar(value=self.auto)
        self.auto_button = ttk.Checkbutton(body, text='启动时自动检查（仅在发现新版时打开提示）', variable=self.auto_var)
        self.auto_button.pack(anchor='w', pady=(2, 10))
        ttk.Label(body, text='更新说明', style='Muted.TLabel').pack(anchor='w')
        self.notes = tk.Text(body, height=6, width=48, wrap='word', relief='flat',
                             bg='#080e18', fg='#e8edf4', insertbackground='white',
                             font=('Microsoft YaHei UI', 10), padx=8, pady=8, state='disabled')
        self.notes.pack(fill='both', expand=True, pady=4)
        self.progress = ttk.Progressbar(body, mode='determinate', maximum=100)
        self.progress.pack(fill='x', pady=(8, 4))
        self.status_label = ttk.Label(body, text=self.status, justify='left', anchor='w', wraplength=600)
        self.status_label.pack(fill='x')
        self.status_label.bind('<Configure>', lambda e: self.status_label.configure(wraplength=max(1, e.width - 4)))
        ttk.Label(body, text='下载完成后解压到新目录，并复制旧版data文件夹以保留布局和设置。',
                  style='Muted.TLabel', wraplength=600).pack(fill='x', pady=(8, 0))
        self.refresh()
        window.update_idletasks()
        left, top, right, bottom = work_area(window)
        width = min(max(650, window.winfo_reqwidth()), right - left - 32)
        height = min(max(540, window.winfo_reqheight()), bottom - top - 64)
        window.minsize(width, height)
        window.geometry(f'{width}x{height}')
        return window

    def hide(self):
        # Closing the dialog cancels its operation; it never stops the dashboard.
        if self.busy:
            self.cancel()
        if self.window is not None:
            self.window.destroy()
            self.window = None

    def visible(self):
        return self.window is not None and self.window.winfo_exists()

    def refresh(self):
        if not self.visible():
            return
        state = 'disabled' if self.busy else 'normal'
        for widget in (self.check_button, self.source_entry, self.save_button, self.auto_button):
            widget.configure(state=state)
        self.download_button.configure(state='normal' if not self.busy and self.release and self.release.newer_than() else 'disabled')
        self.cancel_button.configure(state='normal' if self.busy else 'disabled')
        self.status_label.configure(text=self.status)
        self.latest.configure(text=f'发布版本  {self.release.version}' if self.release else '发布版本  —')
        self.notes.configure(state='normal')
        self.notes.delete('1.0', 'end')
        self.notes.insert('1.0', self.release.notes if self.release else '检查后显示更新说明。')
        self.notes.configure(state='disabled')

    def save(self):
        if self.busy:
            return False
        try:
            source = self.url_var.get().strip() if self.visible() else self.source
            if source:
                https_url(source)
            auto = self.auto_var.get() if self.visible() else self.auto
            if auto and not source:
                raise ValueError('请先填写更新源，再开启自动检查')
            atomic_json(self.preferences, {'manifest_url': source, 'auto_check': bool(auto)})
            if source != self.source:
                self.release, self.downloaded = None, None
            self.source, self.auto = source, bool(auto)
            self.status = '更新设置已保存' if source else '尚未配置发布地址，请填写更新清单的HTTPS地址。'
            self.refresh()
            return True
        except (OSError, ValueError) as exc:
            self.status = error_text(exc)
            self.refresh()
            return False

    def run(self, operation):
        if self.busy or self.closed:
            return
        self.busy = True
        self.cancel_event = threading.Event()
        cancel = self.cancel_event
        self.refresh()
        def work():
            try:
                result = operation(cancel)
                self.events.put(('done', result))
            except UpdateCancelled:
                self.events.put(('cancelled', None))
            except Exception as exc:
                logging.warning('更新操作失败：%s', exc)
                self.events.put(('error', error_text(exc)))
        threading.Thread(target=work, name='HaloUpdate', daemon=True).start()

    def check(self, automatic=False):
        if self.busy or self.closed:
            return
        if not automatic:
            if self.auto_id is not None:
                self.root.after_cancel(self.auto_id)
                self.auto_id = None
            self.show()
            if not self.save():
                return
        if not self.source:
            self.status = '尚未配置发布地址，请填写更新清单的HTTPS地址。'
            self.refresh()
            return
        url = self.source
        self.release, self.downloaded = None, None
        self.status = '正在检查更新…'
        if self.visible():
            self.progress.configure(value=0)
        def operation(cancel):
            return ('checked', fetch_release(url, cancel), automatic)
        self.run(operation)

    def download(self):
        if self.busy or self.closed or not self.release or not self.release.newer_than():
            return
        release = self.release
        self.status = f'正在下载 {release.version}…'
        self.progress.configure(value=0)
        def operation(cancel):
            last_progress = 0.0
            def progress(received, total):
                nonlocal last_progress
                now = time.monotonic()
                if now - last_progress >= .1 or received == total:
                    self.events.put(('progress', (received, total)))
                    last_progress = now
            path = download_release(release, self.directory, cancel, progress)
            return ('downloaded', path)
        self.run(operation)

    def cancel(self):
        if self.busy:
            self.cancel_event.set()
            self.status = '正在取消，请等待当前网络请求结束…'
            self.refresh()

    def open_directory(self):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            os.startfile(self.directory)
        except OSError as exc:
            self.status = error_text(exc)
            self.refresh()

    def poll(self):
        if self.closed:
            return
        while not self.events.empty():
            kind, value = self.events.get()
            if kind == 'progress':
                received, total = value
                if not self.cancel_event.is_set():
                    self.status = f'正在下载  {received / total:.0%}  ·  {received / 1048576:.1f}/{total / 1048576:.1f} MB'
                if self.visible():
                    self.progress.configure(value=received / total * 100)
                    self.status_label.configure(text=self.status)
                continue
            self.busy = False
            if kind == 'error':
                self.status = f'操作失败：{value}'
            elif kind == 'cancelled':
                self.status = '操作已取消，未完成的下载已清理'
            elif kind == 'done' and value[0] == 'checked':
                self.release = value[1]
                newer = self.release.newer_than()
                self.status = f'发现新版 {self.release.version}，可下载更新包。' if newer else '当前已是最新版本（不低于发布版本）。'
                if newer and value[2]:
                    self.show()
            elif kind == 'done' and value[0] == 'downloaded':
                self.downloaded = value[1]
                self.status = f'下载完成，SHA256及ZIP完整性校验通过。文件：{self.downloaded.name}'
                if self.visible():
                    self.progress.configure(value=100)
            self.refresh()
        self.after_id = self.root.after(80, self.poll)

    def shutdown(self):
        self.closed = True
        self.cancel_event.set()
        for timer in (self.after_id, self.auto_id):
            if timer is not None:
                self.root.after_cancel(timer)
