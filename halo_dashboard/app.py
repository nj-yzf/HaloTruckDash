import argparse
import ctypes
from ctypes import wintypes
import json
import logging
from pathlib import Path
import queue
import sys
import threading
import tempfile
import time
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .device import Halo
from .display import COLORS, GEAR_MODES, format_frame
from .installer import DEFAULT_GAME, install_plugin
from .games import GAMES, GAME_CHOICES, default_game_dir, detect_game
from .telemetry import Telemetry, demo
from .layout import DEFAULT_LAYOUT, validate as validate_layout, gear_text, SPEED_UNITS, convert_speed
from .grid_editor import GridEditor
from .layout_library import LayoutLibrary, atomic_json
from .layout_catalog import LayoutCatalog, LEGACY_DRAFT_NAME, LEGACY_NAMES, choices_for
from .window_geometry import fit_main
from .version import VERSION
from .storage import data_directory
from .branding import configure_windows_app, apply_icon
from .hardware import DeviceRegistry, discover_candidates, device_key, device_rows, diagnostics_document
from .device_dialog import DeviceDialog
from .support import (RuntimeStatus, configure_logging, install_exception_hooks, record_ui_exception,
                      collect_diagnostics, export_feedback, plugin_information, redact_text)

BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
ASSETS = Path(getattr(sys, "_MEIPASS", BASE))
STATE = BASE / "data"

