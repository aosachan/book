"""Local Reading Assistant.

Only semantic notes are persisted. Source page images remain in memory while a
page is being processed and are then released.
"""

__version__ = "0.1.0"
from .windows_dpi import enable_per_monitor_dpi_awareness


enable_per_monitor_dpi_awareness()
