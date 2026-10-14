"""Size windows for their content and monitor's usable desktop."""
import ctypes
from ctypes import wintypes

def work_area(window):
    fallback = (0, 0, window.winfo_screenwidth(), window.winfo_screenheight())
    try:
        class MonitorInfo(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                        ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user.MonitorFromWindow.restype = wintypes.HANDLE
        user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        user.GetMonitorInfoW.restype = wintypes.BOOL
        monitor = user.MonitorFromWindow(window.winfo_id(), 2)
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if monitor and user.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return info.work.left, info.work.top, info.work.right, info.work.bottom
    except (AttributeError, OSError):
        pass
    return fallback

def fit_main(window):
    # Text height grows with Windows/Tk scaling, while a fixed geometry does
    # not. Include the footer's requested height before choosing a minimum.
    window.update_idletasks()
    left, top, right, bottom = work_area(window)
    available_width = max(320, right - left - 32)
    available_height = max(300, bottom - top - 64)
    minimum_width = min(available_width, max(730, window.winfo_reqwidth()))
    minimum_height = min(available_height, max(650, window.winfo_reqheight()))
    width = min(available_width, max(780, minimum_width))
    height = min(available_height, max(660, minimum_height))
    window.minsize(minimum_width, minimum_height)
    window.geometry(f'{width}x{height}')


def fit_editor(window):
    left, top, right, bottom = work_area(window)
    width = min(1320, max(320, right - left - 32))
    height = min(660, max(300, bottom - top - 64))
    window.minsize(min(1100, width), min(420, height))
    x = left + (right - left - width) // 2
    y = top + max(8, (bottom - top - height) // 2 - 16)
    window.geometry(f'{width}x{height}{x:+d}{y:+d}')
