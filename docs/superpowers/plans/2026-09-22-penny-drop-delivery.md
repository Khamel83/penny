# Penny to Drop Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Penny a text-and-metadata producer for Drop, with Drop owning independent Slack and Maya delivery.

**Architecture:** Extend Penny's transactional outbox and use Drop's existing intake unchanged. Add one Drop-owned Slack reader next to its existing Maya reader. Do not introduce a broker, a second Maya reader, or a general routing platform.

**Tech Stack:** Existing Python, SQLite, urllib, launchd, systemd, Drop HTTP contracts, Slack Web API.

**Spec:** `docs/penny-drop-handoff-design.md`

## Global Constraints

- Audio, local paths and credentials never enter the payload.
- Penny retains its original audio, canonical ledger and backups.
- Historical items enter Drop and Maya but produce no Slack flood and never execute old instructions.
- Do not run independent automatic senders for the same memo.
- Report intake acceptance, archive receipt, Slack message receipt and Maya receipt separately.
- Do not modify, commit or deploy unrelated changes with this work.
- Only existing ordinary/general Drop access is in scope. This is not a private-collection grant or a promise of per-project isolation.
- Keep dependencies unchanged unless an existing dependency cannot satisfy a demonstrated requirement.

## Review Focus

1. Accepted POST with lost response: retain an uncertain delivery and reconcile; never blindly duplicate.
2. Emoji, quotes, newlines and Slack mentions: preserve UTF-8 bytes without triggering mentions or markup.
3. A crash between external acceptance and local commit: recover by identity/receipt rather than assuming failure.
4. A memo spanning the cutover: assign delivery ownership once, not from changing runtime flags on each retry.
5. Historical placeholders or weak-quality text: exclude missing text; preserve quality labels and suppress historical notifications.

## Contract and file map

Penny changes: `transcript_log.py` owns additive schema and transactional state;
new `drop_delivery.py` owns HTTP submission/reconciliation; `config.py` and
`config.toml` own non-secret policy; `watcher.py` drains bounded work;
`doctor.py` reports metadata-only health; new `scripts/export_drop.py` handles
explicit historical import; existing deployment code installs configuration
without printing credentials. Tests live under `tests/`.

Drop changes: new `deploy/homelab/slack_reader.py` owns a callback using the
existing `clients/python/drop_client.py`; new `slack_delivery_store.py` owns
its local delivery ledger; new `drop-slack-reader.service` owns supervision.
Extend `scripts/deploy-homelab.sh`, `integrations.toml`, reader tests and the
operational docs. Do not change the Worker or Maya ingestion contract.

Each artifact is a UTF-8 `.txt` file: one compact ASCII JSON metadata line,
one blank line, then the unchanged canonical transcript. Required metadata:
`schema=penny.transcript.v1`, `producer_id`, `transcript_id`,
`transcript_sha256`, `recorded_at` (null if unknown), `duration_seconds`,
`quality_status`, `historical`, `notify_slack`. Producer ID is a persisted
installation UUID, not a hostname or local path. Event identity is
`penny:<producer_id>:<transcript_id>:<transcript_sha256>`. Payload bytes and
policy flags are frozen before any network attempt.

Submit `Content-Type: text/plain; charset=utf-8`, `X-Drop-Kind: text`,
`X-Drop-Client: penny`, `X-Filename: penny-<id>-<sha12>.txt`. Send ASCII JSON
in `X-Drop-Hints`, containing only `producer`, `producer_id`, `transcript_id`,
`transcript_sha256`, `historical`, `notify_slack`, `quality_status`, `schema`.
These eight hints are context, not authorization. Metadata in the body ensures
the existing Maya reader preserves it along with the text.

## Task 1: Transactional Penny state and immutable payload

**Files:** `transcript_log.py`, new `tests/test_drop_outbox.py`.

