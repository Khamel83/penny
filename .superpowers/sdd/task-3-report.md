# Task 3 report — Penny v2 delivery and provenance-safe retry

## Scope and SHA

- Base SHA: `0d2be9bc6728de7ed103216cde8ab8c38787efbb`
- Commit subject: `fix: deliver Penny captures to Maya once`
- Changed production files: `maya_delivery.py`, `core.py`, `watcher.py`,
  `webhook/server.py`
- Changed tests: `tests/test_transcript_contract.py`,
  `tests/test_core_and_classifier.py`, `tests/test_webhook.py`,
  `tests/test_watcher.py`

## RED evidence

All new behavior tests were written before the corresponding production change
and observed to fail for the intended missing behavior:

1. `/Users/macmini/penny/venv/bin/python -m pytest
   tests/test_transcript_contract.py -q -k maya`
   → `3 failed, 5 passed, 2 deselected, 2 subtests passed`; all three failures
   were `ModuleNotFoundError: No module named 'maya_delivery'`.
2. `/Users/macmini/penny/venv/bin/python -m pytest
   tests/test_core_and_classifier.py tests/test_webhook.py
   tests/test_watcher.py -q -k 'maya_origin_always or upload_success or
   ingest_success or maya_origin_retry'`
   → `4 failed, 67 deselected`; the legacy route was called for a `maya:*`
   source and canonical callers did not pass `allow_maya=False`.
3. `/Users/macmini/penny/venv/bin/python -m pytest tests/test_watcher.py -q
   -k 'new_recording_routes or ingest_pass_drains or maya_outbox_helper'`
   → `3 failed, 10 deselected`; the initial Voice Memo route lacked
   `allow_maya=False`, and the independent Maya outbox helper/loop did not
   exist.
4. `/Users/macmini/penny/venv/bin/python -m pytest
   tests/test_transcript_contract.py -q -k 'posts_authenticated or
   transport_retry'`
   → `2 failed, 8 deselected`; requests passed a dictionary through `json=`
   instead of exposing stable serialized request bytes through `data=`.

The brief's literal `python -m pytest` cannot run in this shell because
`python` is unavailable. Evidence uses Penny's configured virtual-environment
interpreter.

## GREEN evidence

- `/Users/macmini/penny/venv/bin/python -m pytest
  tests/test_transcript_contract.py tests/test_core_and_classifier.py
  tests/test_webhook.py tests/test_watcher.py -q`
  → `82 passed, 2 subtests passed in 0.28s`
- `/Users/macmini/penny/venv/bin/python -m pytest -q -k 'not
  test_process_audio_file_links_already_logged_voice_memo'`
  → `183 passed, 1 deselected, 2 subtests passed in 1.10s`
- `/Users/macmini/penny/venv/bin/python -m py_compile maya_delivery.py core.py
  watcher.py webhook/server.py tests/test_transcript_contract.py
  tests/test_core_and_classifier.py tests/test_webhook.py tests/test_watcher.py`
  → pass
- `git diff --check` → pass

The unfiltered full suite is `183 passed, 1 failed, 2 subtests passed`. The
single failure is pre-existing at the required base SHA:
`tests/test_sqlite_leak.py::SQLiteConnectionLeakTests::
test_process_audio_file_links_already_logged_voice_memo` patches
`watcher.transcribe`, but base `watcher.py` imports and calls only
`transcribe_with_quality`. Task 3 does not modify that test or seam.

## Self-review

### Standards

No repository-specific Python coding-standard file was present. Manual review
against the repository's existing module style and the code-review smell
baseline found no actionable standards issue. The new worker is isolated,
small, and uses the existing config and Task 2 persistence interfaces.

### Spec

- Every eligible request is the exact persisted `penny-maya.v2` envelope,
  serialized deterministically to stable UTF-8 bytes, authenticated with the
  Maya bearer token, and sent with a 10-second timeout.
- Receipt validation requires the exact six-field v2 receipt, matching
  transcript ID/hash, a non-empty Drop ID, a timezone-aware durable
  acknowledgement, and a real boolean duplicate marker before sent state.
- Exact duplicate receipts are accepted; Task 2's atomic receipt transition
  accepts only the same durable Drop ID and rejects conflicts.
- Timeouts, request failures, 408, 425, 429, and 5xx responses leave the
  persisted row pending for retry. This path never calls Apple Notes.
  Non-transient rejections and invalid/conflicting receipts fail closed into
  bounded durable error state.
- Initial Voice Memo, webhook upload, webhook text, and watcher retry paths
  route locally with `allow_maya=False`. Retry source comes from the persisted
  row. Core additionally forces every `maya:*` source to disallow Maya.
- Task 2's pending query and envelope builder independently exclude
  `quality_status=needs_review`, `ingest_state=needs_review`, and `maya:*`
  sources, so those rows never enter the v2 worker.
