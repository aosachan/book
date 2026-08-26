from __future__ import annotations

import json
import re
import sqlite3
from copy import deepcopy
from difflib import SequenceMatcher
from typing import Any


ENTITY_PREFIXES = {
    "character": "character",
    "event": "event",
    "relationship": "relationship",
    "clue": "clue",
    "question": "question",
}


def enrich_and_track_entities(
    db: sqlite3.Connection,
    session_id: int,
    payload: dict[str, Any],
    *,
    page_index: int,
    source_kind: str,
    source_index: int,
    chapter_index: int | None,
    now: str,
) -> dict[str, Any]:
    """Attach stable IDs and persist current state/history in one transaction."""

    enriched = deepcopy(payload)
    mappings = [
        ("character", "character_actions_and_emotions", "character_id", _character_key),
        ("character", "character_states", "character_id", _character_key),
        ("event", "event_timeline", "event_id", _event_key),
        ("event", "range_events", "event_id", _event_key),
        ("relationship", "relationship_changes", "relationship_id", _relationship_key),
        ("clue", "new_clues", "clue_id", _text_key),
        ("question", "new_questions", "question_id", _text_key),
        ("question", "continuing_questions", "question_id", _text_key),
        ("question", "resolved_questions", "question_id", _text_key),
        ("clue", "resolved_clues", "clue_id", _text_key),
    ]
    unresolved = enriched.get("unresolved_questions")
    if isinstance(unresolved, dict):
        for subsection in ("new", "continuing"):
            _track_list(
                db,
                session_id,
                unresolved.get(subsection),
                "question",
                "question_id",
                _text_key,
                page_index,
                f"{source_kind}:unresolved_{subsection}",
                source_index,
                chapter_index,
                now,
                resolved=False,
            )

    for entity_type, field, id_field, key_builder in mappings:
        _track_list(
            db,
            session_id,
            enriched.get(field),
            entity_type,
            id_field,
            key_builder,
            page_index,
            f"{source_kind}:{field}",
            source_index,
            chapter_index,
            now,
            resolved=field in {"resolved_questions", "resolved_clues"},
        )

    carryover = enriched.get("carryover")
    if isinstance(carryover, dict):
        _track_list(
            db, session_id, carryover.get("active_characters"), "character",
            "character_id", _character_key, page_index, f"{source_kind}:carry_characters", source_index,
            chapter_index, now, resolved=False,
        )
        _track_list(
            db, session_id, carryover.get("unresolved_clues"), "clue",
            "clue_id", _text_key, page_index, f"{source_kind}:carry_clues", source_index,
            chapter_index, now, resolved=False,
        )
        _track_list(
            db, session_id, carryover.get("open_questions"), "question",
            "question_id", _text_key, page_index, f"{source_kind}:carry_questions", source_index,
            chapter_index, now, resolved=False,
        )
    return enriched


