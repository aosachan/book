from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .models import Rect


class RegionSelector:
    def __init__(
        self,
        parent: tk.Misc,
        bounds: Rect,
        allowed_bounds: Rect | None = None,
    ) -> None:
        self.parent = parent
        self.bounds = bounds
        self.allowed_bounds = allowed_bounds or bounds
        self.result: Rect | None = None
        self.start: tuple[int, int] | None = None
        self.rectangle_id: int | None = None

    def select(self) -> Rect | None:
        overlay = tk.Toplevel(self.parent)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.38)
        overlay.configure(bg="#07111f")
        overlay.geometry(_geometry(self.bounds))
        canvas = tk.Canvas(overlay, bg="#07111f", highlightthickness=2, highlightbackground="#43d9ad", cursor="crosshair")
        canvas.pack(fill="both", expand=True)
        instruction_id = canvas.create_text(
            24,
            22,
            anchor="nw",
            fill="white",
            font=("Yu Gothic UI", 12, "bold"),
            text="本文だけをドラッグで囲んでください  •  Escでキャンセル",
        )

        def local_point(event: tk.Event) -> tuple[int, int]:
            return (
                min(self.bounds.width, max(0, int(event.x))),
                min(self.bounds.height, max(0, int(event.y))),
            )

        def press(event: tk.Event) -> None:
            x, y = local_point(event)
            self.start = (x, y)
            canvas.itemconfigure(
                instruction_id,
                text="本文だけをドラッグで囲んでください  •  Escでキャンセル",
                fill="white",
            )
            if self.rectangle_id:
                canvas.delete(self.rectangle_id)
            self.rectangle_id = canvas.create_rectangle(
                x,
                y,
                x,
                y,
                outline="#43d9ad",
                width=3,
                fill="#ffffff",
                stipple="gray25",
            )

        def drag(event: tk.Event) -> None:
            if self.start and self.rectangle_id:
                x, y = local_point(event)
                canvas.coords(
                    self.rectangle_id,
                    self.start[0],
                    self.start[1],
                    x,
                    y,
                )

        def release(event: tk.Event) -> None:
            if not self.start:
                return
            end_x, end_y = local_point(event)
            left, right = sorted((self.start[0], end_x))
            top, bottom = sorted((self.start[1], end_y))
            candidate = Rect(
                self.bounds.left + left,
                self.bounds.top + top,
                self.bounds.left + right,
                self.bounds.top + bottom,
            )
            candidate = intersection(candidate, self.allowed_bounds)
            try:
                if candidate is None:
                    raise ValueError("対象外")
                candidate.validate()
            except ValueError:
                self.start = None
                if self.rectangle_id:
                    canvas.delete(self.rectangle_id)
                    self.rectangle_id = None
                canvas.itemconfigure(
                    instruction_id,
                    text="対象ウィンドウ内を80px以上の大きさで囲んでください",
                    fill="#ffb454",
                )
                return
            self.result = candidate
            close()

        def close() -> None:
            try:
                overlay.grab_release()
            except tk.TclError:
                pass
            overlay.destroy()

        canvas.bind("<ButtonPress-1>", press)
        canvas.bind("<B1-Motion>", drag)
        canvas.bind("<ButtonRelease-1>", release)
        overlay.bind("<Escape>", lambda _: close())
        overlay.protocol("WM_DELETE_WINDOW", close)
        overlay.update_idletasks()
        overlay.wait_visibility()
        overlay.lift()
        overlay.grab_set()
        overlay.focus_force()
        self.parent.wait_window(overlay)
        return self.result


def _geometry(bounds: Rect) -> str:
    x = f"+{bounds.left}" if bounds.left >= 0 else str(bounds.left)
    y = f"+{bounds.top}" if bounds.top >= 0 else str(bounds.top)
    return f"{bounds.width}x{bounds.height}{x}{y}"


def left_half(bounds: Rect) -> Rect:
    """Return the left half of a monitor rectangle."""
    midpoint = bounds.left + bounds.width // 2
    result = Rect(bounds.left, bounds.top, midpoint, bounds.bottom)
    result.validate()
    return result


def intersection(first: Rect, second: Rect) -> Rect | None:
    result = Rect(
        max(first.left, second.left),
        max(first.top, second.top),
        min(first.right, second.right),
        min(first.bottom, second.bottom),
    )
    return result if result.width > 0 and result.height > 0 else None
