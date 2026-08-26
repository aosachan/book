from __future__ import annotations

import json
from typing import Any

from .context_budget import compact_value


FINAL_PASS_4_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "revision_summary": {"type": "string", "maxLength": 500},
        "applied_corrections": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "issue": {"type": "string", "maxLength": 120},
                    "corrected_view": {"type": "string", "maxLength": 180},
                    "basis": {"type": "string", "maxLength": 140},
                    "evidence_level": {
                        "type": "string",
                        "enum": ["FACT", "STRONG_INFERENCE", "SPECULATION", "UNCERTAIN"],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": [
                    "issue",
                    "corrected_view",
                    "basis",
                    "evidence_level",
                    "confidence",
                ],
            },
        },
        "claims_to_exclude": {
            "type": "array",
            "maxItems": 6,
            "items": {"type": "string", "maxLength": 160},
        },
        "uncertainties_to_preserve": {
            "type": "array",
            "maxItems": 6,
            "items": {"type": "string", "maxLength": 160},
        },
        "reading_journey_corrections": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 180},
        },
        "report_writing_rules": {
            "type": "array",
            "maxItems": 6,
            "items": {"type": "string", "maxLength": 150},
        },
    },
    "required": [
        "revision_summary",
        "applied_corrections",
        "claims_to_exclude",
        "uncertainties_to_preserve",
        "reading_journey_corrections",
        "report_writing_rules",
    ],
}


REPORT_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        # Sectional reports concatenate several responses. Keeping each part
        # below this size prevents JSON truncation in a 4096-token context while
        # still yielding a detailed whole-book document.
        "markdown": {"type": "string", "maxLength": 2400},
    },
    "required": ["markdown"],
}


PAGE_SCHEMA = {
    "reading_status": "READABLE",
    "short_summary": "",
    "scene_location": "",
    "characters": [
        {
            "name": "",
            "role_or_action": "",
            "emotion": "",
            "evidence_scene": "",
            "psychology": [
                {
                    "text": "",
                    "evidence_level": "STRONG_INFERENCE",
                    "confidence": 0.0,
                    "basis": "",
                }
            ],
        }
    ],
    "events": [
        {
            "text": "",
            "actor": "",
            "action": "",
            "target": "",
            "location": "",
            "outcome": "",
            "evidence_level": "FACT",
            "confidence": 0.0,
        }
    ],
    "important_utterances": [
        {
            "speaker": "",
            "target": "",
            "meaning": "",
            "reaction_or_result": "",
            "evidence_level": "FACT",
            "confidence": 0.0,
        }
    ],
    "new_facts": [],
    "apparent_emotions": [],
    "relationship_updates": [
        {
            "source": "",
            "target": "",
            "change": "",
            "evidence_level": "FACT",
            "confidence": 0.0,
        }
    ],
    "foreshadowing_or_suspicious_points": [],
    "unresolved_questions": [],
    "important_details": [],
    "information_gaps": [],
    "continuity_from_previous_page": "",
    "possible_chapter_boundary": False,
    "confidence": 0.0,
    "readability": 0.0,
    "important_score": 0.0,
}


def _short(value: Any, limit: int) -> str:
    text = str(value or "").strip().replace("\x00", "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _statement(value: Any, limit: int = 110) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "text": _short(value.get("text", ""), limit),
            "evidence_level": _short(value.get("evidence_level", "UNCERTAIN"), 20),
        }
    return {"text": _short(value, limit), "evidence_level": "UNCERTAIN"}


def _event(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"text": _short(value, 140), "evidence_level": "UNCERTAIN"}
    return {
        "text": _short(value.get("text", ""), 140),
        "actor": _short(value.get("actor", ""), 40),
        "action": _short(value.get("action", ""), 90),
        "target": _short(value.get("target", ""), 40),
        "location": _short(value.get("location", ""), 50),
        "outcome": _short(value.get("outcome", value.get("result", "")), 90),
        "evidence_level": _short(value.get("evidence_level", "UNCERTAIN"), 20),
    }


def _utterance(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"speaker": "不明", "meaning": _short(value, 130)}
    return {
        "speaker": _short(value.get("speaker", "不明"), 40),
        "target": _short(value.get("target", ""), 40),
        "meaning": _short(value.get("meaning", value.get("text", "")), 130),
        "reaction_or_result": _short(
            value.get("reaction_or_result", value.get("result", "")), 90
        ),
    }


