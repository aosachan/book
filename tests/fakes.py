from __future__ import annotations

import re
from pathlib import Path

from PIL import Image

from reading_assistant.llm_client import LLMCallResult


class FakeLLMClient:
    def __init__(self) -> None:
        self.vision_calls = 0
        self.text_calls = 0

    def vision_json(self, prompt: str, image: Image.Image, deep: bool = False) -> LLMCallResult:
        self.vision_calls += 1
        match = re.search(r"論理ページ\s+(\d+)", prompt)
        page = int(match.group(1)) if match else self.vision_calls
        data = {
            "short_summary": f"主人公ミナが記録を調べ、ページ{page}時点の新しい手掛かりに気づく。",
            "characters": [
                {
                    "name": "ミナ",
                    "role_or_action": "記録を調べる",
                    "psychology": [
                        {
                            "text": "慎重さと好奇心が併存している",
                            "evidence_level": "STRONG_INFERENCE",
                            "confidence": 0.77,
                            "basis": "行動の選び方",
                        }
                    ],
                }
            ],
            "events": [{"text": f"手掛かり{page}を得る", "evidence_level": "FACT", "confidence": 0.9}],
            "apparent_emotions": [],
            "relationship_updates": [],
            "foreshadowing_or_suspicious_points": [
                {"text": "時計の時刻に違和感", "evidence_level": "STRONG_INFERENCE", "confidence": 0.7}
            ],
            "unresolved_questions": [
                {"text": "誰が記録を変えたのか", "evidence_level": "SPECULATION", "confidence": 0.5}
            ],
            "important_details": [],
            "continuity_from_previous_page": "調査が継続する",
            "possible_chapter_boundary": False,
            "confidence": 0.88,
            "readability": 0.96,
            "important_score": 0.65,
        }
        return LLMCallResult(data, 0.01)

    def text_json(
        self,
        prompt: str,
        deep: bool = True,
        response_schema: dict | None = None,
    ) -> LLMCallResult:
        self.text_calls += 1
        if "種類:" in prompt and "Markdownレポート" in prompt:
            match = re.search(r"種類:\s*([a-zA-Z0-9_]+)", prompt)
            key = match.group(1) if match else "report"
            return LLMCallResult({"markdown": f"# {key}\n\n自作サンプルに基づく詳細な意味要約。"}, 0.01)
        if "章の読書記録として統合" in prompt or "章読書記録へ統合" in prompt:
            return LLMCallResult(
                {
                    "chapter_label": "記録の違和感",
                    "detailed_summary": "ミナは記録を比較し、時計の時刻に続く矛盾を見つけた。",
                    "event_timeline": [
                        {
                            "event_id": "",
                            "page_range": "1-5",
                            "location": "資料室",
                            "characters": ["ミナ"],
                            "action": "ミナが複数の記録時刻を比較した",
                            "utterance_meaning": "",
                            "outcome": "時刻の矛盾を確認した",
                            "evidence_level": "FACT",
                            "confidence": 0.9,
                        }
                    ],
                    "new_facts": [{"text": "記録の時刻が一致しない", "evidence_level": "FACT", "confidence": 0.9}],
                    "character_actions_and_emotions": [
                        {
                            "character_id": "",
                            "name": "ミナ",
                            "actions": ["記録を比較した"],
                            "emotion": "警戒と好奇心",
                            "evidence_scene": "矛盾を見つけても調査を続けた",
                            "evidence_level": "STRONG_INFERENCE",
                            "confidence": 0.8,
                        }
                    ],
                    "relationship_changes": [],
                    "important_utterances": [],
                    "new_clues": [{"clue_id": "", "text": "時計のずれ", "confidence": 0.8}],
                    "unresolved_questions": {
                        "new": [{"question_id": "", "text": "誰が記録を変えたのか", "status": "unresolved"}],
                        "continuing": [],
                    },
                    "resolved_questions": [],
                    "memorable_scenes": ["ミナが時刻の矛盾を並べて確認する場面"],
                    "chapter_analysis": [
                        {"text": "記録改変は意図的な可能性がある", "evidence_level": "SPECULATION", "confidence": 0.45}
                    ],
                    "predictions_at_chapter_end": ["管理人が関係する可能性"],
                    "emotional_impact": ["静かな不安"],
                    "unreadable_pages": [],
                    "confidence": 0.84,
                    "carryover": {
                        "active_characters": [
                            {"character_id": "", "name": "ミナ", "state": "記録改変を警戒している"}
                        ],
                        "unresolved_clues": [{"clue_id": "", "text": "時計のずれ"}],
                        "open_questions": [{"question_id": "", "text": "誰が記録を変えたのか"}],
                        "immediate_situation": "ミナが時刻矛盾を確認し、記録改変の調査を続ける。",
                    },
                },
                0.01,
            )
        if "ページ要約だけを材料" in prompt:
            data = {
                "range_events": [{"text": "ミナが連続した手掛かりを集めた", "evidence_level": "FACT", "confidence": 0.9}],
                "character_states": [
                    {
                        "name": "ミナ",
                        "current_goal": "記録改変の理由を知る",
                        "psychology": "警戒が強くなる",
                        "important_actions": ["記録を比較した"],
                        "possible_secret": "",
                        "suspicious_points": [],
                        "interpretation": "調査を続ける",
                        "evidence_level": "STRONG_INFERENCE",
                        "confidence": 0.8,
                        "changed_from_previous": "時計の矛盾により警戒へ変化",
                    }
                ],
                "relationship_changes": [],
                "important_foreshadowing": ["時計のずれ"],
                "oddities": ["記録の時刻が不整合"],
                "unresolved_items": ["誰が変えたのか"],
                "new_facts": ["記録が連続している"],
                "revisions_to_previous_interpretations": ["偶然ではない可能性が増した"],
                "predictions_at_this_point": [
                    {"text": "管理人が関係するかもしれない", "evidence_level": "SPECULATION", "confidence": 0.45}
                ],
                "memorable_developments": ["矛盾の発見"],
                "emotional_impact": ["静かな不安"],
                "especially_important": ["途中予想を保持する"],
                "confidence": 0.84,
            }
            return LLMCallResult(data, 0.01)
        return LLMCallResult({"verified": True, "notes": ["模擬最終検証"]}, 0.01)


class SequenceFrameSource:
    def __init__(self, images: list[Image.Image]) -> None:
        self.images = [image.copy() for image in images]
        self.index = 0

    def capture(self, rect) -> Image.Image:
        index = min(self.index, len(self.images) - 1)
        image = self.images[index].copy()
        self.index += 1
        return image

    def close(self) -> None:
        for image in self.images:
            image.close()


class FakeController:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    def send_page_key(self, handle: int, key_name: str) -> None:
        self.sent.append((handle, key_name))


def sample_image(index: int, size: tuple[int, int] = (640, 900)) -> Image.Image:
    image = Image.new("RGB", size, "white")
    pixels = image.load()
    # Unique, high-contrast deterministic bands give perceptual hashes distance.
    for y in range(60, size[1] - 60):
        for band in range(8):
            x0 = 40 + band * 68
            width = 8 + ((index * (band + 3)) % 37)
            shade = 15 + ((index * 31 + band * 17) % 80)
            if (y // (20 + (index % 7))) % 3 == band % 3:
                for x in range(x0, min(size[0] - 40, x0 + width)):
                    pixels[x, y] = (shade, shade, shade)
    return image
