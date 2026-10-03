# Penny current context

Verified October 2, 2026, 19:38 UTC. Penny is the only repository in this task.
The owner authorized completion of Penny repairs and self-review/normal merge
when hosted review is delayed. Protected dirty runtime files remain intact.

## Decisions

Use one shared pinned Parakeet v3 primary, bounded Whisper second opinions and
serial model loading/unloading. Apple pilot remains disabled. Structural quality
checks can hold malformed/repetitive output; they do not reliably detect fluent
omissions or establish ground truth. Do not replay held recordings or old
external deliveries. [ASR contract](docs/shared-parakeet.md).

## Verified state

- Source: PR94–96 merged. Final repair merge is
  `6ccf2286a2c6af1919e43b4eaba72465f8eb614b`. Local suite: 765 passed, 2 skipped,
  60 subtests. Trust: 497 tests, 2 skipped, PASS. PR96 hosted Python checks passed.
- Runtime: exact reviewed Apple modules/operator script installed through a
  scoped update; watcher, webhook and tasks carry `6ccf2286`. Shared ASR and
  export retain `c341598c`. Root Git HEAD and owner edits were preserved; this
  is a component deployment, not a whole-checkout revision claim. [INFRA](INFRA.md).
- Provider: one Note exists for canonical row 770. Notes' advertised `container`
  getter failed after creation; folder-membership and full normalized text
  readback succeeded. Explicit reconciliation stored the existing provider ID
  at attempt seven. The failed/uncertain history remains in private receipts.
- Ordinary processing: watcher routed row 770 and Voice Memo 443 at 19:36:51 UTC.
  Their existing archive and accepted Drop receipt are unchanged; no direct
  Slack/Maya delivery was added. Downstream consumers were not replayed or
  independently reverified by this Note repair.
- Readiness: installed `/ready` returns HTTP 200/degraded, no unready component.
  Shared pinned Parakeet is idle with zero resident workers; model/offline/memory
  checks pass. Capture coverage gap and current terminal failures are zero.
  Archive, backup and delivery queues are ready.
- Historical exceptions remain visible: one synthetic Apple quarantine,
  nine Maya dead letters, two old missing-audio failures and one unavailable
  memo. Held row 769 is unchanged and routing-suppressed.
- Reusable Apple skills are installed; Notes/Reminders access was verified.
  The Notes reference now records exact-folder membership readback and preserves
  uncertainty after a failed post-create probe.

The condensed handoff retains explicit local-routing, independent Slack and
independent Maya v2 receipt boundaries. The existing documentation contract
caught their omitted wording in PR97; restoring it changes guidance only,
without modifying deployed code or provider state.

## Remaining evidence

P01/P02 in [TODO.md](TODO.md) require a new ordinary capture or eligible direct
Maya input. The newest canonical ID remains 771; none has arrived since the
Parakeet cutover. Old queued-Note repair is real provider/routing evidence, not
new ASR evidence. Long-term stability is observation over time, not another
bulk recognition test.

Previous dated checkpoints remain in the
[historical context](https://github.com/Khamel83/penny/blob/6ccf2286a2c6af1919e43b4eaba72465f8eb614b/CONTEXT.md).
<!-- janitor:begin:recent -->
- **2026-10-03 — Documentation evidence boundaries closed out.** Source `f80b2516bcc436a53b76871d10b47fa951831c74` merged PR98, containing commit `90ee99301e46cde81b866823415d387d86e1977f` to preserve explicit independent delivery evidence in the Penny handoff. This is documentation guidance only; it does not establish new deployed code, provider state, or downstream receipt evidence.
- **2026-10-02 — Penny repair state consolidated.** PR97 merged at `1179fe31a3b7d23ca015d903a7f7184c91881d94`, with closeout and consolidation at `2a9454148e7ea43e685bef0a13909af52195b84b`. Current documented state remains: final repair merge `6ccf2286a2c6af1919e43b4eaba72465f8eb614b`; local suite 765 passed, 2 skipped, 60 subtests; trust suite 497 tests, 2 skipped, PASS; PR96 hosted checks passed. The reviewed Apple components are installed through a scoped update while protected dirty root files and their existing revision are preserved.
- **2026-10-02 — Provider and routing evidence reconciled.** Canonical row 770 was repaired without recreating its Note; normalized content and exact-folder membership were read back, and the existing provider ID was reconciled at attempt seven. Notes' advertised `container` getter remained unreliable after creation, so that probe's failure remains uncertain. Ordinary watcher routing covered row 770 and Voice Memo 443 at 19:36:51 UTC; archive and accepted Drop receipts remained unchanged, and no direct Slack or Maya delivery was added.
- **2026-10-02 — Operational readiness remains degraded, not unready.** `/ready` returns HTTP 200 with no unready component. The pinned shared Parakeet primary is idle with zero resident workers; model, offline and memory checks pass. Capture coverage gaps and current terminal failures are zero, while historical quarantine, dead-letter and unavailable-input exceptions remain visible.
- **Open evidence gates.** P01 still requires an ordinary post-Parakeet capture newer than canonical row 771. P02 still requires the next eligible direct Maya v2 input. Neither repaired row 770 nor held row 769 constitutes that evidence.
<!-- janitor:end:recent -->
