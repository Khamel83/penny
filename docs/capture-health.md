# Current capture health and retained historical failures

Approved 2026-09-22 after a real 10.17-second memo passed automatic capture,
local transcription, Drop acceptance, Slack read-back and Maya store-only receipt.
Penny ID 762 / source 436 reached Slack in about 104 seconds, without manual replay.

Apple's `voicememod` can exit while idle: the observed launchd exit reason was
`JETSAM_REASON_MEMORY_IDLE_EXIT`, followed by normal running state. Its presence
is diagnostic, not a requirement for every health snapshot. Fresh readable source
evidence, responsive Voice Memos, coverage, launchd and health age remain required.
This does not prove that iCloud has synced an unseen recording from another device.

The fixed `voice_memos.historical_failure_before` setting acknowledges failures
already terminal before `2026-09-22T16:45:38Z`. The live preflight found exactly
two: source 112 (missing audio) and 135 (transcription failure). Their rows, states,
errors and timestamps are unchanged. Total, historical and current terminal
failure counts remain visible; historical failures produce degraded readiness.

Classification uses failure time, never recording age or a moving age window.
A later failure remains current even for an old recording. Missing or invalid
failure timestamps remain current. Invalid, timezone-free or future cutoffs fail
closed. The default setting is empty: no history is acknowledged unless configured.
Do not advance the cutoff merely to make health green; that requires explicit
review of the affected failures. This setting cannot recover missing audio or
upgrade transcription quality.

New terminal failures, unreadable source/ledger, stale evidence, missing required
service evidence and source coverage gaps still fail readiness. Pending delivery
and historical Apple/Maya exceptions retain their independent component states.
No new Slack notification, resend, audio transfer or data migration is introduced.

Verification: regression tests cover idle-daemon reporting, historical/current
failure separation, unclassified timestamps and invalid configuration. Run the
whole suite, deploy pushed main with `scripts/deploy_penny.py --apply`, then check
the installed `/ready` response and each loaded source revision. The private real
memo receipt is `~/.penny/real-memo-762-verification-2026-09-22.json`.

Source verification: 678 tests and 53 subtests passed, two skipped. Independent
review identified SQLite's permissive timestamp parsing; the corrected regression
keeps numeric, time-only, invalid-calendar, NULL and equal-cutoff values current.
Strict parsing preserves complete legacy UTC timestamps. Review cleared the fix.
