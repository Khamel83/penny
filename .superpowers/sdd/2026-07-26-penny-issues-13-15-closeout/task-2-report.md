Task 2 report — durable Slack outbox and skipped/oversized-file behavior

Date: July 26, 2026
Workspace: `/Volumes/2TB_SSD/GitHub/.codex-worktrees/penny-slack-delivery-idempotency`
Base: `445114e2798a58807165e8a31cfbffbdca1bc593`

Changed files

- `transcript_log.py`
- `slack_delivery.py`
- `watcher.py`
- `tasks_poller.py`
- `webhook/server.py`
- `tests/test_transcript_log.py`
- `tests/test_slack_delivery.py`
- `tests/test_webhook.py`
- `tests/test_watcher.py`
- `README.md`
- `docs/reliability.md`

Design decisions

- Kept the existing UUIDv5 `client_msg_id` generation unchanged and preserved the existing bounded error-redaction path.
- Extended `slack_deliveries` to carry `next_attempt_at` and `provider_ts`, plus a status/next-attempt index for due-row selection.
- Added explicit `enqueue_slack` control to `insert_transcript(...)`; successful iCloud voice transcripts remain eligible by default, while non-voice and skipped placeholder paths now opt out explicitly.
- Preserved one durable Slack delivery row per transcript via `UNIQUE(transcript_row_id)` and a public `queue_slack_delivery(transcript_id)` helper.
- Switched retry scheduling to bounded backoff with `Retry-After` support, capped delays, and a terminal `failed` state after `SLACK_MAX_ATTEMPTS = 5`.
- Kept selection bounded and explicit in `get_pending_slack_deliveries(...)` by fetching only due `pending` rows and only the needed columns.
- Recorded Slack `ts` on acknowledgement and surfaced Slack pending/failed counts through watcher health output.

Tests, commands, and outputs

1. Focused regression suite after implementation:

```bash
pytest -q tests/test_transcript_log.py tests/test_slack_delivery.py tests/test_webhook.py tests/test_watcher.py
```

Output:

```text
...................................................                      [100%]
51 passed in 0.28s
```

2. Full repository verification:

```bash
pytest -q
```

Output:

```text
........................................................................ [ 64%]
.......................................                                  [100%]
111 passed in 0.37s
```

3. Diff hygiene:

```bash
git diff --check
```

Output:

```text
[no output]
```

Requirement coverage

- Durable outbox row per eligible transcript: implemented.
- Idempotent queueing and replay safety: implemented and covered.
- `status`, `attempt_count`, `next_attempt_at`, `last_error`, `provider_ts`, `created_at`, `updated_at`: implemented.
- Efficient due-row selection index: implemented.
- Explicit skipped oversized placeholder behavior with `enqueue_slack=False`: implemented and covered.
- Explicit non-voice opt-out paths (`Shortcut`, generic ingest, Maya-deliver, Google Tasks): implemented.
- Bounded timeout / existing worker boundary: preserved (`requests.post(..., timeout=10)` inside the watcher outbox pass).
- `Retry-After`, transient failure handling, terminal failure visibility in health: implemented and covered.
- Exact transcript body sent to Slack without truncation/summarization: preserved and covered.

Unresolved concerns

- The retry policy is now explicit and bounded at five attempts. The brief required a bounded terminal policy but did not prescribe an exact attempt count, so `5` is the local implementation choice for this PR stream.
- `get_pending_slack_deliveries(...)` now intentionally returns only due `pending` rows; terminal `failed` rows are surfaced through health/reporting rather than the pending selector.
