from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reading_assistant.context_budget import (
    DEEP_PROMPT_TOKEN_BUDGET,
    REPORT_PROMPT_TOKEN_BUDGET,
    estimate_tokens,
)
from reading_assistant.integrator import ChunkIntegrator
from reading_assistant.config import LLMSettings
from reading_assistant.llm_client import LLMCallResult, LocalLLMClient
from reading_assistant.prompts import (
    FINAL_PASS_4_SCHEMA,
    REPORT_RESPONSE_SCHEMA,
    chunk_prompt,
    compact_page_note,
    compact_prior_memory,
)
from reading_assistant.reports import REPORT_FILES, ReportGenerator
from tests.fakes import FakeLLMClient


class RecordingFakeLLM(FakeLLMClient):
    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[str] = []
        self.schemas: list[dict | None] = []

    def text_json(self, prompt: str, deep: bool = True, response_schema=None):
        self.prompts.append(prompt)
        self.schemas.append(response_schema)
        return super().text_json(prompt, deep, response_schema)


class ContextBudgetTests(unittest.TestCase):
    def test_ollama_auto_thinking_is_safe_for_4096_context(self) -> None:
        class PayloadClient(LocalLLMClient):
            def __init__(self, settings):
                super().__init__(settings)
                self.payload = None

            def _retry_call(self, url, payload, parser):
                self.payload = payload
                return LLMCallResult({}, 0.0)

        automatic = PayloadClient(LLMSettings(thinking_control="auto"))
        automatic._call_ollama([{"role": "user", "content": "test"}], deep=True)
        self.assertIs(automatic.payload["think"], False)

        explicit = PayloadClient(LLMSettings(thinking_control="on"))
        explicit._call_ollama([{"role": "user", "content": "test"}], deep=True)
        self.assertIs(explicit.payload["think"], True)

    def test_long_chunk_is_hierarchical_and_every_prompt_is_bounded(self) -> None:
        client = RecordingFakeLLM()
        notes = [
            {
                "page_index": page,
                "short_summary": f"ページ{page}" + "長い意味要約" * 220,
                "characters": [
                    {"name": "ミナ", "role_or_action": "調査" * 180, "psychology": []}
                ],
                "events": [{"text": "出来事" * 180, "evidence_level": "FACT"}],
                "unresolved_questions": ["疑問" * 180],
            }
            for page in range(1, 21)
        ]

        chunk, _ = ChunkIntegrator(client).integrate(1, notes, {})

        self.assertEqual(chunk.end_page, 20)
        self.assertGreater(client.text_calls, 1)
        self.assertTrue(client.prompts)
        self.assertLessEqual(
            max(estimate_tokens(prompt) for prompt in client.prompts),
            DEEP_PROMPT_TOKEN_BUDGET,
        )

    def test_single_page_over_budget_drops_inherited_context_first(self) -> None:
        text = "具体的な出来事。さらに続く。"
        note = {
            "page_index": 27,
            "reading_status": "READABLE",
            "short_summary": text,
            "scene_location": "駅前",
            "events": [
                {
                    "text": text,
                    "actor": "主人公",
                    "action": text,
                    "target": "友人",
                    "location": "喫茶店",
                    "outcome": text,
                    "evidence_level": "FACT",
                }
            ],
            "new_facts": [{"text": text, "evidence_level": "FACT"}],
            "important_utterances": [
                {
                    "speaker": "友人",
                    "target": "主人公",
                    "meaning": text,
                    "reaction_or_result": text,
                }
            ],
            "characters": [
                {
                    "name": "主人公",
                    "role_or_action": text,
                    "emotion": "警戒",
                    "evidence_scene": text,
                }
            ],
            "relationship_updates": [],
            "foreshadowing_or_suspicious_points": [text],
            "unresolved_questions": [text],
            "information_gaps": [],
            "continuity_from_previous_page": text,
        }
        prior = {
            "last_chapter_checkpoint": {
                "carryover": {
                    "active_characters": [
                        {
                            "character_id": f"character_{index:03}",
                            "name": f"人物{index}",
                            "state": "現在も調査中",
                        }
                        for index in range(8)
                    ],
                    "unresolved_clues": [
                        {"clue_id": f"clue_{index:03}", "text": "伏線は未解決"}
                        for index in range(8)
                    ],
                    "open_questions": [
                        {
                            "question_id": f"question_{index:03}",
                            "text": "疑問は未解決",
                        }
                        for index in range(8)
                    ],
                    "immediate_situation": "主人公が友人と対話中",
                }
            },
            "recent_chunks": [
                {
                    "start_page": 1,
                    "end_page": 20,
                    "summary": {"event_timeline": [f"前の出来事{i}" for i in range(8)]},
                }
            ],
            "current_character_states": [
                {
                    "name": f"人物{index}",
                    "page_index": 20,
                    "state": {"goal": "調査", "emotion": "警戒", "action": "待機"},
                }
                for index in range(8)
            ],
            "tracked_entities": [
                {
                    "entity_uid": f"question_{index:03}",
                    "label": f"未解決疑問{index}",
                    "status": "unresolved",
                }
                for index in range(8)
            ],
        }
        initial = chunk_prompt(
            27,
            27,
            [compact_page_note(note)],
            compact_prior_memory(prior),
            "BALANCED",
        )
        self.assertGreater(estimate_tokens(initial), DEEP_PROMPT_TOKEN_BUDGET)

        client = RecordingFakeLLM()
        chunk, _ = ChunkIntegrator(client).integrate(2, [note], prior)

        self.assertEqual(chunk.start_page, 27)
        self.assertTrue(client.prompts)
        self.assertLessEqual(
            max(estimate_tokens(prompt) for prompt in client.prompts),
            DEEP_PROMPT_TOKEN_BUDGET,
        )
        # The full current page fact remains in the actual integration prompt.
        self.assertIn("具体的な出来事", client.prompts[0])

    def test_large_book_material_finishes_all_reports_with_bounded_prompts(self) -> None:
        client = RecordingFakeLLM()
        chunks = [
            {
                "chunk_index": index,
                "start_page": (index - 1) * 20 + 1,
                "end_page": index * 20,
                "summary": {
                    "range_events": ["出来事" * 250] * 8,
                    "character_states": [{"name": "ミナ", "psychology": "警戒" * 250}] * 5,
                    "predictions_at_this_point": ["予想" * 250] * 6,
                    "revisions_to_previous_interpretations": ["修正" * 250] * 6,
                },
            }
            for index in range(1, 31)
        ]
        material = {
            "session": {"id": 99, "title": "長編テスト", "read_pages": 600},
            "chunk_summaries": chunks,
            "user_notes": [
                {"page_index": index * 20, "note": "ユーザーメモ" * 120}
                for index in range(1, 31)
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            result = ReportGenerator(client).generate(material, Path(directory))
            for filename in REPORT_FILES.values():
                self.assertTrue((result / filename).exists())

        self.assertGreater(client.text_calls, 11)
        self.assertLessEqual(
            max(estimate_tokens(prompt) for prompt in client.prompts),
            DEEP_PROMPT_TOKEN_BUDGET,
        )
        report_prompts = [prompt for prompt in client.prompts if "種類:" in prompt]
        self.assertGreater(len(report_prompts), 7)
        self.assertLessEqual(
            max(estimate_tokens(prompt) for prompt in report_prompts),
            REPORT_PROMPT_TOKEN_BUDGET,
        )
        self.assertIn(FINAL_PASS_4_SCHEMA, client.schemas)
        self.assertIn(REPORT_RESPONSE_SCHEMA, client.schemas)


if __name__ == "__main__":
    unittest.main()
