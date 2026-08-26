from __future__ import annotations

import ctypes
import time

from .errors import CaptureError


VK_CODES = {
    "Left": 0x25,
    "Up": 0x26,
    "Right": 0x27,
    "Down": 0x28,
    "PageUp": 0x21,
    "PageDown": 0x22,
    "Space": 0x20,
}


class WindowsWindowController:
    """Sends an ordinary user-level key; it does not call target app APIs."""

    def __init__(self) -> None:
        self.user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None

    def activate(self, handle: int) -> None:
        if self.user32 is None or not self.user32.IsWindow(handle):
            raise CaptureError("対象ウィンドウが閉じられています。")
        # Restore only minimized windows. Calling SW_RESTORE unconditionally
        # also unmaximizes a window to its previous left/right snap position.
        if self.user32.IsIconic(handle):
            self.user32.ShowWindow(handle, 9)  # SW_RESTORE
        if not self.user32.SetForegroundWindow(handle):
            raise CaptureError("対象ウィンドウを前面にできません。手動で選択して再試行してください。")

    def send_page_key(self, handle: int, key_name: str) -> None:
        if key_name not in VK_CODES:
            raise ValueError(f"未対応のページ送りキー: {key_name}")
        self.activate(handle)
        time.sleep(0.08)
        virtual_key = VK_CODES[key_name]
        self.user32.keybd_event(virtual_key, 0, 0, 0)
        self.user32.keybd_event(virtual_key, 0, 0x0002, 0)  # KEYEVENTF_KEYUP
