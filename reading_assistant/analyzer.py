from __future__ import annotations

import json

from PIL import Image

from .errors import ExcessiveTranscriptionError
from .llm_client import LLMCallResult, LocalLLMClient
from .models import PageAnalysis
from .prompts import page_prompt


class PageAnalyzer:
    def __init__(self, client: LocalLLMClient, quality: str = "BALANCED") -> None:
        self.client = client
        self.quality = quality

    def analyze(
        self,
        image: Image.Image,
        page_index: int,
        recent_context: dict,
    ) -> tuple[PageAnalysis, LLMCallResult]:
        result = self.client.vision_json(
            page_prompt(page_index, recent_context, self.quality),
            image,
            deep=False,
        )
        self._guard_against_transcription(result.data)
        return PageAnalysis.from_dict(result.data, page_index), result

    @staticmethod
    def _guard_against_transcription(data: dict) -> None:
        summary = str(data.get("short_summary", ""))
        serialized = json.dumps(data, ensure_ascii=False)
        longest = max((len(str(value)) for value in _walk_scalars(data)), default=0)
        if len(summary) > 900 or len(serialized) > 9000 or longest > 1400:
            raise ExcessiveTranscriptionError(
                "モデルが本文を大量転記した可能性があるため、この応答は保存しません。"
            )


def _walk_scalars(value):
    if isinstance(value, dict):
        for nested in value.values():
            yield from _walk_scalars(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_scalars(nested)
    else:
        yield value

