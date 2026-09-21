# Voice Memo Historical Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a resumable, local-only historical Voice Memo backfill that indexes every current Apple source row, transcribes safely available audio, and reports exact source coverage without creating downstream effects.

**Architecture:** Extend the canonical SQLite schema with an explicit durable routing-suppression policy, then thread a `local_only` option through the existing safe Voice Memo processing path. Add a metadata-only operator command that enumerates the complete Apple source independently of the incremental watermark, processes bounded candidates, and reports unmatched source IDs as compact ranges. Project source/ledger coverage counters through the existing watcher health receipt and Doctor while leaving the normal watcher path unchanged.

**Tech Stack:** Python 3.11, SQLite migrations in `transcript_log.py`, existing `watcher.py` staging/transcription/archive primitives, `argparse`, pytest/unittest, macOS Voice Memos compatibility database.

**Spec:** `docs/superpowers/specs/2026-09-21-voice-memo-historical-backfill-design.md`

## Global Constraints

- Never write to Apple’s Voice Memos database or lower `source_watermarks`.
- The backfill must persist source metadata before file access or transcription.
- Historical processing must set `enqueue_slack=False`, `maya_delivery_eligible=False`, and durable `routing_suppressed=1`.
- Historical processing must not call `classify_and_route`, Apple Notes/Reminders, Hermes, Maya, Slack, or GitHub delivery adapters.
- Raw audio, transcript bodies, labels, paths, hashes, provider responses, and secrets must not appear in command output or operational logs.
- Use the existing no-symlink, in-root, stable-copy staging path and bounded retry/terminal-state rules.
- Preserve duplicate content-hash deduplication and existing downstream receipts.
- Run RED-GREEN TDD for every production behavior change.

## Review Focus

- Source rows below the live watermark must be enumerated and indexed without moving the cursor backward; test this in `tests/test_watcher.py` and `tests/test_backfill_voice_memos.py`.
- Local-only transcripts must never enter normal routing or any downstream outbox after a watcher restart; test suppression in `tests/test_transcript_log.py` and the backfill tests.
- A source row with an empty or unavailable path must remain visible with a bounded retryable/terminal state; test it in `tests/test_watcher.py`.
- A duplicate audio hash must link the new source row without adding a second canonical transcript or delivery row; test it in `tests/test_backfill_voice_memos.py`.
- Health output must report source/ledger coverage without leaking private content or paths; test the watcher receipt and Doctor projection in their focused suites.

### Task 1: Add durable local-only transcript policy and coverage queries

**Files:**
- Modify: `transcript_log.py:150-275, 1060-1170, 1860-2040, 5260-5315, 6380-6485`
- Test: `tests/test_transcript_log.py:3650-end`

**Interfaces:**
- Consumes: existing `insert_transcript_result`, `insert_transcript`, `get_pending`, and `voice_memo_ingest` schema.
- Produces: `routing_suppressed INTEGER`, `routing_suppression_reason TEXT`; `insert_transcript_result(..., routing_suppressed=False, routing_suppression_reason=None)`; `get_voice_memo_recording_pks() -> set[int]`; `get_voice_memo_coverage() -> dict[str, int]`.

- [ ] **Step 1: Write the failing migration and suppression tests**

Add tests that initialize a temporary database and prove:

```python
def test_local_only_transcript_is_not_returned_as_pending(self) -> None:
    row_id = transcript_log.insert_transcript(
        content_hash="local-only-hash",
        source="iCloud",
        transcript="historical text",
        ingest_state="transcribed",
        quality_status="passed",
        enqueue_slack=False,
        routing_suppressed=True,
        routing_suppression_reason="historical_local_only",
    )

    self.assertEqual(transcript_log.get_pending(), [])
    self.assertEqual(transcript_log.get_pending_slack_deliveries(), [])
    row = transcript_log.get_transcript(row_id)
    self.assertEqual(row["routing_suppressed"], 1)
    self.assertEqual(row["routing_suppression_reason"], "historical_local_only")
```

Add a coverage test with two source rows, one linked and one unlinked, and assert `get_voice_memo_recording_pks()` returns both and `get_voice_memo_coverage()` reports the ledger total, linked total, and unlinked total.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
/Users/macmini/penny/venv/bin/python -m pytest -q tests/test_transcript_log.py -k 'local_only or coverage'
```

Expected: failure because the migration columns, keyword arguments, and coverage functions do not exist.

- [ ] **Step 3: Implement the additive schema and query changes**

Add the two columns to the initial `transcripts` table and `_ensure_transcript_columns`. Thread the values through `_insert_transcript_transaction`, `insert_transcript_result`, and the compatibility `insert_transcript` wrapper. Add a separate `enqueue_quality_failure` flag, defaulting to `True` so the existing `enqueue_slack=False` contract remains unchanged; set it to `False` only for local-only historical processing. Change `get_pending` to include only rows where `COALESCE(routing_suppressed, 0) = 0`.

Add metadata-only queries with these exact shapes:

```python
def get_voice_memo_recording_pks() -> set[int]:
    """Return all source primary keys represented in the local ledger."""