def _compact_latest_page(page: dict[str, Any]) -> dict[str, Any]:
    characters = []
    for item in (page.get("characters") or [])[:4]:
        if isinstance(item, dict):
            psychology = item.get("psychology") or []
            characters.append(
                {
                    "name": _short(item.get("name", ""), 50),
                    "role_or_action": _short(item.get("role_or_action", ""), 100),
                    "psychology": [_statement(psychology[0], 80)] if psychology else [],
                }
            )
        else:
            characters.append({"name": _short(item, 50)})
    relationships = []
    for item in (page.get("relationship_updates") or [])[:2]:
        if isinstance(item, dict):
            relationships.append(
                {
                    "source": _short(item.get("source", ""), 40),
                    "target": _short(item.get("target", ""), 40),
                    "change": _short(item.get("change", ""), 100),
                    "evidence_level": _short(item.get("evidence_level", "UNCERTAIN"), 20),
                }
            )
    return {
        "page_index": page.get("page_index"),
        "reading_status": page.get("reading_status", "READABLE"),
        "short_summary": _short(page.get("short_summary", ""), 240),
        "scene_location": _short(page.get("scene_location", ""), 60),
        "characters": characters,
        "events": [_event(item) for item in (page.get("events") or [])[:3]],
        "new_facts": [_statement(item, 130) for item in (page.get("new_facts") or [])[:3]],
        "important_utterances": [
            _utterance(item) for item in (page.get("important_utterances") or [])[:2]
        ],
        "relationship_updates": relationships,
        "suspicious_points": [
            _statement(item) for item in (page.get("foreshadowing_or_suspicious_points") or [])[:2]
        ],
        "unresolved_questions": [_statement(item) for item in (page.get("unresolved_questions") or [])[:2]],
        "important_details": [_statement(item) for item in (page.get("important_details") or [])[:2]],
        "information_gaps": [
            _short(item, 90) for item in (page.get("information_gaps") or [])[:2]
        ],
        "continuity": _short(page.get("continuity_from_previous_page", ""), 140),
    }


def _compact_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    summary = chunk.get("summary", {}) if isinstance(chunk, dict) else {}
    if not isinstance(summary, dict):
        summary = {}
    return {
        "pages": [chunk.get("start_page"), chunk.get("end_page")],
        "event_timeline": [
            compact_value(item, 110) for item in (summary.get("event_timeline") or summary.get("range_events") or [])[-4:]
        ],
        "new_facts": [
            compact_value(item, 100) for item in (summary.get("new_facts") or [])[-3:]
        ],
        "important_utterances": [
            compact_value(item, 90) for item in (summary.get("important_utterances") or [])[-2:]
        ],
        "unresolved": [
            compact_value(item, 90)
            for item in (
                summary.get("new_questions")
                or summary.get("unresolved_items")
                or []
            )[-3:]
        ],
    }


def compact_page_context(recent_context: dict[str, Any], max_chars: int = 900) -> dict[str, Any]:
    """Keep page calls inside small local-runtime context windows.

    The database retains the complete semantic notes. This projection is only
    for the next Vision request, where an image and the output allowance also
    have to fit inside Ollama's often-small default context (commonly 4096).
    """

    pages = [item for item in (recent_context.get("recent_pages") or []) if isinstance(item, dict)]
    latest = _compact_latest_page(pages[-1]) if pages else {}
    compact: dict[str, Any] = {
        "prior_page_summaries": [
            {
                "page_index": page.get("page_index"),
                "short_summary": _short(page.get("short_summary", ""), 150),
            }
            for page in pages[-3:-1]
        ],
        "latest_page": latest,
    }
    chapter = recent_context.get("last_chapter_checkpoint")
    if isinstance(chapter, dict) and isinstance(chapter.get("carryover"), dict):
        compact["previous_chapter_carryover"] = compact_value(
            chapter["carryover"], 420
        )

    chunks = [item for item in (recent_context.get("recent_chunks") or []) if isinstance(item, dict)]
    if chunks:
        compact["latest_integrated_chunk"] = _compact_chunk(chunks[-1])
    predictions = recent_context.get("prediction_history_tail") or []
    if predictions:
        compact["prediction_tail"] = [
            {
                "page_index": item.get("page_index"),
                "text": _short(item.get("prediction_text", ""), 100),
                "status": _short(item.get("status", ""), 24),
            }
            for item in predictions[-3:]
            if isinstance(item, dict)
        ]

    # Drop lower-priority details as a complete JSON field, never by slicing
    # through serialized JSON. The full notes remain untouched in SQLite.
    drop_order = [
        ("root", "prediction_tail"),
        ("latest", "important_details"),
        ("latest", "information_gaps"),
        ("latest", "unresolved_questions"),
        ("latest", "suspicious_points"),
        ("latest", "relationship_updates"),
        ("latest", "characters"),
        ("root", "prior_page_summaries"),
        ("root", "latest_integrated_chunk"),
        ("latest", "important_utterances"),
        ("latest", "new_facts"),
        ("latest", "events"),
    ]
    for target, key in drop_order:
        if len(json.dumps(compact, ensure_ascii=False, separators=(",", ":"))) <= max_chars:
            break
        container = compact if target == "root" else latest
        container.pop(key, None)
    return compact


def page_prompt(page_index: int, recent_context: dict[str, Any], quality: str) -> str:
    context_text = json.dumps(
        compact_page_context(recent_context), ensure_ascii=False, separators=(",", ":")
    )
    quality_note = {
        "FAST": "簡潔さと速度を最優先する。",
        "DEEP": "曖昧さと心理の根拠を慎重に区別するが、出力件数は増やさない。",
    }.get(quality, "重要項目に絞り、正確さと速度を両立する。")
    return f"""あなたは一冊をページ順に読む事実記録担当です。画像は意味を読み取り、OCR全文は作りません。

対象は論理ページ {page_index}。{quality_note}

厳守:
- 最優先は、この画像で直接確認できる具体的な出来事を保存すること。考察より事実を優先する。
- eventsには、可能な範囲で場所・行動者・行動・対象・結果を入れる。
- 重要な会話は原文を転記せず、「誰が誰へ何を伝え、どう反応されたか」をimportant_utterancesへ入れる。
- new_factsには、このページで初めて判明した事実だけを入れる。直近記憶の既知情報を再掲しない。
- 本文の逐語転記、長い引用、段落の復元をしない。固有名詞以外は必ず自分の言葉で要約する。
- 画像で明確な事実=FACT、強い示唆=STRONG_INFERENCE、予想=SPECULATION、読めない/曖昧=UNCERTAIN。
- SPECULATIONはページの事実・出来事・新事実へ入れない。
- 直近記憶は人物識別と場面の接続にだけ使う。そこにある過去の出来事を現在ページの出来事として再出力しない。
- 読めないページを前後の記憶から補完しない。読めない場合はreading_status=UNREADABLE、short_summary="内容判定不能"とし、events/new_facts等を空配列にする。
- 一部だけ読める場合はreading_status=PARTIALとし、確認できた事実だけを保存してinformation_gapsへ不足を書く。
- ページ番号・ヘッダー・アプリUIは物語本文として扱わない。
- short_summaryは180文字以内。charactersは最大4人、各人物のpsychologyは最大1件。
- eventsは最大4件、relationship_updatesは最大3件、それ以外の配列は各最大3件。情報を削る場合は events > new_facts > important_utterances > character action > relationship > emotion/考察 の順で残す。
- 各text/role/basis/changeは120文字以内。網羅より重要度を優先する。
- JSONオブジェクトだけを返す。Markdownや説明を付けない。

直近の圧縮記憶（原文ではない）:
{context_text}

出力スキーマ例（値は画像に合わせて置換）:
{json.dumps(PAGE_SCHEMA, ensure_ascii=False)}
"""


CHUNK_SCHEMA = {
    "range_summary": "",
    "event_timeline": [
        {
            "event_id": "",
            "page_range": "",
            "location": "",
            "characters": [],
            "action": "",
            "utterance_meaning": "",
            "outcome": "",
            "evidence_level": "FACT",
            "confidence": 0.0,
        }
    ],
    "new_facts": [{"text": "", "evidence_level": "FACT", "confidence": 0.0}],
    "character_actions_and_emotions": [
        {
            "character_id": "",
            "name": "",
            "actions": [],
            "emotion": "",
            "evidence_scene": "",
            "evidence_level": "FACT",
            "confidence": 0.0,
        }
    ],
    "relationship_changes": [
        {
            "relationship_id": "",
            "source": "",
            "target": "",
            "change": "",
            "basis_scene": "",
            "evidence_level": "FACT",
            "confidence": 0.0,
        }
    ],
    "important_utterances": [{"speaker": "", "target": "", "meaning": "", "result": ""}],
    "new_clues": [{"clue_id": "", "text": "", "confidence": 0.0}],
    "new_questions": [{"question_id": "", "text": "", "status": "unresolved"}],
    "continuing_questions": [{"question_id": "", "text": "", "status": "unresolved"}],
    "resolved_questions": [{"question_id": "", "text": "", "answer": "", "basis": "", "status": "resolved"}],
    "resolved_clues": [{"clue_id": "", "text": "", "answer": "", "basis": "", "status": "resolved"}],
    "memorable_scenes": [],
    "analysis": [{"text": "", "evidence_level": "SPECULATION", "confidence": 0.0}],
    "emotional_impact": [],
    "predictions_at_this_point": [],
    "unreadable_pages": [{"page_index": 0, "status": "UNREADABLE", "reason": ""}],
    "confidence": 0.0,
}


CHAPTER_SCHEMA = {
    "chapter_label": "章番号または短い仮題",
    "detailed_summary": "300〜800文字を目安に、実際の出来事を時系列で具体的に記録",
    "event_timeline": [],
    "new_facts": [],
    "character_actions_and_emotions": [],
    "relationship_changes": [],
    "important_utterances": [],
    "new_clues": [],
    "unresolved_questions": {"new": [], "continuing": []},
    "resolved_questions": [],
    "resolved_clues": [],
    "memorable_scenes": [],
    "chapter_analysis": [],
    "emotional_impact": [],
    "predictions_at_chapter_end": [],
    "unreadable_pages": [],
    "confidence": 0.0,
    "carryover": {
        "active_characters": [],
        "unresolved_clues": [],
        "open_questions": [],
        "immediate_situation": "章末の具体的な状況。次ページから続きを理解できる一文",
    },
}


def chunk_prompt(
    start_page: int,
    end_page: int,
    page_notes: list[dict[str, Any]],
    prior_memory: dict[str, Any],
    quality: str,
) -> str:
    depth = {
        "FAST": "事実タイムラインを簡潔に統合する。",
        "DEEP": "事実を落とさず、新情報と既知情報を慎重に区別する。",
    }.get(quality, "具体的な出来事と新情報を正確に統合する。")
    return f"""ページ要約だけを材料に、AI用の長期読書記憶を作成してください。入力には下位の統合メモを含む場合があります。元画像や本文の復元は禁止です。{depth}

範囲: {start_page}〜{end_page}
重要ルール:
- 優先順位は、出来事 > 新事実 > 重要発言 > 人物の行動 > 関係変化 > 未解決事項 > 印象的場面 > 感情 > 考察 > 予想。
- range_summaryとevent_timelineには、場所・人物・行動・発言の意味・結果を可能な範囲で時系列に保存する。抽象語だけで済ませない。
- prior_memoryは現在範囲の理解とID照合にだけ使う。過去の出来事を、この範囲で起きた出来事として出力しない。
- new_facts/new_clues/new_questionsには、この範囲で初めて追加された情報だけを入れる。
- 新情報のない前章事項はcontinuing_questionsへ1項目1行で残し、詳細を再説明しない。
- resolved_questions/resolved_cluesでは既存ID、答え、根拠を明示する。
- 重要発言は原文引用せず、誰が誰へ何を伝えたかを意味で記録する。
- UNREADABLE/PARTIALページはunreadable_pagesへ明記し、前後から内容を補完しない。
- 読める事実が一つもない範囲はrange_summary="内容判定不能"とし、事実系配列を空にする。
- FACT / STRONG_INFERENCE / SPECULATION / UNCERTAIN を混同しない。
- 基本項目はFACT中心。STRONG_INFERENCEは感情等の必要箇所だけ、SPECULATIONはanalysis/predictions以外に入れない。
- memorable_scenesは具体的な場面を最大3件、emotional_impactも最大3件にする。
- 根拠のない固有設定を作らない。JSONオブジェクトだけを返す。

従来の圧縮記憶:
{json.dumps(prior_memory, ensure_ascii=False, separators=(",", ":"))}

この範囲のページ読書メモ:
{json.dumps(page_notes, ensure_ascii=False, separators=(",", ":"))}

出力スキーマ:
{json.dumps(CHUNK_SCHEMA, ensure_ascii=False)}
"""


