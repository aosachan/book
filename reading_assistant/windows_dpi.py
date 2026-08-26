from __future__ import annotations

import ctypes


def enable_per_monitor_dpi_awareness() -> None:
    """Use physical desktop coordinates consistently across Win32, Tk and PIL."""

    if not hasattr(ctypes, "windll"):
        return
    user32 = ctypes.windll.user32
    try:
        setter = user32.SetProcessDpiAwarenessContext
        setter.argtypes = [ctypes.c_void_p]
        setter.restype = ctypes.c_bool
        if setter(ctypes.c_void_p(-4)):  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            return
    except (AttributeError, OSError):
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) in (0, -2147024891):
            return
    except (AttributeError, OSError):
        pass
    try:
        user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass
