from __future__ import annotations

import base64
import io
import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from PIL import Image

from .config import LLMSettings
from .context_budget import (
    DEEP_PROMPT_TOKEN_BUDGET,
    VISION_PROMPT_TOKEN_BUDGET,
    estimate_tokens,
)
from .errors import LLMConnectionError, LLMResponseError, UnsafeEndpointError


EVIDENCE_LEVELS = ["FACT", "STRONG_INFERENCE", "SPECULATION", "UNCERTAIN"]
STATEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "maxLength": 120},
        "evidence_level": {"type": "string", "enum": EVIDENCE_LEVELS},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "basis": {"type": "string", "maxLength": 120},
    },
    "required": ["text", "evidence_level", "confidence"],
}
DIRECT_FACT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "maxLength": 140},
        "evidence_level": {"type": "string", "enum": ["FACT", "UNCERTAIN"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "basis": {"type": "string", "maxLength": 120},
    },
    "required": ["text", "evidence_level", "confidence"],
}
EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "maxLength": 150},
        "actor": {"type": "string", "maxLength": 50},
        "action": {"type": "string", "maxLength": 100},
        "target": {"type": "string", "maxLength": 60},
        "location": {"type": "string", "maxLength": 60},
        "outcome": {"type": "string", "maxLength": 110},
        "evidence_level": {"type": "string", "enum": ["FACT", "UNCERTAIN"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "text",
        "actor",
        "action",
        "target",
        "location",
        "outcome",
        "evidence_level",
        "confidence",
    ],
}
UTTERANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "speaker": {"type": "string", "maxLength": 50},
        "target": {"type": "string", "maxLength": 50},
        "meaning": {"type": "string", "maxLength": 140},
        "reaction_or_result": {"type": "string", "maxLength": 100},
        "evidence_level": {"type": "string", "enum": ["FACT", "UNCERTAIN"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "speaker",
        "target",
        "meaning",
        "reaction_or_result",
        "evidence_level",
        "confidence",
    ],
}
PAGE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reading_status": {
            "type": "string",
            "enum": ["READABLE", "PARTIAL", "UNREADABLE"],
        },
        "short_summary": {"type": "string", "maxLength": 180},
        "scene_location": {"type": "string", "maxLength": 80},
        "characters": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "maxLength": 60},
                    "role_or_action": {"type": "string", "maxLength": 120},
                    "psychology": {
                        "type": "array",
                        "maxItems": 1,
                        "items": STATEMENT_SCHEMA,
                    },
                    "emotion": {"type": "string", "maxLength": 80},
                    "evidence_scene": {"type": "string", "maxLength": 120},
                },
                "required": [
                    "name",
                    "role_or_action",
                    "psychology",
                    "emotion",
                    "evidence_scene",
                ],
            },
        },
        "events": {"type": "array", "maxItems": 4, "items": EVENT_SCHEMA},
        "important_utterances": {
            "type": "array",
            "maxItems": 3,
            "items": UTTERANCE_SCHEMA,
        },
        "new_facts": {"type": "array", "maxItems": 3, "items": DIRECT_FACT_SCHEMA},
        "apparent_emotions": {"type": "array", "maxItems": 3, "items": STATEMENT_SCHEMA},
        "relationship_updates": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "maxLength": 60},
                    "target": {"type": "string", "maxLength": 60},
                    "change": {"type": "string", "maxLength": 120},
                    "evidence_level": {"type": "string", "enum": EVIDENCE_LEVELS},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["source", "target", "change", "evidence_level", "confidence"],
            },
        },
        "foreshadowing_or_suspicious_points": {
            "type": "array",
            "maxItems": 3,
            "items": STATEMENT_SCHEMA,
        },
        "unresolved_questions": {"type": "array", "maxItems": 3, "items": STATEMENT_SCHEMA},
        "important_details": {"type": "array", "maxItems": 3, "items": STATEMENT_SCHEMA},
        "information_gaps": {
            "type": "array",
            "maxItems": 3,
            "items": {"type": "string", "maxLength": 100},
        },
        "continuity_from_previous_page": {"type": "string", "maxLength": 160},
        "possible_chapter_boundary": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "readability": {"type": "number", "minimum": 0, "maximum": 1},
        "important_score": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "reading_status",
        "short_summary",
        "scene_location",
        "characters",
        "events",
        "important_utterances",
        "new_facts",
        "apparent_emotions",
        "relationship_updates",
        "foreshadowing_or_suspicious_points",
        "unresolved_questions",
        "important_details",
        "information_gaps",
        "continuity_from_previous_page",
        "possible_chapter_boundary",
        "confidence",
        "readability",
        "important_score",
    ],
}


