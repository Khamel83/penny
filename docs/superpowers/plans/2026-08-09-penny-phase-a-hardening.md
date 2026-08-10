# Penny Phase A Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing macOS 26 Penny pipeline durable, authenticated, restorable, locally transcribed, idempotent, and truthfully observable without requiring Just Press Record, macOS 27, or a Swift rewrite.

**Architecture:** Preserve SQLite and the existing Python services as the Phase A operational core. Add typed persistence outcomes and additive schema primitives first, then layer durable source retry, a Penny-owned raw-audio/archive outbox, Apple-effect receipts, bounded Maya delivery, versioned backup/restore, an offline-pinned MLX backend, and a read-only Doctor. Every external effect is persisted before acknowledgement and every migration remains backward-readable during rollout.

**Tech Stack:** Python 3.14, SQLite/WAL, Flask, MLX Whisper 0.4.3, ffmpeg, AppleScript/`osascript`, launchd, rsync/SSH, unittest, pytest.

## Global Constraints

- Phase A must preserve the current Voice Memos + MLX + local Apple routing + independent Slack/Maya v2 behavior.
- Do not implement JPR ingestion, the Maya reasoning/OpenRouter cutover, Swift/EventKit, Apple Speech, MacWhisper CLI, or the macOS 27 upgrade in this plan.
- Keep legacy `content_hash`/MD5 behavior for compatibility; add full audio SHA-256 as a separate identity.
- Raw audio and transcription stay local; the explicitly approved verbatim `#penny` mirror and authenticated Maya/Hermes transcript path remain unchanged.
- The iCloud projection uses the original audio extension plus same-basename `.md` and `.json` files.
- Schema changes are additive and serialized through `transcript_log.py`; never run two schema-editing tasks concurrently.
- No secret values, transcript bodies, raw audio, or full environments may appear in logs, tests, commits, Doctor output, or deployment evidence.
- Preserve the current `/deliver` `PENNY_WEBHOOK_SECRET` contract; `/upload` and `/ingest` use a new dedicated `PENNY_INGEST_TOKEN`.
- Use bounded retry and explicit terminal state; never turn a timeout into an assumed external success or blindly retry an uncertain effect.
- Every task ends with focused tests and an explicit commit before the next task changes shared files.

---

## File and module structure

- `transcript_log.py` remains the sole SQLite schema/migration owner and exposes typed persistence, source retry, archive outbox, Apple receipt, and Maya dead-letter primitives.
- `ingress_auth.py` owns constant-time HTTP Bearer validation and content limits; `webhook/server.py` only wires it to routes.
- `archive.py` owns complete-copy staging, SHA-256, immutable local objects, Markdown/JSON rendering, and manifest-last iCloud publication.
- `apple_effects.py` owns deterministic effect keys and durable receipt orchestration; `reminders.py` remains the narrow AppleScript transport.
- `backup.py` owns SQLite snapshots, immutable archive catalogs, backup-set creation, and staging-only verification.
- `doctor.py` owns read-only probes and readiness policy; `scripts/penny_doctor.py` is only a CLI adapter.
- `transcript_quality.py` remains the transcription quality boundary and receives a resolved local model path from `config.py`.

### Task 1: Authenticate and bound alternate ingress

