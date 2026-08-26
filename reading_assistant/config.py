from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse


class QualityPreset(str, Enum):
    FAST = "FAST"
    BALANCED = "BALANCED"
    DEEP = "DEEP"


class ReadingMode(str, Enum):
    SEMI_AUTO = "半自動"
    MANUAL = "手動"


class SpreadMode(str, Enum):
    SINGLE = "1ページ"
    DOUBLE = "2ページ見開き"
    AUTO = "自動判定"


class ReadingDirection(str, Enum):
    AUTO = "自動"
    LEFT_TO_RIGHT = "左→右"
    RIGHT_TO_LEFT = "右→左"


@dataclass
class LLMSettings:
    base_url: str = "http://127.0.0.1:11434/v1"
    model: str = "qwen3.5:9b"
    api_key: str = ""
    temperature: float = 0.2
    page_max_tokens: int = 1200
    deep_max_tokens: int = 3500
    timeout_seconds: float = 180.0
    retries: int = 2
    # auto uses known controls only for a positively detected runtime.
    thinking_control: str = "auto"

    def is_local(self) -> bool:
        try:
            host = (urlparse(self.base_url).hostname or "").lower()
        except ValueError:
            return False
        return host in {"localhost", "127.0.0.1", "::1"}


@dataclass
class CaptureSettings:
    change_timeout_seconds: float = 8.0
    change_poll_seconds: float = 0.25
    stable_checks: int = 2
    duplicate_hamming_threshold: int = 3
    suspicious_hamming_threshold: int = 7
    black_mean_threshold: float = 5.0
    flat_stddev_threshold: float = 2.0
    turn_key: str = "Right"


@dataclass
class AppConfig:
    llm: LLMSettings = field(default_factory=LLMSettings)
    capture: CaptureSettings = field(default_factory=CaptureSettings)
    quality: str = QualityPreset.BALANCED.value
    reading_mode: str = ReadingMode.SEMI_AUTO.value
    spread_mode: str = SpreadMode.AUTO.value
    reading_direction: str = ReadingDirection.AUTO.value
    chunk_size: int = 20
    total_pages: int = 300
    recent_chunks_on_resume: int = 3
    hotkey_enabled: bool = True
    hotkey: str = "Ctrl+Shift+R"

    @classmethod
    def load(cls, path: Path) -> "AppConfig":
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        llm = LLMSettings(**raw.get("llm", {}))
        # Early builds saved 900, which can truncate a complete 13-field page
        # object on dense Japanese pages. Upgrade that legacy value in memory.
        llm.page_max_tokens = max(1200, llm.page_max_tokens)
        return cls(
            llm=llm,
            capture=CaptureSettings(**raw.get("capture", {})),
            **{k: v for k, v in raw.items() if k not in {"llm", "capture"}},
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        # API keys are accepted for the running process but never persisted.
        payload["llm"]["api_key"] = ""
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def user_data_dir() -> Path:
    override = os.environ.get("LRA_DATA_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "LocalReadingAssistant"
    return Path.home() / ".local-reading-assistant"


def default_config_path() -> Path:
    return user_data_dir() / "config.json"


def default_database_path() -> Path:
    return user_data_dir() / "reading_memory.sqlite3"


def default_reports_dir() -> Path:
    return user_data_dir() / "reports"
