# Penny overview for agents

## Purpose

Penny is local-first voice capture middleware. It accepts Apple Watch/Voice
Memos captures and approved uploads, preserves them locally, transcribes with a
verified offline MLX Whisper model, and routes through durable local, Slack, and
Maya v2 boundaries.

## Authority and ownership

- `transcript_log.py` owns the additive SQLite schema and canonical state.
- `watcher.py` owns source discovery, local staging, transcription orchestration,
  and bounded outbox polling.
- `archive.py` owns immutable local audio objects and iCloud mirror publication.
- `backup.py` owns versioned snapshots, catalogs, and scratch-only verification.
- `doctor.py` owns metadata-only readiness probes.
- Maya owns interpretation, policy, approval state, and action envelopes.
- Hermes owns execution of approved capability calls and execution evidence.
- Slack is a confirmation/notification stream, never the canonical ledger.

## Durable flow

```text
capture -> staged bytes -> SQLite row -> MLX transcript -> policy/action
        -> Apple receipt / independent Slack / independent Maya v2
```

Every external effect has a stable idempotency key, a durable attempt state, and
a provider receipt or explicit bounded failure. A database failure never counts
as an acknowledgement. Voice Memos discovery and completion watermarks are
separate; failed or incomplete captures remain retryable or quarantined.

## Model boundary

Phase A uses the exact pinned MLX Whisper package/model revision from the local
model inventory and requires `HF_HUB_OFFLINE=1`. The model path is verified
before use; provisioning is the only network boundary. Apple Speech and
MacWhisper are later challengers and cannot replace canonical transcripts until
measured gates pass.

Any remaining direct OpenRouter classification is transitional. Do not remove it
until Maya's replacement is deployed, authenticated, idempotent, and verified.
OpenRouter is not part of the transcription path.

## Readiness

`venv/bin/python scripts/penny_doctor.py` emits only bounded metadata. Exit `0`
means ready, `1` degraded, and `2` unready. `/health` is liveness; `/ready` is
readiness. Doctor does not read transcript/audio bodies, call providers, inspect
TCC databases, repair state, or report secrets, URLs, raw paths, errors, or PIDs.

## Agent rules

Preserve raw audio, manifests, SQLite IDs, outbox rows, receipts, dead letters,
and backup sets. Treat iCloud as a rebuildable mirror and JSON exports as
readable aids, never as the operational backup. Use scratch-only restore checks.
Do not infer deployment or downstream success from a template, process status,
log line, HTTP request, or generated summary; require an exact revision and a
durable receipt.