def tracked_entities(db: sqlite3.Connection, session_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        """SELECT entity_uid,entity_type,label,status,first_page,last_page,
                  first_chapter,last_chapter,state_json,updated_at
           FROM semantic_entity WHERE session_id=?
           ORDER BY entity_type,entity_uid""",
        (session_id,),
    ).fetchall()
    return [
        {
            "entity_id": row["entity_uid"],
            "entity_type": row["entity_type"],
            "label": row["label"],
            "status": row["status"],
            "first_page": row["first_page"],
            "last_page": row["last_page"],
            "first_chapter": row["first_chapter"],
            "last_chapter": row["last_chapter"],
            "state": json.loads(row["state_json"]),
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def _track_list(
    db: sqlite3.Connection,
    session_id: int,
    value: Any,
    entity_type: str,
    id_field: str,
    key_builder: Any,
    page_index: int,
    source_kind: str,
    source_index: int,
    chapter_index: int | None,
    now: str,
    *,
    resolved: bool,
) -> None:
    if isinstance(value, dict):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        canonical_key, label = key_builder(item)
        if not canonical_key or label in {"", "不明", "特になし"}:
            continue
        supplied = str(item.get(id_field, "")).strip()
        entity_uid = _valid_existing_id(db, session_id, entity_type, supplied)
        if not entity_uid:
            entity_uid = _find_matching_id(
                db, session_id, entity_type, canonical_key, label
            )
        if not entity_uid:
            entity_uid = _next_id(db, session_id, entity_type)
        item[id_field] = entity_uid
        status = "resolved" if resolved or str(item.get("status", "")).lower() == "resolved" else (
            "unresolved" if entity_type in {"question", "clue"} else "active"
        )
        state_json = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        existing = db.execute(
            "SELECT first_page,first_chapter FROM semantic_entity WHERE session_id=? AND entity_uid=?",
            (session_id, entity_uid),
        ).fetchone()
        if existing:
            db.execute(
                """UPDATE semantic_entity
                   SET canonical_key=?,label=?,status=?,last_page=?,last_chapter=?,
                       state_json=?,updated_at=?
                   WHERE session_id=? AND entity_uid=?""",
                (
                    canonical_key, label, status, page_index, chapter_index,
                    state_json, now, session_id, entity_uid,
                ),
            )
        else:
            db.execute(
                """INSERT INTO semantic_entity(
                       session_id,entity_uid,entity_type,canonical_key,label,status,
                       first_page,last_page,first_chapter,last_chapter,state_json,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    session_id, entity_uid, entity_type, canonical_key, label, status,
                    page_index, page_index, chapter_index, chapter_index, state_json, now,
                ),
            )
        db.execute(
            """INSERT INTO semantic_entity_history(
                   session_id,entity_uid,source_kind,source_index,page_index,
                   chapter_index,status,state_json,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(session_id,entity_uid,source_kind,source_index)
               DO UPDATE SET page_index=excluded.page_index,
                             chapter_index=excluded.chapter_index,
                             status=excluded.status,
                             state_json=excluded.state_json,
                             created_at=excluded.created_at""",
            (
                session_id, entity_uid, source_kind, source_index, page_index,
                chapter_index, status, state_json, now,
            ),
        )


def _valid_existing_id(
    db: sqlite3.Connection, session_id: int, entity_type: str, entity_uid: str
) -> str:
    if not entity_uid:
        return ""
    row = db.execute(
        "SELECT 1 FROM semantic_entity WHERE session_id=? AND entity_type=? AND entity_uid=?",
        (session_id, entity_type, entity_uid),
    ).fetchone()
    return entity_uid if row else ""


def _find_matching_id(
    db: sqlite3.Connection,
    session_id: int,
    entity_type: str,
    canonical_key: str,
    label: str,
) -> str:
    exact = db.execute(
        """SELECT entity_uid FROM semantic_entity
           WHERE session_id=? AND entity_type=? AND canonical_key=?""",
        (session_id, entity_type, canonical_key),
    ).fetchone()
    if exact:
        return str(exact["entity_uid"])
    if entity_type not in {"question", "clue"}:
        return ""
    rows = db.execute(
        """SELECT entity_uid,canonical_key,label FROM semantic_entity
           WHERE session_id=? AND entity_type=? AND status!='resolved'""",
        (session_id, entity_type),
    ).fetchall()
    normalized_label = _normalize(label)
    for row in rows:
        other = str(row["canonical_key"])
        other_label = _normalize(str(row["label"]))
        if (
            canonical_key in other
            or other in canonical_key
            or SequenceMatcher(None, normalized_label, other_label).ratio() >= 0.82
        ):
            return str(row["entity_uid"])
    return ""


def _next_id(db: sqlite3.Connection, session_id: int, entity_type: str) -> str:
    prefix = ENTITY_PREFIXES[entity_type]
    rows = db.execute(
        "SELECT entity_uid FROM semantic_entity WHERE session_id=? AND entity_type=?",
        (session_id, entity_type),
    ).fetchall()
    largest = 0
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)$")
    for row in rows:
        match = pattern.match(str(row["entity_uid"]))
        if match:
            largest = max(largest, int(match.group(1)))
    return f"{prefix}_{largest + 1:03d}"


def _character_key(item: dict[str, Any]) -> tuple[str, str]:
    label = str(item.get("name", item.get("label", ""))).strip()
    return _normalize(label), label


def _relationship_key(item: dict[str, Any]) -> tuple[str, str]:
    source = str(item.get("source", "")).strip()
    target = str(item.get("target", "")).strip()
    label = f"{source} → {target}".strip()
    return f"{_normalize(source)}>{_normalize(target)}", label


def _event_key(item: dict[str, Any]) -> tuple[str, str]:
    label = str(
        item.get("action")
        or item.get("text")
        or item.get("event")
        or item.get("summary")
        or ""
    ).strip()
    location = str(item.get("location", "")).strip()
    page_range = str(item.get("page_range", "")).strip()
    return _normalize(f"{page_range}|{location}|{label}"), label


def _text_key(item: dict[str, Any]) -> tuple[str, str]:
    label = str(
        item.get("text")
        or item.get("question")
        or item.get("clue")
        or item.get("summary")
        or item.get("label")
        or ""
    ).strip()
    return _normalize(label), label


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Zぁ-んァ-ヶ一-龠々]+", "", value.casefold())[:500]
