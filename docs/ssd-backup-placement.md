# Mac backup placement — 2026-09-22

The owner approved moving backup staging to the always-connected SSD and keeping Homelab as the off-host backup destination. This changes installed placement, not the live capture ledger or audio-object root.

## Installed runtime

- Backup root: `/Volumes/2TB_SSD/AI/Penny/backup`.
- Verification receipt: `/Volumes/2TB_SSD/AI/Penny/backup/last_verification.json`.
- `com.penny.export`: existing six-hour schedule and backup command, now wrapped by `/Users/macmini/.local/libexec/compost/with-storage-volume.py` with `/opt/homebrew/bin/python3`.
- The wrapper requires `/Volumes/2TB_SSD` to be mounted with volume UUID `4FAC8D02-5B3B-4D77-A140-5E3C8332508A`. A missing or different disk exits 75 before the backup command runs. It does not create an internal fallback directory.
- `PENNY_BACKUP_ROOT` and `PENNY_BACKUP_VERIFICATION_RECEIPT` in the export and webhook LaunchAgents point at the SSD. Existing secret environment values were preserved.
- Compost's Sunday 04:50 local history job uses the same root and guard, retiring only older exact remote duplicates. The current set and shared objects remain on SSD; no remote history is deleted.

**Future deployment must preserve these two environment values and the volume wrapper.** The generic templates are not a receipt of this host-specific installation. Rendering an older template without carrying the placement forward can rebuild internal backup staging. Do not replace the root with a symlink: backup validation rejects symlink components.

A shell Doctor must receive the same backup environment as the webhook:

```sh
PENNY_BACKUP_ROOT=/Volumes/2TB_SSD/AI/Penny/backup \
PENNY_BACKUP_VERIFICATION_RECEIPT=/Volumes/2TB_SSD/AI/Penny/backup/last_verification.json \
venv/bin/python scripts/penny_doctor.py
```

## Evidence

All 329 original staging files matched the SSD copy. Before internal retirement, object/set files also matched Homelab by size and SHA-256; the old verification receipt was retained privately. Internal retirement removed 1,764,090,450 bytes. Live ledger/audio roots were unchanged.

A new set `20260922T063949Z` passed Penny's scratch restore and remote propagation/catalog verification. Export launchd run 2 exited 0. The initial SSD run failed before publishing a new receipt; a bounded propagation check and full retry succeeded. Its original cause was not exposed by the generic failure output. The old verified receipt survived the failure.

After webhook reload, `/health` is OK and the backup Doctor component reports OK with current catalog and receipt binding. Overall `/ready` remains 503 for separate capture/delivery/readiness conditions (Apple quarantine, Maya dead letters, Voice Memos terminal failure, launchd probe). This is not a claim that all Penny downstream effects are healthy.

Host-private receipts and original plist copies: `~/.local/state/compost/storage-migration-20260922/`. Keep them out of Git. The guard and retirement code are owned by [Compost](https://github.com/Khamel83/compost/tree/main/deploy/macos); the [full migration receipt](https://github.com/Khamel83/compost/blob/main/docs/plans/2026-09-22-ssd-unattended.md) records tests and limitations.

If the SSD is absent, leave the guard failure intact and restore the correct mounted disk. Do not create a folder at its missing mount point. If code must be rolled back, keep the SSD backup root and current receipt; do not silently point Doctor or backup creation back to the retired internal path.
