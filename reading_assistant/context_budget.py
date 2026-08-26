from __future__ import annotations

import json
import math
from typing import Any, Callable, Iterable


# Ollama commonly starts models at 4096 context tokens. A 2600-token deep
# prompt left only about 1500 tokens for Pass 4, whose JSON was then truncated
# before its closing brace. These limits deliberately reserve at least roughly
# half of the context for structured output and runtime framing. Hierarchical
# reduction is slower, but remains reliable for 300-page books.
DEEP_PROMPT_TOKEN_BUDGET = 1600
REPORT_PROMPT_TOKEN_BUDGET = 1250
VISION_PROMPT_TOKEN_BUDGET = 1700


def estimate_tokens(text: str) -> int:
    """Conservative dependency-free estimate for mixed Japanese/ASCII prompts."""

    cjk = 0
    for char in text:
        code = ord(char)
        if (
            0x3000 <= code <= 0x30FF
            or 0x3400 <= code <= 0x9FFF
            or 0xF900 <= code <= 0xFAFF
        ):
            cjk += 1
    return cjk + math.ceil((len(text) - cjk) / 4)


def fits_prompt(prompt: str, budget: int = DEEP_PROMPT_TOKEN_BUDGET) -> bool:
    return estimate_tokens(prompt) <= budget


def compact_value(value: Any, token_budget: int) -> Any:
    """Return complete JSON under a token budget without slicing serialized JSON.

    Lists retain both their beginning and end so chronology does not silently
    lose the latest state. This is a last-resort projection; callers should use
    hierarchical LLM reduction first when there are multiple independent items.
    """

    if token_budget < 32:
        raise ValueError("token_budget is too small")
    settings = (
        (500, 16, 8),
        (320, 10, 7),
        (220, 7, 6),
        (140, 5, 5),
        (90, 3, 4),
        (56, 2, 3),
        (32, 1, 2),
    )
    for max_string, max_list, max_depth in settings:
        projected = _project(value, max_string, max_list, max_depth, 0)
        if estimate_tokens(_json(projected)) <= token_budget:
            return projected

    # Preserve top-level labels and add values only while the complete JSON fits.
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, nested in value.items():
            candidate = dict(result)
            candidate[str(key)] = _project(nested, 24, 1, 1, 0)
            if estimate_tokens(_json(candidate)) <= token_budget:
                result = candidate
        return result
    return _project(value, 24, 1, 1, 0)


def pack_prompt_batches(
    items: Iterable[Any],
    render: Callable[[list[Any]], str],
    budget: int = DEEP_PROMPT_TOKEN_BUDGET,
) -> list[list[Any]]:
    """Pack ordered items so every rendered prompt fits the configured budget."""

    batches: list[list[Any]] = []
    current: list[Any] = []
    for item in items:
        candidate = [*current, item]
        if current and not fits_prompt(render(candidate), budget):
            batches.append(current)
            current = [item]
        else:
            current = candidate
        if not fits_prompt(render(current), budget):
            raise ValueError("単一の統合項目がコンテキスト予算を超えています。")
    if current:
        batches.append(current)
    return batches


def fit_payload(
    value: Any,
    render: Callable[[Any], str],
    prompt_budget: int,
) -> Any:
    """Project one already-integrated payload until its rendered prompt fits."""

    if fits_prompt(render(value), prompt_budget):
        return value
    for ratio in (0.82, 0.68, 0.54, 0.42, 0.32, 0.24, 0.16):
        projected = compact_value(value, max(48, int(prompt_budget * ratio)))
        if fits_prompt(render(projected), prompt_budget):
            return projected
    raise ValueError("統合済み素材をコンテキスト予算内へ収められません。")


def _project(
    value: Any,
    max_string: int,
    max_list: int,
    max_depth: int,
    depth: int,
) -> Any:
    if depth >= max_depth:
        if isinstance(value, (dict, list, tuple)):
            return "[階層要約済み]"
        return _scalar(value, max_string)
    if isinstance(value, dict):
        return {
            str(key): _project(nested, max_string, max_list, max_depth, depth + 1)
            for key, nested in value.items()
        }
    if isinstance(value, (list, tuple)):
        selected = _head_tail(list(value), max_list)
        return [
            _project(nested, max_string, max_list, max_depth, depth + 1)
            for nested in selected
        ]
    return _scalar(value, max_string)


def _head_tail(items: list[Any], limit: int) -> list[Any]:
    if len(items) <= limit:
        return items
    if limit <= 1:
        return [items[-1]]
    head = math.ceil(limit / 2)
    tail = limit - head
    return items[:head] + items[-tail:]


def _scalar(value: Any, limit: int) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value).strip().replace("\x00", "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