class Worker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.commands = queue.Queue()
        self.events = queue.Queue()
        self.settings = {"mode": "preset1", "demo": False, "alerts": True,
                         "color": COLORS["冰蓝"], "hz": 4,
                         "custom": DEFAULT_LAYOUT.copy(), "gear_mode": 'auto', 'speed_unit': 'km/h'}
        self.active = False
        self.finished = threading.Event()
        self.runtime = RuntimeStatus()

    def event(self, kind, value):
        self.events.put((kind, value))

    def run(self):
        try:
            self._run()
        except Exception:
            logging.exception('Worker initialization or cleanup failed')
            self.event('error', '后台线程异常退出，请打开“设备与诊断”导出反馈包')
        finally:
            self.active = False
            self.runtime.update(sync_active=False, device_connected=False, worker_finished=True)
            self.event('active', False)
            self.finished.set()

    def _run(self):
        reader = Telemetry()
        halo = Halo(STATE / "screen-recovery.json")
        registry = getattr(halo, 'registry', None) or DeviceRegistry(STATE / 'validated-devices.json')
        start = time.monotonic()
        last_send = 0.0
        first_send = False
        last_scan = 0.0
        next_reconnect = 0.0
        reconnect_attempts = 0
        last_error = None
        quitting = False
        telemetry_state = None
        last_summary = start
        try:
            while not quitting:
                while not self.commands.empty():
                    command = self.commands.get()
                    if isinstance(command, tuple):
                        action, key = command
                        try:
                            devices = discover_candidates()
                            if action == 'hardware_verify':
                                if self.active:
                                    raise RuntimeError('请先停止同步，再验证和选用设备')
                                matches = [info for info in devices if device_key(info) == key]
                                if len(matches) != 1:
                                    raise RuntimeError('设备已拔出或标识已变化，请刷新列表后重新选择')
                                with self.runtime.operation('verify_protocol'):
                                    halo.verify_candidate(matches[0])
                                logging.info('Device protocol verified VID=%04X PID=%04X interface=%s',
                                             matches[0]['vendor_id'], matches[0]['product_id'], matches[0].get('interface_number'))
                                notice = '基础协议验证通过，已选用于同步；未改动屏幕。显示效果仍需开始同步后观察。'
                            elif action == 'hardware_export':
                                atomic_json(STATE / 'diagnostics.json', diagnostics_document(registry, devices, reader.read()))
                                notice = f'诊断已导出：{STATE / "diagnostics.json"}（不含序列号和设备路径）'
                            elif action == 'hardware_scan':
                                notice = f'发现{len(devices)}个相关HID接口；枚举未发送任何HID查询。'
                            else:
                                raise ValueError('未知的设备操作')
                            self.event('hardware', {'rows': device_rows(registry, devices, include_keys=True), 'active': self.active})
                            self.event('hardware_notice', {'text': notice, 'error': False})
                        except Exception as exc:
                            logging.exception('Device operation failed action=%s', action)
                            self.event('hardware_notice', {'text': str(exc), 'error': True})
                        continue
                    if command in ("stop", "quit"):
                        self.active = False
                        self.runtime.update(sync_active=False)
                        logging.info('Sync stop requested action=%s', command)
                        try:
                            with self.runtime.operation('restore_screen'):
                                if halo.saved and not halo.device:
                                    halo.open()
                                halo.restore()
                            logging.info('Screen restored after stop')
                            self.event("device", "已停止同步，原屏幕设置已恢复")
                        except Exception as exc:
                            logging.exception('Screen restore after stop failed')
                            self.event("error", f"恢复屏幕失败：{exc}。恢复记录已保留，可点击“恢复原屏幕”重试")
                        finally:
                            halo.close()
                            self.runtime.update(device_connected=False)
                            self.event("active", False)
                        quitting = command == "quit"
                    elif command in ("start", "recover"):
                        if self.active:
                            continue
                        if command == "start":
                            self.active = True
                            self.runtime.update(sync_active=True)
                            logging.info('Sync start requested mode=%s hz=%s demo=%s', self.settings['mode'], self.settings['hz'], self.settings['demo'])
                            next_reconnect = 0.0
                            reconnect_attempts = 0
                            self.event("active", True)
                            continue
                        try:
                            with self.runtime.operation('recover_connect'):
                                halo.open()
                            if command == "recover" and not halo.recovery_path.exists():
                                halo.close()
                                self.event("device", "没有待恢复的屏幕记录")
                                continue
                            with self.runtime.operation('recover_screen'):
                                halo.capture()
                                halo.restore()
                            logging.info('Manual screen recovery succeeded')
                            halo.close()
                            self.event("device", "原屏幕已恢复")
                        except Exception as exc:
                            logging.exception('Manual screen recovery failed')
                            halo.close()
                            self.event("error", str(exc))
                if quitting:
                    break
                now = time.monotonic()
                settings = self.settings.copy()
                truck = demo(now - start) if settings["demo"] else reader.read()
                current_telemetry = (truck.connected, truck.game_id, truck.paused, truck.reason, settings['demo'])
                if current_telemetry != telemetry_state:
                    logging.info('Telemetry changed connected=%s game=%s paused=%s demo=%s reason=%s', *current_telemetry[:3], current_telemetry[4], current_telemetry[3])
                    telemetry_state = current_telemetry
                    self.runtime.update(telemetry_connected=truck.connected, game_id=truck.game_id,
                                        paused=truck.paused, telemetry_reason=truck.reason, demo=settings['demo'])
                try:
                    frame = format_frame(truck, settings["mode"], color=settings['color'], alerts=settings['alerts'],
                                         custom=settings['custom'], gear_mode=settings['gear_mode'], speed_unit=settings.get('speed_unit', 'km/h'))
                except ValueError as exc:
                    # Invalid editing must not terminate the worker or start an
                    # endless HID reconnect loop. Keep the proven text layout.
                    frame = format_frame(truck, "preset1", color=settings["color"],
                                         alerts=settings["alerts"], gear_mode=settings['gear_mode'], speed_unit=settings.get('speed_unit', 'km/h'))
                    self.event("layout_warning", str(exc))
                self.event("frame", (truck, frame))
                if self.active and not halo.device and now >= next_reconnect:
                    try:
                        self.runtime.increment('connect_attempts')
                        with self.runtime.operation('connect_device'):
                            halo.open()
                        with self.runtime.operation('capture_screen'):
                            halo.capture()
                        self.runtime.increment('connections')
                        self.runtime.update(device_connected=True, last_error=None, consecutive_connect_failures=0)
                        first_send = True
                        reconnect_attempts = 0
                        last_error = None
                        logging.info("HID 已连接：PID=%04X", halo.info['product_id'])
                        self.event("device", f"正在同步 Halo PixelBar · USB {halo.info['product_id']:04X}")
                    except Exception as exc:
                        halo.close()
                        reconnect_attempts += 1
                        self.runtime.update(device_connected=False, last_error=redact_text(exc),
                                            consecutive_connect_failures=reconnect_attempts)
                        delay = min(10, 2 * reconnect_attempts)
                        next_reconnect = time.monotonic() + delay
                        self.event("device", f"音响连接异常，{delay} 秒后自动重试：{exc}")
                        if str(exc) != last_error:
                            logging.exception("HID 连接失败，自动重试 attempt=%s delay=%ss", reconnect_attempts, delay)
                            last_error = str(exc)
                if self.active and halo.device and now - last_send >= 1 / settings["hz"]:
                    try:
                        with self.runtime.operation('sync_frame'):
                            halo.show(frame, verify=first_send)
                        self.runtime.increment('sync_cycles')
                        first_send = False
                        last_send = now
                    except Exception as exc:
                        self.runtime.increment('sync_failures')
                        self.runtime.update(device_connected=False, last_error=redact_text(exc))
                        logging.exception("HID 同步失败，将自动重连；保留原屏幕恢复记录")
                        halo.close()
                        next_reconnect = time.monotonic() + 2
                        self.event("device", f"同步中断，2 秒后自动重连：{exc}")
                if not self.active and now - last_scan > 5:
                    try:
                        rows = device_rows(registry, include_keys=True)
                        usable = sum(row['usable'] for row in rows)
                        self.event('hardware', {'rows': rows, 'active': self.active})
                        self.event("scan", '音响已连接' if usable else '发现候选接口，请打开“设备与诊断”验证' if rows else '未检测到音响 USB 接口')
                    except Exception as exc:
                        logging.warning('Device enumeration failed: %s', exc)
                        self.event("scan", str(exc))
                    last_scan = now
                if self.active and now - last_summary >= 60:
                    logging.info('Runtime summary %s', json.dumps(self.runtime.snapshot(), ensure_ascii=False))
                    last_summary = now
                self.finished.wait(.1)
        except Exception as exc:
            logging.exception("后台线程异常")
            self.event("error", f"后台线程退出：{exc}，请关闭后重新启动")
        finally:
            logging.info('Worker final runtime %s', json.dumps(self.runtime.snapshot(), ensure_ascii=False))
            try:
                if halo.device:
                    halo.restore()
            except Exception:
                logging.exception("退出时恢复失败，保留恢复文件")
            halo.close()
            reader.close()
            self.finished.set()

