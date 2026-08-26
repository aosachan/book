from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from .context_budget import (
    DEEP_PROMPT_TOKEN_BUDGET,
    REPORT_PROMPT_TOKEN_BUDGET,
    compact_value,
    fit_payload,
    fits_prompt,
    pack_prompt_batches,
)
from .llm_client import LocalLLMClient
from .prompts import (
    FINAL_PASS_4_SCHEMA,
    REPORT_RESPONSE_SCHEMA,
    final_pass_prompt,
    report_prompt,
)


REPORT_FILES = {
    "01_summary": "01_summary.md",
    "02_characters": "02_characters.md",
    "03_mysteries": "03_mysteries.md",
    "04_reading_journey": "04_reading_journey.md",
    "05_final_review": "05_final_review.md",
    "06_evidence_check": "06_evidence_check.md",
    "handoff_for_chatgpt": "handoff_for_chatgpt.md",
}

REPORT_TITLES = {
    "01_summary": "全巻あらすじ",
    "02_characters": "人物・心理・関係性",
    "03_mysteries": "伏線・違和感・未解決事項",
    "04_reading_journey": "読書体験と予想の変化",
    "05_final_review": "最終感想・考察",
    "06_evidence_check": "解釈の根拠検証",
    "handoff_for_chatgpt": "別AIへの読書体験引き継ぎ",
}

SECTIONAL_REPORTS = {
    "01_summary",
    "02_characters",
    "03_mysteries",
    "04_reading_journey",
    "06_evidence_check",
    "handoff_for_chatgpt",
}