def get_voice_memo_coverage() -> dict[str, int]:
    """Return bounded ledger counts without reading labels, paths, or bodies."""
```

`get_voice_memo_coverage()` must include `ledger_count`, `linked_count`, `unlinked_count`, `retryable_count`, `terminal_count`, and `local_only_count`.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the focused command again, then run the full ledger suites:

```bash
/Users/macmini/penny/venv/bin/python -m pytest -q tests/test_transcript_log.py tests/test_transcript_contract.py
```

Expected: all focused and ledger tests pass with no new Slack rows for the local-only fixture.

- [ ] **Step 5: Commit the ledger seam**

```bash
git add transcript_log.py tests/test_transcript_log.py tests/test_transcript_contract.py
git commit -m "feat: persist local-only Voice Memo policy"
```

### Task 2: Add all-source enumeration and local-only watcher processing

**Files:**
- Modify: `watcher.py:445-520, 745-1050`
- Test: `tests/test_watcher.py:1550-1735, 2420-2605`

**Interfaces:**
- Consumes: Task 1’s transcript policy and coverage functions; existing `get_new_recordings()` incremental query.
- Produces: `get_all_recordings() -> list[dict[str, Any]]`; `process_recording(recording, *, already_upserted=False, local_only=False) -> bool`; `_process_audio_file(..., local_only=False) -> bool`.

- [ ] **Step 1: Write the failing enumeration and policy tests**

Add a temporary source SQLite database containing primary keys `10`, `11`, and `12`, set the Penny watermark to `12`, and assert:

```python
recordings = watcher.get_all_recordings()
assert [row["Z_PK"] for row in recordings] == [10, 11, 12]
```

Add a local-only processing test that patches transcription and every downstream route seam, processes one regular audio fixture, and asserts the canonical row is linked with `routing_suppressed=1`, no Slack row exists, and `classify_and_route` is not called. Add a missing-path test that asserts the source row remains in `awaiting_file` or bounded retry state. Add a duplicate-hash test that links a second source PK to an existing transcript without inserting a second transcript or Slack row.

- [ ] **Step 2: Run the focused watcher tests and verify RED**

Run:

```bash
/Users/macmini/penny/venv/bin/python -m pytest -q tests/test_watcher.py -k 'all_recordings or local_only or duplicate_hash or missing_path'
```

Expected: failures because all-source enumeration and the `local_only` parameter do not exist.

- [ ] **Step 3: Implement the minimal watcher changes**

Refactor the source query into a bounded helper and add:

```python
def get_all_recordings() -> list[dict[str, Any]]:
    """Read every current Voice Memo source row ordered by Z_PK."""
```

Keep `get_new_recordings()` as the existing `Z_PK > watermark` call. Thread `local_only=False` through `process_recording` and `_process_audio_file`, defaulting to the existing behavior. For local-only inserts, pass `enqueue_slack=not local_only`, `maya_delivery_eligible=not local_only`, `routing_suppressed=local_only`, and reason `historical_local_only`. Do not call `classify_and_route` when `local_only` is true; leave the canonical transcript in its transcription-complete state and link the source row without fabricating a downstream receipt. Preserve existing duplicate and quality-review behavior, including archive queueing.

When a missing or empty source path is encountered, retain the existing `awaiting_file` plus bounded retry behavior and do not expose the path in logs.

- [ ] **Step 4: Run focused and full watcher tests**

Run:

```bash
/Users/macmini/penny/venv/bin/python -m pytest -q tests/test_watcher.py -k 'all_recordings or local_only or duplicate_hash or missing_path'
/Users/macmini/penny/venv/bin/python -m pytest -q tests/test_watcher.py
```

Expected: all watcher tests pass, including the existing incremental-watermark and downstream-routing tests.

- [ ] **Step 5: Commit the watcher seam**

```bash
git add watcher.py tests/test_watcher.py
git commit -m "feat: support local-only historical Voice Memo processing"
```

### Task 3: Build the bounded backfill command and exact coverage report

**Files:**
- Create: `scripts/backfill_voice_memos.py`
- Create: `tests/test_backfill_voice_memos.py`

**Interfaces:**
- Consumes: Task 2’s `get_all_recordings()`, `_upsert_recording_metadata()`, and `process_recording(..., local_only=True)`.
- Produces: CLI `python scripts/backfill_voice_memos.py [--limit N] [--dry-run]`; `compact_ranges(values: Iterable[int]) -> list[str]`; `run_backfill(limit: int | None, dry_run: bool) -> dict[str, Any]`.

- [ ] **Step 1: Write failing command tests**

Use a temporary source database and temporary Penny database. Add tests proving:

```python
def test_backfill_processes_records_below_watermark_without_downstream_effects():
    report = run_backfill(limit=None, dry_run=False)
    assert report["source_records"] == 3
    assert report["unindexed_ranges"] == ["10-11"]
    assert report["processed_count"] == 2
    assert report["downstream_effect_count"] == 0
