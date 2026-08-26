from __future__ import annotations

import tkinter as tk
from pathlib import Path

from PIL import Image, ImageTk


class SampleReader:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("LRA Sample Reader — 自作テスト文章")
        self.root.geometry("720x900+40+40")
        self.paths = sorted((Path(__file__).resolve().parents[1] / "samples" / "generated").glob("page_*.png"))
        if not self.paths:
            raise SystemExit("先に tools/generate_sample_book.py を実行してください。")
        self.index = 0
        self.photo = None
        self.label = tk.Label(root, bg="#222")
        self.label.pack(fill="both", expand=True)
        self.status = tk.Label(root, text="", anchor="w", padx=10)
        self.status.pack(fill="x")
        root.bind("<Right>", lambda _: self.next())
        root.bind("<Left>", lambda _: self.previous())
        root.bind("<Prior>", lambda _: self.previous())
        root.bind("<Next>", lambda _: self.next())
        self.show()

    def show(self) -> None:
        self.root.title(f"LRA Sample Reader — 自作テスト文章 — page {self.index + 1}")
        image = Image.open(self.paths[self.index]).convert("RGB")
        image.thumbnail((680, 820), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image)
        image.close()
        self.label.configure(image=self.photo)
        self.status.configure(text=f"自作サンプル  {self.index + 1} / {len(self.paths)}   ← → でページ送り")

    def next(self) -> None:
        if self.index < len(self.paths) - 1:
            self.index += 1
            self.show()

    def previous(self) -> None:
        if self.index > 0:
            self.index -= 1
            self.show()


if __name__ == "__main__":
    root = tk.Tk()
    SampleReader(root)
    root.mainloop()
