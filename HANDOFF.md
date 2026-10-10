# Penny handoff

## Current checkpoint — October 9, 2026

Done: immediate SSD relocation, checksum verification, SQLite integrity check,
SSD mount guards, restored continuous services and fresh Voice Memos access. Internal disk free space is
26 GiB; SSD approximately 37 GiB. Actual checkout is
`/Volumes/2TB_SSD/penny-runtime`; home paths resolve to SSD. Owner edits remain.
[Evidence and private receipt location](docs/ssd-storage-20261009.md).

Source: [PR113](https://github.com/Khamel83/penny/pull/113) merged as
`5d63847073dd00ac874611a8b0273611277b520b`. Runtime configuration is installed;
old component revision stamps are retained.
Done: owner-directed local retirement of note 779 Drop delivery. Audio,
transcript and original failure evidence remain; no resend or fabricated
acceptance. `/ready` HTTP 200 with zero unready components. Drop ready with
uncertain=0, failed=0, pending=0 and skipped=1. Shared ASR healthy.
[Evidence](docs/drop-owner-skip-779-20261010.md).

In flight: source publication of explicit skipped-count reporting and this record;
the scoped Doctor update is installed and 51 focused tests pass. Drop158
is retired as owner-declined delivery. Retry retention #112 is separate
previously tracked work; it is not a readiness blocker.

Next: observe ordinary new captures. Recheck `curl -s
http://127.0.0.1:5678/ready` and `curl -s http://127.0.0.1:10311/health`.
Keep skipped 779 locally; do not requeue it automatically.

## Current acceptance — October 4, 2026

P01 is complete: three ordinary voice notes (772–774, October 2–3) used pinned
Parakeet, passed quality and routed. Local audio hashes and published archive
receipts, matching Drop archive bytes, Slack sent receipts and live Maya
store-only source-event receipts are verified. [Evidence and limitations](docs/natural-parakeet-acceptance-20261004.md).
Private metadata receipt: `~/.penny/recovery/20261004-natural-parakeet/receipts.json`.
No new transcription, test capture, replay, provider write or runtime change.

P02 is retired as a normal voice-note gate: new iCloud captures intentionally
use Penny → Drop → Maya and are direct-v2-ineligible. Maya already received all
three. The separate legacy direct-v2 route would need its own acceptance only
when explicitly used; preserve its nine dead letters.

There is no remaining input-gated work for the ordinary Penny voice-note path.
Continue normal monitoring. Recheck `/ready` and inspect new capture/delivery
receipts separately if a future failure appears. Atlas publication is not
asserted by Penny's receipts. The October 2 repair details below remain history.

## Done — October 2, 2026, 19:38 UTC

Penny PR94–96 are merged. The Note correction is installed; one existing Note
was fully verified and reconciled, then the normal watcher routed canonical
row 770 / Voice Memo 443 at 19:36:51 UTC. `/ready` is HTTP 200/degraded with no
unready component. Historical exceptions and held recordings remain intact.
Final code tests: 765 passed, 2 skipped, 60 subtests; trust 497 tests, 2 skipped,
PASS. Both PR96 hosted Python checks passed. See [current context](CONTEXT.md).

A successful local routing receipt does not establish independent Slack or
independent Maya v2 delivery. For Voice Memos, accepted Drop intake is a separate
boundary from each consumer's downstream receipt. Verify archive and provider
receipts separately; never infer delivery from healthy services or passing tests.

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

## Rechecking the installed runtime

The earlier P01/P02 input waits are superseded by the October 4 acceptance above.
Keep local routing, independent Slack and independent Maya v2 evidence separate;
Maya's Drop receipt verifies the active route without accepting legacy direct v2.

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
