from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EvidenceLevel(str, Enum):
    FACT = "FACT"
    STRONG_INFERENCE = "STRONG_INFERENCE"
    SPECULATION = "SPECULATION"
    UNCERTAIN = "UNCERTAIN"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    def validate(self, minimum: int = 80) -> None:
        if self.width < minimum or self.height < minimum:
            raise ValueError(f"キャプチャ領域が小さすぎます: {self.width}x{self.height}")

    def to_dict(self) -> dict[str, int]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Rect":
        return cls(**{k: int(value[k]) for k in ("left", "top", "right", "bottom")})


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    rect: Rect
    process_id: int = 0

    def display_name(self) -> str:
        return f"{self.title}  [0x{self.handle:X}]"


@dataclass
class ClassifiedStatement:
    text: str
    evidence_level: str = EvidenceLevel.UNCERTAIN.value
    confidence: float = 0.5
    basis: str = ""

    @classmethod
    def from_value(cls, value: Any) -> "ClassifiedStatement":
        if isinstance(value, str):
            return cls(text=value)
        if not isinstance(value, dict):
            return cls(text=str(value))
        level = str(value.get("evidence_level", EvidenceLevel.UNCERTAIN.value)).upper()
        if level not in {item.value for item in EvidenceLevel}:
            level = EvidenceLevel.UNCERTAIN.value
        return cls(
            text=str(value.get("text", "")).strip(),
            evidence_level=level,
            confidence=_float01(value.get("confidence", 0.5)),
            basis=str(value.get("basis", "")).strip(),
        )


@dataclass
class CharacterObservation:
    name: str
    role_or_action: str = ""
    psychology: list[ClassifiedStatement] = field(default_factory=list)
    character_id: str = ""
    emotion: str = ""
    evidence_scene: str = ""

    @classmethod
    def from_value(cls, value: Any) -> "CharacterObservation":
        if isinstance(value, str):
            return cls(name=value)
        if not isinstance(value, dict):
            return cls(name=str(value))
        psychology = value.get("psychology", [])
        if isinstance(psychology, (str, dict)):
            psychology = [psychology]
        return cls(
            name=str(value.get("name", "不明")).strip() or "不明",
            role_or_action=str(value.get("role_or_action", value.get("action", ""))).strip(),
            psychology=[ClassifiedStatement.from_value(item) for item in psychology],
            character_id=str(value.get("character_id", "")).strip(),
            emotion=str(value.get("emotion", "")).strip(),
            evidence_scene=str(value.get("evidence_scene", value.get("emotion_basis", ""))).strip(),
        )


@dataclass
class EventObservation:
    text: str
    actor: str = ""
    action: str = ""
    target: str = ""
    location: str = ""
    outcome: str = ""
    evidence_level: str = EvidenceLevel.FACT.value
    confidence: float = 0.5
    basis: str = ""
    event_id: str = ""

    @classmethod
    def from_value(cls, value: Any) -> "EventObservation":
        if not isinstance(value, dict):
            return cls(text=str(value), evidence_level=EvidenceLevel.UNCERTAIN.value)
        statement = ClassifiedStatement.from_value(value)
        action = str(value.get("action", "")).strip()
        actor = str(value.get("actor", "")).strip()
        target = str(value.get("target", "")).strip()
        outcome = str(value.get("outcome", value.get("result", ""))).strip()
        text = str(value.get("text", "")).strip()
        if not text:
            text = " / ".join(part for part in (actor, action, target, outcome) if part)
        return cls(
            text=text,
            actor=actor,
            action=action,
            target=target,
            location=str(value.get("location", "")).strip(),
            outcome=outcome,
            evidence_level=statement.evidence_level,
            confidence=statement.confidence,
            basis=statement.basis,
            event_id=str(value.get("event_id", "")).strip(),
        )


@dataclass
class UtteranceObservation:
    speaker: str
    target: str = ""
    meaning: str = ""
    reaction_or_result: str = ""
    evidence_level: str = EvidenceLevel.FACT.value
    confidence: float = 0.5

    @classmethod
    def from_value(cls, value: Any) -> "UtteranceObservation":
        if not isinstance(value, dict):
            return cls(speaker="不明", meaning=str(value), evidence_level=EvidenceLevel.UNCERTAIN.value)
        level = str(value.get("evidence_level", EvidenceLevel.FACT.value)).upper()
        if level not in {item.value for item in EvidenceLevel}:
            level = EvidenceLevel.UNCERTAIN.value
        return cls(
            speaker=str(value.get("speaker", "不明")).strip() or "不明",
            target=str(value.get("target", "")).strip(),
            meaning=str(value.get("meaning", value.get("text", ""))).strip(),
            reaction_or_result=str(value.get("reaction_or_result", value.get("result", ""))).strip(),
            evidence_level=level,
            confidence=_float01(value.get("confidence", 0.5)),
        )


@dataclass
class RelationshipObservation:
    source: str
    target: str
    change: str
    evidence_level: str = EvidenceLevel.UNCERTAIN.value
    confidence: float = 0.5
    relationship_id: str = ""
    basis: str = ""

    @classmethod
    def from_value(cls, value: Any) -> "RelationshipObservation":
        if not isinstance(value, dict):
            return cls("不明", "不明", str(value))
        statement = ClassifiedStatement.from_value(value)
        return cls(
            source=str(value.get("source", "不明")).strip() or "不明",
            target=str(value.get("target", "不明")).strip() or "不明",
            change=str(value.get("change", value.get("text", ""))).strip(),
            evidence_level=statement.evidence_level,
            confidence=statement.confidence,
            relationship_id=str(value.get("relationship_id", "")).strip(),
            basis=str(value.get("basis", "")).strip(),
        )


