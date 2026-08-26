from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reading_assistant.chapter import minimal_carryover, normalize_chapter_data, write_chapter_markdown
from reading_assistant.integrator import normalize_chunk_data
from reading_assistant.memory import ReadingMemory
from reading_assistant.models import ChapterCheckpoint, ChunkSummary, PageAnalysis


class FactFirstMemoryTests(unittest.TestCase):
    def test_unreadable_page_discards_guessed_content_and_is_tracked(self) -> None:
        analysis = PageAnalysis.from_dict(
            {
                "reading_status": "UNREADABLE",
                "short_summary": "前章から推測した架空の出来事",
                "events": [{"text": "推測イベント", "evidence_level": "FACT"}],
                "new_facts": [{"text": "推測事実", "evidence_level": "FACT"}],
                "characters": [{"name": "推測人物"}],
                "information_gaps": ["吹き出しを読めない"],
                "confidence": 0.1,
                "readability": 0.05,
            },
            12,
        )
        self.assertEqual(analysis.short_summary, "内容判定不能（読み取り失敗または情報不足）")
        self.assertEqual(analysis.events, [])
        self.assertEqual(analysis.new_facts, [])
        self.assertEqual(analysis.characters, [])

        chunk = normalize_chunk_data({}, [analysis.to_dict()])
        self.assertEqual(chunk["unreadable_pages"][0]["page_index"], 12)
        self.assertEqual(chunk["unreadable_pages"][0]["status"], "UNREADABLE")

    def test_question_keeps_id_until_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            memory = ReadingMemory(Path(directory) / "memory.sqlite3")
            session_id = memory.create_session("ID追跡", 100, "BALANCED", 20, {})
            first = ChunkSummary(
                1,
                1,
                20,
                {
                    "event_timeline": [
                        {
                            "event_id": "",
                            "page_range": "18-20",
                            "location": "駅",
                            "action": "主人公が昔の写真を見つける",
                            "outcome": "過去の恋人を思い出す",
                        }
                    ],
                    "character_actions_and_emotions": [
                        {"character_id": "", "name": "主人公", "actions": ["写真を見る"]}
                    ],
                    "new_questions": [
                        {
                            "question_id": "",
                            "text": "主人公と6年前の恋人が別れた理由は何か",
                            "status": "unresolved",
                        }
                    ],
                },
            )
            memory.save_chunk(session_id, first)
            question_id = first.summary["new_questions"][0]["question_id"]
            self.assertEqual(question_id, "question_001")
            self.assertEqual(
                first.summary["character_actions_and_emotions"][0]["character_id"],
                "character_001",
            )
            self.assertEqual(first.summary["event_timeline"][0]["event_id"], "event_001")

            continuing = ChunkSummary(
                2,
                21,
                40,
                {
                    "continuing_questions": [
                        {
                            "question_id": "",
                            "text": "主人公と6年前の恋人が別れた理由",
                            "status": "unresolved",
                        }
                    ]
                },
            )
            memory.save_chunk(session_id, continuing)
            self.assertEqual(
                continuing.summary["continuing_questions"][0]["question_id"],
                question_id,
            )

            resolved = ChunkSummary(
                3,
                41,
                60,
                {
                    "resolved_questions": [
                        {
                            "question_id": question_id,
                            "text": "主人公と6年前の恋人が別れた理由",
                            "answer": "転居による離別だった",
                            "basis": "本人同士の会話で判明",
                            "status": "resolved",
                        }
                    ]
                },
            )
            memory.save_chunk(session_id, resolved)
            tracked = {item["entity_id"]: item for item in memory.tracked_entities(session_id)}
            self.assertEqual(tracked[question_id]["status"], "resolved")
            self.assertEqual(tracked[question_id]["state"]["answer"], "転居による離別だった")
            memory.close()

    def test_chapter_markdown_is_fact_first_and_carryover_is_minimal(self) -> None:
        data = normalize_chapter_data(
            {
                "detailed_summary": "主人公は駅でAと会い、写真について尋ねた。Aは写真が6年前に撮られたと説明し、主人公はその場を離れた。",
                "event_timeline": ["主人公が駅でAに写真の来歴を尋ねる"],
                "new_facts": [],
                "relationship_changes": [],
                "chapter_analysis": [
                    {"text": "主人公がAへ過去の恋人を投影している可能性がある", "evidence_level": "SPECULATION"}
                ],
                "carryover": {
                    "active_characters": [{"name": "主人公"}, {"name": "A"}],
                    "unresolved_clues": [{"clue_id": "clue_001", "text": "写真の日付"}],
                    "open_questions": [{"question_id": "question_001", "text": "別れた理由"}],
                    "immediate_situation": "主人公が駅を去り、Aが一人残っている。",
                    "themes": ["投影", "トラウマ"],
                    "active_predictions": ["Aは恋人の代替かもしれない"],
                },
            }
        )
        carryover = minimal_carryover(data["carryover"])
        self.assertEqual(
            set(carryover),
            {"active_characters", "unresolved_clues", "open_questions", "immediate_situation"},
        )
        chapter = ChapterCheckpoint(1, 1, 20, data, carryover)
        with tempfile.TemporaryDirectory() as directory:
            path = write_chapter_markdown(chapter, "自作漫画", 1, Path(directory))
            text = path.read_text(encoding="utf-8")
        self.assertIn("## 出来事タイムライン", text)
        self.assertIn("主人公が駅でAに写真の来歴を尋ねる", text)
        self.assertIn("## 新しく判明した事実\n\n- 特になし", text)
        self.assertIn("## 関係性の変化\n\n- 大きな変化なし", text)
        self.assertIn("SPECULATION", text)
        self.assertNotIn("active_predictions", text)


if __name__ == "__main__":
    unittest.main()
