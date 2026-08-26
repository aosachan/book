from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reading_assistant.analyzer import PageAnalyzer
from reading_assistant.config import AppConfig
from reading_assistant.integrator import ChunkIntegrator
from reading_assistant.memory import ReadingMemory
from reading_assistant.models import Rect, WindowInfo
from reading_assistant.orchestrator import ReadingOrchestrator
from reading_assistant.prompts import compact_page_context
from reading_assistant.reports import ReportGenerator
from tests.fakes import FakeController, FakeLLMClient, SequenceFrameSource, sample_image


class ChapterCheckpointTests(unittest.TestCase):
    def test_manual_chapter_close_saves_review_and_resets_only_active_context(self) -> None:
        images = [sample_image(index) for index in range(1, 6)]
        source = SequenceFrameSource(images)
        for image in images:
            image.close()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            memory = ReadingMemory(root / "memory.sqlite3")
            client = FakeLLMClient()
            config = AppConfig(chunk_size=20, spread_mode="1ページ", total_pages=300)
            orchestrator = ReadingOrchestrator(
                config,
                memory,
                source,
                PageAnalyzer(client),
                ChunkIntegrator(client),
                ReportGenerator(client),
                FakeController(),
                root / "reports",
            )
            session_id = orchestrator.new_session("章区切り用の自作物語", 300)
            window = WindowInfo(1, "Sample", Rect(0, 0, 640, 900))
            orchestrator.set_capture_target(window, window.rect)
            orchestrator.start()
            for _ in range(5):
                orchestrator.read_current_page()

            chapter_path = orchestrator.close_chapter()
            self.assertTrue(chapter_path.exists())
            chapter_text = chapter_path.read_text(encoding="utf-8")
            self.assertIn("出来事タイムライン", chapter_text)
            self.assertIn("新しく判明した事実", chapter_text)
            self.assertIn("ミナが複数の記録時刻を比較した", chapter_text)
            self.assertEqual(len(memory.page_notes(session_id)), 5)
            self.assertEqual(len(memory.chapter_summaries(session_id)), 1)

            context = memory.recent_context(session_id)
            self.assertEqual(context["recent_pages"], [])
            self.assertEqual(context["recent_chunks"], [])
            self.assertEqual(
                context["last_chapter_checkpoint"]["end_page"], 5
            )
            compact = compact_page_context(context)
            self.assertIn("previous_chapter_carryover", compact)
            self.assertIn("active_characters", compact["previous_chapter_carryover"])
            self.assertIn("immediate_situation", compact["previous_chapter_carryover"])

            memory.close()
            memory = ReadingMemory(root / "memory.sqlite3")
            resumed = memory.recent_context(session_id)
            self.assertEqual(resumed["last_chapter_checkpoint"]["end_page"], 5)
            self.assertEqual(memory.next_page_index(session_id), 6)
            memory.close()
        source.close()


if __name__ == "__main__":
    unittest.main()
