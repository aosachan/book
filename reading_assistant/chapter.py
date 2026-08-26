from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .context_budget import compact_value, fits_prompt, pack_prompt_batches
from .llm_client import LocalLLMClient
from .memory_schemas import CHAPTER_RESPONSE_SCHEMA
from .models import ChapterCheckpoint
from .prompts import chapter_prompt


CHAPTER_PROMPT_TOKEN_BUDGET = 1500


class ChapterIntegrator:
    def __init__(self, client: LocalLLMClient, quality: str = "BALANCED") -> None:
        self.client = client
        self.quality = quality

    def integrate(
        self,
        chapter_index: int,
        start_page: int,
        end_page: int,
        chunk_records: list[dict[str, Any]],
        prior_carryover: dict[str, Any] | None = None,
    ) -> ChapterCheckpoint:
        if not chunk_records:
            raise ValueError("章へ統合する読書メモがありません。")
        prior = compact_value(prior_carryover or {}, 280)
        current = [compact_value(record, 520) for record in chunk_records]

        def render(batch: list[dict[str, Any]]) -> str:
            return chapter_prompt(
                chapter_index,
                int(batch[0].get("start_page", start_page)),
                int(batch[-1].get("end_page", end_page)),
                batch,
                prior if isinstance(prior, dict) else {},
                self.quality,
            )

        def fit_atomic(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
            nonlocal prior

            if all(
                fits_prompt(render([item]), CHAPTER_PROMPT_TOKEN_BUDGET)
                for item in records
            ):
                return records

            # As with page-to-chunk integration, batching can only proceed
            # after a single chunk fits. Prefer dropping prompt-only inherited
            # context over thinning this chapter's factual material.
            for prior_budget in (220, 160, 96, 48):
                candidate = compact_value(prior_carryover or {}, prior_budget)
                prior = candidate if isinstance(candidate, dict) else {}
                if all(
                    fits_prompt(render([item]), CHAPTER_PROMPT_TOKEN_BUDGET)
                    for item in records
                ):
                    return records
            prior = {}

            if all(
                fits_prompt(render([item]), CHAPTER_PROMPT_TOKEN_BUDGET)
                for item in records
            ):
                return records

            for item_budget in (460, 400, 340, 280, 220, 160, 96):
                reduced = [compact_value(record, item_budget) for record in records]
                if all(
                    fits_prompt(render([item]), CHAPTER_PROMPT_TOKEN_BUDGET)
                    for item in reduced
                ):
                    return reduced
            raise RuntimeError(
                "単一チャンクの章統合素材を安全なコンテキスト内へ縮小できませんでした。"
            )

        while True:
            current = fit_atomic(current)
            if fits_prompt(render(current), CHAPTER_PROMPT_TOKEN_BUDGET):
                data = self.client.text_json(
                    render(current),
                    deep=True,
                    response_schema=CHAPTER_RESPONSE_SCHEMA,
                ).data
                break
            batches = pack_prompt_batches(
                current, render, CHAPTER_PROMPT_TOKEN_BUDGET
            )
            next_level: list[dict[str, Any]] = []
            for part, batch in enumerate(batches, 1):
                result = self.client.text_json(
                    render(batch),
                    deep=True,
                    response_schema=CHAPTER_RESPONSE_SCHEMA,
                ).data
                next_level.append(
                    {
                        "start_page": int(batch[0].get("start_page", start_page)),
                        "end_page": int(batch[-1].get("end_page", end_page)),
                        "part": part,
                        "summary": compact_value(result, 600),
                    }
                )
            if len(next_level) >= len(current):
                current = [compact_value(item, 320) for item in next_level]
                if len(pack_prompt_batches(current, render, CHAPTER_PROMPT_TOKEN_BUDGET)) >= len(current):
                    raise RuntimeError("章の階層統合が収束しませんでした。")
            else:
                current = next_level

        data = normalize_chapter_data(data)
        carryover = minimal_carryover(data.get("carryover", {}))
        carryover = compact_value(carryover, 650)
        if not isinstance(carryover, dict):
            carryover = {}
        return ChapterCheckpoint(
            chapter_index=chapter_index,
            start_page=start_page,
            end_page=end_page,
            summary=data,
            carryover=carryover,
        )


def write_chapter_markdown(
    chapter: ChapterCheckpoint,
    book_title: str,
    session_id: int,
    reports_root: Path,
) -> Path:
    folder = reports_root / f"{_slug(book_title)}_session_{session_id}" / "chapter_notes"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (
        f"chapter_{chapter.chapter_index:03d}_pages_"
        f"{chapter.start_page}-{chapter.end_page}.md"
    )
    summary = chapter.summary
    unresolved = summary.get("unresolved_questions", {})
    if not isinstance(unresolved, dict):
        unresolved = {"new": unresolved or [], "continuing": []}
    sections = [
        ("章の詳細要約", summary.get("detailed_summary") or "内容判定不能"),
        ("出来事タイムライン", summary.get("event_timeline") or ["内容判定不能または具体的出来事なし"]),
        ("新しく判明した事実", summary.get("new_facts") or ["特になし"]),
        ("キャラクターの行動と感情", summary.get("character_actions_and_emotions") or ["特になし"]),
        ("関係性の変化", summary.get("relationship_changes") or ["大きな変化なし"]),
        ("重要な発言", summary.get("important_utterances") or ["特になし"]),
        ("伏線・違和感", summary.get("new_clues") or ["特になし"]),
        ("未解決事項 / 新規", unresolved.get("new") or ["特になし"]),
        ("未解決事項 / 継続", unresolved.get("continuing") or ["特になし"]),
        (
            "解決された事項",
            [
                *(summary.get("resolved_questions") or []),
                *(summary.get("resolved_clues") or []),
            ]
            or ["特になし"],
        ),
        ("印象的な場面", summary.get("memorable_scenes") or ["特になし"]),
        ("この章についての考察", summary.get("chapter_analysis") or ["特になし"]),
        ("この時点の予想", summary.get("predictions_at_chapter_end") or ["特になし"]),
        ("感情的インパクト", summary.get("emotional_impact") or ["特になし"]),
        ("読み取り不能・情報不足", summary.get("unreadable_pages") or ["特になし"]),
        ("次章への引き継ぎ", chapter.carryover),
    ]
    lines = [
        f"# 第{chapter.chapter_index}章の読書記録 — {book_title}",
        "",
        f"> 読書ページ {chapter.start_page}〜{chapter.end_page}。本文引用ではなくAIの意味メモです。",
    ]
    for heading, value in sections:
        rendered = _render(value)
        if rendered:
            lines.extend(["", f"## {heading}", "", rendered])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def normalize_chapter_data(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize new fact-first output while accepting legacy chapter JSON."""

    if not isinstance(data, dict):
        data = {}
    normalized = dict(data)
    normalized.setdefault("chapter_label", "")
    normalized.setdefault("detailed_summary", data.get("detailed_summary", ""))
    normalized.setdefault("event_timeline", data.get("key_events", []))
    normalized.setdefault("new_facts", data.get("new_facts", []))
    normalized.setdefault(
        "character_actions_and_emotions", data.get("character_end_states", [])
    )
    normalized.setdefault("relationship_changes", data.get("relationship_end_states", []))
    normalized.setdefault("important_utterances", data.get("important_utterances", []))
    normalized.setdefault("new_clues", data.get("important_foreshadowing", []))
    unresolved = data.get("unresolved_questions")
    if not isinstance(unresolved, dict):
        unresolved = {"new": data.get("unresolved_points", []) or [], "continuing": []}
    normalized["unresolved_questions"] = {
        "new": unresolved.get("new", []) or [],
        "continuing": unresolved.get("continuing", []) or [],
    }
    normalized.setdefault("resolved_questions", data.get("resolved_points", []))
    normalized.setdefault("resolved_clues", data.get("resolved_clues", []))
    normalized.setdefault("memorable_scenes", data.get("memorable_developments", []))
    legacy_analysis = []
    if data.get("chapter_review"):
        legacy_analysis.append(data["chapter_review"])
    legacy_analysis.extend(data.get("interpretation_revisions", []) or [])
    normalized.setdefault("chapter_analysis", legacy_analysis)
    normalized.setdefault("emotional_impact", data.get("emotional_impact", []))
    normalized.setdefault("predictions_at_chapter_end", data.get("predictions_at_chapter_end", []))
    normalized.setdefault("unreadable_pages", data.get("unreadable_pages", []))
    normalized["memorable_scenes"] = list(normalized.get("memorable_scenes", []) or [])[:3]
    normalized["emotional_impact"] = list(normalized.get("emotional_impact", []) or [])[:3]
    normalized.setdefault("confidence", data.get("confidence", 0.0))
    normalized["carryover"] = minimal_carryover(data.get("carryover", {}))
    return normalized


def minimal_carryover(value: Any) -> dict[str, Any]:
    carryover = value if isinstance(value, dict) else {}
    return {
        "active_characters": carryover.get("active_characters", []) or [],
        "unresolved_clues": carryover.get("unresolved_clues", []) or [],
        "open_questions": carryover.get("open_questions", []) or [],
        "immediate_situation": str(
            carryover.get("immediate_situation", carryover.get("continuity_bridge", ""))
        ).strip(),
    }


def _render(value: Any, depth: int = 0) -> str:
    if value is None or value == "" or value == [] or value == {}:
        return ""
    if isinstance(value, dict):
        lines = []
        for key, nested in value.items():
            text = _render(nested, depth + 1)
            if text:
                lines.append(f"- {key}: {text}" if "\n" not in text else f"- {key}:\n{text}")
        return "\n".join(lines)
    if isinstance(value, list):
        return "\n".join(f"- {_render(item, depth + 1)}" for item in value if _render(item, depth + 1))
    return str(value).strip()


def _slug(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*]+', "_", value).strip(" ._")
    return (value[:60] or "book").replace(" ", "_")
