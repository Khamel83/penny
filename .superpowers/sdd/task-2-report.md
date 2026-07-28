# Task 2 report — Penny v2 delivery identity

## Scope and SHA

- Base SHA: `cac7437ac9665e627d580cbf88609e391d998b50`
- Commit subject: `feat: persist Penny v2 delivery identity`
- Changed files: `transcript_log.py`, `tests/test_transcript_log.py`,
  `tests/test_transcript_contract.py`, and this report only.

## RED evidence

All feature tests were written before their corresponding production code and
observed to fail for the missing behavior:

1. The legacy canonical-migration test failed with `no such column:
   quality_status`.
2. The canonical-insert test failed because `insert_transcript` did not accept
   `quality_status`.
3. The v2 contract test failed because `build_maya_v2_envelope` did not exist;
   the receipt-state test likewise failed for the missing Maya marker helpers.
4. The persisted-timestamp test failed because SQLite returned
   `2026-07-28 18:38:28`, not the required UTC ISO-8601 form.
5. The processed-file migration test failed because its
   `transcript_sha256` was `NULL`.

The brief's literal `python -m pytest` could not run because this shell has no
`python` executable. All evidence used Penny's configured interpreter:
`/Users/macmini/penny/venv/bin/python -m pytest`.

## GREEN evidence

- `/Users/macmini/penny/venv/bin/python -m pytest tests/test_transcript_log.py tests/test_transcript_contract.py -q`
  → `48 passed, 2 subtests passed in 0.48s`
- `/Users/macmini/penny/venv/bin/python -m py_compile transcript_log.py tests/test_transcript_log.py tests/test_transcript_contract.py`
  → pass
- `git diff --check` → pass

## Self-review

- Migration is idempotent and additive: no table is dropped, legacy transcript
  rows retain their values, and every pre-existing or newly migrated transcript
  receives the exact `sha256(transcript.encode("utf-8")).hexdigest()` value.
- New canonical state persists quality, delivery status, Drop ID, bounded Maya
  error detail, and nullable supersession identity. Existing Slack schema and
  migrations remain unchanged.
- Slack and Maya enqueue eligibility requires `quality_status == "passed"`.
  Maya pending delivery additionally excludes `maya:*` sources and
  `needs_review` rows.
- The persisted-row envelope contains exactly the ten `penny-maya.v2` fields,
  lowercases source, retains only redacted audio provenance, uses empty source
  spans, derives `client_ref` from the stable row ID, and normalizes capture
  time to UTC ISO-8601.
- Maya sent state accepts only an exact replay of the durable Drop ID;
  conflicting Drop IDs fail closed. Maya failure state is separate from Slack
  and stores only the existing bounded delivery-error vocabulary.

## Important-findings remediation

Base SHA: `c445980bc0697cc688264c53d399990c5289f6f3`.

### RED evidence

The new regression tests were added before implementation and all failed on
the prior commit:

1. The v2 contract exposed `/tmp/penny-v2-test.m4a` through
   `audio_provenance.audio_path` instead of `null`.
2. The envelope builder accepted both a `maya:*` source and a
   `needs_review` row whose quality status had been incorrectly marked
   `passed`.
3. A queued Slack delivery remained visible after its transcript was changed
   to `quality_status='needs_review'`.
4. A barrier-controlled conflicting receipt race returned two successes,
   proving the old read-then-write transition could overwrite a Drop ID.
5. A late Maya failure changed an already sent receipt back to `failed`.

### GREEN evidence

- `/Users/macmini/penny/venv/bin/python -m pytest tests/test_transcript_log.py tests/test_transcript_contract.py -q -k 'pending_slack_delivery_excludes or concurrent_conflicting_maya_receipts or maya_delivery_failure_does_not or maya_v2_envelope_is_persisted or maya_v2_envelope_rejects'`
  → `5 passed`
- `/Users/macmini/penny/venv/bin/python -m pytest tests/test_transcript_log.py tests/test_transcript_contract.py -q`
  → `52 passed, 2 subtests passed in 0.39s`
- `/Users/macmini/penny/venv/bin/python -m py_compile transcript_log.py tests/test_transcript_log.py tests/test_transcript_contract.py`
  → pass
- `git diff --check` → pass

### Remediation review

- The local audio path remains stored in Penny's transcript row but v2 emits
  `audio_path: null`.
- The builder itself now rejects `maya:*`, non-passed, and `needs_review`
  rows; the pending query remains a second boundary.
- Slack dequeue joins the transcript quality gate, so a preexisting outbox row
  cannot bypass later quarantine.
- Sent receipts use one conditional update: pending/failed rows with no Drop
  ID may become sent, and an already-sent row only accepts the identical Drop
  ID. The conflicting-race test gates the old initial read and proves exactly
  one Drop ID wins.
- Failure updates exclude sent or acknowledged rows, preserving terminal
  delivery evidence under delayed failure reports.