class ReportGenerator:
    def __init__(self, client: LocalLLMClient, quality: str = "BALANCED") -> None:
        self.client = client
        self.quality = quality

    def generate(
        self,
        material: dict,
        output_root: Path,
        status: Callable[[str], None] | None = None,
    ) -> Path:
        notify = status or (lambda _: None)
        session = material.get("session", {})
        book_title = str(session.get("title", "book"))
        session_id = int(session.get("id", 0))
        output_dir = output_root / f"{_slug(book_title)}_session_{session_id}"
        output_dir.mkdir(parents=True, exist_ok=True)
        cache_dir = output_dir / ".generation_cache" / _material_digest(material)
        cache_dir.mkdir(parents=True, exist_ok=True)

        notify("最終検証 Pass 1/4: 全巻事実記録を統合中")
        chapter_records = material.get("chapter_summaries", [])
        source_records = chapter_records or material.get("chunk_summaries", [])
        source_kind = "chapter_summary" if chapter_records else "chunk_summary"
        chunk_items = [
            {"kind": source_kind, "value": item}
            for item in source_records
        ]
        user_items = [
            {"kind": "user_note", "value": item}
            for item in material.get("user_notes", [])
        ]
        session_item = {"kind": "session", "value": material.get("session", {})}
        pass1 = self._cached_json(
            cache_dir / "pass_1.json",
            lambda: self._hierarchical_pass(1, [session_item, *chunk_items, *user_items]),
        )

        notify("最終検証 Pass 2/4: 人物・関係性・伏線・テーマを統合中")
        pass2 = self._cached_json(
            cache_dir / "pass_2.json",
            lambda: self._hierarchical_pass(
                2,
                [{"kind": "fact_record", "value": pass1}, *chunk_items, *user_items],
            ),
        )

        notify("最終検証 Pass 3/4: 捏造・矛盾・事実混同を独立監査中")
        pass3 = self._cached_json(
            cache_dir / "pass_3.json",
            lambda: self._hierarchical_pass(
                3,
                [
                    {"kind": "fact_record", "value": pass1},
                    {"kind": "integrated_analysis", "value": pass2},
                ],
            ),
        )

        notify("最終検証 Pass 4/4: 監査を反映したマスター記録を修正中")
        corrected = self._cached_json(
            cache_dir / "pass_4.json",
            lambda: self._hierarchical_pass(
                4,
                [
                    {
                        "kind": "book",
                        "value": {"title": book_title, "read_pages": session.get("read_pages")},
                    },
                    {"kind": "fact_record", "value": pass1},
                    {"kind": "integrated_analysis", "value": pass2},
                    {"kind": "critical_audit", "value": pass3},
                    *chunk_items,
                    *user_items,
                ],
            ),
        )

        report_material = {
            "book": {"title": book_title, "read_pages": session.get("read_pages")},
            "fact_record": pass1,
            "integrated_analysis": pass2,
            "critical_audit": pass3,
            "corrected_master_record": corrected,
        }

        for index, (key, filename) in enumerate(REPORT_FILES.items(), 1):
            notify(f"最終レポート {index}/7 を執筆中: {filename}")
            chunks = source_records
            if key in SECTIONAL_REPORTS and len(chunks) > 3:
                text = self._sectional_report(
                    key,
                    book_title,
                    chunks,
                    material.get("user_notes", []),
                    report_material,
                    cache_dir,
                    notify,
                )
            else:
                text = self._single_report(
                    key,
                    self._report_scope(key, report_material),
                    cache_dir / f"report_{key}_full.json",
                )
            if not text:
                text = self._fallback_report(key, book_title, pass1, pass2, pass3)
            if not text.startswith("#"):
                text = f"# {book_title}\n\n{text}"
            (output_dir / filename).write_text(text.rstrip() + "\n", encoding="utf-8")
        notify(f"レポート生成完了: {output_dir}")
        return output_dir

    def _single_report(
        self,
        key: str,
        payload: dict,
        cache_path: Path,
        scope_note: str = "",
    ) -> str:
        bounded = fit_payload(
            payload,
            lambda value: report_prompt(key, value, self.quality, scope_note),
            REPORT_PROMPT_TOKEN_BUDGET,
        )
        generated = self._cached_json(
            cache_path,
            lambda: self.client.text_json(
                report_prompt(key, bounded, self.quality, scope_note),
                deep=True,
                response_schema=REPORT_RESPONSE_SCHEMA,
            ).data,
        )
        return str(generated.get("markdown", "")).strip()

    def _sectional_report(
        self,
        key: str,
        book_title: str,
        chunks: list[dict],
        user_notes: list[dict],
        report_material: dict,
        cache_dir: Path,
        notify: Callable[[str], None],
    ) -> str:
        item_budget = 500 if key == "04_reading_journey" else 390
        bounded_chunks = [compact_value(item, item_budget) for item in chunks]
        global_context = compact_value(self._report_scope(key, report_material), 230)

        def payload_for(batch: list[dict]) -> dict:
            start = int(batch[0].get("start_page", 1))
            end = int(batch[-1].get("end_page", start))
            notes = [
                note
                for note in user_notes
                if start <= int(note.get("page_index", 0)) <= end
            ]
            return {
                "book": report_material.get("book", {}),
                "verified_global_context": global_context,
                "range": {"start_page": start, "end_page": end},
                "chunk_summaries": batch,
                "user_notes_in_range": compact_value(notes, 180),
            }

        def render(batch: list[dict]) -> str:
            start = int(batch[0].get("start_page", 1))
            end = int(batch[-1].get("end_page", start))
            return report_prompt(
                key,
                payload_for(batch),
                self.quality,
                f"ページ {start}〜{end}",
            )

        try:
            batches = pack_prompt_batches(
                bounded_chunks, render, REPORT_PROMPT_TOKEN_BUDGET
            )
        except ValueError:
            bounded_chunks = [compact_value(item, 300) for item in chunks]
            batches = pack_prompt_batches(
                bounded_chunks, render, REPORT_PROMPT_TOKEN_BUDGET
            )
        max_chunks_per_part = 2 if key == "04_reading_journey" else 3
        batches = [
            batch[offset : offset + max_chunks_per_part]
            for batch in batches
            for offset in range(0, len(batch), max_chunks_per_part)
        ]

        parts: list[str] = []
        overview_keys = {"02_characters", "03_mysteries", "handoff_for_chatgpt"}
        if key in overview_keys:
            overview = self._single_report(
                key,
                self._report_scope(key, report_material),
                cache_dir / f"report_{key}_overview.json",
                "全巻の統合的な概観",
            )
            if overview:
                parts.append("## 全巻の統合的な概観\n\n" + _without_h1(overview))

        for part_number, batch in enumerate(batches, 1):
            start = int(batch[0].get("start_page", 1))
            end = int(batch[-1].get("end_page", start))
            notify(
                f"{REPORT_FILES[key]}: 詳細パート {part_number}/{len(batches)} "
                f"（page {start}〜{end}）"
            )
            text = self._single_report(
                key,
                payload_for(batch),
                cache_dir / f"report_{key}_{start}_{end}.json",
                f"ページ {start}〜{end}",
            )
            if text:
                parts.append(f"## ページ {start}〜{end}\n\n{_without_h1(text)}")

        if not parts:
            return ""
        return (
            f"# {REPORT_TITLES[key]} — {book_title}\n\n"
            "> 300ページ級の長編でも中盤の情報を落とさないよう、検証済みチャンクを範囲別に執筆して結合しています。\n\n"
            + "\n\n".join(parts)
        ).strip()

    @staticmethod
    def _cached_json(path: Path, producer: Callable[[], dict]) -> dict:
        if path.exists():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(cached, dict):
                    return cached
            except (OSError, json.JSONDecodeError):
                pass
        value = producer()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(path)
        return value

    def _hierarchical_pass(self, pass_number: int, items: list[dict]) -> dict:
        current = [compact_value(item, 650) for item in (items or [{}])]

        def render(batch: list[dict]) -> str:
            return final_pass_prompt(
                pass_number,
                {"hierarchical_records_in_reading_order": batch},
                self.quality,
            )

        def request(batch: list[dict]) -> dict:
            if pass_number == 4:
                return self.client.text_json(
                    render(batch),
                    deep=True,
                    response_schema=FINAL_PASS_4_SCHEMA,
                ).data
            return self.client.text_json(render(batch), deep=True).data

        while True:
            if fits_prompt(render(current), DEEP_PROMPT_TOKEN_BUDGET):
                return request(current)
            batches = pack_prompt_batches(current, render, DEEP_PROMPT_TOKEN_BUDGET)
            next_level: list[dict] = []
            for index, batch in enumerate(batches, 1):
                result = request(batch)
                next_level.append(
                    {
                        "kind": f"pass_{pass_number}_partial",
                        "part": index,
                        "value": compact_value(result, 700),
                    }
                )
            if len(next_level) >= len(current):
                # Smaller projections guarantee at least pairwise convergence on
                # the next render while retaining the beginning and end.
                current = [compact_value(item, 360) for item in next_level]
                retry_batches = pack_prompt_batches(
                    current, render, DEEP_PROMPT_TOKEN_BUDGET
                )
                if len(retry_batches) >= len(current):
                    raise RuntimeError("最終検証の階層統合が収束しませんでした。")
            else:
                current = next_level

    @staticmethod
    def _report_scope(key: str, material: dict) -> dict:
        fields = {
            "01_summary": ("book", "fact_record", "corrected_master_record"),
            "02_characters": ("book", "integrated_analysis", "corrected_master_record"),
            "03_mysteries": (
                "book",
                "integrated_analysis",
                "critical_audit",
                "corrected_master_record",
            ),
            "04_reading_journey": ("book", "integrated_analysis", "corrected_master_record"),
            "05_final_review": (
                "book",
                "fact_record",
                "integrated_analysis",
                "corrected_master_record",
            ),
            "06_evidence_check": ("book", "critical_audit", "corrected_master_record"),
            "handoff_for_chatgpt": (
                "book",
                "fact_record",
                "integrated_analysis",
                "critical_audit",
                "corrected_master_record",
            ),
        }[key]
        return {field: material.get(field, {}) for field in fields}

    @staticmethod
    def _fallback_report(key: str, title: str, pass1: dict, pass2: dict, pass3: dict) -> str:
        payload = {"fact_record": pass1, "integrated_analysis": pass2, "audit": pass3}
        return f"# {REPORT_TITLES[key]} — {title}\n\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"


def _slug(value: str) -> str:
    value = re.sub(r"[<>:\"/\\|?*]+", "_", value).strip(" ._")
    return (value[:60] or "book").replace(" ", "_")


def _material_digest(material: dict[str, Any]) -> str:
    session = material.get("session", {})
    stable = {
        "session": {
            key: session.get(key)
            for key in ("id", "title", "read_pages", "last_integrated_page", "chunk_size")
        },
        "chunk_summaries": material.get("chunk_summaries", []),
        "chapter_summaries": material.get("chapter_summaries", []),
        "user_notes": material.get("user_notes", []),
    }
    encoded = json.dumps(
        stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def _without_h1(markdown: str) -> str:
    lines = markdown.strip().splitlines()
    if lines and lines[0].lstrip().startswith("# "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines.pop(0)
    return "\n".join(lines).strip()
