from __future__ import annotations

from .context_budget import (
    DEEP_PROMPT_TOKEN_BUDGET,
    compact_value,
    fits_prompt,
    pack_prompt_batches,
)
from .llm_client import LLMCallResult, LocalLLMClient
from .memory_schemas import CHUNK_RESPONSE_SCHEMA
from .models import ChunkSummary
from .prompts import chunk_prompt, compact_page_note, compact_prior_memory


class ChunkIntegrator:
    def __init__(self, client: LocalLLMClient, quality: str = "BALANCED") -> None:
        self.client = client
        self.quality = quality

    def integrate(
        self,
        chunk_index: int,
        page_notes: list[dict],
        prior_memory: dict,
    ) -> tuple[ChunkSummary, LLMCallResult]:
        if not page_notes:
            raise ValueError("統合するページ読書メモがありません。")
        start_page = int(page_notes[0]["page_index"])
        end_page = int(page_notes[-1]["page_index"])
        bounded_notes = [compact_page_note(note) for note in page_notes]
        bounded_prior = compact_prior_memory(prior_memory)
        direct_prompt = chunk_prompt(
            start_page, end_page, bounded_notes, bounded_prior, self.quality
        )
        if fits_prompt(direct_prompt, DEEP_PROMPT_TOKEN_BUDGET):
            result = self.client.text_json(
                direct_prompt, deep=True, response_schema=CHUNK_RESPONSE_SCHEMA
            )
            result.data = normalize_chunk_data(result.data, page_notes)
            return ChunkSummary(chunk_index, start_page, end_page, result.data), result

        # A full batch may legitimately be too large, but pack_prompt_batches
        # also requires every *single* item to fit.  Fact-rich page notes can
        # otherwise exceed the limit by a few tokens once inherited memory and
        # the response schema are added.  Reduce inherited context first; the
        # database copy of both the page note and chapter memory stays intact.
        bounded_notes, bounded_prior = _fit_single_page_prompts(
            page_notes,
            prior_memory,
            self.quality,
        )
        direct_prompt = chunk_prompt(
            start_page, end_page, bounded_notes, bounded_prior, self.quality
        )
        if fits_prompt(direct_prompt, DEEP_PROMPT_TOKEN_BUDGET):
            result = self.client.text_json(
                direct_prompt, deep=True, response_schema=CHUNK_RESPONSE_SCHEMA
            )
            result.data = normalize_chunk_data(result.data, page_notes)
            return ChunkSummary(chunk_index, start_page, end_page, result.data), result

        calls: list[LLMCallResult] = []
        partials: list[dict] = []

        def render_notes(batch: list[dict]) -> str:
            return chunk_prompt(
                int(batch[0].get("page_index", start_page)),
                int(batch[-1].get("page_index", end_page)),
                batch,
                bounded_prior,
                self.quality,
            )

        for batch in pack_prompt_batches(
            bounded_notes, render_notes, DEEP_PROMPT_TOKEN_BUDGET
        ):
            batch_start = int(batch[0].get("page_index", start_page))
            batch_end = int(batch[-1].get("page_index", batch_start))
            call = self.client.text_json(
                chunk_prompt(
                    batch_start,
                    batch_end,
                    batch,
                    bounded_prior,
                    self.quality,
                ),
                deep=True,
                response_schema=CHUNK_RESPONSE_SCHEMA,
            )
            calls.append(call)
            partials.append(
                {"start_page": batch_start, "end_page": batch_end, "summary": call.data}
            )

        while len(partials) > 1:
            bounded_partials, bounded_prior = _fit_single_partial_prompts(
                partials,
                prior_memory,
                self.quality,
                start_page,
                end_page,
            )

            def render_partials(batch: list[dict]) -> str:
                return chunk_prompt(
                    int(batch[0].get("start_page", start_page)),
                    int(batch[-1].get("end_page", end_page)),
                    batch,
                    bounded_prior,
                    self.quality,
                )

            batches = pack_prompt_batches(
                bounded_partials, render_partials, DEEP_PROMPT_TOKEN_BUDGET
            )
            next_level: list[dict] = []
            for batch in batches:
                batch_start = int(batch[0].get("start_page", start_page))
                batch_end = int(batch[-1].get("end_page", end_page))
                call = self.client.text_json(
                    render_partials(batch),
                    deep=True,
                    response_schema=CHUNK_RESPONSE_SCHEMA,
                )
                calls.append(call)
                next_level.append(
                    {"start_page": batch_start, "end_page": batch_end, "summary": call.data}
                )
            if len(next_level) >= len(partials):
                reduced = [compact_value(item, 170) for item in next_level]
                retry_batches = pack_prompt_batches(
                    reduced, render_partials, DEEP_PROMPT_TOKEN_BUDGET
                )
                if len(retry_batches) >= len(next_level):
                    raise RuntimeError("階層チャンク統合が収束しませんでした。入力予算を確認してください。")
                partials = reduced
                continue
            partials = next_level

        final_data = normalize_chunk_data(partials[0]["summary"], page_notes)
        aggregate = LLMCallResult(
            data=final_data,
            elapsed_seconds=sum(call.elapsed_seconds for call in calls),
            retry_count=sum(call.retry_count for call in calls),
            json_failed_once=any(call.json_failed_once for call in calls),
        )
        return ChunkSummary(chunk_index, start_page, end_page, final_data), aggregate


