from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

from .entity_tracking import enrich_and_track_entities, tracked_entities
from .models import ChapterCheckpoint, ChunkSummary, PageRecord, Rect, WindowInfo, utc_now


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS book (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    total_pages INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES book(id),
    status TEXT NOT NULL DEFAULT 'ready',
    quality TEXT NOT NULL,
    chunk_size INTEGER NOT NULL,
    settings_json TEXT NOT NULL DEFAULT '{}',
    capture_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    read_pages INTEGER NOT NULL DEFAULT 0,
    duplicate_pages INTEGER NOT NULL DEFAULT 0,
    failed_pages INTEGER NOT NULL DEFAULT 0,
    total_processing_seconds REAL NOT NULL DEFAULT 0,
    last_integrated_page INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS page_note (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    page_index INTEGER NOT NULL,
    capture_index INTEGER NOT NULL,
    source_part TEXT NOT NULL,
    image_hash TEXT NOT NULL,
    short_summary TEXT NOT NULL,
    analysis_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    readability REAL NOT NULL,
    important_score REAL NOT NULL,
    user_important INTEGER NOT NULL DEFAULT 0,
    processing_seconds REAL NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    json_failed_once INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, page_index)
);

CREATE INDEX IF NOT EXISTS idx_page_note_session_page ON page_note(session_id, page_index);
CREATE INDEX IF NOT EXISTS idx_page_note_hash ON page_note(session_id, image_hash);

