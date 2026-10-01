# Penny host and Apple pilot placement

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
