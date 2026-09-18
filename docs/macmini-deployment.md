# Penny deployment on the Mac mini

This runbook describes a controlled deployment. It does not claim that the
current host is on this revision. Record the exact pushed SHA, runtime checkout
SHA, launchd labels, and Doctor result before calling a deployment complete.

## Runtime layout

The repository checkout contains Python services, `config.toml`, launchd
templates, scripts, and tests. The runtime state directory (configured by
`PENNY_*` paths) contains:

- canonical `transcripts.db`;
- immutable local archive objects for audio-bearing rows (text-only rows may be
  `not_applicable`/`no_raw_audio`);
- iCloud `Penny Archive` mirror metadata;
- versioned backup sets and the latest verification receipt;
- health freshness files and service diagnostics;
- private OAuth/runtime state where required.

The launchd-installed wrappers and plists are runtime artifacts, not tracked
templates. A wrapper must invoke the intended checkout/virtualenv and preserve
the dedicated runtime environment. A template documents the expected shape; it
does not prove that a plist is loaded, approved, or running. The launchd
`watcher.system.log` file is diagnostic output only.

## Services

| Label | Function | Schedule |
| --- | --- | --- |
| `com.penny.shared-whisper` | Single killable `large-v3-turbo` model owner for Penny and MinusPod | on demand/idle TTL |
| `com.penny.watcher` | Voice Memos compatibility ingest, staging, shared-Whisper client, local routing, and outboxes | continuous/polling |
| `com.penny.tasks` | Approved Google Tasks input and durable local routing | periodic |
| `com.penny.webhook` | Authenticated upload/ingest/callback plus `/health` and `/ready`; loopback is the target bind policy | continuous |
| `com.penny.export` | Versioned backup, scratch verification, and safe verification receipt | periodic |

## Preconditions

1. Work from a clean, reviewed revision and run the repository trust check.
2. Confirm the Mac has the approved arm64 Python/MLX/ffmpeg runtime and
   `mlx-whisper==0.4.3`.
3. Confirm model revision `a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb` at the
   absolute default path
   `/Users/macmini/.penny/models/whisper-large-v3-turbo/a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb`
   and verify its local manifest/weights receipt.
4. Keep `HF_HUB_OFFLINE=1` for the transcription services.
5. Confirm the host has only one large Whisper owner. The shared supervisor
   must refuse to start while the old `agent-cli` Whisper service or another
   shared worker is present. The tiny `com.wyoming.whisper` service on ports
   10300/10301 is a separate legacy consumer and is not changed by this
   rollout.
6. Confirm the 16 GB Mac has acceptable free-memory pressure before starting
   the worker. The default guard requires at least 12% free memory, refuses
   unreadable pressure/process probes, and unloads the idle worker after 300
   seconds. Record the worker RSS and `memory_pressure -Q` output in the
   maintenance receipt; do not tune the model size from guesswork.
7. Load dedicated credentials through the runtime secret mechanism; never put
   values in tracked config, templates, logs, or shell history.
8. Confirm the tracked/runtime webhook templates converge to loopback or an
   explicitly protected non-loopback policy; Doctor fails an unprotected bind.
   The callback uses `PENNY_WEBHOOK_SECRET`; Hermes uses the dedicated
   `PENNY_HERMES_WEBHOOK_SECRET`.
9. Create a verified backup set before changing code/config.

## Controlled deployment

Run local checks first:

```bash
venv/bin/python scripts/trust_check.py
venv/bin/python -m pytest -q
```

Before bootstrapping `com.penny.shared-whisper`, stop the old
`com.atlas.minuspod-whisper` job and prove its recorded PID and port 10311
listener are gone. If the old PID remains, stop and investigate; never launch
the new worker beside it. Then copy the reviewed checkout and wrapper/template inputs using the approved
deployment channel. Preserve runtime state, databases, archive objects,
outboxes, receipts, and prior backup sets. Update the installed wrappers/plists
only after checking their rendered environment for names (never values): model
path/revision, offline mode, dedicated ingress/callback/Hermes credentials,
Slack, and Maya v2.

Restart only the Penny labels that changed, using the normal launchd operator
procedure. Do not restart Apple providers, alter durable state, or replay outboxes as a
deployment step. Verify the installed labels and wrapper revision, then run the
Doctor and both HTTP endpoints locally. The shared service status must show one
model identity and at most one worker. Activity Monitor should show the stable
titles `Penny Shared Whisper` and `Penny Shared Whisper Worker (large-v3-turbo)`;
there must not be a second large model process.

## Acceptance evidence

Deployment evidence must include:

- pushed SHA equals the runtime checkout SHA;
- wrappers point to the intended checkout and virtualenv;
- launchd labels are registered and approved (registration is not a health
  result by itself);
- `penny doctor` exit/status and component reason codes;
- `/health` liveness and `/ready` readiness responses;
- shared-Whisper status with the pinned revision, one-worker count, no old
  large owner, and acceptable memory pressure;
- RSS samples for the supervisor and worker before and during a synthetic
  Atlas request plus one safe Penny canary;
- latest backup verification receipt bound to its catalog and database metadata;
- missing/wrong-token ingress requests return `401`, oversized requests return
  `413`, and hermetic valid-token tests pass; no live canary is implied.

Do not call a deployment healthy based on process presence, `watcher.system.log`, a template,
or a provider request. Physical Watch, Apple effect, Slack, and Maya canaries
require their own explicit approval and downstream receipts.

## Rollback

If a gate fails, stop Atlas intake, stop `com.penny.shared-whisper`, confirm
its worker PID is gone, restore the prior reviewed code
and runtime configuration, and rerun read-only Doctor/backup checks. Preserve
new staged objects, SQLite rows, outboxes, receipts, dead letters, and backup
sets for investigation. Restore the whole database only from a verified set and
only in a staging/scratch procedure before any external effect resumes.

Never delete or replace Apple Voice Memos data, the canonical SQLite database,
archive objects, or backup sets to force a green check. Credential rotation,
permanent deletion, external sends/shares, and production deployment remain
explicit human gates.

## Ongoing checks

Use the Doctor for readiness and the ledger/receipt tables for durable evidence.
Use `watcher.system.log` and other service logs only to explain a bounded reason
code. Selected provider, Google Tasks, and webhook runtime logs use bounded
fields and redacted exception classes; historical log artifacts are not
retroactively rewritten.
Keep iCloud as a rebuildable mirror and homelab backup sets as the
independent recovery source; neither should be silently substituted for the
canonical SQLite ledger.