@dataclass
class LLMCallResult:
    data: dict[str, Any]
    elapsed_seconds: float
    retry_count: int = 0
    json_failed_once: bool = False


class LocalLLMClient:
    """OpenAI-compatible client with an Ollama-native fast path.

    Network calls are refused unless the endpoint is loopback. No telemetry or
    cloud fallback exists.
    """

    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings
        self.runtime_kind = "unknown"

    def update_settings(self, settings: LLMSettings) -> None:
        self.settings = settings
        self.runtime_kind = "unknown"

    def ensure_local(self) -> None:
        if not self.settings.is_local():
            raise UnsafeEndpointError(
                "localhost以外は使用できません。この設定では画像や読書メモが外部へ送信される可能性があります。"
            )

    def check_connection(self) -> tuple[bool, str, list[str]]:
        self.ensure_local()
        try:
            models_url = self._openai_base() + "/models"
            response = self._request_json(models_url, method="GET", payload=None, timeout=5.0)
            models = [str(item.get("id")) for item in response.get("data", []) if item.get("id")]
            self.runtime_kind = "openai-compatible"
            if self._looks_like_ollama():
                self.runtime_kind = "ollama"
            return True, self.runtime_kind, models
        except Exception as exc:
            return False, str(exc), []

    @staticmethod
    def detect_local_servers() -> list[tuple[str, list[str]]]:
        found: list[tuple[str, list[str]]] = []
        for base in (
            "http://127.0.0.1:11434/v1",
            "http://127.0.0.1:1234/v1",
            "http://127.0.0.1:8080/v1",
            "http://127.0.0.1:5000/v1",
        ):
            settings = LLMSettings(base_url=base, timeout_seconds=2.0)
            client = LocalLLMClient(settings)
            ok, _, models = client.check_connection()
            if ok:
                found.append((base, models))
        return found

    def vision_json(self, prompt: str, image: Image.Image, deep: bool = False) -> LLMCallResult:
        self.ensure_local()
        estimated = estimate_tokens(prompt)
        if estimated > VISION_PROMPT_TOKEN_BUDGET:
            raise LLMResponseError(
                "Vision入力が安全なコンテキスト予算を超えました"
                f"（推定{estimated} tokens）。画像送信前に停止しました。"
            )
        encoded = self._encode_image(image)
        try:
            if self._use_ollama_native():
                messages = [{"role": "user", "content": prompt, "images": [encoded]}]
                return self._call_ollama(
                    messages,
                    deep=deep,
                    response_schema=PAGE_RESPONSE_SCHEMA,
                )
            data_url = f"data:image/jpeg;base64,{encoded}"
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ]
            return self._call_openai(messages, deep=deep)
        finally:
            encoded = ""  # release the transient base64 reference promptly

    def text_json(
        self,
        prompt: str,
        deep: bool = True,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMCallResult:
        self.ensure_local()
        estimated = estimate_tokens(prompt)
        if estimated > DEEP_PROMPT_TOKEN_BUDGET:
            raise LLMResponseError(
                "統合入力が安全なコンテキスト予算を超えました"
                f"（推定{estimated} tokens）。LLM送信前に停止しました。"
            )
        messages = [{"role": "user", "content": prompt}]
        if self._use_ollama_native():
            return self._call_ollama(
                messages,
                deep=deep,
                response_schema=response_schema,
            )
        return self._call_openai(messages, deep=deep)

    def _call_openai(self, messages: list[dict[str, Any]], deep: bool) -> LLMCallResult:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.deep_max_tokens if deep else self.settings.page_max_tokens,
            "stream": False,
        }
        return self._retry_call(
            self._openai_base() + "/chat/completions",
            payload,
            parser=lambda body: body["choices"][0]["message"].get("content", ""),
        )

    def _call_ollama(
        self,
        messages: list[dict[str, Any]],
        deep: bool,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMCallResult:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "stream": False,
            "format": response_schema or "json",
            "keep_alive": "10m",
            "options": {
                "temperature": self.settings.temperature,
                "num_predict": self.settings.deep_max_tokens if deep else self.settings.page_max_tokens,
            },
        }
        if self.settings.thinking_control == "auto":
            # Ollama's common 4096-token default lets Qwen consume the entire
            # remaining window as hidden thinking and return an empty JSON body.
            # Hierarchical multi-pass integration supplies depth without that
            # failure mode. Users with a larger configured runtime context can
            # still explicitly select "on".
            payload["think"] = False
        elif self.settings.thinking_control in {"on", "off"}:
            payload["think"] = self.settings.thinking_control == "on"
        return self._retry_call(
            self._server_root() + "/api/chat",
            payload,
            parser=self._parse_ollama_content,
        )

    @staticmethod
    def _parse_ollama_content(body: dict[str, Any]) -> str:
        content = str(body.get("message", {}).get("content", "") or "")
        if not content.strip():
            reason = str(body.get("done_reason", "") or "")
            counts = (
                f"prompt={body.get('prompt_eval_count', '?')}, "
                f"output={body.get('eval_count', '?')}"
            )
            raise LLMResponseError(
                f"Ollamaの応答本文が空です（終了理由={reason or '不明'}, {counts}）。"
            )
        return content

    def _retry_call(self, url: str, payload: dict[str, Any], parser: Any) -> LLMCallResult:
        started = time.perf_counter()
        last_error: Exception | None = None
        json_failed_once = False
        for attempt in range(self.settings.retries + 1):
            body: dict[str, Any] | None = None
            try:
                body = self._request_json(url, "POST", payload, self.settings.timeout_seconds)
                content = parser(body)
                parsed = extract_json_object(content)
                return LLMCallResult(parsed, time.perf_counter() - started, attempt, json_failed_once)
            except (json.JSONDecodeError, KeyError, TypeError, LLMResponseError) as exc:
                if body and (body.get("done_reason") or body.get("eval_count") is not None):
                    last_error = LLMResponseError(
                        f"{exc} (Ollama終了理由={body.get('done_reason', '不明')}, "
                        f"prompt={body.get('prompt_eval_count', '?')}, "
                        f"output={body.get('eval_count', '?')})"
                    )
                else:
                    last_error = exc
                json_failed_once = True
                options = payload.get("options")
                if isinstance(options, dict):
                    options["temperature"] = 0
            except (
                urllib.error.URLError,
                TimeoutError,
                socket.timeout,
                ConnectionError,
                LLMConnectionError,
            ) as exc:
                last_error = exc
            if attempt < self.settings.retries:
                time.sleep(min(2.0, 0.35 * (2**attempt)))
        raise LLMResponseError(f"LLM/JSON応答に失敗しました（{self.settings.retries + 1}回試行）: {last_error}")

    def _request_json(
        self,
        url: str,
        method: str,
        payload: dict[str, Any] | None,
        timeout: float,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read(1200).decode("utf-8", errors="replace")
            raise LLMConnectionError(f"LLM HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise LLMConnectionError(f"ローカルLLMへ接続できません: {exc}") from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise LLMResponseError("LLMサーバーが不正なJSONを返しました。") from exc

    def _use_ollama_native(self) -> bool:
        if self.runtime_kind == "unknown":
            self.runtime_kind = "ollama" if self._looks_like_ollama() else "openai-compatible"
        return self.runtime_kind == "ollama"

    def _looks_like_ollama(self) -> bool:
        try:
            body = self._request_json(self._server_root() + "/api/version", "GET", None, 2.0)
            return bool(body.get("version"))
        except Exception:
            return False

    def _openai_base(self) -> str:
        base = self.settings.base_url.rstrip("/")
        return base if base.endswith("/v1") else base + "/v1"

    def _server_root(self) -> str:
        base = self.settings.base_url.rstrip("/")
        return base[:-3] if base.endswith("/v1") else base

    @staticmethod
    def _encode_image(image: Image.Image) -> str:
        working = image.convert("RGB")
        max_edge = 1800
        if max(working.size) > max_edge:
            working.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        working.save(buffer, format="JPEG", quality=88, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        buffer.close()
        working.close()
        return encoded


def extract_json_object(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        raise LLMResponseError("JSONオブジェクトではなく配列が返されました。")
    text = str(content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:-1] if len(lines) >= 3 else lines
        text = "\n".join(lines)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise LLMResponseError("応答内にJSONオブジェクトがありません。")
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise LLMResponseError("JSONオブジェクト形式ではありません。")
    return value
