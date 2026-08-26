from __future__ import annotations

import ctypes
from ctypes import wintypes

from PIL import Image, ImageGrab

from ..errors import CaptureError
from ..models import Rect, WindowInfo


user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


if user32 is not None:
    # ctypes otherwise assumes a 32-bit int return value. HMONITOR is
    # pointer-sized, so that default can truncate the handle on 64-bit Windows.
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL


class WindowsWindowProvider:
    def list_windows(self) -> list[WindowInfo]:
        if user32 is None:
            return []
        windows: list[WindowInfo] = []
        enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd: int, _: int) -> bool:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            title_buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buffer, length + 1)
            title = title_buffer.value.strip()
            if not title:
                return True
            rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            if rect.right - rect.left < 120 or rect.bottom - rect.top < 100:
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            windows.append(
                WindowInfo(
                    handle=int(hwnd),
                    title=title,
                    rect=Rect(rect.left, rect.top, rect.right, rect.bottom),
                    process_id=int(pid.value),
                )
            )
            return True

        callback_ref = enum_proc_type(callback)
        user32.EnumWindows(callback_ref, 0)
        windows.sort(key=lambda item: item.title.casefold())
        return windows

    def get_window_rect(self, handle: int) -> Rect:
        if user32 is None or not user32.IsWindow(handle):
            raise CaptureError("対象ウィンドウが見つかりません。")
        rect = wintypes.RECT()
        if not user32.GetWindowRect(handle, ctypes.byref(rect)):
            raise CaptureError("対象ウィンドウの位置を取得できません。")
        return Rect(rect.left, rect.top, rect.right, rect.bottom)

    def get_monitor_rect(self, handle: int) -> Rect:
        if user32 is None or not user32.IsWindow(handle):
            raise CaptureError("対象ウィンドウが見つかりません。")
        monitor = user32.MonitorFromWindow(handle, 2)  # MONITOR_DEFAULTTONEAREST
        if not monitor:
            raise CaptureError("対象ウィンドウのモニターを取得できません。")
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            raise CaptureError("モニター領域を取得できません。")
        rect = info.rcMonitor
        return Rect(rect.left, rect.top, rect.right, rect.bottom)


class WindowsScreenCapture:
    """Captures only normal, currently rendered desktop pixels.

    It deliberately does not use PrintWindow, app internals, DRM APIs, or any
    attempt to bypass capture protection.
    """

    def capture(self, rect: Rect) -> Image.Image:
        rect.validate()
        try:
            image = ImageGrab.grab(
                bbox=(rect.left, rect.top, rect.right, rect.bottom),
                all_screens=True,
            )
        except Exception as exc:  # Pillow maps several Win32 failures here.
            raise CaptureError(f"画面を取得できません: {exc}") from exc
        return image.convert("RGB")