def _fit_single_page_prompts(
    page_notes: list[dict],
    prior_memory: dict,
    quality: str,
) -> tuple[list[dict], dict]:
    """Fit every atomic page prompt without changing persisted reading notes."""

    notes = [compact_page_note(note) for note in page_notes]

    def all_fit(candidate_notes: list[dict], candidate_prior: dict) -> bool:
        for note in candidate_notes:
            page_index = int(note.get("page_index", 0))
            prompt = chunk_prompt(
                page_index,
                page_index,
                [note],
                candidate_prior,
                quality,
            )
            if not fits_prompt(prompt, DEEP_PROMPT_TOKEN_BUDGET):
                return False
        return True

    # Context inherited from earlier pages/chapters is expendable in this
    # particular call because it remains available in SQLite and later chapter
    # integration. Preserve the current page's facts at full projection first.
    for prior_budget in (420, 340, 280, 220, 160, 96):
        prior = compact_prior_memory(prior_memory, prior_budget)
        if all_fit(notes, prior):
            return notes, prior
    if all_fit(notes, {}):
        return notes, {}

    # Only a pathological single page reaches here. Gradually project its
    # prompt copy while retaining fact-first key order. The complete note in
    # SQLite is never overwritten.
    for note_budget in (440, 380, 320, 260, 220, 180, 140, 96):
        reduced_notes = [
            compact_page_note(note, note_budget) for note in page_notes
        ]
        if all_fit(reduced_notes, {}):
            return reduced_notes, {}
    raise RuntimeError(
        "単一ページの統合素材を安全なコンテキスト内へ縮小できませんでした。"
    )


def _fit_single_partial_prompts(
    partials: list[dict],
    prior_memory: dict,
    quality: str,
    default_start: int,
    default_end: int,
) -> tuple[list[dict], dict]:
    """Fit atomic lower-level summaries before the next reduction level."""

    bounded = [compact_value(item, 300) for item in partials]

    def all_fit(items: list[dict], prior: dict) -> bool:
        return all(
            fits_prompt(
                chunk_prompt(
                    int(item.get("start_page", default_start)),
                    int(item.get("end_page", default_end)),
                    [item],
                    prior,
                    quality,
                ),
                DEEP_PROMPT_TOKEN_BUDGET,
            )
            for item in items
        )

    for prior_budget in (420, 340, 280, 220, 160, 96):
        prior = compact_prior_memory(prior_memory, prior_budget)
        if all_fit(bounded, prior):
            return bounded, prior
    if all_fit(bounded, {}):
        return bounded, {}
    for item_budget in (260, 220, 180, 140, 96):
        reduced = [compact_value(item, item_budget) for item in partials]
        if all_fit(reduced, {}):
            return reduced, {}
    raise RuntimeError(
        "単一の中間統合素材を安全なコンテキスト内へ縮小できませんでした。"
    )


def normalize_chunk_data(data: dict, page_notes: list[dict]) -> dict:
    """Normalize fact-first chunk JSON and preserve explicit read failures."""

    if not isinstance(data, dict):
        data = {}
    normalized = dict(data)
    normalized.setdefault("range_summary", data.get("summary", ""))
    normalized.setdefault("event_timeline", data.get("range_events", []))
    normalized.setdefault("new_facts", data.get("new_facts", []))
    normalized.setdefault(
        "character_actions_and_emotions", data.get("character_states", [])
    )
    normalized.setdefault("relationship_changes", data.get("relationship_changes", []))
    normalized.setdefault("important_utterances", data.get("important_utterances", []))
    normalized.setdefault("new_clues", data.get("important_foreshadowing", []))
    normalized.setdefault("new_questions", data.get("unresolved_items", []))
    normalized.setdefault("continuing_questions", data.get("continuing_questions", []))
    normalized.setdefault("resolved_questions", data.get("resolved_questions", []))
    normalized.setdefault("resolved_clues", data.get("resolved_clues", []))
    normalized.setdefault("memorable_scenes", data.get("memorable_developments", []))
    legacy_analysis = [
        *(data.get("oddities", []) or []),
        *(data.get("revisions_to_previous_interpretations", []) or []),
    ]
    normalized.setdefault("analysis", legacy_analysis)
    normalized.setdefault("emotional_impact", data.get("emotional_impact", []))
    normalized.setdefault("predictions_at_this_point", data.get("predictions_at_this_point", []))
    unreadable = list(data.get("unreadable_pages", []) or [])
    known_pages = {
        int(item.get("page_index", -1))
        for item in unreadable
        if isinstance(item, dict)
    }
    for note in page_notes:
        status = str(note.get("reading_status", "READABLE")).upper()
        if status not in {"PARTIAL", "UNREADABLE"}:
            continue
        page_index = int(note.get("page_index", 0))
        if page_index in known_pages:
            continue
        gaps = note.get("information_gaps", []) or []
        unreadable.append(
            {
                "page_index": page_index,
                "status": status,
                "reason": " / ".join(str(item) for item in gaps if str(item).strip())
                or ("内容判定不能" if status == "UNREADABLE" else "情報不足"),
            }
        )
    normalized["unreadable_pages"] = unreadable
    normalized["memorable_scenes"] = list(normalized.get("memorable_scenes", []) or [])[:3]
    normalized["emotional_impact"] = list(normalized.get("emotional_impact", []) or [])[:3]
    normalized.setdefault("confidence", data.get("confidence", 0.0))
    return normalized