class App:
    def __init__(self, root):
        self.root = root
        self.closing = False
        self.root.title(f"HaloTruckDash · 欧卡/美卡点阵仪表 {VERSION}")
        apply_icon(root, ASSETS / 'assets')
        self.root.geometry("780x660")
        self.root.minsize(730, 650)
        self.root.configure(bg="#101722")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#101722")
        style.configure("TLabel", background="#101722", foreground="#e8edf4", font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 23, "bold"))
        style.configure("Muted.TLabel", foreground="#8fa2b8")
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(12, 8))
        style.configure("TCheckbutton", background="#101722", foreground="#e8edf4", font=("Microsoft YaHei UI", 10))
        style.map("TCheckbutton", background=[("active", "#1c293a")])
        self.mode = tk.StringVar(value="默认布局1")
        self.gear_mode = tk.StringVar(value='跟随游戏')
        self.color = tk.StringVar(value="冰蓝")
        self.hz = tk.StringVar(value="4")
        self.speed_unit = tk.StringVar(value='km/h')
        self.demo = tk.BooleanVar(value=False)
        self.alerts = tk.BooleanVar(value=True)
        self.game_dir = tk.StringVar(value=str(DEFAULT_GAME))
        self.install_target = tk.StringVar(value=GAMES['ets2'].label)
        self.game_dirs = {key: str(default_game_dir(key)) for key in GAMES}
        self._install_key = 'ets2'
        self.custom_layout = DEFAULT_LAYOUT.copy()
        self.layout_library = LayoutLibrary(STATE / 'layouts.json')
        self.layout_catalog = LayoutCatalog(self.layout_library)
        self.layout_choices = {}
        self.editor = None
        self.device_dialog = None
        self.feedback_busy = False
        root.report_callback_exception = self.ui_exception
        self.hardware_state = {'rows': [], 'active': False}
        self.refresh_layout_choices()
        self.load_settings()
        container = ttk.Frame(root, padding=(20, 14))
        container.pack(fill="both", expand=True)
        # Reserve the footer before packing the body, so resizing cannot cut
        # off the final line. Wrap to the real available width, not a constant.
        self.footer = ttk.Label(container, text="同步时请关闭其他程序对音响屏幕的控制。",
                                style="Muted.TLabel", anchor="w", justify="left")
        self.footer.pack(side="bottom", fill="x", pady=(8, 0))
        self.footer.bind("<Configure>", lambda e: self.footer.configure(wraplength=max(1, e.width - 4)))
        shell = ttk.Frame(container)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text="HaloTruckDash", style="Title.TLabel").pack(anchor="w")
        ttk.Label(shell, text="欧卡2 / ETS2 · 美卡 / ATS  →  Halo PixelBar", style="Muted.TLabel").pack(anchor="w", pady=(3, 12))
        self.canvas = tk.Canvas(shell, height=98, bg="#050910", highlightthickness=1, highlightbackground="#2b3d53")
        self.canvas.pack(fill="x")
        self.preview = self.canvas.create_text(364, 49, text="WAIT ETS2/ATS", fill="#66afff", font=("Consolas", 40, "bold"))
        self.canvas.bind("<Configure>", lambda e: self.canvas.coords(self.preview, e.width / 2, 49))
        ttk.Label(shell, text="发送内容预览 · 字体与实际点阵屏可能不同", style="Muted.TLabel").pack(anchor="w", pady=(5, 10))
        self.values = ttk.Label(shell, text="车速 —    挡位 —    转速 —    燃油 —")
        self.values.pack(anchor="w")
        self.telemetry_status = ttk.Label(shell, text="正在检查游戏遥测…", style="Muted.TLabel")
        self.telemetry_status.pack(anchor="w", pady=(5, 0))
        self.device_status = ttk.Label(shell, text="正在检查音响 USB 接口…", style="Muted.TLabel")
        self.device_status.pack(anchor="w", pady=(5, 10))
        row = ttk.Frame(shell)
        row.pack(fill="x")
        for label, var, choices, width in [("显示方案", self.mode, list(self.layout_choices), 17), ("颜色", self.color, list(COLORS), 7),
                                            ("刷新/秒", self.hz, ["2", "4", "5"], 4),
                                            ("挡位模式", self.gear_mode, list(GEAR_MODES), 10)]:
            group = ttk.Frame(row)
            group.pack(side="left", padx=(0, 14))
            ttk.Label(group, text=label, style="Muted.TLabel").pack(anchor="w")
            combo = ttk.Combobox(group, textvariable=var, values=choices, width=width, state="readonly")
            combo.pack(pady=(3, 0))
            if var is self.mode:
                self.mode_combo = combo
                combo.configure(postcommand=self.refresh_layout_choices)
                combo.bind('<<ComboboxSelected>>', self.select_layout)
        checks = ttk.Frame(shell)
        checks.pack(fill="x", pady=10)
        ttk.Checkbutton(checks, text="超速变红 / 低油量 / 驻车提示", variable=self.alerts).pack(side="left")
        units = ttk.Frame(checks)
        units.pack(side='left', padx=14)
        ttk.Label(units, text='速度单位').pack(side='left', padx=(0, 5))
        self.unit_combo = ttk.Combobox(units, textvariable=self.speed_unit, values=SPEED_UNITS, width=6, state='readonly')
        self.unit_combo.pack(side='left')
        self.unit_combo.bind('<<ComboboxSelected>>', self.speed_unit_changed)
        ttk.Checkbutton(checks, text="模拟演示数据", variable=self.demo).pack(side="right")
        controls = ttk.Frame(shell)
        controls.pack(fill="x", pady=(0, 12))
        self.start_button = ttk.Button(controls, text="开始同步到音响", command=lambda: self.command("start"))
        self.start_button.pack(side="left", padx=(0, 10))
        self.stop_button = ttk.Button(controls, text="停止并恢复屏幕", command=lambda: self.command("stop"), state="disabled")
        self.stop_button.pack(side="left", padx=(0, 10))
        ttk.Button(controls, text="恢复原屏幕", command=lambda: self.command("recover")).pack(side="left")
        ttk.Button(controls, text="布局编辑器…", command=self.edit_layout).pack(side="right")
        ttk.Separator(shell).pack(fill="x", pady=(1, 12))
        ttk.Label(shell, text="首次使用：为欧卡2 / 美卡分别安装插件，重启对应游戏并进入驾驶").pack(anchor="w")
        location = ttk.Frame(shell)
        location.pack(fill="x", pady=6)
        self.target_combo = ttk.Combobox(location, textvariable=self.install_target, values=list(GAME_CHOICES), width=13, state='readonly')
        self.target_combo.pack(side='left', padx=(0, 6))
        self.target_combo.bind('<<ComboboxSelected>>', self.install_target_changed)
        ttk.Entry(location, textvariable=self.game_dir).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(location, text="选择目录", command=self.browse).pack(side="left")
        bottom = ttk.Frame(shell)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="安装遥测插件", command=self.install).pack(side="left")
        ttk.Button(bottom, text='设备与诊断…', command=self.open_device_dialog).pack(side='left', padx=8)
        ttk.Button(bottom, text="使用说明", command=self.help).pack(side="right")
        fit_main(root)
        self.worker = Worker()
        self.worker.start()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = self.root.after(100, self.poll)

    def load_settings(self):
        try:
            data = json.loads((STATE / "settings.json").read_text(encoding="utf-8"))
            for key, var, choices in [("color", self.color, COLORS),
                                      ("hz", self.hz, ("2", "4", "5")), ('gear_mode', self.gear_mode, GEAR_MODES),
                                      ('speed_unit', self.speed_unit, SPEED_UNITS)]:
                if data.get(key) in choices:
                    var.set(data[key])
            if isinstance(data.get('game_dir'), str):
                self.game_dirs['ets2'] = data['game_dir']
            if isinstance(data.get('game_dirs'), dict):
                self.game_dirs.update({key: value for key, value in data['game_dirs'].items() if key in GAMES and isinstance(value, str)})
            self._install_key = data.get('install_target') if data.get('install_target') in GAMES else 'ets2'
            self.install_target.set(GAMES[self._install_key].label)
            self.game_dir.set(self.game_dirs[self._install_key])
            self.alerts.set(bool(data.get("alerts", True)))
            self.custom_layout = validate_layout(data.get('custom', DEFAULT_LAYOUT))
            saved_name = data.get('saved_layout')
            selected = (self.layout_catalog.label_for_saved(saved_name) if saved_name else None)
            old_draft = validate_layout(data.get('draft', self.custom_layout))
            migrate_active = data.get('mode') == LEGACY_DRAFT_NAME and not saved_name
            if migrate_active or (old_draft['items'] and 'draft' in data and
                                  old_draft not in self.layout_library.entries().values()):
                name = self.layout_library.save(self.layout_library.new_name(), old_draft)
                self.refresh_layout_choices()
                if migrate_active:
                    selected = self.layout_catalog.label_for_saved(name)
            selected = selected or LEGACY_NAMES.get(data.get('mode'), data.get('mode'))
            if selected in self.layout_choices:
                self.mode.set(selected)
                kind, _ = self.layout_choices[selected]
                if kind == 'saved':
                    _, self.custom_layout = self.layout_catalog.resolve(selected, self.speed_unit.get())
            if 'draft' in data or migrate_active:
                self.save_settings()
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            logging.exception('Preferences could not be loaded; using available defaults')

    def settings(self):
        kind, key = self.layout_choices.get(self.mode.get(), ('preset', 1))
        return {"mode": f'preset{key}' if kind == 'preset' else 'custom', "color": COLORS[self.color.get()], "hz": int(self.hz.get()),
                "demo": self.demo.get(), "alerts": self.alerts.get(),
                "custom": self.custom_layout.copy(), 'gear_mode': GEAR_MODES[self.gear_mode.get()], 'speed_unit': self.speed_unit.get()}

    def refresh_layout_choices(self):
        try:
            self.layout_choices = self.layout_catalog.choices()
        except (OSError, ValueError) as exc:
            logging.warning('布局列表无法读取：%s', exc)
            self.layout_choices = choices_for({})
        if self.mode.get() not in self.layout_choices:
            self.mode.set('默认布局1')
        if hasattr(self, 'mode_combo'):
            self.mode_combo.configure(values=list(self.layout_choices))
        if self.editor is not None and self.editor.window.winfo_exists():
            self.editor.refresh_names()
        if hasattr(self, 'worker'):
            kind, _ = self.layout_choices.get(self.mode.get(), ('preset', 1))
            if kind == 'saved':
                try:
                    _, self.custom_layout = self.layout_catalog.resolve(self.mode.get(), self.speed_unit.get())
                except (OSError, ValueError):
                    self.mode.set('默认布局1')
            self.worker.settings = self.settings()
            self.save_settings()

    def select_layout(self, event=None):
        try:
            _, model = self.layout_catalog.resolve(self.mode.get(), self.speed_unit.get())
            if self.layout_choices[self.mode.get()][0] != 'preset':
                self.custom_layout = model
            self.worker.settings = self.settings()
            self.save_settings()
        except (OSError, ValueError, KeyError) as exc:
            self.mode.set('默认布局1')
            self.worker.settings = self.settings()
            self.device_status.configure(text=f'无法读取布局：{exc}')

    def command(self, name):
        self.worker.settings = self.settings()
        self.worker.commands.put(name)

    def poll(self):
        if self.closing:
            return
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
            self.poll_id = None
        self.worker.settings = self.settings()
        latest_frame = None
        while not self.worker.events.empty():
            kind, value = self.worker.events.get()
            if kind == "frame":
                latest_frame = value
            elif kind in ("device", "scan"):
                if kind == "device" or not self.worker.active:
                    self.device_status.configure(text=value)
            elif kind == "active":
                self.start_button.configure(state="disabled" if value else "normal")
                self.stop_button.configure(state="normal" if value else "disabled")
                self.hardware_state['active'] = value
                if self.device_dialog is not None and self.device_dialog.exists():
                    self.device_dialog.set_state(self.hardware_state)
            elif kind == 'hardware':
                self.hardware_state = value
                if self.device_dialog is not None and self.device_dialog.exists():
                    self.device_dialog.set_state(value)
            elif kind == 'hardware_notice':
                if self.device_dialog is not None and self.device_dialog.exists():
                    self.device_dialog.notice(value['text'], value['error'])
            elif kind == 'feedback_ready':
                self.feedback_busy = False
                if self.device_dialog is not None and self.device_dialog.exists():
                    self.device_dialog.feedback_button.configure(state='normal')
                    self.device_dialog.notice(value['text'], value['error'])
                if not value['error']:
                    try:
                        os.startfile(value['path'].parent)
                    except OSError:
                        logging.exception('Could not open feedback folder')
            elif kind == "error":
                logging.error(value)
                self.device_status.configure(text=value, wraplength=720)
                messagebox.showerror("HaloTruckDash", value, parent=self.root)
            elif kind == "layout_warning":
                self.device_status.configure(text=f"自定义布局无效，暂用默认布局1：{value}", wraplength=720)
        if latest_frame:
            truck, frame = latest_frame
            rgb = "#" + "".join(f"{v:02x}" for v in frame.color)
            font_size = min(40, max(18, int((self.canvas.winfo_width() - 30) / max(1, len(frame.text)) / .82)))
            self.canvas.itemconfigure(self.preview, text=frame.text, fill=rgb, font=("Consolas", font_size, "bold"))
            if truck.connected:
                gear = gear_text(truck, GEAR_MODES[self.gear_mode.get()])
                fuel = f"{truck.fuel_percent:.0f}%" if truck.fuel_percent is not None else "—"
                speed = convert_speed(abs(truck.speed), self.speed_unit.get())
                self.values.configure(text=f"车速 {speed:.0f} {self.speed_unit.get()}    挡位 {gear}    转速 {truck.rpm:.0f} rpm    燃油 {fuel}")
            else:
                self.values.configure(text="车速 —    挡位 —    转速 —    燃油 —")
            self.telemetry_status.configure(text=truck.reason + (" · " + frame.detail if frame.detail != truck.reason else ""))
        self.poll_id = self.root.after(100, self.poll)

    def browse(self):
        directory = filedialog.askdirectory(title="选择欧卡2或美卡游戏根目录", initialdir=self.game_dir.get())
        if directory:
            self.game_dirs[self._install_key] = self.game_dir.get()
            try:
                game = detect_game(directory)
                self._install_key = game.key
                self.install_target.set(game.label)
            except ValueError:
                pass
            self.game_dir.set(directory)
            self.game_dirs[self._install_key] = directory
            self.save_settings()

    def open_device_dialog(self, scan=True):
        if self.device_dialog is None or not self.device_dialog.exists():
            self.device_dialog = DeviceDialog(self.root, self.worker.commands.put, STATE, on_feedback=self.create_feedback)
        else:
            self.device_dialog.window.lift()
        self.device_dialog.set_state(self.hardware_state)
        self.device_dialog.feedback_button.configure(state='disabled' if self.feedback_busy else 'normal')
        if scan:
            self.device_dialog.refresh()
        return self.device_dialog

    def ui_exception(self, exc_type, value, traceback):
        record_ui_exception(exc_type, value, traceback)
        try:
            messagebox.showerror('HaloTruckDash', '界面操作发生异常，详情已记录。\n请打开“设备与诊断…”导出反馈包。', parent=self.root)
        except Exception:
            logging.exception('Could not show UI exception notice')

    def create_feedback(self):
        if self.feedback_busy:
            return
        self.feedback_busy = True
        if self.device_dialog is not None and self.device_dialog.exists():
            self.device_dialog.feedback_button.configure(state='disabled')
            self.device_dialog.status.configure(text='正在导出脱敏反馈包，不操作音响屏幕…')
        # Copy UI values here; the export thread never accesses Tk objects.
        try:
            options = self.settings()
        except Exception:
            logging.exception('Could not collect UI options for feedback')
            options = {}
        game_dirs = self.game_dirs.copy()
        game_dirs[self._install_key] = self.game_dir.get()
        runtime = getattr(self.worker, 'runtime', None)
        def collect():
            try:
                document = collect_diagnostics(STATE)
                path = export_feedback(STATE, document, runtime.snapshot() if runtime else {}, options,
                                       plugin_information(ASSETS, game_dirs))
                result = {'text': f'反馈包已导出：{path.name}。点击“反馈问题…”填写问题并手动附上ZIP。',
                          'path': path, 'error': False}
            except Exception as exc:
                logging.exception('Feedback export failed')
                result = {'text': f'反馈包导出失败：{exc}', 'error': True}
            self.worker.events.put(('feedback_ready', result))
        threading.Thread(target=collect, name='FeedbackExport', daemon=True).start()

    def install_target_changed(self, event=None):
        self.game_dirs[self._install_key] = self.game_dir.get()
        self._install_key = GAME_CHOICES[self.install_target.get()]
        self.game_dir.set(self.game_dirs[self._install_key])
        self.save_settings()

    def speed_unit_changed(self, event=None):
        self.worker.settings = self.settings()
        if self.editor is not None and self.editor.window.winfo_exists():
            self.editor.set_speed_unit(self.speed_unit.get())
        self.save_settings()

    def install(self):
        try:
            logging.info('Plugin installation requested game=%s', self._install_key)
            result = install_plugin(self.game_dir.get(), ASSETS / "assets" / "scs-telemetry.dll", expected_game=self._install_key)
            logging.info('Plugin installation checked successfully game=%s', self._install_key)
            self.save_settings()
            messagebox.showinfo("欧卡2 / 美卡遥测插件", result, parent=self.root)
        except PermissionError:
            logging.exception('Plugin installation permission denied')
            messagebox.showerror("无法写入游戏目录", "请关闭本程序，以管理员身份运行后再安装插件。", parent=self.root)
        except Exception as exc:
            logging.exception('Plugin installation failed')
            messagebox.showerror("插件安装失败", str(exc), parent=self.root)

    def edit_layout(self):
        if self.editor is not None and self.editor.window.winfo_exists():
            self.editor.set_speed_unit(self.speed_unit.get())
            self.editor.select_choice(self.mode.get())
            self.editor.window.lift()
            self.editor.window.focus_force()
            return self.editor
        def apply(model):
            self.custom_layout = validate_layout(model)
            choice = self.editor.current_choice()
            self.mode.set(choice or '默认布局1')
            self.worker.settings = self.settings()
            self.save_settings()
        try:
            _, model = self.layout_catalog.resolve(self.mode.get(), self.speed_unit.get())
        except (OSError, ValueError):
            model = self.custom_layout
        self.editor = GridEditor(self.root, model, apply, GEAR_MODES[self.gear_mode.get()], self.layout_library,
            on_library_change=self.refresh_layout_choices, current_name=self.mode.get(), speed_unit=self.speed_unit.get())
        return self.editor

    def help(self):
        messagebox.showinfo('使用说明',
            '1. 用数据USB线连接音响。首次使用，为对应游戏安装遥测插件，\n'
            '   重启游戏、接受SDK提示并进入驾驶。欧卡2和美卡需分别安装。\n'
            '2. 选择显示方案、速度单位和挡位模式，点击“开始同步到音响”。\n'
            '3. “停止并恢复屏幕”或正常退出会恢复原屏幕，异常退出后可点击\n'
            '   “恢复原屏幕”。同步期间仅由一个程序控制音响屏幕。\n\n'
            '布局编辑器：新建或编辑当前方案，中间30格可拖入控件、键入字符；\n'
            'Shift拖动框选，拖动已选内容可整体移动。保存并应用后启用。\n'
            '支持多个具名方案、JSON导入/导出及打开布局文件夹批量复制。\n'
            '切换速度单位后，自定义布局中手写的单位文字需自行修改。\n\n'
            '兼容性：本程序通过只读共享内存获取遥测；但其他仪表使用的\n'
            'SDK插件版本可能不同；当前版本已得到用户与SimHub共存实测反馈。\n'
            '安装器不会覆盖不同版本的同名插件，请勿直接删改其他软件插件。\n'
            '“设备与诊断”可发现未知PID候选接口，停止同步后验证并选用；\n'
            '验证只查询状态和文字，不改变显示；可导出不含序列号的诊断。\n'
            '遇到问题可“导出反馈包”，再点击“反馈问题…”手动附上ZIP；\n'
            '反馈包包含脱敏近期日志和运行统计，不会自动上传。\n'
            '切换欧卡/美卡前先退出上一款游戏。详细用法见同目录README.md；\n'
            f'设置、布局、日志和恢复记录目录：\n{STATE}', parent=self.root)

    def save_settings(self):
        STATE.mkdir(exist_ok=True)
        self.game_dirs[self._install_key] = self.game_dir.get()
        kind, key = self.layout_choices.get(self.mode.get(), ('preset', 1))
        atomic_json(STATE / 'settings.json', {
            'mode': self.mode.get(), 'color': self.color.get(), 'hz': self.hz.get(),
            'alerts': self.alerts.get(), 'game_dir': self.game_dir.get(),
            'custom': self.custom_layout, 'gear_mode': self.gear_mode.get(),
            'saved_layout': key if kind == 'saved' else None,
            'speed_unit': self.speed_unit.get(), 'install_target': self._install_key, 'game_dirs': self.game_dirs
        })

    def close(self):
        if self.closing:
            return
        self.closing = True
        logging.info('Application shutdown requested')
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
            self.poll_id = None
        self.root.title("正在恢复屏幕并退出…")
        try:
            self.save_settings()
        except Exception:
            logging.exception('Could not save preferences during shutdown')
        self.worker.commands.put("quit")
        self.wait_close()

    def wait_close(self):
        if self.worker.finished.is_set():
            self.root.destroy()
        else:
            self.root.after(100, self.wait_close)

