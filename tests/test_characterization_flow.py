from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from reading_assistant.analyzer import PageAnalyzer
from reading_assistant.config import AppConfig
from reading_assistant.errors import DuplicatePageError, ProtectedCaptureError
from reading_assistant.integrator import ChunkIntegrator
from reading_assistant.memory import ReadingMemory
from reading_assistant.models import Rect, WindowInfo
from reading_assistant.orchestrator import ReaderCallbacks, ReaderState, ReadingOrchestrator
from reading_assistant.reports import REPORT_FILES, ReportGenerator
from tests.fakes import FakeController, FakeLLMClient, SequenceFrameSource, sample_image


def _error_callbacks(events: list[tuple[str, object]]) -> ReaderCallbacks:
    def preview(image: Image.Image | None) -> None:
        if image is None:
            events.append(("preview", None))
            return
        events.append(("preview", image.size))
        image.close()

    return ReaderCallbacks(
        status=lambda message: events.append(("status", message)),
        warning=lambda message: events.append(("warning", message)),
        preview=preview,
        metrics=lambda metrics: events.append(
            (
                "metrics",
                (
                    metrics["read_pages"],
                    metrics["duplicate_pages"],
                    metrics["failed_pages"],
                ),
            )
        ),
    )


class PagePipelineCharacterizationTests(unittest.TestCase):
    def test_success_callbacks_keep_the_current_order_and_payload_shape(self) -> None:
        original = sample_image(1)
        source = SequenceFrameSource([original])
        original.close()
        events: list[tuple[str, object]] = []

        def preview(image: Image.Image | None) -> None:
            if image is None:
                events.append(("preview", None))
                return
            events.append(("preview", image.size))
            image.close()

        callbacks = ReaderCallbacks(
            status=lambda message: events.append(("status", message)),
            warning=lambda message: events.append(("warning", message)),
            preview=preview,
            page=lambda record: events.append(("page", record.analysis.page_index)),
            chunk=lambda summary: events.append(("chunk", summary)),
            metrics=lambda metrics: events.append(("metrics", metrics["read_pages"])),
            understanding=lambda context: events.append(
                ("understanding", len(context["recent_pages"]))
            ),
            calibration=lambda metrics: events.append(("calibration", metrics)),
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            memory = ReadingMemory(root / "memory.sqlite3")
            fake = FakeLLMClient()
            orchestrator = ReadingOrchestrator(
                AppConfig(chunk_size=20, spread_mode="1ページ", total_pages=1),
                memory,
                source,
                PageAnalyzer(fake),
                ChunkIntegrator(fake),
                ReportGenerator(fake),
                FakeController(),
                root / "reports",
                callbacks,
            )
            orchestrator.new_session("一頁の自作物語", 1)
            window = WindowInfo(1, "Sample Reader", Rect(0, 0, 640, 900))
            orchestrator.set_capture_target(window, window.rect)
            orchestrator.start()

            events.clear()
            records = orchestrator.read_current_page()

            self.assertEqual(len(records), 1)
            self.assertEqual(orchestrator.state, ReaderState.READY)
            self.assertEqual(
                events,
                [
                    ("status", "現在ページを画面から取得しています…"),
                    ("preview", (640, 900)),
                    ("status", "論理ページ 1 をVision LLMで読解中…"),
                    ("page", 1),
                    ("understanding", 1),
                    ("status", "保存完了。次ページ待機中です。"),
                    ("metrics", 1),
                    ("preview", None),
                ],
            )
            memory.close()
        source.close()

    def test_duplicate_page_error_callbacks_keep_the_current_order(self) -> None:
        original = sample_image(7)
        source = SequenceFrameSource([original, original])
        original.close()
        events: list[tuple[str, object]] = []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            memory = ReadingMemory(root / "memory.sqlite3")
            fake = FakeLLMClient()
            orchestrator = ReadingOrchestrator(
                AppConfig(chunk_size=20, spread_mode="1ページ", total_pages=2),
                memory,
                source,
                PageAnalyzer(fake),
                ChunkIntegrator(fake),
                ReportGenerator(fake),
                FakeController(),
                root / "reports",
                _error_callbacks(events),
            )
            orchestrator.new_session("重複ページ確認", 2)
            window = WindowInfo(1, "Sample Reader", Rect(0, 0, 640, 900))
            orchestrator.set_capture_target(window, window.rect)
            orchestrator.start()
            orchestrator.read_current_page()

            events.clear()
            with self.assertRaises(DuplicatePageError):
                orchestrator.read_current_page()

            self.assertEqual(orchestrator.state, ReaderState.ERROR)
            self.assertEqual(
                events,
                [
                    ("status", "現在ページを画面から取得しています…"),
                    ("preview", (640, 900)),
                    ("warning", "前ページと同じ画面です。新しいページとして記録しません。"),
                    ("metrics", (1, 1, 0)),
                    ("preview", None),
                ],
            )
            self.assertEqual(fake.vision_calls, 1)
            memory.close()
        source.close()

    def test_black_screen_error_callbacks_keep_the_current_order(self) -> None:
        black = Image.new("RGB", (640, 900), "black")
        source = SequenceFrameSource([black])
        black.close()
        events: list[tuple[str, object]] = []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            memory = ReadingMemory(root / "memory.sqlite3")
            fake = FakeLLMClient()
            orchestrator = ReadingOrchestrator(
                AppConfig(chunk_size=20, spread_mode="1ページ", total_pages=1),
                memory,
                source,
                PageAnalyzer(fake),
                ChunkIntegrator(fake),
                ReportGenerator(fake),
                FakeController(),
                root / "reports",
                _error_callbacks(events),
            )
            orchestrator.new_session("黒画面確認", 1)
            window = WindowInfo(1, "Sample Reader", Rect(0, 0, 640, 900))
            orchestrator.set_capture_target(window, window.rect)
            orchestrator.start()

            events.clear()
            with self.assertRaises(ProtectedCaptureError):
                orchestrator.read_current_page()

            self.assertEqual(orchestrator.state, ReaderState.ERROR)
            self.assertEqual(
                events,
                [
                    ("status", "現在ページを画面から取得しています…"),
                    ("preview", (640, 900)),
                    ("warning", "黒画面または単色画面です。キャプチャ保護を回避せず停止します。"),
                    ("metrics", (0, 0, 1)),
                    ("preview", None),
                ],
            )
            self.assertEqual(fake.vision_calls, 0)
            memory.close()
        source.close()


class ReportLayoutCharacterizationTests(unittest.TestCase):
    def test_report_names_headings_cache_and_progress_order_are_stable(self) -> None:
        material = {
            "session": {
                "id": 77,
                "title": "挙動固定",
                "read_pages": 2,
                "last_integrated_page": 2,
                "chunk_size": 20,
            },
            "page_notes": [],
            "chunk_summaries": [
                {
                    "chunk_index": 1,
                    "start_page": 1,
                    "end_page": 2,
                    "summary": {
                        "range_events": ["ミナが二つの記録を比較した"],
                        "new_facts": ["記録時刻が一致しない"],
                    },
                }
            ],
            "chapter_summaries": [],
            "user_notes": [{"page_index": 2, "note": "時刻の差に注目"}],
            "tracked_entities": [],
        }
        expected_report_files = {
            "01_summary": "01_summary.md",
            "02_characters": "02_characters.md",
            "03_mysteries": "03_mysteries.md",
            "04_reading_journey": "04_reading_journey.md",
            "05_final_review": "05_final_review.md",
            "06_evidence_check": "06_evidence_check.md",
            "handoff_for_chatgpt": "handoff_for_chatgpt.md",
        }
        expected_cache_files = {
            "pass_1.json",
            "pass_2.json",
            "pass_3.json",
            "pass_4.json",
            *{f"report_{key}_full.json" for key in expected_report_files},
        }
        statuses: list[str] = []

        with tempfile.TemporaryDirectory() as directory:
            output = ReportGenerator(FakeLLMClient()).generate(
                material, Path(directory), statuses.append
            )

            self.assertEqual(REPORT_FILES, expected_report_files)
            self.assertEqual(output.name, "挙動固定_session_77")
            self.assertEqual(
                {path.name for path in output.glob("*.md")},
                set(expected_report_files.values()),
            )
            for key, filename in expected_report_files.items():
                text = (output / filename).read_text(encoding="utf-8")
                self.assertTrue(text.startswith(f"# {key}\n"), filename)
                self.assertTrue(text.endswith("\n"), filename)

            cache_roots = list((output / ".generation_cache").iterdir())
            self.assertEqual(len(cache_roots), 1)
            self.assertEqual(
                {path.name for path in cache_roots[0].glob("*.json")},
                expected_cache_files,
            )
            self.assertEqual(
                statuses[:4],
                [
                    "最終検証 Pass 1/4: 全巻事実記録を統合中",
                    "最終検証 Pass 2/4: 人物・関係性・伏線・テーマを統合中",
                    "最終検証 Pass 3/4: 捏造・矛盾・事実混同を独立監査中",
                    "最終検証 Pass 4/4: 監査を反映したマスター記録を修正中",
                ],
            )
            self.assertEqual(
                statuses[4:11],
                [
                    f"最終レポート {index}/7 を執筆中: {filename}"
                    for index, filename in enumerate(expected_report_files.values(), 1)
                ],
            )
            self.assertEqual(statuses[-1], f"レポート生成完了: {output}")


if __name__ == "__main__":
    unittest.main()