def chapter_prompt(
    chapter_index: int,
    start_page: int,
    end_page: int,
    records: list[dict[str, Any]],
    prior_carryover: dict[str, Any],
    quality: str,
) -> str:
    depth = {
        "FAST": "事実中心で簡潔にまとめる。",
        "DEEP": "具体的な出来事と因果関係を落とさず丁寧に統合する。",
    }.get(quality, "章内の事実と前後関係を正確に統合する。")
    return f"""ページ要約から作ったチャンク記憶を、別のAIが物語を理解できる章読書記録へ統合してください。{depth}

章: {chapter_index}
範囲: {start_page}〜{end_page}
厳守:
- 事実の保存を考察より優先する。入力を削る場合は、出来事、新事実、重要発言、人物行動、関係変化の順で必ず残す。
- detailed_summaryは300〜800文字を目安に、誰が・どこで・何をして・何を伝え・どうなったかを時系列で書く。
- event_timelineは具体的な場面を時系列順にし、抽象的な心理説明だけの項目を作らない。
- 前章carryoverは人物識別、ID照合、継続謎の判定にだけ使う。前章の出来事をこの章のtimelineやnew_factsへ入れない。
- 新情報がない継続事項はunresolved_questions.continuingへ1項目1行で置き、詳細を再出力しない。
- 関係性はこの章で実際に変化した場合のみrelationship_changesへ入れる。変化がなければ空配列。
- 重要発言は長文引用せず、発言者・相手・意味・結果を残す。
- 読めなかった範囲を推測で埋めず、unreadable_pagesへ明示する。
- 章全体で読める事実がなければdetailed_summary="内容判定不能"とし、前章から要約を作らない。
- FACT / STRONG_INFERENCE / SPECULATION / UNCERTAIN を混同しない。
- 本文の引用や復元はしない。入力にない設定を作らない。
- chapter_analysisだけで考察を許可する。推測は断定せず根拠と確度を示す。
- memorable_scenesとemotional_impactは各最大3件。
- carryoverはactive_characters、未解決clue/questionのIDと短文、章末の具体的immediate_situationだけにする。テーマや長い既出説明を入れない。
- 入力が下位の章統合メモの場合は、重複を除いて同じ構造へ再統合する。
- JSONオブジェクトだけを返す。

前章からの最小引き継ぎ:
{json.dumps(prior_carryover, ensure_ascii=False, separators=(",", ":"))}

この章の統合素材:
{json.dumps(records, ensure_ascii=False, separators=(",", ":"))}

出力スキーマ:
{json.dumps(CHAPTER_SCHEMA, ensure_ascii=False, separators=(",", ":"))}
"""


def final_pass_prompt(pass_number: int, payload: dict[str, Any], quality: str) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    shared = """入力は本文ではなく、ページ/チャンクごとの独自読書メモです。長い引用や本文再構成は禁止です。
FACT / STRONG_INFERENCE / SPECULATION / UNCERTAIN を維持し、根拠のない補完をしないでください。"""
    if pass_number == 1:
        task = "全チャンクを時系列に統合し、矛盾を明示した全巻事実記録をJSONで作成してください。"
    elif pass_number == 2:
        task = "人物、関係性、伏線、テーマ、途中予想と解釈更新を統合したJSONを作成してください。"
    elif pass_number == 3:
        task = "独立した批評者として、断定、前後矛盾、誤読、捏造、事実と考察の混同を監査し、修正指示をJSONで返してください。"
    else:
        task = (
            "監査結果を反映する修正記録をJSONで作成してください。Pass 1/2の内容を再複製せず、"
            "修正点、除外すべき断定、残すべき不確実性、読書途中の解釈修正だけを記録してください。"
        )
    schema = (
        "\n出力スキーマ:\n"
        + json.dumps(FINAL_PASS_4_SCHEMA, ensure_ascii=False, separators=(",", ":"))
        if pass_number == 4
        else ""
    )
    return f"""{shared}
品質: {quality}
Pass {pass_number}: {task}
{schema}
入力:
{data}

JSONオブジェクトだけを返してください。"""


