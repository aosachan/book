from __future__ import annotations

import hashlib
import json
import unittest

from reading_assistant.llm_client import PAGE_RESPONSE_SCHEMA
from reading_assistant.memory_schemas import CHAPTER_RESPONSE_SCHEMA, CHUNK_RESPONSE_SCHEMA
from reading_assistant.prompts import (
    CHAPTER_SCHEMA,
    CHUNK_SCHEMA,
    FINAL_PASS_4_SCHEMA,
    PAGE_SCHEMA,
    REPORT_RESPONSE_SCHEMA,
    chapter_prompt,
    chunk_prompt,
    final_pass_prompt,
    page_prompt,
    report_prompt,
)
from reading_assistant.reports import REPORT_FILES


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256_text(encoded)


PAGE_CONTEXT = {
    "last_chapter_checkpoint": {
        "chapter_index": 2,
        "start_page": 21,
        "end_page": 40,
        "carryover": {
            "active_characters": [
                {"character_id": "character_001", "name": "ミナ", "state": "資料室を調査中"}
            ],
            "unresolved_clues": [
                {"clue_id": "clue_002", "text": "時計と記録の時刻が一致しない"}
            ],
            "open_questions": [
                {"question_id": "question_004", "text": "誰が記録を書き換えたのか"}
            ],
            "immediate_situation": "ミナが資料室で改変された記録を見つけた直後。",
        },
    },
    "recent_chunks": [
        {
            "chunk_index": 3,
            "start_page": 41,
            "end_page": 42,
            "summary": {
                "range_events": ["ミナが管理人に記録の出所を尋ねた"],
                "new_facts": ["管理人も時刻の不一致を知っていた"],
            },
        }
    ],
    "recent_pages": [
        {
            "page_index": 42,
            "short_summary": "管理人は記録の欠落について返答を避けた。",
            "events": [
                {
                    "event_id": "event_017",
                    "actor": "管理人",
                    "action": "返答を避ける",
                    "evidence_level": "FACT",
                    "confidence": 0.94,
                }
            ],
            "unresolved_questions": [
                {
                    "text": "管理人は何を隠しているのか",
                    "evidence_level": "SPECULATION",
                    "confidence": 0.48,
                }
            ],
        }
    ],
    "current_character_states": [
        {
            "name": "ミナ",
            "page_index": 42,
            "state": {"current_goal": "記録改変の理由を突き止める"},
        }
    ],
    "prediction_history_tail": [
        {
            "page_index": 40,
            "prediction_text": "管理人が改変に関与している可能性",
            "evidence_level": "SPECULATION",
            "confidence": 0.45,
            "status": "open",
        }
    ],
    "tracked_entities": [
        {
            "entity_uid": "question_004",
            "entity_type": "question",
            "label": "誰が記録を書き換えたのか",
            "status": "unresolved",
        }
    ],
}

PAGE_NOTES = [
    {
        "page_index": 41,
        "short_summary": "ミナが管理人に古い記録の出所を尋ねた。",
        "scene_location": "資料室",
        "events": [
            {
                "event_id": "event_016",
                "actor": "ミナ",
                "action": "記録の出所を尋ねる",
                "target": "管理人",
                "outcome": "管理人は即答しなかった",
                "evidence_level": "FACT",
                "confidence": 0.95,
            }
        ],
        "important_utterances": [
            {
                "speaker": "ミナ",
                "target": "管理人",
                "meaning": "欠落した記録の由来を説明するよう求めた",
                "reaction_or_result": "管理人は話題を変えた",
                "evidence_level": "FACT",
                "confidence": 0.9,
            }
        ],
        "new_facts": [],
        "reading_status": "READABLE",
        "confidence": 0.92,
    },
    {
        "page_index": 42,
        "short_summary": "管理人が記録の欠落について返答を避けた。",
        "scene_location": "資料室",
        "events": [
            {
                "event_id": "event_017",
                "actor": "管理人",
                "action": "返答を避ける",
                "target": "ミナ",
                "outcome": "疑問が未解決のまま残る",
                "evidence_level": "FACT",
                "confidence": 0.94,
            }
        ],
        "new_facts": [
            {
                "text": "管理人も記録の欠落を認識している",
                "evidence_level": "FACT",
                "confidence": 0.88,
            }
        ],
        "reading_status": "READABLE",
        "confidence": 0.9,
    },
]

CHUNK_RECORDS = [
    {
        "chunk_index": 3,
        "start_page": 41,
        "end_page": 42,
        "summary": {
            "range_events": ["ミナが管理人へ記録の出所を尋ね、返答を避けられた"],
            "new_facts": ["管理人も記録の欠落を認識している"],
            "unresolved_items": ["管理人が返答を避けた理由"],
        },
    }
]

PRIOR_MEMORY = {
    "previous_chapter_carryover": PAGE_CONTEXT["last_chapter_checkpoint"]["carryover"],
    "tracked_entities": PAGE_CONTEXT["tracked_entities"],
}

FINAL_PAYLOAD = {
    "book": {"title": "時計の記録", "read_pages": 42},
    "hierarchical_records_in_reading_order": [
        {"kind": "chapter_summary", "value": CHUNK_RECORDS[0]},
        {"kind": "user_note", "value": {"page_index": 41, "note": "管理人の反応に注目"}},
    ],
}


