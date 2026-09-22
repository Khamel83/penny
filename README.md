# Penny

Penny is a local-first voice-capture pipeline for an Apple Watch, iPhone, and
Mac. A capture is staged and written to the canonical SQLite ledger before any
transcription, routing, or provider work. The current Phase A source is Voice
Memos; Just Press Record (JPR) is a later, explicitly gated pilot.

## Contract

The deployed Drop handoff uses a persistent cutover for future Voice Memos:
local transcript -> durable Penny Drop outbox -> Drop intake -> independent
Drop Slack/Maya readers. Audio remains local. The cutover is active at canonical
ID 755 after production receipt verification; existing direct delivery receipts
remain intact. Maya stores these notes without executing their contents.
See [Drop operations](docs/drop-delivery.md).

Other existing inputs and pre-cutover captures retain their prior routing path:

```text
capture -> immutable local staging -> canonical SQLite -> local MLX transcript
        -> local routing / Maya reasoning -> Hermes execution -> receipts
```

The ledger is the operational authority. Apple Notes and Reminders are
projections, Slack is an independent delivery stream, and Maya v2 is an
independent delivery stream. A provider outage cannot erase a locally persisted
capture. Every retry uses durable state and a deterministic idempotency key.

The iCloud Drive `Penny Archive` folder is a human-readable mirror, not the
database and not disaster recovery. Audio-bearing rows publish the same basename
for original audio, Markdown transcript, and JSON manifest. Text-only, Maya, and
Tasks rows may be recorded as `not_applicable`/`no_raw_audio` instead. The
manifest is published last, after hashes and complete-copy checks succeed.
Versioned homelab backup sets contain a consistent SQLite snapshot, archive
bytes, and a catalog; verification runs in a scratch directory only.

## Phase A status and boundaries

Phase A hardens the existing Voice Memos + MLX path without requiring JPR,
macOS 27, Swift/EventKit, Apple Speech, or MacWhisper. The transcription
dependency is `mlx-whisper==0.4.3`, with model revision
`a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb`, and requires `HF_HUB_OFFLINE=1`.
The default absolute model path is
`/Users/macmini/.penny/models/whisper-large-v3-turbo/a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb`.
Doctor must verify the local model manifest/weights receipt before readiness;
provisioning is a separate, explicit network step.

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

These are five macOS background services, not five AI agents. The voice-memo
path uses the watcher and shared Whisper; Tasks is a separate input, the webhook
provides intake/health, and export runs scheduled backups rather than continuously.

| Service | Responsibility |
| --- | --- |
| `com.penny.watcher` | Discovers and stages Voice Memos, requests offline transcription, and drains Drop plus legacy outboxes according to persisted ownership |
| `com.penny.shared-whisper` | Owns the shared local transcription model; unloads its worker when idle |
| `com.penny.tasks` | Polls the approved Google Tasks input and persists work before local routing |
| `com.penny.webhook` | Authenticated upload, text ingest, callback, `/health`, and `/ready`; loopback is the target bind policy |
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
- [Drop delivery and completed historical import](docs/drop-delivery.md)
- [Current capture health and historical exceptions](docs/capture-health.md)
- [Reliability](docs/reliability.md)
- [Mac mini deployment](docs/macmini-deployment.md)
- [Troubleshooting](docs/troubleshooting.md)

When investigating a capture, distinguish these evidence streams: local receipt,
durable archive, local routing, Apple receipt, independent Slack, independent
Maya v2, and backup verification. One stream never proves another.

### Historical Voice Memo recovery

Use `scripts/backfill_voice_memos.py` when the recurring watcher has already
advanced its discovery cursor and older Apple Voice Memos rows still need a
Penny ledger state. The command enumerates the complete current source, so it
does not depend on the watcher watermark:

```bash
venv/bin/python scripts/backfill_voice_memos.py --dry-run
venv/bin/python scripts/backfill_voice_memos.py --limit 50
```

Review the metadata-only JSON report before each bounded run. Repeat the
bounded command until `unindexed_ranges` is empty. A zero exact source/ledger
gap proves current source coverage only; each row still needs a linked
transcript or an explicit unavailable, retryable, needs-review, or terminal
state. `--limit 0` removes the batch limit after the dry run is understood.

Migration placeholders are not transcripts. The backfill also revisits linked
placeholder rows, recovers their words from available audio into the same
canonical ID, and publishes a new archive generation. Reports include
`placeholder_source_count`; source coverage alone does not establish that
transcription is complete. Historical placeholders longer than five minutes
use bounded local audio chunks and private restart checkpoints. Their original
audio stays intact. The normal capture path retains its configured size limit.
Historical requests use the shared service's background priority, so a new
Penny capture can interrupt a historical chunk. Recovery resumes from the last
saved chunk. `scripts/run_voice_memo_recovery.py` runs bounded passes under a
single-process lock and saves metadata progress in
`~/.penny/historical-recovery.json`; it is suitable for a supervised local
launchd job and loads credentials from the installed watcher without printing
them. A nonzero exit or remaining placeholder count is incomplete recovery.
The runner freezes its source cutoff in `historical-recovery-scope.json` on its
first start. Later recordings belong to the live watcher and are never silently
absorbed into the local-only historical pass.

The historical pass is local-only: it uses Penny's offline local transcription
backend, does not call external/cloud providers, does not send
Slack/Maya/Apple/Notes/Reminders/Hermes/GitHub effects, and does not run outbox
workers. It may create Penny-owned local staging/archive work for the canonical
ledger row. Any external delivery requires a separate, explicit operator
action and its own receipt.

## Runtime configuration

Non-secret policy lives in `config.toml`. Secrets are runtime-only and dedicated
by boundary. The relevant names are `PENNY_INGEST_TOKEN` for upload/ingest,
`PENNY_WEBHOOK_SECRET` for the callback, and
`PENNY_HERMES_WEBHOOK_SECRET` for the dedicated Hermes notification boundary,
`PENNY_SLACK_BOT_TOKEN` for the Slack outbox, and
`MAYA_INGEST_TOKEN`/`MAYA_TRANSCRIPT_URL` for Maya v2. The callback/Hermes
Values must never be committed, printed, or copied into Doctor output.
The watcher and `com.penny.shared-whisper` launchd services must receive the
same runtime-only `PENNY_SHARED_WHISPER_TOKEN`.
Tracked/runtime webhook
templates must converge to loopback or an explicitly protected non-loopback
policy, and Doctor fails readiness for an unprotected bind.

Selected provider, Google Tasks, and webhook runtime logs now use bounded fields
and redacted exception classes. This is not a claim about every historical log
artifact in the repository; Doctor output and deployment evidence remain
metadata-only.

## Development checks

```bash
venv/bin/python scripts/trust_check.py
venv/bin/python -m pytest -q
```

Tests and trust checks are local evidence only; they do not prove live launchd
registration, macOS privacy permission, provider receipt, or downstream effect.