def report_prompt(
    report_key: str,
    payload: dict[str, Any],
    quality: str,
    scope_note: str = "",
) -> str:
    instructions = {
        "01_summary": "時系列を保った、かなり詳細な全巻あらすじ。事実確度を崩さない。",
        "02_characters": "人物ごとの目的・心理・行動・関係性と、解釈がいつ何で変わったか。",
        "03_mysteries": "伏線、違和感、回収、未回収、別解釈を確度付きで整理する。",
        "04_reading_journey": "各チャンク時点の予想、思い込み、驚き、外れ、解釈修正を時系列で詳しく描く。後知恵で過去を改変しない。",
        "05_final_review": "あらすじの反復ではない長めの感想・考察。面白さ、衝撃、人物造形、心理、関係性、構成、伏線、テーマ、読後感を含める。",
        "06_evidence_check": "重要な解釈ごとに、解釈、根拠となった読書メモ位置、確信度、別解釈を明記する。",
        "handoff_for_chatgpt": "このファイル単独で別AIと深いネタバレ感想会ができる高密度な引き継ぎ。詳細ストーリー、人物、関係、重要イベント、伏線、驚き、途中予想、外れ、テーマ、最終解釈、確信度、語り合う価値のある場面を十分に含める。短くしすぎない。",
    }
    instruction = instructions[report_key]
    scope_instruction = (
        f"対象範囲: {scope_note}\nこの範囲を独立した詳細セクションとして書き、範囲外の展開を補完しない。"
        if scope_note
        else "対象範囲: 全巻"
    )
    return f"""検証済みの独自読書メモから、次のMarkdownレポートを一つだけ執筆してください。

種類: {report_key}
品質: {quality}
要件: {instruction}
{scope_instruction}

厳守:
- 本文の大量引用や逐語的再構成をしない。
- FACT / STRONG INFERENCE / SPECULATION / UNCERTAIN を必要に応じて明示し、捏造しない。
- 監査の修正指示を優先する。
- 内容のある日本語Markdownにする。Markdown本文は2400文字以内に収める。
- JSONオブジェクト {{"markdown":"..."}} だけを返す。

検証済み素材:
{json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}
"""


def compact_page_note(note: dict[str, Any], token_budget: int = 500) -> dict[str, Any]:
    """Bound a page note for hierarchical chunk integration."""

    preferred = {
        "page_index": note.get("page_index"),
        "reading_status": note.get("reading_status", "READABLE"),
        "short_summary": note.get("short_summary", ""),
        "scene_location": note.get("scene_location", ""),
        "events": note.get("events", []),
        "new_facts": note.get("new_facts", []),
        "important_utterances": note.get("important_utterances", []),
        "characters": note.get("characters", []),
        "relationship_updates": note.get("relationship_updates", []),
        "foreshadowing_or_suspicious_points": note.get("foreshadowing_or_suspicious_points", []),
        "unresolved_questions": note.get("unresolved_questions", []),
        "information_gaps": note.get("information_gaps", []),
        "continuity_from_previous_page": note.get("continuity_from_previous_page", ""),
        "possible_chapter_boundary": note.get("possible_chapter_boundary", False),
        "confidence": note.get("confidence", 0.5),
    }
    compacted = compact_value(preferred, token_budget)
    return compacted if isinstance(compacted, dict) else {"page_index": note.get("page_index")}


def compact_prior_memory(memory: dict[str, Any], token_budget: int = 420) -> dict[str, Any]:
    checkpoint = memory.get("last_chapter_checkpoint") or {}
    carryover = checkpoint.get("carryover", {}) if isinstance(checkpoint, dict) else {}
    preferred = {
        "previous_chapter_carryover": carryover,
        "recent_chunks": memory.get("recent_chunks", [])[-1:],
        "current_character_states": memory.get("current_character_states", []),
        "tracked_entities": memory.get("tracked_entities", []),
    }
    compacted = compact_value(preferred, token_budget)
    return compacted if isinstance(compacted, dict) else {}
