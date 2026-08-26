from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reading_assistant.chapter_export import (
    CHATGPT_BUNDLE_NAME,
    chapter_note_paths,
    combine_chapter_notes,
)


class ChapterExportTests(unittest.TestCase):
    def test_opens_in_reading_order_and_combines_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            first = folder / "chapter_001.md"
            second = folder / "chapter_002.md"
            first_text = "# 第一章\n\n途中予想A\n"
            second_text = "# 第二章\n\n解釈修正B\n"
            first.write_text(first_text, encoding="utf-8")
            second.write_text(second_text, encoding="utf-8")
            chapters = [
                {"chapter_index": 2, "markdown_path": str(second)},
                {"chapter_index": 1, "markdown_path": str(first)},
            ]

            self.assertEqual(chapter_note_paths(chapters), [first, second])
            combined = combine_chapter_notes(chapters)

            self.assertEqual(combined.name, CHATGPT_BUNDLE_NAME)
            self.assertEqual(
                combined.read_text(encoding="utf-8"),
                first_text.rstrip() + "\n\n---\n\n" + second_text.rstrip() + "\n",
            )

    def test_missing_chapter_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.md"
            with self.assertRaisesRegex(FileNotFoundError, "第3章"):
                chapter_note_paths(
                    [{"chapter_index": 3, "markdown_path": str(missing)}]
                )


if __name__ == "__main__":
    unittest.main()
