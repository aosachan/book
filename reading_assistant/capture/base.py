from __future__ import annotations

from typing import Protocol

from PIL import Image

from ..models import Rect, WindowInfo


class FrameSource(Protocol):
    """Replaceable boundary for future browser/remote capture implementations."""

    def capture(self, rect: Rect) -> Image.Image:
        """Return the pixels currently visible in rect; callers must release it."""


class WindowProvider(Protocol):
    def list_windows(self) -> list[WindowInfo]: ...

    def get_window_rect(self, handle: int) -> Rect: ...

