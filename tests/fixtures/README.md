# Phase 0 compatibility fixtures

`current_version_session.sqlite3.gz.b64` is a frozen SQLite database created
with the Phase 0 implementation. It is intentionally not generated during a
test run: future persistence implementations must continue to open this exact
database snapshot.

- Encoding: gzip-compressed SQLite bytes, then Base64 text
- Restored size: `110592` bytes
- Restored SHA-256: `5e0a6fe962eeb21394c39f1e1972a8fc50bc84130aae621c0311bcbba7c2edcc`
- Contents: one paused session, one page note, one user note, one chunk, one
  chapter checkpoint, capture settings, character state, prediction, and an
  unresolved question
- Excluded: page images, OCR/full text, API keys, and authentication data

The characterization test restores the SQLite bytes, verifies the size and
SHA-256 above, then opens the database through `ReadingMemory` and checks the
saved resume state. Do not replace this fixture when changing the current
schema; add a new versioned fixture instead.

