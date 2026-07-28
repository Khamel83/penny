# Task 4 report — Penny one-parent Slack Block Kit delivery

## Scope and SHA

- Base SHA: `f4a875516bf4679fcc137b4ff5b04077e7d57cfd`
- Commit subject: `fix: publish Penny transcripts as one Slack parent`
- Changed production files: `slack_delivery.py`, `transcript_log.py`
- Changed tests: `tests/test_slack_delivery.py`,
  `tests/test_transcript_contract.py`
- Schema migrations: none; the existing additive outbox progress and receipt
  columns are sufficient.

## RED evidence

All new production behavior was preceded by a focused failing regression.
The brief's literal `python` executable is unavailable in this shell, so the
commands use Penny's configured virtual-environment interpreter.

1. `/Users/macmini/penny/venv/bin/python3 -m pytest
   tests/test_slack_delivery.py -q -k block`
   → `1 failed, 14 deselected`.
   The 5,406-character regression failed because the outgoing fallback was
   still 5,406 characters instead of the bounded Block Kit fallback; the
   legacy payload had no `blocks`.
2. `/Users/macmini/penny/venv/bin/python3 -m pytest
   tests/test_slack_delivery.py -q -k 'uncertain_extreme or
   extreme_transcript'`
   → `2 failed, 14 deselected`.
   Both failures showed the first parent post was incorrectly treated as the
   complete delivery, so no durable continuation cursor or threaded resume
   occurred.

## GREEN evidence

- First cycle:
  `/Users/macmini/penny/venv/bin/python3 -m pytest
  tests/test_slack_delivery.py -q -k block`
  → `1 passed, 14 deselected`
- Second cycle:
  `/Users/macmini/penny/venv/bin/python3 -m pytest
  tests/test_slack_delivery.py -q -k 'uncertain_extreme or
  extreme_transcript'`
  → `2 passed, 14 deselected`
- Task 4 focus:
  `/Users/macmini/penny/venv/bin/python3 -m pytest
  tests/test_slack_delivery.py tests/test_transcript_contract.py -q`
  → `29 passed, 2 skipped, 2 subtests passed`
- Task 4 focus with Maya's actual canonical model enabled:
  `MAYA_REPO_PATH=/Volumes/2TB_SSD/GitHub/maya
  /Users/macmini/penny/venv/bin/python3 -m pytest
  tests/test_slack_delivery.py tests/test_transcript_contract.py -q`
  → `31 passed, 2 subtests passed`
- Full suite excluding the known base failure:
  `/Users/macmini/penny/venv/bin/python3 -m pytest -q -k
  'not test_process_audio_file_links_already_logged_voice_memo'`
  → `188 passed, 2 skipped, 1 deselected, 2 subtests passed`
- Changed-file `py_compile` → pass
- `git diff --check` → pass

The unfiltered full suite is
`188 passed, 1 failed, 2 skipped, 2 subtests passed`. The one failure is
pre-existing at the required base SHA and remains unchanged:
`tests/test_sqlite_leak.py::SQLiteConnectionLeakTests::
test_process_audio_file_links_already_logged_voice_memo` patches
`watcher.transcribe`, but `watcher.py` exposes only
`transcribe_with_quality`. Task 4 does not modify either file.

## Self-review

### Standards

No repository-specific Python standards file is present. Manual review against
the repository's existing style and the code-review smell baseline found no
actionable standards issue. Block construction is isolated behind small named
helpers, the public builder has the brief's exact signature, transport remains
separate from packing, and durable state transitions remain in
`transcript_log.py`. No unrelated schema, routing, or service changes were
introduced.

### Spec

- `build_transcript_message(transcript_id, text)` deterministically emits a
  bounded fallback, canonical `Penny transcript <id>` context identity, and
  exact `plain_text` sections of at most 3,000 characters.
- The 5,406-character regression emits one `chat.postMessage` call, no
  `thread_ts`, multiple bounded sections, one stable parent
  `client_msg_id`, one parent provider timestamp, and exact reconstruction of
  the persisted transcript from section blocks.
- Each message is capped at 50 blocks: one context plus at most 49 sections.
  Extreme bodies retain exactly one logical top-level parent; overflow is
  emitted only as deterministic numbered thread replies.
- The existing deterministic UUID namespace and per-index identity are
  preserved. An uncertain parent or continuation acknowledgement retries the
  same payload with the same `client_msg_id`.
- The existing `next_chunk_index`, per-part attempt count, and provider receipt
  list now represent parent/continuation progress. Every accepted receipt is
  committed before the cursor advances, and retries resume the first unsent
  continuation.
- `provider_ts` is now pinned to the first accepted parent receipt so all
  continuations use the stable parent thread timestamp; continuation receipts
  remain durably ordered in `chunk_provider_ts`.
- The original transcript remains unchanged in `message_text`, and exact text
  is recoverable by concatenating successful parent and continuation section
  blocks.
- Destination pinning, bounded retry/backoff, warning fail-closed behavior,
  safe error vocabulary, one-post-per-watcher-pass fairness, and terminal
  retry limits remain intact.

No Slack API, credentials, personal data, Maya write endpoint, or other
external service was contacted by the tests.

## Concerns

- The unrelated pre-existing `watcher.transcribe` full-suite failure remains
  outside Task 4 scope.
- This commit is not a deployment; live Slack behavior still requires the
  normal merge/deploy/restart and runtime outbox verification gates.

## Review-finding fixes

### Scope

