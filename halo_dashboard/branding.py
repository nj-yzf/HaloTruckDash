"""Windows taskbar grouping and application/window icons."""
import ctypes
import logging
from pathlib import Path
import tkinter as tk


def configure_windows_app():
    try:
        shell = ctypes.WinDLL('shell32')
        shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
        shell.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        shell.SetCurrentProcessExplicitAppUserModelID('HaloTruckDash.Desktop')
    except (AttributeError, OSError):
        logging.debug('Taskbar application identity unavailable', exc_info=True)


def apply_icon(window, assets):
    try:
        window.iconbitmap(str(Path(assets) / 'HaloTruckDash.ico'))
        window.iconbitmap(default=str(Path(assets) / 'HaloTruckDash.ico'))
    except (OSError, tk.TclError):
        logging.debug('Application icon unavailable', exc_info=True)