CREATE TABLE IF NOT EXISTS user_note (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    page_index INTEGER NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunk_summary (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    start_page INTEGER NOT NULL,
    end_page INTEGER NOT NULL,
    summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS chapter_summary (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    chapter_index INTEGER NOT NULL,
    start_page INTEGER NOT NULL,
    end_page INTEGER NOT NULL,
    summary_json TEXT NOT NULL,
    carryover_json TEXT NOT NULL,
    markdown_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(session_id, chapter_index)
);

CREATE INDEX IF NOT EXISTS idx_chapter_session_page
ON chapter_summary(session_id, end_page);

CREATE TABLE IF NOT EXISTS character_state (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    character_name TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    page_index INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    change_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relationship_state (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    page_index INTEGER NOT NULL,
    source_name TEXT NOT NULL,
    target_name TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prediction (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    page_index INTEGER NOT NULL,
    prediction_text TEXT NOT NULL,
    evidence_level TEXT NOT NULL DEFAULT 'SPECULATION',
    confidence REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'open',
    revision_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS unresolved_question (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    page_index INTEGER NOT NULL,
    question_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS important_event (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    page_index INTEGER NOT NULL,
    event_text TEXT NOT NULL,
    evidence_level TEXT NOT NULL DEFAULT 'UNCERTAIN',
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS semantic_entity (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    entity_uid TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    canonical_key TEXT NOT NULL,
    label TEXT NOT NULL,
    status TEXT NOT NULL,
    first_page INTEGER NOT NULL,
    last_page INTEGER NOT NULL,
    first_chapter INTEGER,
    last_chapter INTEGER,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(session_id, entity_uid),
    UNIQUE(session_id, entity_type, canonical_key)
);

CREATE INDEX IF NOT EXISTS idx_semantic_entity_session_type
ON semantic_entity(session_id, entity_type, status);

CREATE TABLE IF NOT EXISTS semantic_entity_history (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    entity_uid TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_index INTEGER NOT NULL,
    page_index INTEGER NOT NULL,
    chapter_index INTEGER,
    status TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, entity_uid, source_kind, source_index)
);

CREATE TABLE IF NOT EXISTS calibration_run (
    id INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES session(id) ON DELETE CASCADE,
    metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


FORBIDDEN_KEYS = {
    "ocr",
    "ocr_text",
    "raw_text",
    "full_text",
    "transcription",
    "page_image",
    "image_bytes",
    "base64",
}


class ReadingMemory:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self.connection.executescript(SCHEMA)
            self.connection.commit()

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self.connection
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

    def create_session(
        self,
        title: str,
        total_pages: int,
        quality: str,
        chunk_size: int,
        settings_snapshot: dict[str, Any],
    ) -> int:
        now = utc_now()
        safe_settings = dict(settings_snapshot)
        safe_settings.pop("api_key", None)
        with self.transaction() as db:
            cursor = db.execute(
                "INSERT INTO book(title,total_pages,created_at,updated_at) VALUES(?,?,?,?)",
                (title.strip() or "無題の本", max(0, total_pages), now, now),
            )
            book_id = int(cursor.lastrowid)
            cursor = db.execute(
                """INSERT INTO session(book_id,status,quality,chunk_size,settings_json,started_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (book_id, "ready", quality, chunk_size, _safe_json(safe_settings), now, now),
            )
            return int(cursor.lastrowid)

    def list_resumable_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                """SELECT s.id, b.title, b.total_pages, s.status, s.read_pages, s.updated_at,
                          s.last_integrated_page, s.quality
                   FROM session s JOIN book b ON b.id=s.book_id
                   WHERE s.status != 'finished' ORDER BY s.updated_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def get_session(self, session_id: int) -> dict[str, Any]:
        with self._lock:
            row = self.connection.execute(
                """SELECT s.*, b.title, b.total_pages FROM session s
                   JOIN book b ON b.id=s.book_id WHERE s.id=?""",
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"session {session_id}")
        result = dict(row)
        result["settings"] = json.loads(result.pop("settings_json") or "{}")
        result["capture"] = json.loads(result.pop("capture_json") or "{}")
        return result

    def set_capture(self, session_id: int, window: WindowInfo, rect: Rect) -> None:
        payload = {
            "window_handle": window.handle,
            "window_title": window.title,
            "window_process_id": window.process_id,
            "capture_rect": rect.to_dict(),
        }
        self._update_session(session_id, capture_json=_safe_json(payload))

    def update_status(self, session_id: int, status: str) -> None:
        values: dict[str, Any] = {"status": status}
        if status == "finished":
            values["finished_at"] = utc_now()
        self._update_session(session_id, **values)

    def record_page(self, session_id: int, record: PageRecord, user_note: str = "") -> None:
        analysis = sanitize_semantic_payload(record.analysis.to_dict())
        if not str(analysis.get("short_summary", "")).strip():
            raise ValueError("空のページ要約は保存できません。")
        payload = _safe_json(analysis)
        now = utc_now()
        with self.transaction() as db:
            db.execute(
                """INSERT INTO page_note(
                    session_id,page_index,capture_index,source_part,image_hash,short_summary,
                    analysis_json,confidence,readability,important_score,user_important,
                    processing_seconds,retry_count,json_failed_once,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    session_id,
                    record.analysis.page_index,
                    record.capture_index,
                    record.source_part,
                    record.page_hash,
                    record.analysis.short_summary[:1200],
                    payload,
                    record.analysis.confidence,
                    record.analysis.readability,
                    record.analysis.important_score,
                    int(record.user_important),
                    record.processing_seconds,
                    record.retry_count,
                    int(record.json_failed_once),
                    now,
                ),
            )
            if user_note.strip():
                db.execute(
                    "INSERT INTO user_note(session_id,page_index,note,created_at) VALUES(?,?,?,?)",
                    (session_id, record.analysis.page_index, user_note.strip()[:2000], now),
                )
            db.execute(
                """UPDATE session SET read_pages=read_pages+1,
                   total_processing_seconds=total_processing_seconds+?,updated_at=? WHERE id=?""",
                (record.processing_seconds, now, session_id),
            )

    def add_user_note(self, session_id: int, page_index: int, note: str) -> None:
        if not note.strip():
            return
        with self.transaction() as db:
            db.execute(
                "INSERT INTO user_note(session_id,page_index,note,created_at) VALUES(?,?,?,?)",
                (session_id, page_index, note.strip()[:2000], utc_now()),
            )

    def mark_page_important(self, session_id: int, page_index: int, important: bool = True) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE page_note SET user_important=? WHERE session_id=? AND page_index=?",
                (int(important), session_id, page_index),
            )

    def record_duplicate(self, session_id: int) -> None:
        self._increment(session_id, "duplicate_pages")

    def record_failure(self, session_id: int) -> None:
        self._increment(session_id, "failed_pages")

    def save_chunk(self, session_id: int, chunk: ChunkSummary) -> None:
        safe = sanitize_semantic_payload(chunk.summary)
        now = utc_now()
        with self.transaction() as db:
            safe = enrich_and_track_entities(
                db,
                session_id,
                safe,
                page_index=chunk.end_page,
                source_kind="chunk",
                source_index=chunk.chunk_index,
                chapter_index=None,
                now=now,
            )
            chunk.summary = safe
            db.execute(
                """INSERT OR REPLACE INTO chunk_summary(
                    session_id,chunk_index,start_page,end_page,summary_json,created_at
                ) VALUES(?,?,?,?,?,?)""",
                (
                    session_id,
                    chunk.chunk_index,
                    chunk.start_page,
                    chunk.end_page,
                    _safe_json(safe),
                    now,
                ),
            )
            db.execute(
                "UPDATE session SET last_integrated_page=?,updated_at=? WHERE id=?",
                (chunk.end_page, now, session_id),
            )
            self._persist_chunk_entities(db, session_id, chunk, safe, now)

    def save_chapter(
        self,
        session_id: int,
        chapter: ChapterCheckpoint,
        markdown_path: str = "",
    ) -> None:
        summary = sanitize_semantic_payload(chapter.summary)
        carryover = sanitize_semantic_payload(chapter.carryover)
        with self.transaction() as db:
            combined = dict(summary)
            combined["carryover"] = carryover
            enriched = enrich_and_track_entities(
                db,
                session_id,
                combined,
                page_index=chapter.end_page,
                source_kind="chapter",
                source_index=chapter.chapter_index,
                chapter_index=chapter.chapter_index,
                now=chapter.created_at,
            )
            carryover = enriched.pop("carryover", carryover)
            summary = enriched
            chapter.summary = summary
            chapter.carryover = carryover
            db.execute(
                """INSERT OR REPLACE INTO chapter_summary(
                    session_id,chapter_index,start_page,end_page,summary_json,
                    carryover_json,markdown_path,created_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    session_id,
                    chapter.chapter_index,
                    chapter.start_page,
                    chapter.end_page,
                    _safe_json(summary),
                    _safe_json(carryover),
                    str(markdown_path),
                    chapter.created_at,
                ),
            )

    def pages_since_last_integration(self, session_id: int) -> list[dict[str, Any]]:
        session = self.get_session(session_id)
        with self._lock:
            rows = self.connection.execute(
                """SELECT analysis_json FROM page_note
                   WHERE session_id=? AND page_index>? ORDER BY page_index""",
                (session_id, session["last_integrated_page"]),
            ).fetchall()
        return [json.loads(row["analysis_json"]) for row in rows]

    def page_notes(self, session_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT analysis_json FROM page_note WHERE session_id=? ORDER BY page_index",
                (session_id,),
            ).fetchall()
        return [json.loads(row["analysis_json"]) for row in rows]

    def chunk_summaries(self, session_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                """SELECT chunk_index,start_page,end_page,summary_json,created_at
                   FROM chunk_summary WHERE session_id=? ORDER BY chunk_index""",
                (session_id,),
            ).fetchall()
        return [
            {
                "chunk_index": row["chunk_index"],
                "start_page": row["start_page"],
                "end_page": row["end_page"],
                "summary": json.loads(row["summary_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def chapter_summaries(self, session_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                """SELECT chapter_index,start_page,end_page,summary_json,
                          carryover_json,markdown_path,created_at
                   FROM chapter_summary WHERE session_id=? ORDER BY chapter_index""",
                (session_id,),
            ).fetchall()
        return [
            {
                "chapter_index": row["chapter_index"],
                "start_page": row["start_page"],
                "end_page": row["end_page"],
                "summary": json.loads(row["summary_json"]),
                "carryover": json.loads(row["carryover_json"]),
                "markdown_path": row["markdown_path"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def chunks_since_last_chapter(self, session_id: int) -> list[dict[str, Any]]:
        chapters = self.chapter_summaries(session_id)
        boundary = int(chapters[-1]["end_page"]) if chapters else 0
        return [
            chunk
            for chunk in self.chunk_summaries(session_id)
            if int(chunk["end_page"]) > boundary
        ]

    def user_notes(self, session_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT page_index,note,created_at FROM user_note WHERE session_id=? ORDER BY page_index,id",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_context(self, session_id: int, chunks: int = 3) -> dict[str, Any]:
        chapter_rows = self.chapter_summaries(session_id)
        last_chapter = chapter_rows[-1] if chapter_rows else None
        chapter_boundary = int(last_chapter["end_page"]) if last_chapter else 0
        chunk_rows = [
            row
            for row in self.chunk_summaries(session_id)
            if int(row["end_page"]) > chapter_boundary
        ][-max(1, chunks) :]
        with self._lock:
            page_rows = self.connection.execute(
                """SELECT analysis_json FROM page_note WHERE session_id=? AND page_index>?
                   ORDER BY page_index DESC LIMIT 4""",
                (session_id, chapter_boundary),
            ).fetchall()
            character_rows = self.connection.execute(
                """SELECT c.character_name,c.state_json,c.page_index FROM character_state c
                   JOIN (SELECT character_name,MAX(id) id FROM character_state
                         WHERE session_id=? GROUP BY character_name) latest ON latest.id=c.id
                   ORDER BY c.character_name""",
                (session_id,),
            ).fetchall()
            prediction_rows = self.connection.execute(
                """SELECT page_index,prediction_text,evidence_level,confidence,status
                   FROM prediction WHERE session_id=? AND page_index>?
                   ORDER BY id DESC LIMIT 12""",
                (session_id, chapter_boundary),
            ).fetchall()
        pages = [json.loads(row["analysis_json"]) for row in reversed(page_rows)]
        return {
            "last_chapter_checkpoint": last_chapter,
            "recent_chunks": chunk_rows,
            "recent_pages": pages,
            "current_character_states": [
                {
                    "name": row["character_name"],
                    "page_index": row["page_index"],
                    "state": json.loads(row["state_json"]),
                }
                for row in character_rows
            ],
            "prediction_history_tail": [dict(row) for row in reversed(prediction_rows)],
            "tracked_entities": self.tracked_entities(session_id),
        }

    def next_page_index(self, session_id: int) -> int:
        with self._lock:
            row = self.connection.execute(
                "SELECT COALESCE(MAX(page_index),0)+1 value FROM page_note WHERE session_id=?",
                (session_id,),
            ).fetchone()
        return int(row["value"])

    def next_capture_index(self, session_id: int) -> int:
        with self._lock:
            row = self.connection.execute(
                "SELECT COALESCE(MAX(capture_index),0)+1 value FROM page_note WHERE session_id=?",
                (session_id,),
            ).fetchone()
        return int(row["value"])

    def last_page_hash(self, session_id: int) -> str | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT image_hash FROM page_note WHERE session_id=? ORDER BY page_index DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return str(row["image_hash"]) if row else None

    def metrics(self, session_id: int) -> dict[str, Any]:
        session = self.get_session(session_id)
        read = int(session["read_pages"])
        total_seconds = float(session["total_processing_seconds"])
        with self._lock:
            row = self.connection.execute(
                """SELECT COALESCE(SUM(retry_count),0) retries,
                          COALESCE(SUM(json_failed_once),0) json_failures,
                          COALESCE(AVG(confidence),0) avg_confidence,
                          COALESCE(AVG(readability),0) avg_readability
                   FROM page_note WHERE session_id=?""",
                (session_id,),
            ).fetchone()
            chunks = self.connection.execute(
                "SELECT COUNT(*) value FROM chunk_summary WHERE session_id=?",
                (session_id,),
            ).fetchone()["value"]
            chapters = self.connection.execute(
                "SELECT COUNT(*) value FROM chapter_summary WHERE session_id=?",
                (session_id,),
            ).fetchone()["value"]
        attempts = read + int(session["failed_pages"])
        return {
            "read_pages": read,
            "duplicate_pages": int(session["duplicate_pages"]),
            "failed_pages": int(session["failed_pages"]),
            "total_processing_seconds": total_seconds,
            "average_seconds_per_page": total_seconds / read if read else 0.0,
            "success_rate": read / attempts if attempts else 0.0,
            "retries": int(row["retries"]),
            "json_failures": int(row["json_failures"]),
            "average_confidence": float(row["avg_confidence"]),
            "average_readability": float(row["avg_readability"]),
            "chunks": int(chunks),
            "chapters": int(chapters),
            "last_integrated_page": int(session["last_integrated_page"]),
            "total_pages": int(session["total_pages"]),
            "chunk_size": int(session["chunk_size"]),
        }

    def save_calibration(self, session_id: int | None, metrics: dict[str, Any]) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO calibration_run(session_id,metrics_json,created_at) VALUES(?,?,?)",
                (session_id, _safe_json(metrics), utc_now()),
            )

    def all_semantic_material(self, session_id: int) -> dict[str, Any]:
        return {
            "session": {k: v for k, v in self.get_session(session_id).items() if k != "capture"},
            "page_notes": self.page_notes(session_id),
            "chunk_summaries": self.chunk_summaries(session_id),
            "chapter_summaries": self.chapter_summaries(session_id),
            "user_notes": self.user_notes(session_id),
            "tracked_entities": self.tracked_entities(session_id),
        }

    def tracked_entities(self, session_id: int) -> list[dict[str, Any]]:
        with self._lock:
            return tracked_entities(self.connection, session_id)

    def _persist_chunk_entities(
        self,
        db: sqlite3.Connection,
        session_id: int,
        chunk: ChunkSummary,
        summary: dict[str, Any],
        now: str,
    ) -> None:
        character_items = summary.get("character_actions_and_emotions") or summary.get("character_states")
        for state in _as_dict_list(character_items):
            name = str(state.get("name", "不明"))[:200]
            db.execute(
                """INSERT INTO character_state(session_id,character_name,chunk_index,page_index,
                   state_json,change_reason,created_at) VALUES(?,?,?,?,?,?,?)""",
                (
                    session_id,
                    name,
                    chunk.chunk_index,
                    chunk.end_page,
                    _safe_json(state),
                    str(state.get("changed_from_previous", ""))[:1200],
                    now,
                ),
            )
        for relation in _as_dict_list(summary.get("relationship_changes")):
            db.execute(
                """INSERT INTO relationship_state(session_id,chunk_index,page_index,source_name,
                   target_name,state_json,created_at) VALUES(?,?,?,?,?,?,?)""",
                (
                    session_id,
                    chunk.chunk_index,
                    chunk.end_page,
                    str(relation.get("source", "不明"))[:200],
                    str(relation.get("target", "不明"))[:200],
                    _safe_json(relation),
                    now,
                ),
            )
        for item in _as_statement_list(summary.get("predictions_at_this_point")):
            db.execute(
                """INSERT INTO prediction(session_id,chunk_index,page_index,prediction_text,
                   evidence_level,confidence,created_at) VALUES(?,?,?,?,?,?,?)""",
                (
                    session_id,
                    chunk.chunk_index,
                    chunk.end_page,
                    item["text"][:1600],
                    item["evidence_level"],
                    item["confidence"],
                    now,
                ),
            )
        question_items = [
            *(_as_dict_list(summary.get("new_questions"))),
            *(_as_dict_list(summary.get("continuing_questions"))),
        ]
        if not question_items:
            question_items = _as_statement_list(summary.get("unresolved_items"))
        for item in _as_statement_list(question_items):
            db.execute(
                """INSERT INTO unresolved_question(session_id,chunk_index,page_index,question_text,created_at)
                   VALUES(?,?,?,?,?)""",
                (session_id, chunk.chunk_index, chunk.end_page, item["text"][:1600], now),
            )
        event_items = summary.get("event_timeline") or summary.get("range_events")
        for item in _as_statement_list(event_items):
            db.execute(
                """INSERT INTO important_event(session_id,chunk_index,page_index,event_text,
                   evidence_level,confidence,created_at) VALUES(?,?,?,?,?,?,?)""",
                (
                    session_id,
                    chunk.chunk_index,
                    chunk.end_page,
                    item["text"][:1600],
                    item["evidence_level"],
                    item["confidence"],
                    now,
                ),
            )

    def _increment(self, session_id: int, column: str) -> None:
        if column not in {"duplicate_pages", "failed_pages"}:
            raise ValueError(column)
        with self.transaction() as db:
            db.execute(
                f"UPDATE session SET {column}={column}+1,updated_at=? WHERE id=?",
                (utc_now(), session_id),
            )

    def _update_session(self, session_id: int, **values: Any) -> None:
        allowed = {"status", "capture_json", "finished_at"}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"Unsupported fields: {unknown}")
        values["updated_at"] = utc_now()
        columns = ",".join(f"{key}=?" for key in values)
        params = list(values.values()) + [session_id]
        with self.transaction() as db:
            db.execute(f"UPDATE session SET {columns} WHERE id=?", params)


def sanitize_semantic_payload(value: Any, key: str = "") -> Any:
    if key.casefold() in FORBIDDEN_KEYS:
        raise ValueError(f"永続保存禁止フィールドです: {key}")
    if isinstance(value, bytes):
        raise ValueError("画像/バイナリデータは永続保存できません。")
    if isinstance(value, dict):
        return {str(k): sanitize_semantic_payload(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_semantic_payload(item, key) for item in value]
    if isinstance(value, str):
        if len(value) > 2400:
            raise ValueError("ページ読書メモ内の単一テキストが長すぎます（全文転記防止）。")
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _safe_json(value: Any) -> str:
    return json.dumps(sanitize_semantic_payload(value), ensure_ascii=False, separators=(",", ":"))


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _as_statement_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        value = [value] if value else []
    results: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            text = str(
                item.get(
                    "text",
                    item.get(
                        "event",
                        item.get("action", item.get("meaning", item.get("prediction", ""))),
                    ),
                )
            )
            level = str(item.get("evidence_level", "UNCERTAIN"))
            try:
                confidence = min(1.0, max(0.0, float(item.get("confidence", 0.5))))
            except (TypeError, ValueError):
                confidence = 0.5
        else:
            text, level, confidence = str(item), "UNCERTAIN", 0.5
        if text.strip():
            results.append({"text": text.strip(), "evidence_level": level, "confidence": confidence})
    return results