```

Add tests for `--limit` leaving the remaining source IDs in the next report, rerunning without duplicate transcript rows, preserving a missing-path source row, compacting `[1, 2, 3, 8]` to `['1-3', '8']`, and `--dry-run` producing no SQLite mutations. Assert the JSON report contains no fixture labels, paths, transcript text, or audio hashes.

- [ ] **Step 2: Run the command tests and verify RED**

Run:

```bash
/Users/macmini/penny/venv/bin/python -m pytest -q tests/test_backfill_voice_memos.py
```

Expected: failure because the command module and report functions do not exist.

- [ ] **Step 3: Implement the bounded operator command**

Implement `run_backfill()` as follows:

1. Call `transcript_log.init_db()`.
2. Read all source rows using `watcher.get_all_recordings()`.
3. Read the existing ledger PK set and select ascending candidates that are not represented or are unlinked retryable rows; do not reopen terminal rows unless a later explicit replay feature is added.
4. For each selected row, durably upsert metadata, then call `watcher.process_recording(row, already_upserted=True, local_only=True)`.
5. Do not modify the watermark, invoke outbox workers, or call any provider.
6. Read metadata-only ledger coverage and build exact unmatched source ranges from source PKs minus ledger PKs.
7. Print one stable JSON object with counts and bounded state names. Exit `0` when the command completed its selected batch, `1` for source/database failure, and `2` for invalid arguments.

The default batch limit is `50`; `--limit 0` means no limit. `--dry-run` performs source and ledger reads only. The command must not print logger output containing private source fields; configure its result output as the only operator-facing summary.

- [ ] **Step 4: Run focused tests and a hermetic CLI smoke test**

Run:

```bash
/Users/macmini/penny/venv/bin/python -m pytest -q tests/test_backfill_voice_memos.py tests/test_watcher.py -k 'backfill or all_recordings or local_only'
/Users/macmini/venv/bin/python scripts/backfill_voice_memos.py --help
```

Expected: all focused tests pass and help exits `0` without touching the live database.

- [ ] **Step 5: Commit the operator command**

```bash
git add scripts/backfill_voice_memos.py tests/test_backfill_voice_memos.py
git commit -m "feat: add resumable Voice Memo backfill command"
```

### Task 4: Project coverage into watcher health and Doctor

**Files:**
- Modify: `watcher.py:336-420`
- Modify: `doctor.py:40-125, 430-470, 850-905, 1060-1205`
- Test: `tests/test_watcher.py:2400-end`
- Test: `tests/test_doctor.py:1-end`

**Interfaces:**
- Consumes: Task 1’s `get_voice_memo_coverage()` and Task 2’s source snapshot.
- Produces: health fields `voice_memo_source_records`, `voice_memo_ledger_records`, `voice_memo_coverage_gap`, and Doctor projection of those fields plus `source_coverage_gap` when the gap is positive.

- [ ] **Step 1: Write failing health and Doctor tests**

Extend watcher health fixtures with source count `315` and ledger count `143`; assert the serialized receipt contains:

```text
|voice_memo_source_records:315|voice_memo_ledger_records:143|voice_memo_coverage_gap:172|
```

Add a Doctor fixture with those fields and assert the metadata output includes the same counters and returns a coverage reason without exposing a path, label, transcript, hash, or secret. Add a zero-gap fixture that does not add the reason.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
/Users/macmini/penny/venv/bin/python -m pytest -q tests/test_watcher.py tests/test_doctor.py -k 'coverage or source_records or ledger_records'
```

Expected: failures because the receipt fields and Doctor projection do not exist.

- [ ] **Step 3: Implement the health projection**

