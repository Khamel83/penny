# Penny SSD storage — October 9, 2026

Owner directed immediate removal of Penny-owned data from the internal disk.
This was a local relocation and runtime configuration change, with no manual
transcription, replay, provider call or downstream send. Ordinary jobs resumed.

## Verified placement

- Canonical state: `/Volumes/2TB_SSD/AI/Penny/state`. All of the prior
  `~/.penny` moved, including SQLite, archive, model, backup history, logs,
  credentials and recovery/deployment receipts. `~/.penny` is a compatibility
  symlink, with no second internal copy.
- Actual runtime checkout and its environment: `/Volumes/2TB_SSD/penny-runtime`.
  Both `/Users/macmini/penny` and `/Volumes/2TB_SSD/GitHub/penny` resolve there.
  The latter had previously pointed back to the internal disk. Owner changes
  in `LLM-OVERVIEW.md` and untracked `CLAUDE.md` were preserved.
- Cache and scratch: `/Volumes/2TB_SSD/AI/Penny/cache`; old cache path is a
  compatibility link. All five jobs use SSD TMPDIR and Python/cache roots.
- Retry receipts: existing `/Volumes/2TB_SSD/penny-asr-runtime/asr-retries`.
- Scheduled backups retain `/Volumes/2TB_SSD/AI/Penny/backup`.
- Future rebuildable archive mirror writes use
  `/Volumes/2TB_SSD/AI/Penny/archive-mirror`. Historical iCloud trios remain
  preserved and evicted; this operation did not hydrate them or prove a new
  mirror publication. Apple-owned Voice Memos/iCloud source storage is unchanged.

## Verification

All writers were stopped while state and checkout were copied. `rsync -acni
--delete` reported no differences before each internal root was removed and
replaced with a compatibility link. The old empty cache was relocated into
SSD cache with existing test bytecode preserved. SQLite integrity is `ok`.

The five Penny labels validate the enrolled mount UUID before starting.
Launchd uses a neutral home working directory and `/dev/null` at spawn time:
external working directory/log paths caused EX_CONFIG on this Mac.
`scripts/storage_guard.py` checks the SSD, enters the SSD checkout, opens the
existing SSD system log, then executes the real entrypoint. This preserves logs
without bulk writes on the internal disk. Both correct-volume success (0) and
wrong-identity refusal (75) were verified through all five installed guards.

The watcher/webhook/tasks guard uses the original resolved runtime Python
interpreter as its launcher. Launching these through Homebrew Python caused
Voice Memos database access to fail after exec; restoring the original
interpreter identity restored source access without changing any privacy grant.
Final source readback: 334 Apple records, 335 ledger records, zero coverage gap,
fresh healthy watcher. Shared ASR subsequently resumed an ordinary Atlas request
with one worker; no completion or publication is inferred.

Four continuous services are running; scheduled export is registered and idle.
Shared ASR is idle, pinned Parakeet, zero workers. `/ready` reports archive,
backup, SQLite, services and transcription ready. HTTP 503 remains due to
`drop: uncertain_effect`, also present in the saved pre-migration result.
No new provider/downstream acceptance is claimed.

Internal free space rose from 18 GiB to 26 GiB during this operation, following
the earlier retry move. SSD free space is approximately 37 GiB. No additional
Time Machine snapshot deletion was needed. Private before-images, content
verification, migration scripts and readback live under
`/Volumes/2TB_SSD/AI/Penny/storage-migration-20261009/`.

Focused checks: 41 tests and 10 subtests passed (configuration, deployment guard
compatibility and mount refusal). Scoped runtime changes include the mirror
configuration, storage guard and deployment guard recognition. Existing runtime
component revision stamps remain unchanged; this is not a full source release.

Retry retention from issue #112 remains separate work; audio and receipts were
preserved on SSD. The pre-existing uncertain Drop effect remains unresolved.
Recheck `curl -s http://127.0.0.1:10311/health`,
`curl -s http://127.0.0.1:5678/ready`, `df -h /System/Volumes/Data
/Volumes/2TB_SSD`, and the resolved compatibility links.