- Fix base SHA: `162caea2b05612e799ab1c3621b35f9704e132ec`
- Commit subject: `fix: harden Penny Slack delivery plan receipts`
- Changed production files: `slack_delivery.py`, `transcript_log.py`
- Changed tests: `tests/test_slack_delivery.py`,
  `tests/test_transcript_log.py`

### RED evidence

1. `/Users/macmini/penny/venv/bin/python3 -m pytest
   tests/test_transcript_log.py -q -k versions_legacy_plans`
   → `1 failed, 45 deselected`.
   The seeded pre-version table had no durable `delivery_plan_version`, so the
   migration could not distinguish sent, unstarted, and partially progressed
   legacy rows.
2. After the first plan migration implementation,
   `/Users/macmini/penny/venv/bin/python3 -m pytest
   tests/test_transcript_log.py -q`
   → `1 failed, 45 passed`.
   The rollback fixture proved that a narrower legacy table also needed an
   additive `last_error` column before reconciliation could be recorded.
3. `/Users/macmini/penny/venv/bin/python3 -m pytest
   tests/test_slack_delivery.py -q -k non_v2_pending_plan`
   → `1 failed, 16 deselected`.
   The worker still posted and marked an explicitly legacy-plan row sent,
   proving the durable version was not yet enforced at execution.
4. `/Users/macmini/penny/venv/bin/python3 -m pytest
   tests/test_slack_delivery.py -q -k
   'invalid_parent_provider_ts or invalid_continuation_provider_ts'`
   → `6 failed, 2 passed, 17 deselected`.
   Missing, empty, and non-string timestamps advanced both parent and
   continuation cursors.

The markup/Unicode boundary finding was a test-coverage gap rather than a
production defect. Its new regression passed on first execution and required
no production change.

### GREEN evidence

- Seeded legacy-plan migration:
  `/Users/macmini/penny/venv/bin/python3 -m pytest
  tests/test_transcript_log.py -q -k versions_legacy_plans`
  → `1 passed, 45 deselected`
- Complete transcript-log migration suite:
  `/Users/macmini/penny/venv/bin/python3 -m pytest
  tests/test_transcript_log.py -q`
  → `46 passed`
- Runtime non-v2 fail-closed behavior:
  `/Users/macmini/penny/venv/bin/python3 -m pytest
  tests/test_slack_delivery.py -q -k non_v2_pending_plan`
  → `1 passed, 16 deselected`
- Parent and continuation receipt validation:
  `/Users/macmini/penny/venv/bin/python3 -m pytest
  tests/test_slack_delivery.py -q -k
  'invalid_parent_provider_ts or invalid_continuation_provider_ts'`
  → `2 passed, 17 deselected, 6 subtests passed`
- Markup/Unicode boundary preservation:
  `/Users/macmini/penny/venv/bin/python3 -m pytest
  tests/test_slack_delivery.py -q -k boundary_crossing_markup`
  → `1 passed, 19 deselected`
- Combined Task 4 focus:
  `/Users/macmini/penny/venv/bin/python3 -m pytest
  tests/test_slack_delivery.py tests/test_transcript_log.py
  tests/test_transcript_contract.py -q`
  → `79 passed, 2 skipped, 8 subtests passed`
- Full suite excluding the known base seam:
  `/Users/macmini/penny/venv/bin/python3 -m pytest -q -k
  'not test_process_audio_file_links_already_logged_voice_memo'`
  → `193 passed, 2 skipped, 1 deselected, 8 subtests passed`
- Changed-file `py_compile` → pass
- `git diff --check` → pass

### Self-review

#### Standards

No repository-specific Python standards file is present. Manual review against
the repository's existing style and the code-review smell baseline found no
actionable issue. Plan classification remains inside the transactional
migration, runtime enforcement is a small pre-transport guard, receipt
validation remains at the provider boundary, and no test-only production API
was introduced.

#### Spec

- Fresh-schema and newly queued rows persist `block_kit_v2`.
- Existing unversioned rows are classified transactionally. Sent rows remain
  unchanged and audit-readable as `legacy_top_level_v1`. Pending or retryable
  rows are upgraded only when `next_chunk_index = 0`, `provider_ts IS NULL`,
  and the receipt list is exactly empty.
- Any unversioned row with non-empty or inconsistent progress is retained with
  its original cursor and receipts, marked `failed`, assigned
  `legacy_top_level_v1`, and given the bounded
  `legacy_partial_reconciliation_required` error with no retry time.
- The worker independently rejects any pending plan other than
  `block_kit_v2` before transport and records the same explicit terminal
  reconciliation error.
- An `ok: true` Slack response now reaches persistence only when `ts` is a
  non-empty string. Missing, empty, and non-string values become bounded
  `provider_response_error` retries.
- Parent and continuation invalid-receipt tests prove no provider timestamp,
  receipt entry, or cursor update occurs, and the subsequent retry sends the
  byte-equivalent payload with the same `client_msg_id`.
- The boundary regression crosses section limits with `&`, `<`, `>`,
  mention-shaped text, backticks, CRLF, tab, emoji, and a combining character.
  Concatenated submitted `plain_text` sections equal the persisted transcript
  as both Python text and UTF-8 bytes.

### Remaining concerns

- Live deployment must separately query for partial pending pre-version rows
  before restart and verify the post-migration plan/status counts, as requested.
- The unrelated pre-existing `watcher.transcribe` full-suite failure remains
  outside Task 4 scope.
- No live Slack API, runtime database, credentials, or external service was
  contacted by these tests.