- The watcher drains one Maya delivery per ingest pass. The legacy v1 Maya
  helper remains available to noncanonical callers, preserving compatibility.

No external services, credentials, Apple Notes, Slack, Maya, or personal data
were contacted by the tests.

## Important-findings fixes

### Scope

- Fix base SHA: `183db460f38f0e543831738ce334a39d1499f8c3`
- Commit subject: `fix: address Penny Maya delivery review findings`
- Changed production files: `maya_delivery.py`, `transcript_log.py`, `watcher.py`
- Changed tests/artifact: `tests/test_transcript_contract.py`,
  `tests/test_transcript_log.py`, `tests/test_watcher.py`,
  `tests/fixtures/maya_penny_transcript_submission.schema.json`

### RED evidence

1. `/Users/macmini/penny/venv/bin/python -m pytest
   tests/test_transcript_contract.py tests/test_transcript_log.py
   tests/test_watcher.py -q -k 'local_maya_receipt_write or
   backs_off_transient or canonical_migration_adds_safe or
   maya_outbox_helper'`
   → `4 failed, 66 deselected`.
   - A simulated local SQLite receipt write was converted to terminal `failed`.
   - Transient delivery had no persisted attempt/backoff fields.
   - Legacy migration did not add the retry columns.
   - The watcher requested only one Maya row per pass.
2. `/Users/macmini/penny/venv/bin/python -m pytest
   tests/test_transcript_contract.py -q -k 'maya_v2_envelope_is_persisted or
   posts_authenticated'`
   → `2 failed, 10 deselected`; both failed because the canonical generated
   Maya JSON-schema fixture did not yet exist.

### GREEN evidence

- `/Users/macmini/penny/venv/bin/python -m pytest
  tests/test_transcript_contract.py tests/test_transcript_log.py
  tests/test_watcher.py -q -k 'local_maya_receipt_write or
  backs_off_transient or canonical_migration_adds_safe or maya_outbox_helper
  or maya_v2_envelope_is_persisted or posts_authenticated'`
  → `6 passed, 64 deselected`
- `/Users/macmini/penny/venv/bin/python -m pytest
  tests/test_transcript_contract.py tests/test_transcript_log.py
  tests/test_core_and_classifier.py tests/test_webhook.py
  tests/test_watcher.py -q`
  → `129 passed, 2 subtests passed in 0.68s`
- `/Users/macmini/penny/venv/bin/python -m pytest -q -k 'not
  test_process_audio_file_links_already_logged_voice_memo'`
  → `185 passed, 1 deselected, 2 subtests passed in 0.78s`
- Changed-file `py_compile` → pass
- Generated-artifact comparison against Maya's actual
  `PennyTranscriptSubmission.model_json_schema()` → exact match; recorded
  source and schema SHA-256 values match
- `git diff --check` → pass

The unfiltered broader suite remains `185 passed, 1 failed, 2 subtests passed`.
The only failure is the separately tracked pre-existing `watcher.transcribe`
test seam documented above; these Important-findings fixes do not modify it.

### Canonical artifact provenance

- Maya model:
  `app.integrations.penny.contracts.PennyTranscriptSubmission`
- Maya commit: `a8af56f0ef57848832d9ba0f0f4b923c7f1a3918`
- Model source SHA-256:
  `042c55c7133a46d831e798fc38061d33b202500ae99001c42e45ba7764e942e5`
- Generated schema SHA-256:
  `f23a15776806318844659c81f3008e0bb9766cf467ce2b10f63cff1cc53a7d8d`

Penny's tests use a generic standard-library JSON-schema subset validator
against this checked artifact. They do not define a second Pydantic contract.
The artifact validates exact fields, `extra="forbid"` behavior, scalar types,
SHA-256 patterns, date-time format, audio-provenance value types, and source
span structure. Existing semantic assertions continue to verify transcript
hash, stable client reference, and persisted provenance values. Schema and
source hashes make drift detectable; when the sibling Maya source is present,
the test also compares its live SHA-256.

### Self-review

#### Standards

No repository-specific standards violations or actionable smell-baseline
findings were found. Retry state remains in the existing transcript ledger,
and transport/validation/persistence responsibilities are separated in the
delivery worker.

#### Spec

- Remote malformed receipts and request identity/hash conflicts enter bounded
  terminal receipt failure state.
- Local receipt persistence exceptions are logged separately, leave the row
  replayable, and never call terminal invalid-receipt/conflict persistence.
- Transient request/408/425/429/5xx failures increment a durable attempt count,
  retain bounded error vocabulary, and schedule exponential 30–1,800 second
  backoff.
- Due-row selection excludes scheduled future attempts. A worker call snapshots
  up to its limit and continues across failures, while the watcher requests a
  bounded 20-row pass, preventing the oldest transient row from starving later
  eligible rows.
- The known earlier `watcher.transcribe` seam remains separately tracked and
  unchanged.