Have `watcher.update_health_check()` combine the current source snapshot count with `get_voice_memo_coverage()` and write the three bounded numeric fields. Extend Doctor’s safe-key allowlist and source/services inference to read the fields from the health receipt. A positive gap adds `source_coverage_gap` to the source reason; it remains distinct from daemon, database, transcription, archive, Slack, Maya, and Apple-effect states.

- [ ] **Step 4: Run focused and full Doctor/watcher tests**

Run:

```bash
/Users/macmini/penny/venv/bin/python -m pytest -q tests/test_watcher.py tests/test_doctor.py
```

Expected: all focused suites pass.

- [ ] **Step 5: Commit health projection**

```bash
git add watcher.py doctor.py tests/test_watcher.py tests/test_doctor.py
git commit -m "feat: expose Voice Memo source coverage"
```

### Task 5: Document operations, run full verification, and inspect the live backfill

**Files:**
- Modify: `README.md:35-100`
- Modify: `docs/reliability.md:20-45, 90-115`
- Modify: `docs/troubleshooting.md:1-140`
- Test: `tests/test_backfill_voice_memos.py`

**Interfaces:**
- Consumes: the completed CLI, health receipt, and Doctor behavior from Tasks 1–4.
- Produces: operator instructions and fresh evidence for local index, transcript, archive, runtime, and downstream boundaries.

- [ ] **Step 1: Write documentation tests/checks first**

Add a small `tests/test_backfill_voice_memos.py` assertion that the README names `scripts/backfill_voice_memos.py`, documents `--dry-run`, and states that the command does not send historical downstream effects. This fails until the docs are updated.

- [ ] **Step 2: Verify the documentation check fails**

Run:

```bash
/Users/macmini/penny/venv/bin/python -m pytest -q tests/test_backfill_voice_memos.py -k documentation
```

Expected: failure because the operator command is not documented.

- [ ] **Step 3: Document the workflow**

Add the dry-run, bounded-run, repeat-until-gap-zero, and metadata-only report commands. State that a zero source/ledger gap proves current source coverage only; each audio row still needs a transcript or explicit unavailable/failed state. State that the pass does not send historical content to any downstream provider and that external delivery requires a separate operator action.

- [ ] **Step 4: Run the documentation test and repository gates**

Run all of the following from the worktree:

```bash
/Users/macmini/penny/venv/bin/python -m pytest -q tests/test_backfill_voice_memos.py -k documentation
/Users/macmini/penny/venv/bin/python -m pytest -q
/Users/macmini/penny/venv/bin/python scripts/trust_check.py
git diff --check
```

Expected: the documentation test, full suite, trust check, and whitespace check all pass.

- [ ] **Step 5: Run a live metadata-only dry run**

With the isolated branch and the live runtime database selected read-only by the command, run:

```bash
/Users/macmini/penny/venv/bin/python scripts/backfill_voice_memos.py --dry-run
```

Verify the JSON contains only bounded counts/ranges, confirms the expected source/ledger gap, and does not contain any known private label, path, transcript text, audio hash, provider response, or secret. Do not run the mutating command until this read-only report is reviewed.

- [ ] **Step 6: Review the frozen diff and commit documentation**

```bash
git diff --stat ebf0af5...HEAD
git diff --check ebf0af5...HEAD
git status --short --branch
git add README.md docs/reliability.md docs/troubleshooting.md tests/test_backfill_voice_memos.py
git commit -m "docs: document historical Voice Memo recovery"
```

Review the full branch for raw-content leakage, accidental provider calls, watermark mutation, unsafe source paths, duplicate delivery creation, and any test that relies only on mocks rather than durable ledger state.

- [ ] **Step 7: Execute the approved live backfill only after verification**

Run the command in bounded batches, beginning with:

```bash
/Users/macmini/venv/bin/python scripts/backfill_voice_memos.py --limit 50
```

Repeat until the metadata-only report shows no unindexed source ranges and all remaining rows are explicitly linked, waiting, retryable, needs-review, or terminal. After each batch, record source count, ledger count, transcript-linked count, quality state counts, archive state, and downstream outbox counts separately. Do not run Slack/Maya/Apple outbox workers as part of verification.

- [ ] **Step 8: Final verification before integration**

Run:

```bash
git status --short --branch
git log -1 --oneline
/Users/macmini/venv/bin/python scripts/backfill_voice_memos.py --dry-run
/Users/macmini/venv/bin/python scripts/penny_doctor.py
```

Report the exact branch SHA, test/trust results, source-to-ledger coverage, transcript/quality outcomes, archive receipt state, runtime state, and downstream state independently. Do not claim complete delivery unless a provider receipt and downstream effect are separately proven.
