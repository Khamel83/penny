## Historical health acknowledgement — installed October 19, 2026 UTC

Private `~/.penny/health-history.json` is on the existing SSD state path,
mode0600, with exact-record fingerprints for the owner-retired exceptions.
PR132 merged8606b497 Doctor/helper/operator bytes are installed; only webhook
was reloaded/stamped. Current readiness/OCI are ready and Homelab API healthy.
Kuma22/23/24all have persisted ordinary UP heartbeats at06:25:46/47UTC.
No port, provider, credential, Kuma threshold or macOS permission changed.
[Owner decision, deployment receipt and rollback](docs/health-audit-20261018.md).

## ASR retry component — installed October 16, 2026 09:52 UTC

Merged PR122/85900798 retry_receipt.py is installed with SHA256
`c568bd45bde9ae5d3d801740471ed7503fd72566a8bbf32aa0fafa289ea8dd2b`.
Only idle `com.penny.shared-whisper` was reloaded, now PID58688/source85900798.
Callers, keeper and other plists stay unchanged; webhook remains c9b0368a.
Primary HEAD65758e82 is preserved with intentional Doctor/retry-helper deltas.
ASR health200/idle declares pinned Parakeet with no resident worker; a future
ordinary retry remains unobserved. Original #112 test and installation acceptance
is complete; normal-use observation does not keep that issue held.

Actual retry root remains `/Volumes/2TB_SSD/penny-asr-runtime/asr-retries` on
the enrolled mounted SSD. No migration was necessary. The helper now defaults
there and rejects missing mounts/nonphysical overrides before receipt writes.
Terminal receipt rename is fsynced before copied audio release;14day expiry
preserves pending/unknown/malformed/symlink-containing records. Before activation,
449files/10,059,792,302bytes were hash-verified into a durable write-protected
local snapshot; original backup and source/plist before-images remain under
`/Volumes/2TB_SSD/AI/Penny/deployments/20261016-retry112/`.
[Acceptance, limits and rollback](HANDOFF.md).

## Doctor component — installed October 16, 2026 UTC

Only Doctor and `com.penny.webhook` were updated from merged PR115/c9b0368a.
Doctor SHA256 is
`3210731d6fa985342f4c3a29c5baa531c3eee22a8816dc72790cde00e4e10a71`;
webhook PID30252 loads the c9b0368a source stamp. Primary Git HEAD65758e82 and
its keeper branch are preserved; doctor.py is the intentional runtime delta.
ASR PID2025/source c341598c and all peer plists remain unchanged. The existing
port5678 `/ready` succeeds locally and from OCI through its existing Mac SSH
route, with zero unready components and explicit skipped_count=1. No new route,
credential, grant or observer configuration was introduced. The OCI scheduled
Doctor observer has a narrower environment; it remains separate evidence.

A first immediate probe raced startup and restored the prior bytes; independent
readback verified service before a separate bounded-startup attempt accepted.
Fresh backup verification, both attempts and scoped rollback before-images are
on SSD in `/Volumes/2TB_SSD/AI/Penny/deployments/20261016-doctor115{,-warmup}/`.
[Current receipt and validation](HANDOFF.md).

## Shared ASR keeper — installed October 16, 2026

`com.penny.shared-whisper-keeper` runs every 120 seconds with `RunAtLoad` and
`KeepAlive=false`, using macOS system tools from `/`. Its only volatile state
is an empty strike directory below the validated 0700 Darwin per-user temporary
root, so late SSD mounts do not prevent probing. After two failed local health
checks it requests recovery of the existing ASR label. Healthy busy responses
clear the strike; failed recovery exits nonzero and logs the failure.

Merged source `6330b398` is installed with its exact source stamp. Only the
keeper was reloaded; the ASR daemon PID stayed unchanged. Installed hash,
initial and first natural exit-0 runs and independent Homelab health are verified, with an SSD
before-image/receipt. The shared endpoint is
`http://omars-mac-mini.deer-panga.ts.net:10311/health` (current IP100.89.194.46).
Infra owns Kuma monitor `atlas.mac-asr`; its monitor receipt is separate from
keeper recovery. [Evidence and rollback](docs/shared-whisper-keeper-20261016.md).

## Current storage placement — October 9, 2026

