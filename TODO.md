# Penny TODO

Verified October 2, 2026, 19:38 UTC. This is Penny's active queue. Older dated
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

## Blocked on ordinary input

- [ ] **P01 — New post-Parakeet Penny recording.** No canonical capture newer
  than row 771 exists. After the next ordinary recording, verify actual model,
  canonical row, archive receipt and independent downstream receipts. Synthetic
  canaries and repair of old row 770 do not prove this. Do not manufacture input
  or release held row 769 to close this item.
- [ ] **P02 — Next eligible direct Maya v2 input.** Installed endpoint cutover
  is verified, but no ordinary direct delivery is pending. On its next eligible
  input, verify a durable v2 receipt and independent core readback. Voice Memo
  Drop handoff is a different route. Preserve all nine historical dead letters.

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
