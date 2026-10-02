# Penny host and Apple pilot placement

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
