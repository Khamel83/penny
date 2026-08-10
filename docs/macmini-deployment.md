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
| `com.penny.watcher` | Voice Memos compatibility ingest, staging, offline MLX, local routing, and outboxes | continuous/polling |
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
5. Load dedicated credentials through the runtime secret mechanism; never put
   values in tracked config, templates, logs, or shell history.
6. Confirm the tracked/runtime webhook templates converge to loopback or an
   explicitly protected non-loopback policy; Doctor fails an unprotected bind.
   The callback credential is currently reused for Hermes notifications;
   `PENNY_HERMES_WEBHOOK_SECRET` is the target future dedicated name, not a
   live Phase A setting.
7. Create a verified backup set before changing code/config.

## Controlled deployment

Run local checks first:

```bash
venv/bin/python scripts/trust_check.py
venv/bin/python -m pytest -q
```

Copy the reviewed checkout and wrapper/template inputs using the approved
deployment channel. Preserve runtime state, databases, archive objects,
outboxes, receipts, and prior backup sets. Update the installed wrappers/plists
only after checking their rendered environment for names (never values): model
path/revision, offline mode, dedicated ingress/callback credentials, Slack, and
Maya v2.

Restart only the Penny labels that changed, using the normal launchd operator
procedure. Do not restart Apple providers, alter durable state, or replay outboxes as a
deployment step. Verify the installed labels and wrapper revision, then run the
Doctor and both HTTP endpoints locally.

## Acceptance evidence

Deployment evidence must include:

- pushed SHA equals the runtime checkout SHA;
- wrappers point to the intended checkout and virtualenv;
- launchd labels are registered and approved (registration is not a health
  result by itself);
- `penny doctor` exit/status and component reason codes;
- `/health` liveness and `/ready` readiness responses;
- latest backup verification receipt bound to its catalog and database metadata;
- missing/wrong-token ingress requests return `401`, oversized requests return
  `413`, and hermetic valid-token tests pass; no live canary is implied.

Do not call a deployment healthy based on process presence, `watcher.system.log`, a template,
or a provider request. Physical Watch, Apple effect, Slack, and Maya canaries
require their own explicit approval and downstream receipts.

## Rollback

If a gate fails, stop the changed Penny labels, restore the prior reviewed code
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
code. Ordinary logs still have a provider-URL/exception redaction follow-up.
Keep iCloud as a rebuildable mirror and homelab backup sets as the
independent recovery source; neither should be silently substituted for the
canonical SQLite ledger.