Actual runtime root is `/Volumes/2TB_SSD/penny-runtime`; canonical state/ledger
is `/Volumes/2TB_SSD/AI/Penny/state/transcripts.db`. The historical home paths
are compatibility symlinks. All Penny data, logs, caches and scratch are SSD
backed; future mirror writes use `/Volumes/2TB_SSD/AI/Penny/archive-mirror`.
Scheduled backup and pinned Parakeet paths retain their existing SSD placement.

All five labels execute the scoped `scripts/storage_guard.py`, validating
`COMPOST_STORAGE_VOLUME` and enrolled `COMPOST_STORAGE_UUID`, then changing
to `PENNY_RUNTIME_ROOT` and opening SSD `PENNY_RUNTIME_LOG`. Launchd itself
starts from home with `/dev/null` diagnostic descriptors to avoid the observed
external-path EX_CONFIG; logs are opened by the guarded Python caller on SSD.
Watcher/webhook/tasks use the original resolved runtime Python as guard launcher
to preserve the established Mac caller identity. No port, token or privacy grant changed. The compost maintenance job retains
its existing guard. [Exact evidence](docs/ssd-storage-20261009.md).
Older placement and revision entries below are historical.

## Current installed state — October 2, 2026, 19:38 UTC

Runtime root: `/Users/macmini/penny`; canonical ledger: `~/.penny/transcripts.db`.
Watcher, webhook and tasks carry `6ccf2286a2c6af1919e43b4eaba72465f8eb614b`.
Only `transcript_log.py`, `apple_effects.py` and `scripts/repair_capped_note.py`
were replaced with reviewed merged bytes. Shared ASR and export remain at
`c341598c484734ace251944f3f7ca56ab0bb0009`; root Git HEAD and owner edits are
preserved. This scoped component update has backups, ledger snapshot, exact
file hashes, protected-file hashes and verified loaded revisions under
`~/.penny/deployments/20261002T1936Z-note-reconciliation/`. Prior scoped receipt:
`~/.penny/deployments/20261002T1926Z-note-repair/`.

Port 10311 retains the shared Parakeet owner and pinned SSD environment/model;
Whisper fallback loads serially and the idle worker unloads. Apple pilot is off.
Port 5678 `/ready` reports the installed caller's configuration and revision:
HTTP 200/degraded with historical exceptions only. No port, credential, macOS
grant or downstream registration changed in the Note repair.

The reusable Notes skill reference is installed in both discoverable skill roots
(`~/.codex/skills` and `~/.agents/skills`), with per-file hashes and before-images
under `~/.penny/recovery/20261002-notes-skill-readback/`. Other skill files are
preserved. This is operator guidance, not a new daemon or write backend.

OCI's `penny-health.timer` is active. Its natural run at 09:00 UTC recorded the
actual Apple provider failure. The supervised post-repair run at 19:37:34 UTC
recorded degraded with Apple quarantine, historical Maya/Voice Memo exceptions
and no unready component. Receipt:
`/home/ubuntu/.local/state/penny-health/receipts/20261002T193734.217878+0000-4250399a4cc346fe8fbf389601e2ca1e.json`.
The observer invokes a bounded SSH Doctor with backup/offline settings; it does
not inherit all launchd configuration, so its source is unknown and Drop appears
disabled. It proves observed degradation, not loaded source or Drop readiness;
those are verified through installed `/ready`. No observer source/config changed.
Hosted GitHub tests replace the retired unmatched legacy workflows.

## Historical placement and cutover records

The dated records below explain earlier stages. Current component revisions
and installed state are defined above.


## Direct Maya endpoint — checked October 2, 2026 02:02 UTC

Installed `com.penny.watcher`, `com.penny.webhook` and `com.penny.tasks` have
`MAYA_TRANSCRIPT_URL=https://maya.khamel.com/ingest/transcript`, with loaded
configuration and running jobs verified. The existing ingest token matches the
Homelab core and is retained privately. Runtime source remains `ca6322b697a4bcea8de52849d975d7543a994970`.
The shared transcription process and export job were not reloaded. Private
before-images, backup and receipts: `~/.local/state/maya-penny-core-route-20261002/`.
The next ordinary direct v2 delivery remains a separate acceptance gate. Do not
replay the nine historical dead letters. Voice Memo Drop routing stays active.