**Files:**
- Create: `ingress_auth.py`
- Modify: `config.py`
- Modify: `webhook/server.py`
- Modify: `launchd/com.penny.webhook.plist.template`
- Modify: `secrets.env.example`
- Modify: `docs/ios-shortcut-setup.md`
- Test: `tests/test_webhook.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `authorize_bearer(request, expected_token: str) -> bool`
- Produces: `MAX_INGEST_TEXT_BYTES = 65_536`
- Produces: `WebhookConfig.ingest_token: str` and `WebhookConfig.max_request_bytes: int`
- Preserves: `/deliver` validates only `PENNY_WEBHOOK_SECRET`; `/health` remains unauthenticated liveness.

- [ ] **Step 1: Write failing ingress-authentication and early-size-limit tests**

```python
def _ingest_auth(token: str = "ingest-test-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_upload_rejects_missing_token_before_transcription(client, monkeypatch):
    transcribe = MagicMock()
    monkeypatch.setattr(server_module, "transcribe", transcribe)
    response = client.post(
        "/upload",
        data={"audio": (io.BytesIO(b"audio"), "memo.m4a")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 401
    transcribe.assert_not_called()


def test_ingest_token_cannot_authorize_deliver(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "deliver-secret")
    response = client.post(
        "/deliver", json=DELIVER_PAYLOAD, headers=_ingest_auth()
    )
    assert response.status_code == 401


def test_oversized_ingest_is_rejected_before_route(client, monkeypatch):
    route = MagicMock()
    monkeypatch.setattr(server_module, "classify_and_route", route)
    response = client.post(
        "/ingest",
        json={"text": "x" * 65_537},
        headers=_ingest_auth(),
    )
    assert response.status_code == 413
    route.assert_not_called()
```

- [ ] **Step 2: Run focused tests and confirm authentication tests fail**

Run: `PENNY_INGEST_TOKEN=ingest-test-token venv/bin/python -m pytest tests/test_webhook.py tests/test_config.py -q`

Expected: new tests fail because `/upload` and `/ingest` still accept unauthenticated requests and `WebhookConfig` has no ingest token.

- [ ] **Step 3: Implement the constant-time route guard and pre-body limits**

```python
# ingress_auth.py
from __future__ import annotations

import hmac
from flask import Request

MAX_INGEST_TEXT_BYTES = 65_536


def authorize_bearer(request: Request, expected_token: str) -> bool:
    if not expected_token:
        return False
    header = request.headers.get("Authorization", "")
    scheme, separator, supplied = header.partition(" ")
    return bool(
        separator
        and scheme.lower() == "bearer"
        and supplied
        and hmac.compare_digest(supplied, expected_token)
    )
```

In `webhook/server.py`, set `app.config["MAX_CONTENT_LENGTH"]` to the configured audio maximum plus `1 * 1024 * 1024` bytes of multipart overhead. Call one `_require_ingest_auth()` helper at the start of `/upload` and `/ingest`, before `request.files`, `request.data`, or `request.get_json()`. Check `request.content_length` and the UTF-8 byte length of `text`; return JSON `401` or `413` without echoing content.

- [ ] **Step 4: Add dedicated runtime configuration without reusing callback/Hermes secrets**

```python
@dataclass
class WebhookConfig:
    port: int
    host: str
    ingest_token: str
    max_request_bytes: int

# get_config()
webhook=WebhookConfig(
    port=raw["webhook"]["port"],
    host=raw["webhook"]["host"],
    ingest_token=env("PENNY_INGEST_TOKEN"),
    max_request_bytes=(raw["voice_memos"]["max_file_size_mb"] + 1) * 1024 * 1024,
),
```

Add `PENNY_INGEST_TOKEN` to the webhook launchd template and secret example. Update Shortcut instructions to send `Authorization: Bearer <PENNY_INGEST_TOKEN>` and state that old headerless clients receive `401`.

- [ ] **Step 5: Run focused ingress tests**

Run: `PENNY_INGEST_TOKEN=ingest-test-token venv/bin/python -m pytest tests/test_webhook.py tests/test_config.py -q`

Expected: all focused tests pass, including valid-token success paths and `/deliver` secret separation.

- [ ] **Step 6: Commit the ingress boundary**

```bash
git add ingress_auth.py config.py webhook/server.py launchd/com.penny.webhook.plist.template secrets.env.example docs/ios-shortcut-setup.md tests/test_webhook.py tests/test_config.py
git commit -m "fix: authenticate and bound Penny ingress"
```

### Task 2: Add typed transcript persistence outcomes

**Files:**
- Modify: `transcript_log.py`
- Test: `tests/test_transcript_log.py`
- Test: `tests/test_sqlite_leak.py`

**Interfaces:**
- Produces: `InsertOutcome(str, Enum)` with `INSERTED`, `DUPLICATE`, and `FAILED`.
- Produces: `TranscriptInsertResult(outcome, row_id, existing_status, error_code)`.
- Produces: `insert_transcript_result(**kwargs) -> TranscriptInsertResult`.
- Preserves: `insert_transcript(**kwargs) -> int | None` as a compatibility wrapper until all callers migrate.

- [ ] **Step 1: Write failing inserted/duplicate/database-failure tests**

```python
def test_insert_result_distinguishes_duplicate_from_failure(self) -> None:
    inserted = transcript_log.insert_transcript_result(
        content_hash="typed-result", source="test", transcript="first"
    )
    duplicate = transcript_log.insert_transcript_result(
        content_hash="typed-result", source="test", transcript="first"
    )
    self.assertEqual(inserted.outcome, transcript_log.InsertOutcome.INSERTED)
    self.assertEqual(duplicate.outcome, transcript_log.InsertOutcome.DUPLICATE)
    self.assertEqual(duplicate.row_id, inserted.row_id)


def test_insert_result_reports_database_failure(self) -> None:
    with patch.object(transcript_log, "_get_conn", side_effect=sqlite3.OperationalError("locked")):
        result = transcript_log.insert_transcript_result(
            content_hash="db-failure", source="test", transcript="never stored"
        )
    self.assertEqual(result.outcome, transcript_log.InsertOutcome.FAILED)
    self.assertIsNone(result.row_id)
    self.assertEqual(result.error_code, "database_unavailable")
```

- [ ] **Step 2: Run focused tests and confirm the typed API is absent**

Run: `venv/bin/python -m pytest tests/test_transcript_log.py tests/test_sqlite_leak.py -q`

Expected: failures report missing `InsertOutcome`, `TranscriptInsertResult`, and `insert_transcript_result`.

- [ ] **Step 3: Implement the typed result without changing legacy callers**

```python
class InsertOutcome(str, Enum):
    INSERTED = "inserted"
    DUPLICATE = "duplicate"
    FAILED = "failed"


@dataclass(frozen=True)
class TranscriptInsertResult:
    outcome: InsertOutcome
    row_id: int | None = None
    existing_status: str | None = None
    error_code: str | None = None


def insert_transcript_result(**kwargs: Any) -> TranscriptInsertResult:
    content_hash = str(kwargs["content_hash"])
    try:
        row_id = _insert_transcript_transaction(**kwargs)
        if row_id is not None:
            return TranscriptInsertResult(InsertOutcome.INSERTED, row_id=row_id)
        existing = get_transcript_by_hash(content_hash)
        if existing is None:
            return TranscriptInsertResult(
                InsertOutcome.FAILED,
                error_code="duplicate_without_canonical_row",
            )
        return TranscriptInsertResult(
            InsertOutcome.DUPLICATE,
            row_id=int(existing["id"]),
            existing_status=str(existing["status"]),
        )
    except sqlite3.Error:
        return TranscriptInsertResult(
            InsertOutcome.FAILED,
            error_code="database_unavailable",
        )


def insert_transcript(**kwargs: Any) -> int | None:
    result = insert_transcript_result(**kwargs)
    return result.row_id if result.outcome is InsertOutcome.INSERTED else None
```

Refactor the current transaction body, unchanged, into `_insert_transcript_transaction(**kwargs: Any) -> int | None`; it remains responsible for the existing transcript, Slack, quality-failure, and Maya inserts in one transaction. Map SQLite operational failures to bounded safe error codes; never put exception text, SQL, paths, or content in the result. Ensure every connection closes on inserted, duplicate, and failed paths.

- [ ] **Step 4: Run typed-result and legacy compatibility tests**

Run: `venv/bin/python -m pytest tests/test_transcript_log.py tests/test_sqlite_leak.py -q`

Expected: new result tests pass and existing `insert_transcript()` integer/`None` expectations remain green.

- [ ] **Step 5: Commit the persistence primitive**

```bash
git add transcript_log.py tests/test_transcript_log.py tests/test_sqlite_leak.py
git commit -m "feat: distinguish transcript insert outcomes"
```

### Task 3: Migrate callers to fail closed on persistence errors

**Files:**
- Modify: `watcher.py`
- Modify: `webhook/server.py`
- Modify: `tasks_poller.py`
- Modify: `transcript_log.py`
- Test: `tests/test_watcher.py`
- Test: `tests/test_webhook.py`
- Test: `tests/test_tasks_poller.py`

**Interfaces:**
- Consumes: `insert_transcript_result()` and `TranscriptInsertResult` from Task 2.
- Produces: `get_transcript_by_hash(content_hash) -> dict | None` as the status authority for duplicate acknowledgement.
- Rule: `FAILED` never routes, marks a Voice Memo complete, returns HTTP success, or completes a Google Task.

- [ ] **Step 1: Write failing caller-behavior tests**

```python
def test_ingest_database_failure_returns_503(client, monkeypatch):
    monkeypatch.setattr(
        server_module,
        "insert_transcript_result",
        lambda **_: TranscriptInsertResult(InsertOutcome.FAILED, error_code="database_unavailable"),
    )
    response = client.post(
        "/ingest", json={"text": "buy milk"}, headers=_ingest_auth()
    )
    assert response.status_code == 503


def test_google_task_is_not_completed_when_persistence_fails(self):
    failed = TranscriptInsertResult(InsertOutcome.FAILED, error_code="database_unavailable")
    with patch.object(tasks_poller, "insert_transcript_result", return_value=failed), patch.object(
        tasks_poller, "_mark_task_complete"
    ) as complete:
        tasks_poller.poll_once()
    complete.assert_not_called()


def test_watcher_does_not_mark_source_routed_after_insert_failure(self):
    audio_path = Path(self.db_dir) / "persistence-failure.m4a"
    audio_path.write_bytes(b"audio")
    failed = TranscriptInsertResult(InsertOutcome.FAILED, error_code="database_unavailable")
    with patch.object(watcher, "insert_transcript_result", return_value=failed), patch.object(
        watcher, "mark_voice_memo_routed"
    ) as routed:
        self.assertFalse(
            watcher._process_audio_file(
                audio_path,
                file_hash="persistence-failure-hash",
                recording_pk=44,
            )
        )
    routed.assert_not_called()
```

- [ ] **Step 2: Run focused tests and verify current callers misclassify failure**

Run: `PENNY_INGEST_TOKEN=ingest-test-token venv/bin/python -m pytest tests/test_watcher.py tests/test_webhook.py tests/test_tasks_poller.py -q`

Expected: tests fail because production callers still use the legacy `int | None` result.

- [ ] **Step 3: Branch every caller explicitly on the typed outcome**

```python
result = insert_transcript_result(
    content_hash=content_hash,
    source=source,
    transcript=transcript,
    audio_path=audio_path,
    duration_seconds=duration_seconds,
)
if result.outcome is InsertOutcome.FAILED:
    raise PersistenceUnavailable(result.error_code or "persistence_failed")
if result.outcome is InsertOutcome.DUPLICATE:
    existing = get_transcript_by_hash(content_hash)
    if existing is None:
        raise PersistenceUnavailable("duplicate_without_canonical_row")
    row_id = int(existing["id"])
else:
    row_id = int(result.row_id)
```

For Google Tasks, acknowledge a duplicate only when the canonical row is already `routed`/`processed`; otherwise retry its pending route. For webhook persistence failure, return safe JSON `503`. For watcher persistence failure, leave or mark the source retryable and return `False`.

- [ ] **Step 4: Run focused caller tests**

Run: `PENNY_INGEST_TOKEN=ingest-test-token venv/bin/python -m pytest tests/test_watcher.py tests/test_webhook.py tests/test_tasks_poller.py -q`

Expected: all focused tests pass; no external acknowledgement occurs on `FAILED`.

- [ ] **Step 5: Commit caller migration**

```bash
git add watcher.py webhook/server.py tasks_poller.py transcript_log.py tests/test_watcher.py tests/test_webhook.py tests/test_tasks_poller.py
git commit -m "fix: fail closed when transcript persistence fails"
```

### Task 4: Make Voice Memo discovery and retry durable

**Files:**
- Modify: `transcript_log.py`
- Modify: `watcher.py`
- Test: `tests/test_transcript_log.py`
- Test: `tests/test_watcher.py`
- Test: `tests/test_sqlite_leak.py`

**Interfaces:**
- Produces: `get_source_watermark(source: str) -> int`.
- Produces: `advance_source_watermark(source: str, discovered_id: int) -> bool`.
- Produces: `get_voice_memo_recordings_for_retry(now, limit) -> list[dict]`.
- Produces: `mark_voice_memo_retryable(recording_pk, error_code, now) -> None`.
- Constants: maximum 8 source-processing attempts; backoff `min(30 * 2**(attempt-1), 1800)` seconds.
- Preserves: `last_pk.txt` as a compatibility mirror, never as the authoritative cursor.

- [ ] **Step 1: Write failing migration, retry, and cursor tests**

```python
def test_failed_voice_row_remains_retryable_after_watermark_advance(self):
    transcript_log.upsert_voice_memo_recording(
        293,
        label="retry me",
        raw_path="retry-293.m4a",
        duration_seconds=12.0,
        recorded_at="2026-08-08T23:00:00Z",
    )
    transcript_log.mark_voice_memo_retryable(293, "transcription_failed", now="2026-08-09T00:00:00Z")
    transcript_log.advance_source_watermark("voice_memos", 400)
    due = transcript_log.get_voice_memo_recordings_for_retry(
        now="2026-08-10T00:00:00Z", limit=10
    )
    self.assertEqual([row["recording_pk"] for row in due], [293])


def test_terminal_quality_row_is_not_retranscribed(self):
    transcript_log.upsert_voice_memo_recording(
        294,
        label="review terminal",
        raw_path="review-294.m4a",
        duration_seconds=8.0,
    )
    row_id = transcript_log.insert_transcript(
        content_hash="review-294",
        source="iCloud",
        transcript="needs review",
        ingest_state="needs_review",
        quality_status="needs_review",
        enqueue_slack=False,
    )
    transcript_log.link_voice_memo_transcript(
        294,
        transcript_row_id=int(row_id),
        content_hash="review-294",
        audio_path="review-294.m4a",
    )
    transcript_log.mark_voice_memo_terminal(294, "needs_review")
    due = transcript_log.get_voice_memo_recordings_for_retry(
        now="2026-08-10T00:00:00Z", limit=10
    )
    self.assertNotIn(294, [row["recording_pk"] for row in due])


def test_failed_upsert_does_not_advance_discovery_cursor(self):
    with patch.object(watcher, "upsert_voice_memo_recording", return_value=False):
        watcher._process_db_batch([{"Z_PK": 501}])
    self.assertLess(watcher.get_last_seen_pk(), 501)
```

- [ ] **Step 2: Run focused tests and verify failed rows are currently skipped**

Run: `venv/bin/python -m pytest tests/test_transcript_log.py tests/test_watcher.py tests/test_sqlite_leak.py -q`

Expected: failures show no durable watermark table, no retry schedule, and unconditional cursor advancement.

- [ ] **Step 3: Add additive watermark and retry schema**

```sql
CREATE TABLE IF NOT EXISTS source_watermarks (
    source TEXT PRIMARY KEY,
    last_discovered_id INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
```

Add `attempt_count`, `last_attempt_at`, `next_attempt_at`, `retryable`, and `terminal_at` columns to `voice_memo_ingest`, plus an index on `(retryable, next_attempt_at)`. Migrate the current `last_pk.txt` value only when no SQLite watermark exists.

- [ ] **Step 4: Update the watcher state machine**

Make `upsert_voice_memo_recording()` return `True` only after commit. Advance the SQLite discovery watermark after every row in the batch has been durably upserted, regardless of later processing outcome. Failed processing with no linked transcript schedules retry; quality-review and oversized rows link their durable transcript and set `retryable=0`. Refresh the Apple source row by PK before retrying.

- [ ] **Step 5: Run retry/restart tests**

Run: `venv/bin/python -m pytest tests/test_transcript_log.py tests/test_watcher.py tests/test_sqlite_leak.py -q`

Expected: crash/restart, backoff, max-attempt, PK-gap, and terminal-row tests pass.

- [ ] **Step 6: Commit durable source retry**

```bash
git add transcript_log.py watcher.py tests/test_transcript_log.py tests/test_watcher.py tests/test_sqlite_leak.py
git commit -m "fix: make Voice Memo discovery retryable"
```

### Task 5: Add Penny-owned raw staging and archive publication

**Files:**
- Create: `archive.py`
- Modify: `config.py`
- Modify: `config.toml`
- Modify: `transcript_log.py`
- Modify: `watcher.py`
- Test: `tests/test_archive.py`
- Test: `tests/test_watcher.py`

**Interfaces:**
- Produces: `StagedAudio(path, audio_sha256, byte_length, extension)`.
- Produces: `stage_audio(source: Path, object_root: Path) -> StagedAudio`.
- Produces: `queue_archive_delivery(transcript_id, staged: StagedAudio, metadata) -> None`.
- Produces: `process_archive_delivery(row: dict, mirror_root: Path) -> ArchiveReceipt`.
- Produces: one immutable local object and one same-basename `<audio>`, `.md`, `.json` iCloud trio.

- [ ] **Step 1: Write failing atomic-copy, deduplication, and manifest-last tests**

```python
def test_stage_audio_hashes_complete_bytes_and_deduplicates(tmp_path):
    source = tmp_path / "memo.m4a"
    source.write_bytes(b"complete-audio")
    first = stage_audio(source, tmp_path / "objects")
    second = stage_audio(source, tmp_path / "objects")
    assert first.audio_sha256 == hashlib.sha256(b"complete-audio").hexdigest()
    assert first.path == second.path
    assert first.path.read_bytes() == b"complete-audio"


def test_publish_writes_manifest_last_and_verifies_hashes(tmp_path):
    source = tmp_path / "memo.m4a"
    source.write_bytes(b"complete-audio")
    staged = stage_audio(source, tmp_path / "objects")
    receipt = publish_archive(
        staged=staged,
        transcript_id=478,
        transcript="buy milk",
        source="voice-memos",
        captured_at="2026-08-09T19:27:31Z",
        duration_seconds=3.2,
        backend="mlx-whisper",
        model="whisper-large-v3-turbo",
        mirror_root=tmp_path / "Penny Archive",
    )
    assert receipt.status == "published"
    manifest = json.loads(receipt.manifest_path.read_text())
    assert manifest["audio_sha256"] == sha256_file(receipt.audio_path)
    assert manifest["transcript_sha256"] == sha256_file(receipt.markdown_path)
```

Also inject a rename failure and assert no manifest appears, the temp files are removed, and the durable local object remains.

- [ ] **Step 2: Run archive tests and verify the module is absent**

Run: `venv/bin/python -m pytest tests/test_archive.py tests/test_watcher.py -q`

Expected: import/function failures for the new archive contract.

- [ ] **Step 3: Implement streaming stage and immutable object identity**

```python
@dataclass(frozen=True)
class StagedAudio:
    path: Path
    audio_sha256: str
    byte_length: int
    extension: str


def stage_audio(source: Path, object_root: Path) -> StagedAudio:
    source_size = source.stat().st_size
    digest = hashlib.sha256()
    object_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = object_root / f".{uuid.uuid4().hex}.partial"
    with source.open("rb") as reader, temporary.open("xb") as writer:
        os.chmod(temporary, 0o600)
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            digest.update(chunk)
            writer.write(chunk)
        writer.flush()
        os.fsync(writer.fileno())
    if source.stat().st_size != source_size or temporary.stat().st_size != source_size:
        temporary.unlink(missing_ok=True)
        raise SourceChangedError(source.name)
    audio_sha256 = digest.hexdigest()
    destination = (
        object_root / "sha256" / audio_sha256[:2]
        / f"{audio_sha256}{source.suffix.lower()}"
    )
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists():
        temporary.unlink()
    else:
        os.replace(temporary, destination)
        fsync_directory(destination.parent)
    return StagedAudio(destination, audio_sha256, source_size, source.suffix.lower())
```

Do not change legacy MD5 `content_hash`. Verify source size before and after the copy; a changing source is retryable, never publishable.

- [ ] **Step 4: Add a durable archive outbox and metadata**

Add `audio_sha256`, `transcription_backend`, and `transcription_model` columns to `transcripts`. Add one `archive_deliveries` row per transcript with unique `transcript_id`, local object path, status, attempts, next-attempt, destination paths, error code, and published timestamp. Store no transcript body in operational errors.

- [ ] **Step 5: Render and atomically publish the approved trio**

```python
basename = (
    f"{captured_at:%Y-%m-%dT%H-%M-%SZ}__p{transcript_id:08d}__"
    f"{safe_source}__{audio_sha256[:12]}"
)
audio_path = day_dir / f"{basename}{extension}"
markdown_path = day_dir / f"{basename}.md"
manifest_path = day_dir / f"{basename}.json"
```

Write audio and Markdown to temporary siblings and rename them; render JSON with schema version, source aliases, timestamps, duration, MIME, byte length, full hashes, backend/model, and quality state; rename the JSON manifest last. `watcher.py` stages before transcription, queues after canonical insert, and retries publication independently from Apple/Slack/Maya routing.

- [ ] **Step 6: Run archive and watcher tests**

Run: `venv/bin/python -m pytest tests/test_archive.py tests/test_watcher.py tests/test_transcript_log.py -q`

Expected: partial-copy, duplicate-source, same-hash alias, atomic failure, and retry tests pass.

- [ ] **Step 7: Commit the archive boundary**

```bash
git add archive.py config.py config.toml transcript_log.py watcher.py tests/test_archive.py tests/test_watcher.py tests/test_transcript_log.py
git commit -m "feat: archive raw Penny captures durably"
```

### Task 6: Make Apple Notes and Reminders idempotent

**Files:**
- Create: `apple_effects.py`
- Modify: `transcript_log.py`
- Modify: `reminders.py`
- Modify: `core.py`
- Test: `tests/test_reminders.py`
- Test: `tests/test_core_and_classifier.py`
- Test: `tests/test_transcript_log.py`

**Interfaces:**
- Produces: `AppleEffectReceipt(effect_key, effect_type, provider_id, state, reconciled)`.
- Produces: `ensure_note(transcript_id, text, folder, source) -> AppleEffectReceipt`.
- Produces: `ensure_reminder(transcript_id, text, list_name, fallback) -> AppleEffectReceipt`.
- Effect keys are derived and validated internally from the canonical transcript ID,
  effect type, requested/fallback target, and normalized payload SHA-256.
- Marker: `penny-effect:<sha256>` stored in the Note HTML comment or Reminder body.

- [ ] **Step 1: Write failing replay and ambiguous-write tests**

```python
def test_note_replay_finds_existing_marker_without_create(self):
    with patch.object(reminders, "_run_osascript", side_effect=["note-id-1", "note-id-1"]) as run:
        first = ensure_note(42, "body", "Penny", "test")
        second = ensure_note(42, "body", "Penny", "test")
    self.assertEqual(first.provider_id, second.provider_id)
    self.assertNotIn("make new note", run.call_args_list[-1].args[0])


def test_crash_after_apple_create_reconciles_marker_on_retry(self):
    real_mark = transcript_log.mark_apple_effect_succeeded
    attempts = 0

    def flaky_mark(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("locked")
        return real_mark(*args, **kwargs)

    with patch.object(
        reminders,
        "find_note_by_marker",
        side_effect=[
            [],
            ["x-coredata://note/provider-1"],
            ["x-coredata://note/provider-1"],
        ],
    ), patch.object(
        reminders,
        "create_note_with_marker",
        return_value="x-coredata://note/provider-1",
    ) as create, patch.object(
        transcript_log,
        "mark_apple_effect_succeeded",
        side_effect=flaky_mark,
    ):
        with self.assertRaisesRegex(AppleEffectError, "database_unavailable"):
            ensure_note(42, "body", "Penny", "test")
        receipt = ensure_note(42, "body", "Penny", "test")
    self.assertEqual(receipt.provider_id, "x-coredata://note/provider-1")
    create.assert_called_once()
```

- [ ] **Step 2: Run focused Apple tests and confirm create-only behavior fails**

Run: `venv/bin/python -m pytest tests/test_reminders.py tests/test_core_and_classifier.py tests/test_transcript_log.py -q`

Expected: tests fail because current adapters return only `bool` and never query provider state.

- [ ] **Step 3: Add the `apple_effects` durable table and effect-key helper**

```sql
CREATE TABLE IF NOT EXISTS apple_effects (
    effect_key TEXT PRIMARY KEY,
    transcript_id INTEGER NOT NULL,
    effect_type TEXT NOT NULL,
    requested_target TEXT NOT NULL,
    fallback_target TEXT NOT NULL DEFAULT '',
    payload_sha256 TEXT NOT NULL,
    state TEXT NOT NULL,
    provider_id TEXT,
    actual_target TEXT,
    reconciled INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_expires_at TEXT,
    stale_attempt_at TEXT,
    last_error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    succeeded_at TEXT,
    FOREIGN KEY(transcript_id) REFERENCES transcripts(id)
);

CREATE TABLE IF NOT EXISTS apple_effect_quarantine (
    id INTEGER PRIMARY KEY,
    effect_key TEXT NOT NULL,
    transcript_id INTEGER,
    effect_type TEXT,
    requested_target TEXT,
    payload_sha256 TEXT,
    state TEXT,
    provider_id TEXT,
    actual_target TEXT,
    reason_code TEXT NOT NULL,
    quarantined_at TEXT NOT NULL,
    UNIQUE(effect_key, reason_code)
);
```

Derive the key from canonical transcript ID, effect type, requested/fallback target,
and normalized payload SHA-256. Use `BEGIN IMMEDIATE` plus an exact lease owner
to claim and transition non-succeeded effects. A `succeeded` provider receipt is
monotonic; permission, marker/provider, invalid, and key conflicts quarantine the
effect. Partial-schema migration preserves valid rows and moves orphan metadata
(never transcript bodies) to `apple_effect_quarantine`.

- [ ] **Step 4: Implement query-before-create AppleScript transports**

For Notes, search the configured folder for `<!-- penny-effect:<key> -->`, return the existing note `id`, otherwise create a note containing the marker and read it back. For Reminders, use the reminder `body` marker and return the provider `id`. A timeout produces `uncertain`, not `failed`; retry reconciles by marker before creating.

- [ ] **Step 5: Migrate `core.classify_and_route()` to effect receipts**

Replace progress booleans as the external idempotency authority. Keep
`routing_progress` as a readable compatibility summary, but call
`ensure_note()`/`ensure_reminder()` with canonical transcript IDs so they derive
and validate keys internally, and mark routed only after durable `succeeded`
receipts.

- [ ] **Step 6: Run Apple replay tests**

Run: `venv/bin/python -m pytest tests/test_reminders.py tests/test_core_and_classifier.py tests/test_transcript_log.py -q`

Expected: normal create, replay, ambiguous timeout, receipt-write failure, and concurrent claim tests pass without duplicate creates.

- [ ] **Step 7: Commit Apple receipts**

```bash
git add apple_effects.py transcript_log.py reminders.py core.py tests/test_reminders.py tests/test_core_and_classifier.py tests/test_transcript_log.py
git commit -m "feat: reconcile Apple effects idempotently"
```

### Task 7: Bound Maya delivery and add dead-letter recovery

**Files:**
- Modify: `config.py`
- Modify: `config.toml`
- Modify: `transcript_log.py`
- Modify: `maya_delivery.py`
- Create: `scripts/replay_maya_delivery.py`
- Test: `tests/test_transcript_log.py`
- Test: `tests/test_watcher.py`

**Interfaces:**
- Constants/config: maximum 20 attempts and maximum age 7 days.
- Produces: `mark_maya_delivery_dead_letter(transcript_id, error_code, now) -> bool`.
- Produces: `replay_maya_delivery(transcript_id, now) -> bool` for explicit operator recovery only.
- Health adds pending/due/dead-letter/oldest-pending/max-attempt counts.

- [ ] **Step 1: Write failing attempt-cap, age-cap, and replay tests**

```python
def test_maya_delivery_dead_letters_at_attempt_cap(self):
    row_id = self._insert_maya_eligible()
    self._set_attempt_count(row_id, 19)
    transcript_log.mark_maya_delivery_retryable(row_id, "timeout", now=NOW)
    row = transcript_log.get_maya_delivery(row_id)
    self.assertEqual(row["maya_delivery_status"], "dead_letter")


def test_explicit_replay_preserves_identity_and_clears_terminal_state(self):
    row_id = self._dead_letter_row()
    envelope_before = transcript_log.build_maya_v2_envelope(row_id)
    self.assertTrue(transcript_log.replay_maya_delivery(row_id, NOW))
    self.assertEqual(
        transcript_log.build_maya_v2_envelope(row_id), envelope_before
    )
```

- [ ] **Step 2: Run Maya tests and verify retry remains unbounded**

Run: `venv/bin/python -m pytest tests/test_transcript_log.py tests/test_watcher.py -q`

Expected: new tests fail because `pending` rows never become terminal.

- [ ] **Step 3: Add terminal columns and monotonic state transitions**

Add `maya_first_attempt_at`, `maya_last_attempt_at`, `maya_dead_letter_at`, and `maya_dead_letter_reason` columns. `sent` and valid receipt fields remain immutable. Before scheduling another retry, compare attempt count and first-attempt age; transition to `dead_letter` when either limit is reached.

- [ ] **Step 4: Add explicit replay CLI without automatic bulk reset**

```python
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript-id", type=int, required=True)
    args = parser.parse_args()
    return 0 if replay_maya_delivery(args.transcript_id, utc_now()) else 1
```

Replay resets delivery scheduling only; it never changes transcript identity, hash, `client_ref`, sent receipts, or local/Slack state.

- [ ] **Step 5: Run bounded-delivery tests**

Run: `venv/bin/python -m pytest tests/test_transcript_log.py tests/test_watcher.py -q`

Expected: attempt/age terminal transitions, no-dequeue-after-terminal, replay, and health counters pass.

- [ ] **Step 6: Commit Maya dead-letter handling**

```bash
git add config.py config.toml transcript_log.py maya_delivery.py scripts/replay_maya_delivery.py tests/test_transcript_log.py tests/test_watcher.py
git commit -m "feat: bound and recover Maya delivery"
```

### Task 8: Produce versioned backups and verify staging-only restores

**Files:**
- Create: `backup.py`
- Create: `scripts/backup_penny.py`
- Create: `scripts/verify_penny_backup.py`
- Modify: `scripts/export_transcripts.py`
- Modify: `launchd/com.penny.export.plist.template`
- Test: `tests/test_backup.py`

**Interfaces:**
- Produces: `create_backup_set(db_path, archive_root, backup_root, now) -> BackupReceipt`.
- Produces: `verify_backup_set(set_path, scratch_root) -> VerificationReceipt`.
- Layout: immutable `objects/sha256/<first-two-hex>/<full-sha256><extension>` plus `sets/<UTC timestamp>/transcripts.db` and `catalog.json`.
- Retention: archive objects indefinite; database/catalog sets 90 days; deletion never propagates from iCloud into retained objects.

- [ ] **Step 1: Write failing snapshot/catalog/restore tests**

```python
def test_backup_uses_sqlite_backup_and_hash_catalog(tmp_path):
    receipt = create_backup_set(db_path, archive_root, tmp_path / "backup", NOW)
    assert receipt.status == "created"
    catalog = json.loads(receipt.catalog_path.read_text())
    assert catalog["database"]["sha256"] == sha256_file(receipt.database_path)
    assert sqlite_integrity(receipt.database_path) == "ok"


def test_restore_verifier_never_opens_live_database_for_write(tmp_path):
    receipt = verify_backup_set(set_path, tmp_path / "scratch")
    assert receipt.valid
    assert live_db.read_bytes() == original_live_bytes
```

Add tests for interrupted catalog write, missing object, wrong hash, rsync failure exit status, WAL activity during snapshot, and cleanup of only the exact scratch directory.

- [ ] **Step 2: Run backup tests and verify the versioned API is absent**

Run: `venv/bin/python -m pytest tests/test_backup.py -q`

Expected: import/function failures.

- [ ] **Step 3: Implement consistent SQLite snapshots and immutable catalogs**

Use `sqlite3.Connection.backup()` into a temporary database, run integrity/foreign-key checks, fsync, and rename. Copy archive objects by SHA-256 only when absent. Write `catalog.json` last with backup-set ID, schema/user version, row count, maximum transcript ID, every path/size/SHA-256, and creation time.

- [ ] **Step 4: Implement staging-only verification and remote propagation**

The verifier requires explicit absolute backup-set and scratch paths, rejects live `~/.penny` as scratch, verifies every catalog entry, opens the snapshot read-only, and emits no content. `scripts/backup_penny.py` rsyncs immutable objects plus the new set to `homelab:~/backups/penny/`; any rsync or remote-catalog failure exits nonzero. Keep the readable JSON export but make its write atomic and its sync result fatal.

- [ ] **Step 5: Run backup and restore tests**

Run: `venv/bin/python -m pytest tests/test_backup.py -q`

Expected: all local snapshot, catalog, corruption, rsync-failure, retention, and scratch-safety tests pass.

- [ ] **Step 6: Commit backup/restore proof**

```bash
git add backup.py scripts/backup_penny.py scripts/verify_penny_backup.py scripts/export_transcripts.py launchd/com.penny.export.plist.template tests/test_backup.py
git commit -m "feat: add versioned Penny backup verification"
```

### Task 9: Pin MLX Whisper locally and prove offline startup

**Files:**
- Modify: `requirements.txt`
- Modify: `config.py`
- Modify: `config.toml`
- Modify: `transcript_quality.py`
- Create: `scripts/pin_whisper_model.py`
- Modify: `launchd/com.penny.watcher.plist.template`
- Modify: `launchd/com.penny.webhook.plist.template`
- Test: `tests/test_config.py`
- Test: `tests/test_transcript_quality.py`
- Test: `tests/test_model_pin.py`

**Interfaces:**
- Produces: `VoiceMemosConfig.whisper_model_path: Path`.
- Produces: `verify_pinned_model(path: Path, expected_revision: str) -> ModelReceipt`.
- Pins: `mlx-whisper==0.4.3` and model revision `a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb`.
- Runtime: `HF_HUB_OFFLINE=1`; production transcription passes a local directory to MLX.

- [ ] **Step 1: Write failing local-path and offline tests**

```python
def test_transcription_rejects_nonlocal_production_model(tmp_path):
    with pytest.raises(ModelUnavailableError):
        resolve_whisper_model("mlx-community/whisper-large-v3-turbo", tmp_path)


def test_transcribe_passes_verified_local_path(monkeypatch, tmp_path):
    model = make_fake_verified_model(tmp_path)
    call = MagicMock(return_value={"text": "buy milk"})
    monkeypatch.setattr(mlx_whisper, "transcribe", call)
    transcribe_with_quality(audio_path, model=str(model))
    assert call.call_args.kwargs["path_or_hf_repo"] == str(model)
```

- [ ] **Step 2: Run focused model tests and verify repository IDs are still accepted**

Run: `venv/bin/python -m pytest tests/test_config.py tests/test_transcript_quality.py tests/test_model_pin.py -q`

Expected: failures show no local model receipt/path validation.

- [ ] **Step 3: Add deterministic provisioning and verification**

`scripts/pin_whisper_model.py` downloads the exact revision into a temporary directory, verifies required `config.json` and weight files, writes a SHA-256 manifest/receipt, fsyncs, and renames into `~/.penny/models/whisper-large-v3-turbo/<revision>/`. It is the only Phase A command allowed to use Hugging Face network access.

- [ ] **Step 4: Make runtime transcription fail closed and offline**

Resolve `PENNY_WHISPER_MODEL_PATH` first, require an absolute verified local directory, and pass it to `mlx_whisper.transcribe`. Add `HF_HUB_OFFLINE=1` and the local path to watcher/webhook templates. Preserve the two-attempt quality gate.

- [ ] **Step 5: Run focused tests with network calls forbidden**

Run: `HF_HUB_OFFLINE=1 venv/bin/python -m pytest tests/test_config.py tests/test_transcript_quality.py tests/test_model_pin.py -q`

Expected: all tests pass and any attempted HTTP/model-repository resolution fails the test.

- [ ] **Step 6: Commit the offline model contract**

```bash
git add requirements.txt config.py config.toml transcript_quality.py scripts/pin_whisper_model.py launchd/com.penny.watcher.plist.template launchd/com.penny.webhook.plist.template tests/test_config.py tests/test_transcript_quality.py tests/test_model_pin.py
git commit -m "feat: pin Penny transcription offline"
```

### Task 10: Add truthful Penny Doctor and readiness

**Files:**
- Create: `doctor.py`
- Create: `scripts/penny_doctor.py`
- Modify: `transcript_log.py`
- Modify: `watcher.py`
- Modify: `webhook/server.py`
- Modify: `.github/workflows/health-check.yml`
- Test: `tests/test_doctor.py`
- Test: `tests/test_webhook.py`

**Interfaces:**
- Produces: `DoctorReport(overall, components, observed_at, source_revision)`.
- CLI exit codes: `0=ready`, `1=degraded`, `2=unready`.
- `/health` stays liveness-only; `/ready` returns the safe Doctor projection and HTTP `200` only for ready/degraded, `503` for unready.
- No probe reads transcript/audio bodies or macOS TCC databases.

- [ ] **Step 1: Write failing readiness-policy and redaction tests**

```python
def test_doctor_marks_source_terminal_failure_unready(tmp_path):
    report = run_doctor(fixture_with_voice_terminal_failure(tmp_path))
    assert report.overall == "unready"
    assert report.components["voice_memos"].reason == "terminal_failure"


def test_doctor_separates_liveness_from_readiness(tmp_path):
    client = configured_client(unready_fixture(tmp_path))
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 503


def test_doctor_json_contains_no_secret_or_transcript(tmp_path):
    output = render_json(run_doctor(sensitive_fixture(tmp_path)))
    assert "secret-value" not in output
    assert "verbatim transcript" not in output
```

- [ ] **Step 2: Run Doctor tests and confirm current health is insufficient**

Run: `venv/bin/python -m pytest tests/test_doctor.py tests/test_webhook.py -q`

Expected: new module/route failures.

- [ ] **Step 3: Implement read-only component probes**

Probe launchd registration and freshness, canonical SQLite read-only integrity/schema, source watermark/retry/terminal counts, archive pending/failed/hash state, local model receipt, Apple permission/receipt state, Slack/Maya pending/dead-letter age, ingress-auth configuration, and latest successful backup/verification receipt. Each component returns `ready`, `degraded`, `unready`, or `unknown` with a bounded reason code and observed timestamp.

- [ ] **Step 4: Add CLI, safe `/ready`, and workflow consumption**

```python
def main() -> int:
    report = run_doctor()
    print(render_json(report) if args.json else render_human(report))
    return {"ready": 0, "degraded": 1, "unready": 2}[report.overall]
```

The GitHub health workflow runs `scripts/penny_doctor.py --json`, publishes only safe component/status fields, and does not automatically reset, delete, replay, or repair anything.

- [ ] **Step 5: Run Doctor and existing health tests**

Run: `venv/bin/python -m pytest tests/test_doctor.py tests/test_webhook.py tests/test_watcher.py -q`

Expected: readiness, stale evidence, unknown probe, redaction, and exit-code tests pass.

- [ ] **Step 6: Commit truthful readiness**

```bash
git add doctor.py scripts/penny_doctor.py transcript_log.py watcher.py webhook/server.py .github/workflows/health-check.yml tests/test_doctor.py tests/test_webhook.py tests/test_watcher.py
git commit -m "feat: add truthful Penny readiness"
```

### Task 11: Converge contracts, migrate, deploy, and verify Phase A

**Files:**
- Modify: `README.md`
- Modify: `HANDOFF.md`
- Modify: `LLM-OVERVIEW.md`
- Modify: `docs/reliability.md`
- Modify: `docs/troubleshooting.md`
- Modify: `docs/macmini-deployment.md`
- Modify: `homelab.yaml`
- Modify: `scripts/trust_check.py`
- Test: `tests/test_config.py`
- Test: `tests/test_transcript_contract.py`
- Test: `tests/test_doctor.py`

**Interfaces:**
- Consumes every Phase A contract from Tasks 1–10.
- Produces one canonical documented flow and a live-safe deployment receipt containing commit SHA, migration version, service states, Doctor status, backup verification ID, and redacted canary IDs.
- Rollback keeps additive columns/tables readable, preserves `last_pk.txt`, and restores config/services without deleting new evidence.

- [ ] **Step 1: Write failing contract assertions for documentation/config drift**

```python
def test_phase_a_contract_paths_and_secrets_are_documented():
    assert "PENNY_INGEST_TOKEN" in read("secrets.env.example")
    assert "PENNY_WEBHOOK_SECRET" in read("secrets.env.example")
    assert "Penny Archive" in read("README.md")
    assert "watcher.system.log" in read("docs/macmini-deployment.md")


def test_canonical_flow_is_local_first_with_independent_outboxes():
    overview = read("HANDOFF.md")
    assert "local routing" in overview
    assert "independent Slack" in overview
    assert "independent Maya v2" in overview
```

- [ ] **Step 2: Run contract and full repository baselines**

Run: `venv/bin/python -m pytest tests/test_config.py tests/test_transcript_contract.py tests/test_doctor.py -q`

Expected: documentation/contract tests fail until stale paths are updated.

- [ ] **Step 3: Update documentation and trust checks to one Phase A contract**

Document the real local-first flow, dedicated ingress/callback secrets, `.md` archive trio, SQLite authority, archive/backup distinction, Doctor exit codes, Voice Memo retry semantics, Apple receipts, Maya dead-letter recovery, offline MLX pin, deployed wrapper/template distinction, and staging-only restore. Remove Telegram-era promises and stale “Maya before Slack”/legacy progress-field claims.

- [ ] **Step 4: Run all hermetic verification before any live restart**

Run: `HF_HUB_OFFLINE=1 PENNY_INGEST_TOKEN=test-token venv/bin/python -m pytest tests/test_webhook.py tests/test_archive.py tests/test_backup.py tests/test_doctor.py tests/test_model_pin.py -q`

Expected: all Phase A focused tests pass.

Run: `HF_HUB_OFFLINE=1 PENNY_INGEST_TOKEN=test-token venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`

Expected: exit `0`, all collected tests pass, only documented skips remain.

Run: `HF_HUB_OFFLINE=1 PENNY_INGEST_TOKEN=test-token venv/bin/python scripts/trust_check.py`

Expected: exit `0`, compile/config/launchd/schema/health checks pass.

- [ ] **Step 5: Create pre-deployment recovery evidence**

Run the new backup command against the live database/archive, then fetch the produced set into a newly created scratch directory and run `scripts/verify_penny_backup.py`. Record only the backup-set ID, catalog SHA-256, SQLite row count/max ID, and verification status. Do not stop services or migrate until this passes.

- [ ] **Step 6: Provision runtime secrets/model without exposing values**

Generate a dedicated high-entropy `PENNY_INGEST_TOKEN` directly into the runtime secret store or installed plist using mode `0600`; never print it. Run `scripts/pin_whisper_model.py` once with network access, verify its manifest, set the absolute `PENNY_WHISPER_MODEL_PATH`, and set `HF_HUB_OFFLINE=1` for watcher/webhook. Compare deployed and expected secrets only by presence and hash metadata.

- [ ] **Step 7: Deploy additive migrations and restart affected launchd jobs**

Stop only `com.penny.watcher`, `com.penny.webhook`, `com.penny.tasks`, and `com.penny.export`; preserve logs, database, archive, and source files. Update the installed wrapper/plist environment, bootstrap the four jobs, and verify their loaded program arguments/environment names without printing values. Do not modify Voice Memos, iCloud source files, Notes, or Reminders during deployment.

- [ ] **Step 8: Run live-safe acceptance and rollback on any failed gate**

Verify exact deployed Git SHA, SQLite integrity/schema/migration version, source watermark/retry counts, authenticated `401`/valid-token request behavior without routing content, archive hash canary using synthetic bytes, MLX model receipt with offline mode, Slack/Maya outbox health, latest backup verification, and `scripts/penny_doctor.py --json`. A process PID or HTTP liveness response alone is not acceptance.

If a gate fails, stop affected new jobs, restore the previous installed config/wrappers and known-good code, retain additive schema/evidence, bootstrap the old services, and verify the preexisting Voice Memos + MLX + local routing path. Never delete new rows, archive objects, dead-letter evidence, or backup sets during rollback.

- [ ] **Step 9: Commit documentation and deployment contracts**

```bash
git add README.md HANDOFF.md LLM-OVERVIEW.md docs/reliability.md docs/troubleshooting.md docs/macmini-deployment.md homelab.yaml scripts/trust_check.py tests/test_config.py tests/test_transcript_contract.py tests/test_doctor.py
git commit -m "docs: converge Penny Phase A operations"
```

- [ ] **Step 10: Integrate and publish only after verification**

Confirm `git diff --check`, clean tracked status, exact commit list, full test exit code, backup/restore receipt, and live Doctor evidence. Merge the isolated Phase A branch into `main` without squashing away migration history, push `main`, restart from the pushed SHA if the deployment occurred before push, and repeat the live-safe acceptance checks against that exact SHA.

## Plan self-review

- Spec coverage: Tasks 1–11 cover all nine Phase A requirements plus migrations, rollback, docs, deployment, and live proof. JPR/OpenRouter cutover/native/macOS 27 work is explicitly excluded.
- Completeness scan: every task names exact files, interfaces, tests, commands, expected results, and commit boundaries.
- Type consistency: typed insert outcomes originate in Task 2 and all callers consume them in Task 3; source retry precedes archive integration; archive/Apple/Maya schema changes are serialized; Doctor consumes finalized backup/model/dead-letter contracts.
- Safety: no step deletes live/user data, prints secrets/content, mutates Apple source storage, or replays external effects automatically.
