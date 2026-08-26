from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from reading_assistant.integrator import ChunkIntegrator
from reading_assistant.memory import ReadingMemory
from reading_assistant.models import PageAnalysis, PageRecord
from reading_assistant.reports import REPORT_FILES, ReportGenerator
from tests.fakes import FakeLLMClient


class ThreeHundredPageEnduranceTests(unittest.TestCase):
    def test_300_pages_resume_15_chunks_and_sectional_reports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "reading.sqlite3"
            memory = ReadingMemory(database)
            session_id = memory.create_session(
                "三百ページ耐久用の自作物語", 300, "BALANCED", 20, {"model": "fake"}
            )
            integrator = ChunkIntegrator(FakeLLMClient())

            for page in range(1, 301):
                analysis = PageAnalysis.from_dict(
                    {
                        "short_summary": f"自作物語のページ{page}で手掛かりP{page:03d}を確認する。",
                        "characters": [
                            {
                                "name": "ミナ",
                                "role_or_action": "記録を調べる",
                                "psychology": [
                                    {
                                        "text": f"ページ{page}時点の警戒と好奇心",
                                        "evidence_level": "STRONG_INFERENCE",
                                        "confidence": 0.8,
                                    }
                                ],
                            }
                        ],
                        "events": [
                            {
                                "text": f"手掛かりP{page:03d}を得る",
                                "evidence_level": "FACT",
                                "confidence": 0.9,
                            }
                        ],
                        "foreshadowing_or_suspicious_points": [
                            {
                                "text": f"予想P{page:03d}は後で変わる可能性がある",
                                "evidence_level": "SPECULATION",
                                "confidence": 0.5,
                            }
                        ],
                        "confidence": 0.9,
                        "readability": 0.95,
                        "important_score": 0.7,
                    },
                    page,
                )
                memory.record_page(
                    session_id,
                    PageRecord(
                        analysis=analysis,
                        page_hash=f"{page:016x}",
                        capture_index=page,
                        processing_seconds=0.01,
                    ),
                    "150ページ付近を重点確認" if page == 150 else "",
                )

                if page == 137:
                    memory.close()
                    memory = ReadingMemory(database)
                    self.assertEqual(memory.next_page_index(session_id), 138)

                if page % 20 == 0:
                    pending = memory.pages_since_last_integration(session_id)
                    chunk, _ = integrator.integrate(
                        page // 20,
                        pending,
                        memory.recent_context(session_id),
                    )
                    memory.save_chunk(session_id, chunk)

            metrics = memory.metrics(session_id)
            self.assertEqual(metrics["read_pages"], 300)
            self.assertEqual(metrics["chunks"], 15)
            self.assertEqual(metrics["last_integrated_page"], 300)

            material = memory.all_semantic_material(session_id)
            memory.close()
            reports_root = root / "reports"
            first_client = FakeLLMClient()
            report_dir = ReportGenerator(first_client).generate(material, reports_root)

            for filename in REPORT_FILES.values():
                self.assertTrue((report_dir / filename).exists(), filename)
            summary = (report_dir / "01_summary.md").read_text(encoding="utf-8")
            journey = (report_dir / "04_reading_journey.md").read_text(encoding="utf-8")
            summary_ranges = [
                tuple(map(int, match))
                for match in re.findall(r"## ページ (\d+)〜(\d+)", summary)
            ]
            journey_ranges = [
                tuple(map(int, match))
                for match in re.findall(r"## ページ (\d+)〜(\d+)", journey)
            ]
            self.assertEqual(summary_ranges[0][0], 1)
            self.assertEqual(summary_ranges[-1][1], 300)
            self.assertTrue(any(start <= 150 <= end for start, end in summary_ranges))
            self.assertTrue(all(end - start + 1 <= 60 for start, end in summary_ranges))
            self.assertTrue(all(end - start + 1 <= 40 for start, end in journey_ranges))

            # A second generation of unchanged semantic material reuses all
            # completed pass/report checkpoints and performs no LLM calls.
            resumed_client = FakeLLMClient()
            resumed_dir = ReportGenerator(resumed_client).generate(material, reports_root)
            self.assertEqual(resumed_dir, report_dir)
            self.assertEqual(resumed_client.text_calls, 0)


if __name__ == "__main__":
    unittest.main()