The normal runtime checkout is `/Users/macmini/penny` on the M4 Mac mini.
Existing services and deployment contract are in `docs/macmini-deployment.md`.
Canonical SQLite remains `~/.penny/transcripts.db`. The authenticated shared
MLX service on port 10311 remains the production ASR owner; Atlas is an HTTP
caller. Tiny Wyoming on 10300/10301 is separate.

The approved Apple shadow pilot adds no listening port. Its service label is
`com.penny.apple-pilot`, using the repository Python environment and working
directory. A revision-named native executable lives at
`~/.penny/bin/apple-transcribe-<source-sha>` with a private source/binary-hash
receipt. Swift source is `native/apple_transcribe.swift`; model assets are
Apple-managed, checked through AssetInventory using that exact binary.

Pilot-owned SQLite, immutable audio copies, results and `health.json` live at
`/Volumes/2TB_SSD/penny-apple-pilot`. The deployment-stamped
`PENNY_APPLE_PILOT_VOLUME_UUID` binds that placement to the actual SSD.
`PENNY_APPLE_PILOT_DIR` opts the existing shared service into shadow capture.
Both values live in installed plists; the shared ASR bearer credential is
preserved and never copied into the pilot worker. The pilot needs no provider
credential and does not send audio or text downstream.

Deploy with `venv/bin/python scripts/deploy_apple_pilot.py --apply`, after
review/merge to current pushed main. Private deployment/backups are under
`~/.penny/deployments/<UTC>-apple-pilot`. Operational evidence and rollback
instructions are in `docs/apple-speech-pilot.md` and the current handoff.
Source configuration here is not proof of deployment; verify launchd revision
and a fresh pilot completion receipt separately.

Verified October 1: corrected activation at `ec0f51a4b86c4649ab063a83377891c4ef513686`; all six installed labels report that source. Pilot health is fresh, Apple assets are installed, and natural Atlas input produced durable shadow results. Private activation receipt: `~/.penny/deployments/20261001T200031Z-apple-pilot/receipt.json`. No new port or downstream consumer registration was introduced.

Owner-directed pause later October 1: Apple sidecar unloaded and its plist retained with `.plist.paused` suffix. Shared pilot environment removed and five-label normal deployment reverified; health reports `apple_pilot_enabled=false`. Keep private queue/results. No automatic resume is authorized. See live receipt and issue #70.

## Shared Parakeet runtime staged — October 1, 2026

Owner approved replacement of the shared primary with selective local Whisper
fallback. Staged Python 3.12 environment: `/Volumes/2TB_SSD/penny-asr-runtime/venv`.
Pinned MLX/audio/runtime dependencies: `requirements-asr.lock`. Approved model
bytes: `/Volumes/2TB_SSD/penny-asr-runtime/models/parakeet-tdt-0.6b-v3/ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15`.
No root-venv or Whisper-weight migration. `PENNY_SHARED_ASR_BACKEND=parakeet`,
`PENNY_PARAKEET_PYTHON` and `PENNY_PARAKEET_MODEL_PATH` will select the staged
child at cutover. Existing port 10311 and launchd label are retained; both
engines share one supervisor slot and never load concurrently. Retry audio and
both model results remain owner-only under `~/.penny/asr-retries`, separate
from canonical ledger/archive/delivery. Source/staging is not deployment proof.
See `docs/shared-parakeet.md`. The earlier staging phase retained Whisper;
the verified activation below records the subsequent Parakeet service cutover.

Verified October 1 shared Parakeet activation: five installed Penny agents select `PENNY_SHARED_ASR_BACKEND=parakeet`; the shared service uses the pinned SSD Python/model paths above. Port 10311 and bearer/header contract are unchanged. Whisper remains available for bounded serial retries; Apple pilot is disabled. Runtime revision `f4909d33d0a15db660c9eec35a02318aab297ca2`; see live activation receipts in HANDOFF.md.
<!-- janitor:begin:catalog -->
## Repository identity
Infrastructure authority: `Khamel83/infra:config/project-catalog.yml`.
This INFRA.md is this project's projection of that authority. The owning
project declares its deploy, config, data and health evidence here;
shared machine/tool/environment policy stays in infra's registries.
- project_id: penny
- name: Penny
- state: observing
- lifecycle: active
- classification: unclassified
- repository: https://github.com/Khamel83/penny
<!-- janitor:end:catalog -->
