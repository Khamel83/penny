# Voice Memos Sync Health Design

## Incident

On 2026-08-12, Voice Memos.app was alive and AppleEvent-responsive while the
local CloudRecordings database remained at recording 408. The user foregrounded
Voice Memos at 08:20 local time; `voicememod` started, recordings 409-411
materialized, and Penny discovered them 12 seconds later. Penny then routed all
three exactly once.

The failure was at the Apple source boundary. Penny treated an app PID, an
AppleEvent response, and a readable but stale database as proof that sync was
healthy. Its recurring `open -g -a VoiceMemos` call did not start the missing
`voicememod` service.

## Requirements

- Penny must not report the Voice Memos source healthy when the per-user
  `com.apple.voicememod` service is absent.
- Penny must attempt a bounded, non-foreground recovery of that service before
  polling the source database.
- Recovery must not write to Apple's private database, expose recording names or
  transcript content, or kill a responsive service.
- Existing app-unresponsive recovery remains separate and unchanged.
- Doctor `/ready` must carry the same daemon evidence as the watcher health
  receipt.
- The repair must be regression-tested and must preserve the live checkout until
  verification and review are complete.

## Design

Add a bounded `_voicememos_sync_daemon_running()` probe using `pgrep -x
voicememod`. During `_ensure_voicememos_running()`, if the service is absent,
invoke `launchctl kickstart gui/<uid>/com.apple.voicememod` once for that poll,
then retain the existing background `open -g -a VoiceMemos` refresh. Do not use
`kickstart -k`, do not foreground Voice Memos, and do not mutate the Apple
database.

Add `voicememod_running:0|1` to the watcher health receipt and require it for
`watcher_ok`. Doctor reads the exact flag for both `voice_memos` and `services`;
an absent daemon maps to `source_unavailable` rather than a false ready state.

The daemon flag is a necessary health signal, not a claim that CloudKit is
complete. Existing source watermark, waiting-file, terminal-failure, database,
and delivery receipts remain authoritative. A future supported upstream receipt
may deepen completeness proof, but this fix addresses the observed missing
service without inventing a private CloudKit API.

## Verification

- RED then GREEN unit tests for missing-daemon kickstart, already-running
  no-kickstart behavior, health receipt, and Doctor readiness.
- Focused watcher/Doctor tests, full Penny pytest, `trust_check.py`, Ruff, and
  `git diff --check`.
- Independent code review at the frozen commit.
- Post-deploy proof checks the loaded source revision, daemon flag, source
  watermark, and absence of duplicate downstream receipts. The next real Voice
  Memo remains the end-to-end CloudKit proof; no synthetic personal recording is
  created.