@dataclass
class PageAnalysis:
    page_index: int
    short_summary: str
    characters: list[CharacterObservation] = field(default_factory=list)
    events: list[EventObservation] = field(default_factory=list)
    apparent_emotions: list[ClassifiedStatement] = field(default_factory=list)
    relationship_updates: list[RelationshipObservation] = field(default_factory=list)
    foreshadowing_or_suspicious_points: list[ClassifiedStatement] = field(default_factory=list)
    unresolved_questions: list[ClassifiedStatement] = field(default_factory=list)
    important_details: list[ClassifiedStatement] = field(default_factory=list)
    important_utterances: list[UtteranceObservation] = field(default_factory=list)
    new_facts: list[ClassifiedStatement] = field(default_factory=list)
    reading_status: str = "READABLE"
    scene_location: str = ""
    information_gaps: list[str] = field(default_factory=list)
    continuity_from_previous_page: str = ""
    possible_chapter_boundary: bool = False
    confidence: float = 0.5
    readability: float = 0.5
    important_score: float = 0.5
    created_at: str = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, value: dict[str, Any], page_index: int) -> "PageAnalysis":
        def statements(key: str) -> list[ClassifiedStatement]:
            raw = value.get(key, [])
            if isinstance(raw, (str, dict)):
                raw = [raw]
            return [ClassifiedStatement.from_value(item) for item in (raw or [])]

        chars = value.get("characters", [])
        if isinstance(chars, (str, dict)):
            chars = [chars]
        rels = value.get("relationship_updates", [])
        if isinstance(rels, (str, dict)):
            rels = [rels]
        events = value.get("events", [])
        if isinstance(events, (str, dict)):
            events = [events]
        utterances = value.get("important_utterances", [])
        if isinstance(utterances, (str, dict)):
            utterances = [utterances]
        readability = _float01(value.get("readability", 0.5))
        reading_status = str(value.get("reading_status", "")).upper()
        if reading_status not in {"READABLE", "PARTIAL", "UNREADABLE"}:
            reading_status = "UNREADABLE" if readability < 0.15 else "READABLE"
        gaps = value.get("information_gaps", [])
        if isinstance(gaps, str):
            gaps = [gaps]
        analysis = cls(
            page_index=page_index,
            short_summary=str(value.get("short_summary", "読み取り内容を要約できませんでした。")).strip(),
            characters=[CharacterObservation.from_value(item) for item in (chars or [])],
            events=[EventObservation.from_value(item) for item in (events or [])],
            apparent_emotions=statements("apparent_emotions"),
            relationship_updates=[RelationshipObservation.from_value(item) for item in (rels or [])],
            foreshadowing_or_suspicious_points=statements("foreshadowing_or_suspicious_points"),
            unresolved_questions=statements("unresolved_questions"),
            important_details=statements("important_details"),
            important_utterances=[
                UtteranceObservation.from_value(item)
                for item in (utterances or [])
            ],
            new_facts=statements("new_facts"),
            reading_status=reading_status,
            scene_location=str(value.get("scene_location", "")).strip(),
            information_gaps=[str(item).strip() for item in (gaps or []) if str(item).strip()],
            continuity_from_previous_page=str(value.get("continuity_from_previous_page", "")).strip(),
            possible_chapter_boundary=bool(value.get("possible_chapter_boundary", False)),
            confidence=_float01(value.get("confidence", 0.5)),
            readability=readability,
            important_score=_float01(value.get("important_score", 0.5)),
        )
        if reading_status == "UNREADABLE":
            analysis.short_summary = "内容判定不能（読み取り失敗または情報不足）"
            analysis.characters = []
            analysis.events = []
            analysis.apparent_emotions = []
            analysis.relationship_updates = []
            analysis.foreshadowing_or_suspicious_points = []
            analysis.unresolved_questions = []
            analysis.important_details = []
            analysis.important_utterances = []
            analysis.new_facts = []
            if not analysis.information_gaps:
                analysis.information_gaps = ["ページ内容を信頼できる形で判定できなかった"]
        return analysis

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PageRecord:
    analysis: PageAnalysis
    page_hash: str
    capture_index: int
    source_part: str = "single"
    processing_seconds: float = 0.0
    retry_count: int = 0
    json_failed_once: bool = False
    user_important: bool = False


@dataclass
class ChunkSummary:
    chunk_index: int
    start_page: int
    end_page: int
    summary: dict[str, Any]
    created_at: str = field(default_factory=utc_now)


@dataclass
class ChapterCheckpoint:
    chapter_index: int
    start_page: int
    end_page: int
    summary: dict[str, Any]
    carryover: dict[str, Any]
    created_at: str = field(default_factory=utc_now)


@dataclass
class CaptureAssessment:
    page_hash: str
    mean_brightness: float
    stddev: float
    hamming_from_previous: int | None
    duplicate: bool
    suspiciously_similar: bool
    black_or_flat: bool
    warning: str = ""


def _float01(value: Any) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.5
