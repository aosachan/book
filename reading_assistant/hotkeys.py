from __future__ import annotations

import ctypes
import tkinter as tk
from ctypes import wintypes
from typing import Callable


class GlobalReadHotkey:
    HOTKEY_ID = 0x4A31
    WM_HOTKEY = 0x0312
    PM_REMOVE = 0x0001

    def __init__(self, root: tk.Misc, callback: Callable[[], None]) -> None:
        self.root = root
        self.callback = callback
        self.user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
        self.registered = False
        self._after_id: str | None = None

    def register(self) -> bool:
        if self.user32 is None:
            return False
        # MOD_NOREPEAT | MOD_CONTROL | MOD_SHIFT, R
        self.registered = bool(self.user32.RegisterHotKey(None, self.HOTKEY_ID, 0x4000 | 0x0002 | 0x0004, ord("R")))
        if self.registered:
            self._poll()
        return self.registered

    def unregister(self) -> None:
        if self._after_id:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        if self.registered and self.user32 is not None:
            self.user32.UnregisterHotKey(None, self.HOTKEY_ID)
        self.registered = False

    def _poll(self) -> None:
        if not self.registered:
            return
        message = wintypes.MSG()
        while self.user32.PeekMessageW(ctypes.byref(message), None, self.WM_HOTKEY, self.WM_HOTKEY, self.PM_REMOVE):
            if int(message.wParam) == self.HOTKEY_ID:
                self.callback()
        self._after_id = self.root.after(100, self._poll)

