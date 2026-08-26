from __future__ import annotations


LEVELS = ["FACT", "STRONG_INFERENCE", "SPECULATION", "UNCERTAIN"]


def _array(item: dict, maximum: int) -> dict:
    return {"type": "array", "maxItems": maximum, "items": item}


def _strings(maximum: int, length: int = 180) -> dict:
    return _array({"type": "string", "maxLength": length}, maximum)


FACT_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "text": {"type": "string", "maxLength": 180},
        "evidence_level": {"type": "string", "enum": ["FACT", "UNCERTAIN"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["text", "evidence_level", "confidence"],
}

EVENT_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "event_id": {"type": "string", "maxLength": 30},
        "page_range": {"type": "string", "maxLength": 30},
        "location": {"type": "string", "maxLength": 80},
        "characters": _strings(6, 60),
        "action": {"type": "string", "maxLength": 180},
        "utterance_meaning": {"type": "string", "maxLength": 160},
        "outcome": {"type": "string", "maxLength": 180},
        "evidence_level": {"type": "string", "enum": ["FACT", "UNCERTAIN"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "event_id", "page_range", "location", "characters", "action",
        "utterance_meaning", "outcome", "evidence_level", "confidence",
    ],
}

CHARACTER_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "character_id": {"type": "string", "maxLength": 30},
        "name": {"type": "string", "maxLength": 60},
        "actions": _strings(6, 150),
        "emotion": {"type": "string", "maxLength": 120},
        "evidence_scene": {"type": "string", "maxLength": 180},
        "evidence_level": {
            "type": "string",
            "enum": ["FACT", "STRONG_INFERENCE", "UNCERTAIN"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "character_id", "name", "actions", "emotion", "evidence_scene",
        "evidence_level", "confidence",
    ],
}

RELATIONSHIP_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "relationship_id": {"type": "string", "maxLength": 30},
        "source": {"type": "string", "maxLength": 60},
        "target": {"type": "string", "maxLength": 60},
        "change": {"type": "string", "maxLength": 180},
        "basis_scene": {"type": "string", "maxLength": 180},
        "evidence_level": {
            "type": "string",
            "enum": ["FACT", "STRONG_INFERENCE", "UNCERTAIN"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "relationship_id", "source", "target", "change", "basis_scene",
        "evidence_level", "confidence",
    ],
}

UTTERANCE_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "speaker": {"type": "string", "maxLength": 60},
        "target": {"type": "string", "maxLength": 60},
        "meaning": {"type": "string", "maxLength": 180},
        "result": {"type": "string", "maxLength": 160},
    },
    "required": ["speaker", "target", "meaning", "result"],
}

CLUE_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "clue_id": {"type": "string", "maxLength": 30},
        "text": {"type": "string", "maxLength": 180},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["clue_id", "text", "confidence"],
}

QUESTION_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "question_id": {"type": "string", "maxLength": 30},
        "text": {"type": "string", "maxLength": 180},
        "status": {"type": "string", "enum": ["unresolved"]},
    },
    "required": ["question_id", "text", "status"],
}

RESOLVED_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "question_id": {"type": "string", "maxLength": 30},
        "text": {"type": "string", "maxLength": 180},
        "answer": {"type": "string", "maxLength": 220},
        "basis": {"type": "string", "maxLength": 180},
        "status": {"type": "string", "enum": ["resolved"]},
    },
    "required": ["question_id", "text", "answer", "basis", "status"],
}

RESOLVED_CLUE_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "clue_id": {"type": "string", "maxLength": 30},
        "text": {"type": "string", "maxLength": 180},
        "answer": {"type": "string", "maxLength": 220},
        "basis": {"type": "string", "maxLength": 180},
        "status": {"type": "string", "enum": ["resolved"]},
    },
    "required": ["clue_id", "text", "answer", "basis", "status"],
}

