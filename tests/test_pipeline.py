from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reading_assistant.analyzer import PageAnalyzer
from reading_assistant.config import AppConfig
from reading_assistant.integrator import ChunkIntegrator
from reading_assistant.memory import ReadingMemory
from reading_assistant.models import Rect, WindowInfo
from reading_assistant.orchestrator import ReaderCallbacks, ReadingOrchestrator
from reading_assistant.reports import REPORT_FILES, ReportGenerator
from tests.fakes import FakeController, FakeLLMClient, SequenceFrameSource, sample_image


class PipelineTests(unittest.TestCase):
    def test_twenty_pages_chunk_resume_and_reports(self) -> None:
        images = [sample_image(index) for index in range(1, 21)]
        source = SequenceFrameSource(images)
        for image in images:
            image.close()
        fake = FakeLLMClient()
        config = AppConfig(chunk_size=20, spread_mode="1ページ", total_pages=20)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            memory = ReadingMemory(root / "memory.sqlite3")
            orchestrator = ReadingOrchestrator(
                config,
                memory,
                source,
                PageAnalyzer(fake),
                ChunkIntegrator(fake),
                ReportGenerator(fake),
                FakeController(),
                root / "reports",
                ReaderCallbacks(preview=lambda image: image.close() if image else None),
            )
            session_id = orchestrator.new_session("二十頁の自作物語", 20)
            window = WindowInfo(1, "Sample Reader", Rect(0, 0, 640, 900))
            orchestrator.set_capture_target(window, window.rect)
            orchestrator.start()
            for page in range(20):
                records = orchestrator.read_current_page(user_note="注目" if page == 4 else "")
                self.assertEqual(len(records), 1)
            metrics = memory.metrics(session_id)
            self.assertEqual(metrics["read_pages"], 20)
            self.assertEqual(metrics["chunks"], 1)
            self.assertEqual(metrics["last_integrated_page"], 20)
            self.assertEqual(len(memory.recent_context(session_id)["current_character_states"]), 1)
            self.assertGreaterEqual(len(memory.recent_context(session_id)["prediction_history_tail"]), 1)

            resumed = ReadingOrchestrator(
                config,
                memory,
                source,
                PageAnalyzer(fake),
                ChunkIntegrator(fake),
                ReportGenerator(fake),
                FakeController(),
                root / "reports",
            )
            resumed.resume_session(session_id)
            self.assertEqual(memory.next_page_index(session_id), 21)
            report_dir = resumed.finalize()
            for filename in REPORT_FILES.values():
                path = report_dir / filename
                self.assertTrue(path.exists(), filename)
                self.assertGreater(path.stat().st_size, 20)
            memory.close()
        source.close()


if __name__ == "__main__":
    unittest.main()

