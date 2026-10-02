# Repair one capped Note

Normal Apple effects stop at five attempts. Restored Notes access does not reset
that cap. `scripts/repair_capped_note.py` provides an explicit operator action
for one existing failed Note whose error is `attempt_cap`.

Run without `--apply` first. The command reads the canonical payload, checks its
quality and suppression state, verifies the saved effect identity/hash, requires
one exact target folder, and reconciles the existing marker. It prints metadata
only. Private content stays in memory on this Mac.

For an authorized repair, add `--apply --expected-attempts <observed-count>
--receipt-dir <new-private-directory>`. The parent directory must already exist.
The new directory is mode 0700; intent and result files are mode 0600. An existing
receipt directory is refused. Preserve it after any uncertain result.

The SQLite claim compares the expected attempt count under its write lock,
retains the original count and increments it once. It refuses quarantined,
changed, already-claimed or mismatched effects. An uncertain effect requires
`--reconcile-only`; this mode can verify an existing Note but cannot create one. The regular watcher
never requests this override. Reusing the old expected count cannot authorize
another creation. A successful effect remains idempotent.

The existing Notes adapter creates only after exact marker reconciliation.
The operator path verifies the provider folder, marker and full normalized
payload before committing success. An ambiguous creation/readback stays
uncertain and must be reconciled before another operator decision. No capture
retranscription, downstream outbox reset, synthetic-quarantine repair or retry-cap
reset is part of this command. Once the exact Note succeeds, only its matching
currently capped route can rejoin the normal routing worker; an already-routed
capture is never downgraded.

October 2 live attempt: the unique Note was created on attempt six, but Notes
rejected its advertised `container` getter with error -1728. The ledger remained
uncertain. Folder-membership lookup by exact folder and Note IDs independently
verified the marker and full normalized payload. Use this readback to reconcile
the existing item; do not rerun creation.

```bash
venv/bin/python scripts/repair_capped_note.py <effect-key> --reconcile-only
venv/bin/python scripts/repair_capped_note.py <effect-key> --reconcile-only \
  --apply --expected-attempts <observed-count> --receipt-dir <new-private-directory>
```

Reconciliation still increments the attempt history. A missing marker or failed
readback remains uncertain and never creates a replacement Note. A changed
count or quarantine refuses the claim. Synthetic fixtures and held captures
remain untouched.

## Completed live repair — October 2, 2026

PR94–96 are merged and correction source `6ccf2286` is installed in Penny's
three caller services. The sole real capped Note for canonical row 770 was
created once on attempt six, then reconciled with complete target/marker/text
readback on attempt seven. The ordinary watcher routed row 770 and Voice Memo
443 at 19:36:51 UTC. Installed `/ready` returned HTTP 200/degraded; only preserved
historical exceptions remain. Synthetic quarantine 493 and held 769 did not
change. Existing archive publication and accepted Drop delivery metadata stayed
identical; no downstream outbox was reset or resent.

Private intent, uncertain, verified, runtime and delivery receipts remain in
`~/.penny/recovery/20261002-note-770-repair/` and
`~/.penny/recovery/20261002-note-770-reconciliation/`.
The Notes skill reference uses the verified membership readback. Final tests:
765 passed, 2 skipped, 60 subtests; trust 497 tests, 2 skipped, PASS; both PR96
hosted Python checks passed. New natural ASR/capture acceptance is separate.
