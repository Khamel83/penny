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
