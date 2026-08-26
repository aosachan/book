from __future__ import annotations

import json
import unittest

from reading_assistant.prompts import compact_page_context, page_prompt


class PromptCompactionTests(unittest.TestCase):
    def test_page_context_is_bounded_and_keeps_latest_summary(self) -> None:
        pages = []
        for index in range(1, 6):
            pages.append(
                {
                    "page_index": index,
                    "short_summary": f"要約{index}" + "長" * 900,
                    "characters": [
                        {
                            "name": f"人物{n}",
                            "role_or_action": "行動" * 200,
                            "psychology": [{"text": "心理" * 200, "evidence_level": "FACT"}],
                        }
                        for n in range(10)
                    ],
                    "events": [{"text": "出来事" * 200, "evidence_level": "FACT"}] * 8,
                    "relationship_updates": [],
                    "foreshadowing_or_suspicious_points": [],
                    "unresolved_questions": [],
                    "important_details": [],
                    "continuity_from_previous_page": "継続" * 200,
                }
            )
        context = {
            "recent_pages": pages,
            "recent_chunks": [],
            "prediction_history_tail": [],
        }

        compact = compact_page_context(context)
        serialized = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))

        self.assertLessEqual(len(serialized), 900)
        self.assertEqual(compact["latest_page"]["page_index"], 5)
        self.assertIn("要約5", compact["latest_page"]["short_summary"])
        self.assertNotIn("長" * 300, page_prompt(6, context, "BALANCED"))


if __name__ == "__main__":
    unittest.main()