def rendered_prompt_cases() -> dict[str, str]:
    cases = {
        "page": page_prompt(43, PAGE_CONTEXT, "BALANCED"),
        "chunk": chunk_prompt(41, 42, PAGE_NOTES, PRIOR_MEMORY, "BALANCED"),
        "chapter": chapter_prompt(3, 41, 42, CHUNK_RECORDS, PRIOR_MEMORY, "DEEP"),
    }
    for pass_number in range(1, 5):
        cases[f"final_pass_{pass_number}"] = final_pass_prompt(
            pass_number, FINAL_PAYLOAD, "DEEP"
        )
    for report_key in REPORT_FILES:
        cases[f"report_{report_key}"] = report_prompt(
            report_key,
            FINAL_PAYLOAD,
            "BALANCED",
            "ページ 41〜42",
        )
    return cases


def schema_cases() -> dict[str, object]:
    return {
        "page_response": PAGE_RESPONSE_SCHEMA,
        "chunk_response": CHUNK_RESPONSE_SCHEMA,
        "chapter_response": CHAPTER_RESPONSE_SCHEMA,
        "final_pass_4_response": FINAL_PASS_4_SCHEMA,
        "report_response": REPORT_RESPONSE_SCHEMA,
        "page_output_example": PAGE_SCHEMA,
        "chunk_output_example": CHUNK_SCHEMA,
        "chapter_output_example": CHAPTER_SCHEMA,
    }


EXPECTED_PROMPT_SHA256 = {
    "page": "c0a7ac8ce78c8c1a990cff980cbd3b5f8991dbd77ecbd4157276e50623e9e88d",
    "chunk": "5310906382373456fc826b8731de8b972894d63f659501aacaacdda2d8f38c66",
    "chapter": "9b98299ad8e2ec1598b7648d610ef677801d96d6319b2822f95d7ed3a1b49965",
    "final_pass_1": "44f3d6470bb25d03418776cbbe02e72813ef26b803c183eadd079cbde714b033",
    "final_pass_2": "d798d75fe273060497bcb05786b52aef1466a8105b1e1fa2a947527b448e1905",
    "final_pass_3": "d004a95d9c8984f1e770652a5cc5a814ed1a026b4d026e83df745fe34f4da6f5",
    "final_pass_4": "6c358153ada2d7c170e33c32069c597132d5d24e7982336bfad3b7e7c675bc7c",
    "report_01_summary": "56bf354e3ee57e4f490ef284de17569a19fbbcd92e529c2ce5082687ee46a3f1",
    "report_02_characters": "a49ffaa943561d9a2ed7e7e880e60ba92b0208c7be30df8808b19b3194d91936",
    "report_03_mysteries": "7e7eeae497143654239af48f42571e1f0c6720c2e76f82d62f08fb43d70228b4",
    "report_04_reading_journey": "c8c2bfe050f809a1436c932d04177d73f8a2f2a72d09b7564de3f0d5fa9af194",
    "report_05_final_review": "29072cbe5c0d64b1b430149ac77a3ee2e06fa0764870ab8ba8a026dc4f7a91ef",
    "report_06_evidence_check": "09f90f67f99332b4beff70f7b59a6bdb3aafc3945d1e5db19ba6e4332dc4a679",
    "report_handoff_for_chatgpt": "97e9de5e9013e9e2643d139773a1dbb8d32ee73bb17aa6a55e600104b2c3abc7",
}

EXPECTED_SCHEMA_SHA256 = {
    "page_response": "6a2f091659e5442b5ca6152d8f71826b988dc60e38900a76c41f5f068f4d5a51",
    "chunk_response": "51623e9f2a2566c70da12c093df619b60b16d9a1820a6a098d0522bd03468ba8",
    "chapter_response": "d0aeb6d02e823cc3f4f4bd681af1d9f844604f5c2becc4b2bf1351ef67a4d307",
    "final_pass_4_response": "c2c5c1f4ce30a550c3d9e33d0beba20de9f93c84a45501ac641599180c5945c7",
    "report_response": "cb868bc52ba610dc21823c8f6cf5f539fb53abf32d6606b040eb8f65e27bdc34",
    "page_output_example": "b7f696f10fdb63e625952745daf2dd66868b15212fbd91aa12c1ded97b9cef70",
    "chunk_output_example": "3d671c1a1bd163950a1668e31b4563acc26ac1ef52a2d34b274aa2b35966470a",
    "chapter_output_example": "bff0e484d423f9aa056ec016b79b57fc9027c9e0d0b1489db1662cd0e5c2015a",
}


class PromptAndSchemaCharacterizationTests(unittest.TestCase):
    def test_rendered_prompts_are_byte_for_byte_unchanged(self) -> None:
        actual = {
            name: _sha256_text(prompt)
            for name, prompt in rendered_prompt_cases().items()
        }
        self.assertEqual(actual, EXPECTED_PROMPT_SHA256)

    def test_json_schemas_and_output_examples_are_unchanged(self) -> None:
        actual = {
            name: _sha256_json(schema)
            for name, schema in schema_cases().items()
        }
        self.assertEqual(actual, EXPECTED_SCHEMA_SHA256)


if __name__ == "__main__":
    unittest.main()

