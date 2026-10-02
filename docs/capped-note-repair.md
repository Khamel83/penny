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
uncertain, changed, already-claimed or mismatched effects. The regular watcher
never requests this override. Reusing the old expected count cannot authorize
another creation. A successful effect remains idempotent.

The existing Notes adapter creates only after exact marker reconciliation.
The operator path verifies the provider folder, marker and full normalized
payload before committing success. An ambiguous creation/readback stays
uncertain and must be reconciled before another operator decision. No capture
retranscription, downstream outbox reset, synthetic-quarantine repair or retry-cap
reset is part of this command.

October 2 preflight: actual failed effect for canonical row 770 has five
attempts, matching payload identity and zero marker matches in its unique Penny
folder. Notes and Reminders reachability pass. Source tests cover one-use claims,
stale-count/quarantine/uncertainty refusal and post-create timeout. Live repair
and final provider/ledger acceptance remain pending until a private result exists.
