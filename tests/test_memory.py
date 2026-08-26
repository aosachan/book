from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from reading_assistant.memory import ReadingMemory, sanitize_semantic_payload
from reading_assistant.models import PageAnalysis, PageRecord


class MemoryTests(unittest.TestCase):
    def test_persists_semantic_note_and_resumes_without_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "memory.sqlite3"
            memory = ReadingMemory(db_path)
            session_id = memory.create_session("自作物語", 10, "BALANCED", 20, {"api_key": "secret"})
            analysis = PageAnalysis(page_index=1, short_summary="主人公が灯台へ向かう。", confidence=0.9)
            memory.record_page(session_id, PageRecord(analysis, "abc123", 1), "ここで驚いた")
            self.assertEqual(memory.next_page_index(session_id), 2)
            self.assertEqual(memory.get_session(session_id)["settings"].get("api_key"), None)
            memory.close()

            raw = sqlite3.connect(db_path)
            dump = "\n".join(raw.iterdump())
            raw.close()
            self.assertNotIn("page_image", dump)
            self.assertNotIn("secret", dump)
            self.assertIn("主人公が灯台へ向かう", dump)

    def test_forbidden_payload_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_semantic_payload({"ocr_text": "本文"})
        with self.assertRaises(ValueError):
            sanitize_semantic_payload({"image_bytes": b"binary"})


if __name__ == "__main__":
    unittest.main()

