# Natural Penny Parakeet acceptance — October 4, 2026

Verified October 4 by read-only inspection of Penny's ledger, local audio,
Drop's archived bytes, Slack's receipt ledger and Maya's live source-event
receipt table. No recognition, capture insertion or delivery replay was run.

| Penny row | Captured (UTC) | Audio | Recorded transcription elapsed |
| --- | --- | --- | --- |
| 772 | October 2, 21:43 | 117.56 seconds | 9.847 seconds |
| 773 | October 3, 22:16 | 42.27 seconds | 6.030 seconds |
| 774 | October 3, 22:27 | 51.24 seconds | 6.988 seconds |

All three report pinned `mlx-parakeet`, quality passed and routed, with linked
Voice Memo rows 445–447 also routed. Their Apple effects succeeded on the first
attempt (two Notes, two Reminders). These are real ordinary captures, not canaries.
Recorded short-note times are not a long-podcast throughput benchmark.

Local archived audio hashes match the ledger; each archive has a published
receipt. Current mirror validation is marked deferred, so this check does not
claim a fresh full iCloud mirror readback. All three Drop archives match Penny's
frozen payload hash and size. Slack's independent ledger records sent with
provider IDs and matching payload hashes; this check did not reread Slack message
content. Maya's live database has one matching version-1 source-event receipt
per Drop item, with matching identity/size, `ok=true`, `replayable=true`,
`capture_policy=store_only`, `classification=information`, `action_route=none`.
Receipt presence establishes stored intake, not execution of the notes' contents.

Private receipt: `~/.penny/recovery/20261004-natural-parakeet/receipts.json`.

## Why a direct Maya capture is not this workflow's gate

Only the audio watcher requests direct Maya eligibility for new captures, using
source `iCloud`. The persisted Drop ownership policy owns future eligible iCloud
rows after cutoff 755. `insert_transcript()` clears direct Maya eligibility and
queues Drop for those rows. The three captures are therefore correctly direct
Maya-ineligible while already received by Maya through Drop. The older direct
v2 route has no current pending delivery; its nine dead letters remain unchanged.

P01 is complete. P02 is retired as a blocker for ordinary Penny voice notes;
a new direct-v2 acceptance check is needed only if that separate route is
explicitly exercised or restored. No fallback or routing policy changed.
Atlas publication is a separate acceptance boundary and is not claimed by these
Penny receipts. Long-term stability continues to be observed during normal use.
