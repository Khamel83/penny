# Penny handoff

## Done — October 2, 2026, 19:38 UTC

Penny PR94–96 are merged. The Note correction is installed; one existing Note
was fully verified and reconciled, then the normal watcher routed canonical
row 770 / Voice Memo 443 at 19:36:51 UTC. `/ready` is HTTP 200/degraded with no
unready component. Historical exceptions and held recordings remain intact.
Final code tests: 765 passed, 2 skipped, 60 subtests; trust 497 tests, 2 skipped,
PASS. Both PR96 hosted Python checks passed. See [current context](CONTEXT.md).

## Runtime and receipts

- Three caller labels: `6ccf2286a2c6af1919e43b4eaba72465f8eb614b`.
  Shared ASR/export and root Git HEAD: `c341598c`. Root owner files are preserved.
  Exact scoped installation: `~/.penny/deployments/20261002T1936Z-note-reconciliation/`.
- Original Note attempt: `~/.penny/recovery/20261002-note-770-repair/`.
  Verified existing-item reconciliation and runtime/delivery acceptance:
  `~/.penny/recovery/20261002-note-770-reconciliation/`.
  Runtime receipt SHA256:
  `371aba60a627e2283ea36d01bf45b05f896a920a7e6d20c1ae88f2aab994bc89`.
- Installed source modules match merged bytes. Backup/before-images permit
  scoped rollback. Do not reset/stash/overwrite the runtime checkout or interpret
  its preserved Git HEAD as the revision of every installed component.
- Earlier shared ASR activation/hardening receipts and accepted consumer state:
  [ASR evidence](docs/asr-hardening-20261002.md).

## No running implementation work; two input gates remain

P01 needs the next ordinary Penny recording: latest canonical row is still 771.
P02 needs the next eligible ordinary direct Maya v2 input; none is pending.
Do not replay old deliveries or synthesize a personal recording to manufacture
acceptance. Exact conditions are in [TODO.md](TODO.md). No owner command or
machine restart is required to unblock normal capture; these checks wait for
normal use.

Recheck the actual installed caller, not a shell Doctor missing its environment:

```bash
curl -fsS http://127.0.0.1:5678/ready
curl -fsS http://127.0.0.1:10311/health
venv/bin/python /Volumes/2TB_SSD/penny-asr-runtime/hardening-20261002/run-installed-doctor.py
```

For the next capture, read only its identity/model/status first, then verify its
archive and delivery receipts separately. Keep transcript/audio bodies local.
`docs/capped-note-repair.md` describes receipt-bound recovery; a succeeded Note
must not be recreated. Synthetic quarantine 493 and quality-held 769 stay intact.

The OCI observer is active and recorded the recovery, but has a narrower
configuration than `/ready`; use the latter for loaded source and Drop status.
[Infrastructure and monitoring evidence](INFRA.md).
Previous dated checkpoints: [historical handoff](https://github.com/Khamel83/penny/blob/6ccf2286a2c6af1919e43b4eaba72465f8eb614b/HANDOFF.md).