ANALYSIS_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "text": {"type": "string", "maxLength": 220},
        "evidence_level": {
            "type": "string",
            "enum": ["STRONG_INFERENCE", "SPECULATION", "UNCERTAIN"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["text", "evidence_level", "confidence"],
}

UNREADABLE_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "page_index": {"type": "integer", "minimum": 0},
        "status": {"type": "string", "enum": ["UNREADABLE", "PARTIAL"]},
        "reason": {"type": "string", "maxLength": 140},
    },
    "required": ["page_index", "status", "reason"],
}


CHUNK_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "range_summary": {"type": "string", "maxLength": 800},
        "event_timeline": _array(EVENT_ITEM, 12),
        "new_facts": _array(FACT_ITEM, 8),
        "character_actions_and_emotions": _array(CHARACTER_ITEM, 6),
        "relationship_changes": _array(RELATIONSHIP_ITEM, 6),
        "important_utterances": _array(UTTERANCE_ITEM, 8),
        "new_clues": _array(CLUE_ITEM, 6),
        "new_questions": _array(QUESTION_ITEM, 6),
        "continuing_questions": _array(QUESTION_ITEM, 8),
        "resolved_questions": _array(RESOLVED_ITEM, 6),
        "resolved_clues": _array(RESOLVED_CLUE_ITEM, 6),
        "memorable_scenes": _strings(3, 200),
        "analysis": _array(ANALYSIS_ITEM, 4),
        "emotional_impact": _strings(3, 140),
        "predictions_at_this_point": _strings(4, 180),
        "unreadable_pages": _array(UNREADABLE_ITEM, 20),
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "range_summary", "event_timeline", "new_facts",
        "character_actions_and_emotions", "relationship_changes",
        "important_utterances", "new_clues", "new_questions",
        "continuing_questions", "resolved_questions", "resolved_clues", "memorable_scenes",
        "analysis", "emotional_impact", "predictions_at_this_point",
        "unreadable_pages", "confidence",
    ],
}


CHAPTER_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "chapter_label": {"type": "string", "maxLength": 80},
        "detailed_summary": {"type": "string", "minLength": 1, "maxLength": 1000},
        "event_timeline": _array(EVENT_ITEM, 16),
        "new_facts": _array(FACT_ITEM, 10),
        "character_actions_and_emotions": _array(CHARACTER_ITEM, 8),
        "relationship_changes": _array(RELATIONSHIP_ITEM, 8),
        "important_utterances": _array(UTTERANCE_ITEM, 10),
        "new_clues": _array(CLUE_ITEM, 8),
        "unresolved_questions": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "new": _array(QUESTION_ITEM, 8),
                "continuing": _array(QUESTION_ITEM, 10),
            },
            "required": ["new", "continuing"],
        },
        "resolved_questions": _array(RESOLVED_ITEM, 8),
        "resolved_clues": _array(RESOLVED_CLUE_ITEM, 8),
        "memorable_scenes": _strings(3, 220),
        "chapter_analysis": _array(ANALYSIS_ITEM, 5),
        "emotional_impact": _strings(3, 160),
        "predictions_at_chapter_end": _strings(4, 180),
        "unreadable_pages": _array(UNREADABLE_ITEM, 24),
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "carryover": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "active_characters": _array(
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "character_id": {"type": "string", "maxLength": 30},
                            "name": {"type": "string", "maxLength": 60},
                            "state": {"type": "string", "maxLength": 120},
                        },
                        "required": ["character_id", "name", "state"],
                    },
                    8,
                ),
                "unresolved_clues": _array(CLUE_ITEM, 8),
                "open_questions": _array(QUESTION_ITEM, 10),
                "immediate_situation": {"type": "string", "maxLength": 260},
            },
            "required": [
                "active_characters", "unresolved_clues", "open_questions",
                "immediate_situation",
            ],
        },
    },
    "required": [
        "chapter_label", "detailed_summary", "event_timeline", "new_facts",
        "character_actions_and_emotions", "relationship_changes",
        "important_utterances", "new_clues", "unresolved_questions",
        "resolved_questions", "resolved_clues", "memorable_scenes", "chapter_analysis",
        "emotional_impact", "predictions_at_chapter_end", "unreadable_pages",
        "confidence", "carryover",
    ],
}