**Interfaces:** `build_drop_payload(row, producer_id, historical, notify_slack)
-> bytes`; `queue_drop_delivery(conn, transcript_id, payload) -> None`;
`claim_drop_delivery(now, lease_seconds=60) -> dict | None`;
`finish_drop_delivery(claim, state, receipt=None, next_attempt_at=None) -> bool`.
All updates require the claim token. Connection-taking queue calls must not
commit their caller's transaction.

- [ ] Write failing tests with isolated temporary databases, including this invariant:

```python
def test_repeated_queue_keeps_frozen_payload(conn, memo):
    payload = build_drop_payload(memo, 'installation-test', True, False)
    queue_drop_delivery(conn, memo['id'], payload)
    queue_drop_delivery(conn, memo['id'], payload)
    rows = conn.execute('SELECT payload FROM drop_deliveries').fetchall()
    assert rows == [(payload,)]
```

- [ ] Run `venv/bin/python -m pytest tests/test_drop_outbox.py -q`; verify the missing implementation causes failure.
- [ ] Implement an additive `drop_deliveries` table: identity unique, transcript foreign key, immutable payload BLOB/hash, status, attempt/lease timestamps, claim token, bounded error code, intake receipt and archive receipt. Statuses: pending, sending, accepted, uncertain, failed. Expired sending claims become uncertain, never pending. Use the existing SQLite transaction conventions.
- [ ] Verify effective SQLite settings per writer connection. Require synchronous FULL for the new durable state; evaluate macOS fullfsync on Penny and test the configured values. Keep network calls outside transactions and bound SQLITE_BUSY retries. Use the existing consistent-backup path, never copy only a live WAL main file.
- [ ] Queue new eligible voice-memo text in the same transaction as its canonical row. Apply the same rule to placeholder recovery/update paths. Normal captures with real needs-review text remain labeled; missing/error placeholders never become transcript payloads. Do not accidentally export Google Tasks or inbound Maya rows.
- [ ] Test rollback removes both transcript and outbox; stale claims cannot finish; duplicate queue cannot change bytes; unknown dates remain null; Unicode transcript survives byte-for-byte; no audio/path/token appears; recovered placeholder queues exactly one real revision. Re-run targeted tests and commit only these files.

## Task 2: Existing Drop intake adapter and reconciliation

**Files:** new `drop_delivery.py`, `tests/test_drop_delivery.py`, `config.py`, `config.toml`, `watcher.py`, `doctor.py`.

**Interfaces:** `submit_payload(payload, headers, token, opener) -> dict`;
`validate_receipt(receipt, payload) -> bool`;
`process_pending_drop_deliveries(limit=1) -> int`;
`reconcile_drop_delivery(claim, client) -> dict | None`.

- [ ] Write failing fake-HTTP tests. Core acceptance rule:

```python
def test_stored_pending_reconciliation_is_accepted(receipt, payload):
    receipt.update(ok=True, status='stored', queue_state='reconcile_pending', retryable=True)
    assert validate_receipt(receipt, payload)
```

- [ ] Run `venv/bin/python -m pytest tests/test_drop_delivery.py -q` and confirm failure.
- [ ] Implement receipt validation for stored status, UUID identity, payload SHA-256 and byte count. `stored` ends submission responsibility even when `retryable=true`; archive verification remains a separate field. Explicit rejected responses fail visibly; explicit retryable not-stored responses schedule retries. An ambiguous transport/server result or malformed success is uncertain. Do not follow authenticated redirects to another host.
- [ ] For uncertainty, page the existing read API and match producer identity, transcript identity and exact payload hash; verify the matching content hash. One match resolves; multiple matches flag duplicate/conflict; no match remains uncertain because absence does not prove failed staging. Keep retryable errors on bounded exponential backoff with jitter; honor supplied retry delays. No indefinite blocking in the transcription loop: one attempt per pass, ten-second network budget, retry scheduling in SQLite.
- [ ] Add disabled-by-default non-secret config; runtime-only `PENNY_DROP_TOKEN`; report pending count, oldest age, uncertain count and last acceptance without content. Test HTTP-200 refusal, storage-pending success, timeout after acceptance, wrong hash/length, multiple matches, token failure, and network outage with locally retained transcript. Run existing watcher/Doctor tests plus new tests and commit.

