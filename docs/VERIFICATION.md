# Verification record

Verified on Windows on 2026-08-18.

## Automated core flow

The bundled runtime passed all seven tests:

```text
test_ten_page_metrics_and_estimates ... ok
test_black_screen_is_rejected ... ok
test_same_image_is_duplicate ... ok
test_spread_order ... ok
test_forbidden_payload_is_rejected ... ok
test_persists_semantic_note_and_resumes_without_source ... ok
test_twenty_pages_chunk_resume_and_reports ... ok
Ran 7 tests ... OK
```

The 20-page integration test executes page analysis, semantic SQLite writes, one 20-page chunk integration, character and prediction state creation, process-level resume, final four-pass analysis, and generation of all seven Markdown files.

## GUI and Windows boundary

- Full single-window UI construction and clean shutdown: `UI_SMOKE_OK`.
- Self-authored sample reader launched as a real Windows window and was found by Win32 enumeration.
- Portable CPython/Tk root creation: Python 3.12.10, Tk 8.6 / Tcl 8.6.15.
- The Codex worker desktop refused `ImageGrab` even for the self-authored window. The application converted this to the required “画面を取得できません” stop path. No alternate protected-capture path was added. Normal interactive-desktop capture should be confirmed by the user with the included sample reader before a real book.

## Real local Vision model

Ollama 0.32.6 and installed `qwen3.5:9b` were detected through localhost. A generated sample page was sent through the production client:

- runtime detected: `ollama`
- response fields: all 13 required page-analysis fields
- retry count: 0
- JSON recovery: not needed
- elapsed: approximately 24 seconds on the first measured page
- model confidence: 0.95
- readability: 1.0

A second generated page also produced valid Japanese semantic summary, events, and evidence classification.

## Privacy scan

- Application network literals: loopback URLs only.
- Screenshot writes: none; JPEG encoding uses `BytesIO` only.
- SQLite BLOB/source text columns: none.
- API key persistence: disabled.
- Included content pages: only the original ten-page sample written for this project.

