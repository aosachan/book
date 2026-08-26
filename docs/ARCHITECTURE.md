# Architecture and safety boundaries

## Data flow

```text
Visible desktop rectangle
  -> FrameSource (WindowsScreenCapture)
  -> black/flat/duplicate/change checks
  -> optional spread split in reading order
  -> local Vision page analysis (short structured JSON)
  -> SQLite semantic page_note
  -> every ~20 pages: deep chunk integration
  -> character / relationship / prediction history
  -> final Pass 1 facts
  -> Pass 2 people, relations, mysteries, themes
  -> Pass 3 independent hallucination/contradiction audit
  -> Pass 4 corrected master
  -> seven independent detailed Markdown generations
```

The page image reference is released after page processing. The UI preview receives a separate in-memory copy and closes it after producing the GUI bitmap. No screenshot path exists in the application data model.

## Module boundaries

- `capture/base.py`: `FrameSource` and `WindowProvider` protocols. A future Chrome-visible-tab source can implement this boundary without changing reading logic.
- `capture/windows.py`: normal pixels currently rendered on the Windows desktop. It deliberately has no PrintWindow, DRM, ebook, DOM, or capture-protection code.
- `window_control.py`: foreground activation and one ordinary user-level page key.
- `duplicate.py`: 256-bit dHash, brightness/variance checks, page similarity, spread splitting and ordering.
- `llm_client.py`: loopback-only OpenAI-compatible client and detected-Ollama native adapter. There is no cloud fallback or telemetry.
- `analyzer.py`: fast page-level semantic analysis plus excessive-transcription guard.
- `integrator.py`: deeper periodic reasoning over page notes, never over page images.
- `memory.py`: transactional SQLite semantic memory and persistence rejection rules.
- `reports.py`: four validation passes followed by one focused generation per deliverable.
- `orchestrator.py`: state machine, immediate persistence, safe pause/stop/error behavior.
- `ui.py`: the single-window presentation layer; long work stays on one worker thread.

## Persistent data

The SQLite schema separates `book`, `session`, `page_note`, `chunk_summary`, `character_state`, `relationship_state`, `prediction`, `unresolved_question`, `important_event`, `user_note`, and `calibration_run`.

At the persistence boundary, binary values and fields named `ocr`, `ocr_text`, `raw_text`, `full_text`, `transcription`, `page_image`, `image_bytes`, or `base64` are rejected. Very long page-note scalar strings are also rejected. The model response is checked earlier for summary/response lengths associated with transcription.

## Evidence semantics

- `FACT`: confirmed in the semantic reading notes.
- `STRONG_INFERENCE`: strongly indicated but not explicit.
- `SPECULATION`: a theory or prediction at that reading position.
- `UNCERTAIN`: image recognition or context is not reliable enough.

Chunk summaries are append-only history. A new interpretation records its change reason; it does not delete the old state. This is what preserves the reading journey rather than only the ending-informed interpretation.

## Failure behavior

Black/flat capture, unchanged page, unstable page transition, disconnected LLM, invalid JSON, repeated page, suspiciously similar image, abnormal region, or possible transcription changes the state to `要確認`. The UI offers retry, skip, and manual confirmation and does not continue by itself.