## Task 3: Drop-owned Slack reader

**Files:** Drop `deploy/homelab/slack_reader.py`, `deploy/homelab/slack_delivery_store.py`, `archive/tests/test_slack_reader.py`, `archive/tests/test_slack_delivery_store.py`.

**Interfaces:** `SlackSink(item: dict, data: bytes) -> None` callback;
`DeliveryStore.claim(identity, payload_hash) -> dict`;
`DeliveryStore.record(identity, state, **receipt_fields) -> None`.
Use a single supervised instance plus an exclusive process lock. Store per-item
state in `/var/lib/drop-slack-reader/deliveries.sqlite3` with private permissions.

- [ ] Write failing tests for sender filtering, historical suppression and exact identity replay:

```python
def test_historical_item_advances_without_slack(sink, historical_item, historical_bytes, slack):
    sink(historical_item, historical_bytes)
    assert slack.calls == []
```

- [ ] Run `python3 -m pytest archive/tests/test_slack_reader.py archive/tests/test_slack_delivery_store.py -q` in Drop and confirm failure.
- [ ] Parse only the versioned Penny envelope after validating content hash, client and source identity. Non-Penny items and historical items return without posting; malformed Penny content is recorded and raises a bounded error. Deduplicate on producer event identity as well as Drop ID; a repeated identity with conflicting bytes stops for review.
- [ ] Short artifacts use one message below 4,000 characters. Use plain-text blocks, suppress link/media unfurls and broadcast mentions, and include a stable non-sensitive identity marker. Validate Slack `ok`, channel and timestamp. Persist an in-flight state before calling Slack; after a crash reconcile channel history for the marker, matching bot and expected content hash. Zero matches does not authorize blind resend.
- [ ] Long artifacts use `files.getUploadURLExternal`, byte upload, then `files.completeUploadExternal` with the configured channel and a brief plain-text comment. Persist `file_id` before uploading and completion intent before completing. Accept only HTTPS Slack upload hosts and never forward the bot token to the upload URL. Reconcile uncertain completion with `files.info` and channel-share evidence; no second file allocation after an uncertain completion. Store the returned file ID and confirmed channel share.
- [ ] Honor HTTP429 Retry-After without truncating the requested wait; schedule rather than spin. Rate-limit channel posts to at most one per second. Treat credential/membership errors as visible failures. Do not swallow an unconfirmed delivery or advance its cursor. Maya's independent cursor continues normally.
- [ ] Persist method cooldowns across process restarts. Test restart during Retry-After. For short messages, budget the 3,000-character plain-text section limit separately from the 4,000-character total message budget; split into at most two sections. Treat truncation warnings as incomplete delivery, not success.
- [ ] Test >300KB text, emoji, literal `<!channel>`, upload interruption, complete response loss, crash after successful short post, rate limiting, revoked token, and restart/replay. Run Drop's existing reader tests too; commit source/tests only.

## Task 4: Supervision and explicit delivery ownership

**Files:** Drop `deploy/homelab/drop-slack-reader.service`, `scripts/deploy-homelab.sh`, `integrations.toml`; Penny `transcript_log.py`, `scripts/export_drop.py`, `tests/test_drop_cutover.py`, `tests/test_export_drop.py`.

**Interfaces:** `set_drop_cutover(conn, producer_id) -> dict` records cutoff and policy in a transaction; `export_drop(dry_run=True, limit=50) -> dict` queues historical artifacts only when explicitly applied.

- [ ] Write failing tests for a new memo concurrent with cutover and interrupted historical batches:

```python
def test_history_never_enables_slack(exporter, existing_memo):
    result = exporter(dry_run=False, limit=1)
    assert result['queued'] == 1
    assert exporter.last_payload_metadata['historical'] is True
    assert exporter.last_payload_metadata['notify_slack'] is False
```

