# Penny TODO

## Immediate SSD relocation — October 9

- [x] Remove Penny-owned state, archive, models, logs, cache, scratch and actual
  runtime checkout/environment from the internal disk; verify copied bytes,
  SQLite integrity, restored services and fresh Voice Memos source access. Internal free space is 26 GiB.
  [Evidence](docs/ssd-storage-20261009.md),
  [PR113](https://github.com/Khamel83/penny/pull/113).
- [ ] Add bounded retry retention on SSD while preserving pending review:
  https://github.com/Khamel83/penny/issues/112. Relocation is complete; retention
  is not implemented by this storage operation.
- [x] Retire note 779's Drop delivery at the owner's request; keep audio,
  transcript, frozen payload and original failure receipt locally.
  `/ready` HTTP 200, Drop uncertain=0 and skipped=1.
  [Evidence](docs/drop-owner-skip-779-20261010.md),
  [Drop158](https://github.com/Khamel83/drop/issues/158).

Updated October 4, 2026; natural-capture evidence below supersedes the October 2 input gates. This is Penny's active queue. Older dated
checklists are superseded; their evidence remains in the
[previous TODO](https://github.com/Khamel83/penny/blob/6ccf2286a2c6af1919e43b4eaba72465f8eb614b/TODO.md) and linked operational documents.

## Completed

- [x] Select, integrate and deploy one shared Parakeet primary with serial,
  bounded Whisper fallback and idle unloading. Preserve actual backend identity,
  timing validation, durable quality holds and protected recordings. Reviewed
  Penny/consumer activation and rollback evidence:
  [shared ASR hardening](docs/asr-hardening-20261002.md),
  [runtime contract](docs/shared-parakeet.md). Apple background pilot stays off.
- [x] Repair capped routing selection and the real queued Note. [PR94](https://github.com/Khamel83/penny/pull/94),
  [PR95](https://github.com/Khamel83/penny/pull/95) and
  [PR96](https://github.com/Khamel83/penny/pull/96) are merged; correction source
  `6ccf2286a2c6af1919e43b4eaba72465f8eb614b` is installed in the three callers.
  Exactly one Note was created; full content/target readback reconciled attempt
  seven. The ordinary watcher routed canonical row 770 and Voice Memo 443 at
  19:36:51 UTC. No transcript or delivery replay. [Procedure/evidence](docs/capped-note-repair.md).
- [x] Pass final local source checks: 765 tests passed, 2 skipped, 60 subtests;
  trust check 497 tests, 2 skipped, PASS. Both PR96 hosted Python 3.11/3.12 checks
  passed. This supersedes the old missing-format-extra full-suite failure.
- [x] Verify installed `/ready` returns HTTP 200 with no unready component;
  capture, archive, backup, shared ASR and delivery queues are ready. Historical
  quarantine, nine Maya dead letters, two old missing-audio failures and one
  unavailable memo remain visible as degraded. [Current state](CONTEXT.md).
- [x] Install reusable Apple app skills and verify Notes/Reminders access.
  Preserve the corrected exact-folder Notes readback in the skill reference.
  [PR91](https://github.com/Khamel83/penny/pull/91),
  [Reminders recovery](docs/reminders-recovery-20261002.md).
- [x] Retire unmatched legacy GitHub review/health runners (commits `3068fe0`,
  `35a4c83`); hosted-only workflow guard is enforced by the trust check. OCI's
  natural 09:00 UTC Penny observer recorded the actual Apple failure; its
  supervised 19:37 UTC check recorded recovery to degraded. Timer remains active.
  Observer environment limits are explicit in [INFRA.md](INFRA.md).
- [x] Preserve explicit local-routing, independent Slack and independent Maya v2
  evidence boundaries in the condensed handoff; keep the documentation contract
  enforced by existing tests.
- [x] Consolidate duplicate and obsolete TODO/CONTEXT/HANDOFF checkpoints;
  keep current evidence and genuine input gates separate from historical plans.

## Natural-capture acceptance completed October 4

- [x] **P01 — New post-Parakeet Penny recording.** Ordinary captures 772–774
  from October 2–3 all used pinned Parakeet, passed quality and routed. Local
  audio hashes, archive publication receipts, matching Drop archive hashes,
  independent Slack sent receipts and Maya store-only source-event receipts
  are verified. [Evidence and limits](docs/natural-parakeet-acceptance-20261004.md).
- ~~**P02 — Wait for a new direct Maya v2 input.**~~ This is not the active
  voice-note route: new iCloud captures are Drop-owned and intentionally direct
  Maya-ineligible. All three already have Maya receipts through Drop. Retain
  direct-v2 acceptance only if that separate path is explicitly exercised;
  preserve its nine historical dead letters.

No input-gated implementation or acceptance task remains for the normal Penny
voice-note path. Observe long-term stability during ordinary use; no new bulk
benchmark or manufactured capture is required.

## Deliberately retired or outside this queue

- ~~Apple primary adoption / further bulk model benchmarks~~ — owner chose
  Parakeet with selective Whisper; [issue70](https://github.com/Khamel83/penny/issues/70)
  is closed as not planned. Existing research and paused pilot artifacts remain.
- ~~Protected Apple Events service kickstart~~ — invalid under enabled SIP;
  working Notes/Reminders access and receipt reconciliation replaced it. Keep
  SIP and privacy grants intact.
- ~~Repeat production rollback solely for evidence~~ — reviewed rollback artifacts and
  bounded switch-back canaries are retained. A disruptive full rollback rehearsal
  remains unexercised and is deferred to a real maintenance need.
- Atlas publication/backlog and held podcast excerpts belong to Atlas; their
  older checkpoints do not reopen a Penny implementation task.
- Another project's first Apple-skill operation needs that project's actual
  request/caller/target. No unrelated project was used to manufacture acceptance.
- Finder window timeout and protected simulator cleanup are outside Penny's
  capture/Notes/Reminders path. No Calendar/Mail/Messages adapter is claimed.
- Held row 769 and synthetic quarantine row 493 are intentional preserved states,
  not requests to retranscribe, replay or erase evidence.
<!-- janitor:begin:todo -->
## Natural-capture acceptance completed October 4

- [x] **P01 — New post-Parakeet Penny recording.** Ordinary captures 772–774
  from October 2–3 all used pinned Parakeet, passed quality and routed. Local
  audio hashes, archive publication receipts, matching Drop archive hashes,
  independent Slack sent receipts and Maya store-only source-event receipts
  are verified. [Evidence and limits](docs/natural-parakeet-acceptance-20261004.md).
- ~~**P02 — Wait for a new direct Maya v2 input.**~~ This is not the active
  voice-note route: new iCloud captures are Drop-owned and intentionally direct
  Maya-ineligible. All three already have Maya receipts through Drop. Retain
  direct-v2 acceptance only if that separate path is explicitly exercised;
  preserve its nine historical dead letters.

No input-gated implementation or acceptance task remains for the normal Penny
voice-note path. Observe long-term stability during ordinary use; no new bulk
benchmark or manufactured capture is required.
<!-- janitor:end:todo -->