def main():
    global STATE
    parser = argparse.ArgumentParser()
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--diagnose", action="store_true")
    commands.add_argument('--feedback', action='store_true', help='Export a local feedback ZIP without opening the UI')
    commands.add_argument("--ui-smoke", action="store_true", help="Open preview briefly; never writes hardware")
    args = parser.parse_args()
    # A smoke preview must neither contend with a driving session nor save
    # preferences into the interactive application's profile.
    preview_state = tempfile.TemporaryDirectory(prefix='halo-dashboard-preview-') if args.ui_smoke else None
    if preview_state is not None:
        STATE = Path(preview_state.name)
    else:
        STATE = data_directory(BASE)
    STATE.mkdir(exist_ok=True)
    configure_logging(STATE)
    install_exception_hooks()
    if args.feedback:
        path = export_feedback(STATE, collect_diagnostics(STATE), plugins=plugin_information(ASSETS, {}))
        logging.info('Command-line feedback export completed file=%s', path.name)
        return
    if args.diagnose:
        reader = Telemetry()
        try:
            registry = DeviceRegistry(STATE / 'validated-devices.json')
            atomic_json(STATE / 'diagnostics.json', diagnostics_document(registry, truck=reader.read()))
        finally:
            reader.close()
        return
    configure_windows_app()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    mutex_name = 'Local\\HaloTruckDash_preview' if args.ui_smoke else 'Local\\HaloTruckDash_v01'
    mutex = kernel.CreateMutexW(None, False, mutex_name)
    if ctypes.get_last_error() == 183:
        root = tk.Tk()
        root.withdraw()
        apply_icon(root, ASSETS / 'assets')
        messagebox.showinfo("HaloTruckDash", "程序已在运行，请切换到已有窗口。")
        root.destroy()
        kernel.CloseHandle(mutex)
        return
    try:
        root = tk.Tk()
        app = App(root)
        if args.ui_smoke:
            app.demo.set(True)
            root.after(350, app.edit_layout)
            root.after(650, lambda: app.open_device_dialog(scan=False))
            root.after(1500, app.close)
        root.mainloop()
    finally:
        logging.info('Session ended')
        if mutex:
            kernel.CloseHandle(mutex)
        if preview_state is not None:
            logging.shutdown()
            preview_state.cleanup()
