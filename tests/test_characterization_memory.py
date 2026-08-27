from __future__ import annotations

import base64
import gzip
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from reading_assistant.memory import ReadingMemory
from reading_assistant.models import (
    ChapterCheckpoint,
    ChunkSummary,
    PageAnalysis,
    PageRecord,
    Rect,
    WindowInfo,
)


class ExistingSessionCharacterizationTests(unittest.TestCase):
    def test_current_version_fixed_sqlite_fixture_remains_resumable(self) -> None:
        fixture_path = (
            Path(__file__).parent
            / "fixtures"
            / "current_version_session.sqlite3.gz.b64"
        )
        compressed = base64.b64decode(
            "".join(fixture_path.read_text(encoding="ascii").split())
        )
        database_bytes = gzip.decompress(compressed)
        self.assertTrue(database_bytes.startswith(b"SQLite format 3\x00"))
        self.assertEqual(len(database_bytes), 110592)
        self.assertEqual(
            hashlib.sha256(database_bytes).hexdigest(),
            "5e0a6fe962eeb21394c39f1e1972a8fc50bc84130aae621c0311bcbba7c2edcc",
        )

        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "current-version-fixture.sqlite3"
            database_path.write_bytes(database_bytes)
            memory = ReadingMemory(database_path)
            try:
                session = memory.get_session(1)
                self.assertEqual(session["title"], "固定SQLite fixture v1")
                self.assertEqual(session["status"], "paused")
                self.assertEqual(session["quality"], "BALANCED")
                self.assertEqual(session["chunk_size"], 20)
                self.assertEqual(session["read_pages"], 1)
                self.assertEqual(session["last_integrated_page"], 1)
                self.assertNotIn("api_key", session["settings"])
                self.assertEqual(
                    session["capture"]["capture_rect"],
                    {"left": 40, "top": 60, "right": 760, "bottom": 940},
                )
                self.assertEqual(memory.next_page_index(1), 2)
                self.assertEqual(memory.next_capture_index(1), 2)
                self.assertEqual(memory.last_page_hash(1), "fixture-page-hash-001")

                context = memory.recent_context(1)
                self.assertEqual(context["recent_pages"], [])
                self.assertEqual(context["recent_chunks"], [])
                self.assertEqual(context["last_chapter_checkpoint"]["end_page"], 1)
                self.assertEqual(
                    context["last_chapter_checkpoint"]["carryover"]["immediate_situation"],
                    "ミナが時計の記録を発見し、調査を始めた直後。",
                )
                self.assertEqual(context["current_character_states"][0]["name"], "ミナ")

                material = memory.all_semantic_material(1)
                self.assertEqual(len(material["page_notes"]), 1)
                self.assertEqual(len(material["chunk_summaries"]), 1)
                self.assertEqual(len(material["chapter_summaries"]), 1)
                self.assertEqual(material["user_notes"][0]["note"], "時計の時刻に注目")
            finally:
                memory.close()

    def test_existing_sqlite_copy_resumes_with_the_same_semantic_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_path = root / "original.sqlite3"
            copied_path = root / "existing-session-copy.sqlite3"

            memory = ReadingMemory(original_path)
            session_id = memory.create_session(
                "再開テスト用の自作物語",
                300,
                "BALANCED",
                20,
                {
                    "base_url": "http://127.0.0.1:11434/v1",
                    "model": "qwen3.5:9b",
                    "quality": "BALANCED",
                    "api_key": "must-not-be-persisted",
                },
            )
            window = WindowInfo(1234, "Sample Reader", Rect(10, 20, 650, 920), 5678)
            capture = Rect(30, 50, 620, 880)
            memory.set_capture(session_id, window, capture)

            for page_index in (1, 2):
                memory.record_page(
                    session_id,
                    PageRecord(
                        analysis=PageAnalysis(
                            page_index=page_index,
                            short_summary=f"ミナが記録{page_index}を確認した。",
                            confidence=0.9,
                            readability=0.95,
                            important_score=0.7,
                        ),
                        page_hash=f"hash-{page_index}",
                        capture_index=page_index,
                        processing_seconds=float(page_index),
                        retry_count=1 if page_index == 2 else 0,
                        json_failed_once=page_index == 2,
                        user_important=page_index == 2,
                    ),
                    user_note="この反応に注目" if page_index == 2 else "",
                )

            memory.save_chunk(
                session_id,
                ChunkSummary(
                    chunk_index=1,
                    start_page=1,
                    end_page=2,
                    summary={
                        "range_events": ["ミナが二つの記録を比較した"],
                        "character_states": [
                            {
                                "name": "ミナ",
                                "current_goal": "記録の矛盾を調べる",
                                "changed_from_previous": "矛盾を発見したため",
                            }
                        ],
                        "predictions_at_this_point": [
                            {
                                "text": "記録が意図的に改変された可能性",
                                "evidence_level": "SPECULATION",
                                "confidence": 0.45,
                            }
                        ],
                        "unresolved_items": ["誰が記録を変えたのか"],
                    },
                ),
            )
            memory.save_chapter(
                session_id,
                ChapterCheckpoint(
                    chapter_index=1,
                    start_page=1,
                    end_page=2,
                    summary={
                        "chapter_label": "記録の矛盾",
                        "detailed_summary": "ミナが二つの記録を比較し、時刻の不一致を確認した。",
                        "event_timeline": ["ミナが二つの記録を比較した"],
                        "new_facts": ["二つの記録の時刻が一致しない"],
                    },
                    carryover={
                        "active_characters": [
                            {
                                "character_id": "character_001",
                                "name": "ミナ",
                                "state": "記録の矛盾を調査中",
                            }
                        ],
                        "unresolved_clues": [
                            {"clue_id": "clue_001", "text": "記録時刻の不一致"}
                        ],
                        "open_questions": [
                            {"question_id": "question_001", "text": "誰が記録を変えたのか"}
                        ],
                        "immediate_situation": "ミナが時刻の不一致を確認した直後。",
                    },
                ),
                "reports/chapter_001.md",
            )
            memory.update_status(session_id, "paused")
            memory.close()

            shutil.copy2(original_path, copied_path)
            resumed = ReadingMemory(copied_path)
            try:
                session = resumed.get_session(session_id)
                self.assertEqual(session["title"], "再開テスト用の自作物語")
                self.assertEqual(session["status"], "paused")
                self.assertEqual(session["read_pages"], 2)
                self.assertEqual(session["last_integrated_page"], 2)
                self.assertEqual(
                    session["settings"],
                    {
                        "base_url": "http://127.0.0.1:11434/v1",
                        "model": "qwen3.5:9b",
                        "quality": "BALANCED",
                    },
                )
                self.assertEqual(
                    session["capture"],
                    {
                        "window_handle": 1234,
                        "window_title": "Sample Reader",
                        "window_process_id": 5678,
                        "capture_rect": {
                            "left": 30,
                            "top": 50,
                            "right": 620,
                            "bottom": 880,
                        },
                    },
                )

                self.assertEqual(resumed.next_page_index(session_id), 3)
                self.assertEqual(resumed.next_capture_index(session_id), 3)
                self.assertEqual(resumed.last_page_hash(session_id), "hash-2")

                metrics = resumed.metrics(session_id)
                self.assertEqual(
                    {
                        "read_pages": metrics["read_pages"],
                        "retries": metrics["retries"],
                        "json_failures": metrics["json_failures"],
                        "chunks": metrics["chunks"],
                        "chapters": metrics["chapters"],
                        "last_integrated_page": metrics["last_integrated_page"],
                    },
                    {
                        "read_pages": 2,
                        "retries": 1,
                        "json_failures": 1,
                        "chunks": 1,
                        "chapters": 1,
                        "last_integrated_page": 2,
                    },
                )

                context = resumed.recent_context(session_id)
                self.assertEqual(context["recent_pages"], [])
                self.assertEqual(context["recent_chunks"], [])
                self.assertEqual(context["last_chapter_checkpoint"]["end_page"], 2)
                self.assertEqual(
                    context["last_chapter_checkpoint"]["carryover"]["immediate_situation"],
                    "ミナが時刻の不一致を確認した直後。",
                )
                self.assertEqual(context["current_character_states"][0]["name"], "ミナ")

                material = resumed.all_semantic_material(session_id)
                self.assertEqual(len(material["page_notes"]), 2)
                self.assertEqual(len(material["chunk_summaries"]), 1)
                self.assertEqual(len(material["chapter_summaries"]), 1)
                self.assertEqual(
                    [(note["page_index"], note["note"]) for note in material["user_notes"]],
                    [(2, "この反応に注目")],
                )
                self.assertNotIn("capture", material["session"])
                self.assertNotIn("api_key", material["session"]["settings"])
            finally:
                resumed.close()


if __name__ == "__main__":
    unittest.main()

