from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable


CHATGPT_BUNDLE_NAME = "all_chapter_notes_for_chatgpt.md"


def chapter_note_paths(chapters: Iterable[dict[str, Any]]) -> list[Path]:
    """Return existing persisted chapter Markdown files in reading order."""

    ordered = sorted(chapters, key=lambda item: int(item.get("chapter_index", 0)))
    paths: list[Path] = []
    missing: list[str] = []
    for chapter in ordered:
        raw_path = str(chapter.get("markdown_path", "")).strip()
        path = Path(raw_path) if raw_path else None
        if path is None or not path.is_file():
            missing.append(f"第{chapter.get('chapter_index', '?')}章")
        else:
            paths.append(path)
    if missing:
        raise FileNotFoundError(
            "章メモのMarkdownが見つかりません: " + "、".join(missing)
        )
    if not paths:
        raise ValueError("保存済みの章メモがありません。")
    return paths


def combine_chapter_notes(chapters: Iterable[dict[str, Any]]) -> Path:
    """Combine chapter files verbatim, adding only Markdown separators."""

    paths = chapter_note_paths(chapters)
    contents = [path.read_text(encoding="utf-8").rstrip() for path in paths]
    destination = paths[0].parent / CHATGPT_BUNDLE_NAME
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text("\n\n---\n\n".join(contents) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return destination