- [ ] Implement persistent ownership policy read in the canonical insertion transaction. Pre-cutover existing Slack rows retain their owner and receipt. Post-cutover voice memos queue Drop, not direct Slack/Maya. Preserve existing direct Maya pending/dead-letter records for explicit reconciliation; do not relabel them sent. Coordinate live workers during cutover so an already-claimed row cannot be transferred to a second owner.
- [ ] Historical export defaults to dry-run, produces metadata-only counts, selects real voice-memo transcript rows including labeled needs-review text, excludes placeholders and non-memo records, and freezes payload identity/notification policy. Repeated apply is a no-op. Bound batches and give new captures priority.
- [ ] Install the Slack reader with restart-on-failure, restrictive filesystem access and vault token retrieval. Reuse deployment backup/hash verification conventions. Register consumer `slack` only after its service works; do not change the Maya cursor. A stalled Slack item must trigger the existing stuck-reader monitor.
- [ ] Test cutover ownership, fallback refusing ambiguous/already-sent rows, export replay, missing text, and concurrent recovery. Run both full suites. Commit changes and update both operational contracts to explain the new boundary.

## Task 5: Production verification, import and rollback

**Files:** both repositories' deployment/operational docs; private metadata-only receipt under Penny's local state directory, not raw transcripts in git.

- [ ] Recheck both git status outputs and remote heads. Use isolated worktrees. Drop was changing during design: implementation milestone `b2f6b57` is now documented as deployed, with additional dirty docs. Verify current state rather than deploying the old snapshot or another session's edits.
- [ ] Run `venv/bin/python scripts/trust_check.py` and `venv/bin/python -m pytest -q` in Penny; `make test` in Drop. Independently review the full diffs against the approved spec, especially uncertain writes and ownership.
- [ ] Push the reviewed commits. Install Drop's Slack reader and registry using the existing deployment scripts; verify installed file hashes, systemd status and consumer health. Install Penny with delivery disabled using `scripts/deploy_penny.py --apply`; verify all loaded revisions. Never print installed environments or credentials.
- [ ] Submit a labeled synthetic Penny artifact (`historical=false`, `notify_slack=true`, not a Drop canary because readers skip canaries). Require matching intake hash, OCI archive hash, Slack message/file read-back and Maya's matching source receipt. An advancing reader cursor alone does not prove Maya receipt.
- [ ] Exercise an isolated failure/restart test without interrupting other captures. Confirm the same identity does not create another Slack delivery. Verify alert/recovery behavior with a synthetic stalled-reader fixture, not by breaking production credentials.
- [ ] Back up Penny, activate persistent cutover, and verify a new real memo when one is available. If none arrives during the session, report the synthetic proof separately and explicitly retain the real-memo gate.
- [ ] Run historical export dry-run; apply bounded batches. Reconcile every submitted identity/hash against Drop archive receipts and Maya receipts, with explicit excluded/failed/uncertain counts. Never retry the complete historical set just because some are pending.
- [ ] Rollback stops new Drop-owned Slack delivery before re-enabling controlled Penny fallback. Reconcile all in-flight receipts first. Retain accepted items, cursors, ledger rows and original audio. Do not delete or repost historical content.
- [ ] Record exact pushed and installed revisions, local/edge/archive/Slack/Maya counts, uncertainty, historical exceptions and rollback state. Mark complete only with evidence for each claimed boundary.

## Current standards references

- Slack recommends short messages and documents truncation: https://docs.slack.dev/reference/methods/chat.postMessage/
- Honor Slack HTTP429 Retry-After: https://docs.slack.dev/apis/web-api/rate-limits/
- Supported file lifecycle: https://docs.slack.dev/messaging/working-with-files/
- Completion is a separate, once-only step: https://docs.slack.dev/reference/methods/files.completeUploadExternal/
- The old files.upload API retired in 2025; do not introduce it: https://docs.slack.dev/changelog/2024-04-a-better-way-to-upload-files-is-here-to-stay/

This plan uses currently published primary-source contracts, not a claim to
know every practice introduced during September 2026. The companion research
note records additional evidence and qualifications.
