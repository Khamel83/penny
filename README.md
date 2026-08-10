# Penny

Penny is a local-first voice-capture pipeline for an Apple Watch, iPhone, and
Mac. A capture is staged and written to the canonical SQLite ledger before any
transcription, routing, or provider work. The current Phase A source is Voice
Memos; Just Press Record (JPR) is a later, explicitly gated pilot.

## Contract

```text
capture -> immutable local staging -> canonical SQLite -> local MLX transcript
        -> local routing / Maya reasoning -> Hermes execution -> receipts
```

The ledger is the operational authority. Apple Notes and Reminders are
projections, Slack is an independent delivery stream, and Maya v2 is an
independent delivery stream. A provider outage cannot erase a locally persisted
capture. Every retry uses durable state and a deterministic idempotency key.

The iCloud Drive `Penny Archive` folder is a human-readable mirror, not the
database and not disaster recovery. Each published object has the same basename
for original audio, Markdown transcript, and JSON manifest. The manifest is
published last, after hashes and complete-copy checks succeed. Versioned
homelab backup sets contain a consistent SQLite snapshot, archive bytes, and a
catalog; verification runs in a scratch directory only.

## Phase A status and boundaries

Phase A hardens the existing Voice Memos + MLX path without requiring JPR,
macOS 27, Swift/EventKit, Apple Speech, or MacWhisper. The MLX Whisper package
and model revision are pinned locally and the transcription path requires
`HF_HUB_OFFLINE=1`. Model provisioning is a separate, explicit network step.

Any remaining direct OpenRouter classification is transitional. It remains only
until the Maya replacement is deployed, authenticated, idempotent, and verified
on representative captures; it is not the transcription backend. No provider
action, purchase, send, share, credential change, or deployment is implied by a
passing local test.

## Repository map

- `watcher.py` — Voice Memos compatibility adapter, staging, transcription, and
  durable outbox polling
- `transcript_log.py` — sole SQLite schema/migration owner and typed state,
  receipt, retry, archive, Slack, and Maya primitives
- `archive.py` — complete-copy staging, immutable objects, and manifest-last
  archive publication
- `backup.py` / `scripts/backup_penny.py` — versioned backup sets and scratch
  verification
- `doctor.py` / `scripts/penny_doctor.py` — read-only readiness probes and CLI
- `webhook/server.py` — authenticated, bounded upload/ingest/deliver routes
- `launchd/` — templates; a template is not proof that the installed agent is
  loaded or approved
- `docs/` — operational contracts and recovery guidance

## Services

| Agent | Responsibility |
| --- | --- |
| `com.penny.watcher` | Polls the Voice Memos compatibility source, stages audio, transcribes offline, and drains local/Slack/Maya outboxes |
| `com.penny.tasks` | Polls the approved Google Tasks input and persists work before local routing |
| `com.penny.webhook` | Loopback-by-default authenticated upload, text ingest, callback, `/health`, and `/ready` |
| `com.penny.export` | Creates a versioned backup, verifies it in scratch, and records a safe verification receipt |

## Readiness and operations

Run the Doctor from the repository environment:

```bash
venv/bin/python scripts/penny_doctor.py
```

Exit status is `0` for ready, `1` for degraded, and `2` for unready. Output is
metadata-only: bounded states, reason codes, counters, ages, and booleans; it
does not include transcript/audio bodies, secrets, paths, URLs, provider
responses, or process IDs. `/health` is an unauthenticated liveness endpoint.
`/ready` returns `200` for ready or degraded and `503` for unready.

Use the canonical docs for recovery and deployment:

- [Handoff](HANDOFF.md)
- [Reliability](docs/reliability.md)
- [Mac mini deployment](docs/macmini-deployment.md)
- [Troubleshooting](docs/troubleshooting.md)

When investigating a capture, distinguish these evidence streams: local receipt,
durable archive, local routing, Apple receipt, independent Slack, independent
Maya v2, and backup verification. One stream never proves another.

## Runtime configuration

Non-secret policy lives in `config.toml`. Secrets are runtime-only and dedicated
by boundary. The relevant names are `PENNY_INGEST_TOKEN` for upload/ingest,
`PENNY_WEBHOOK_SECRET` for the callback, `PENNY_SLACK_BOT_TOKEN` for the Slack
outbox, and `MAYA_INGEST_TOKEN`/`MAYA_TRANSCRIPT_URL` for Maya v2. Values must
never be committed, printed, or copied into Doctor output. The webhook binds to
loopback unless an explicitly protected deployment policy says otherwise.

## Development checks

```bash
venv/bin/python scripts/trust_check.py
venv/bin/python -m pytest -q
```

Tests and trust checks are local evidence only; they do not prove live launchd
registration, macOS privacy permission, provider receipt, or downstream effect.
