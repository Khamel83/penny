## Retry retention accepted — October 16, 2026 09:52 UTC

Done: PR122 exactb5ab29f passed trusted review5545840725 and both native hosted
checks38881833594; normal merge85900798 verified. Native Python3.11 reports
837passed/two skipped/60subtests and trust497/two skips. Installed helper SHA256
`c568bd45bde9ae5d3d801740471ed7503fd72566a8bbf32aa0fafa289ea8dd2b`;
only the idle ASR label was reloaded, now PID58688/source85900798. Independent
health200/idle declares pinned Parakeet, worker PIDnull. Installed synthetic
terminal-release and old-pending preservation probe passed. Local `/ready`
HTTP200/zero unready, Drop pending/failed/uncertain=0/skipped=1; webhook remains
c9b0368a. Callers/keeper/other plists and production code were preserved.
Primary keeper branch/HEAD65758e82 stay; Doctor and retry helper are its two
intentional tracked runtime deltas.

Private SSD root: `/Volumes/2TB_SSD/AI/Penny/deployments/20261016-retry112/`.
`deployment.json` and `independent-readback.json` pin source/native/process
proof; deployment SHA256
`b5b43054bb231711c10903e6a7c879cc047806ad50aafd7d51a9f4bba345bec0`.
Source/plist before-images support helper-only rollback using the existing idle
reload helper. Generation2 backup contains449hash-verified files/10,059,792,302bytes;
all files/directories were fsynced and write-protected. Snapshot tree SHA256
`3e696430c186638e60d098a3ea701728717cdec0dc5f3121c2b69178f95c77e1`.
The original443-file backup remains. Source compact bundles/patches, prior refs
and reused retained worktree are preserved; no cleanup or source prune is
part of this task. No raw payload left the local SSD for this recovery.

Acceptance decision, October16 10:13UTC: close #112 after normal review/merge
of this record. Its original four criteria require tests: SSD-root placement,
terminal audio removal with receipt retained, pending-review preservation and
passing existing tests. These passed in PR122 and the installed synthetic probe;
installation also has independent readback. Waiting for another ordinary retry
was an added requirement, now removed. No ordinary retry or downstream delivery
is claimed by this decision.

Next: monitor ordinary retry metadata during normal use for terminal audio
release/receipt durability or pending-review preservation. No owner decision is
needed. Do not manufacture inference/replay or run a historical prune. Recheck
`curl -fsS http://127.0.0.1:10311/health`, loaded ASR source stamp and helper hash;
check `/ready` separately. #111's useful retained candidatea0bdf579 remains
unpublished; its earlier baseline environment/judge failures are technical,
not proof that the owner must reprioritize it. Infra owns #110 acceptance.

## Current Doctor acceptance — October 16, 2026 UTC

Done: [PR115](https://github.com/Khamel83/penny/pull/115) merged as
`c9b0368a39113f79272f54901883ed91278d03e3` after exact-head trusted PASS and
both hosted Python checks. Focused checks pass 61 tests; trust passes 497 tests
with two skips. The merged Doctor bytes are installed; only the webhook was
reloaded. Local `/ready` and OCI through the existing Mac SSH route return
HTTP200, zero unready components and Drop pending/failed/uncertain=0, skipped=1.
ASR PID2025 and its source stamp are unchanged; 57 other production Python
files and peer launchd plists match their before-images. Primary HEAD65758e82
and its keeper branch remain; its only intentional tracked change is doctor.py.

The first activation probe ran before the HTTP listener started, so it safely
restored the prior Doctor and webhook. Independent readiness proved restoration.
A separate attempt with a bounded startup wait accepted the same reviewed bytes.
Both attempts and the fresh verified SSD/Homelab backup are preserved under
`/Volumes/2TB_SSD/AI/Penny/deployments/20261016-doctor115{,-warmup}/`.
Accepted deployment receipt SHA256:
`739f72f5364a5e18f83f1aa0d091d438b837a9258046a68d031d4d93229d7dff`.
No recording, ledger row, delivery or provider replay was performed.

Next: observe ordinary captures, separately verify each downstream receipt, and
continue the existing #111 quality-rule task; #112 is accepted above. Infra owns
#110 incident acceptance; this scoped report does not close it. Recheck loaded
`http://127.0.0.1:5678/ready`, Doctor hash
`3210731d6fa985342f4c3a29c5baa531c3eee22a8816dc72790cde00e4e10a71`
and `launchctl print gui/$(id -u)/com.penny.webhook`. For scoped rollback use
the private Doctor/plist before-images and the existing reload helper, preserving
ASR and the ledger. The reused retained worktree and prior refs stay intact;
no cleanup is authorized here.

## Current keeper checkpoint — October 16, 2026

Done: PR119 merged `6330b398` after exact-head trusted PASS, both hosted Python
checks and independent Janitor merge receipt. Keeper-only merged bytes were
installed at 07:32:46 UTC with exact source stamp, loaded-byte verification and
SSD before-image/receipt. Initial and first ordinary scheduled runs exited 0
at the 120-second interval. The ASR daemon PID stayed unchanged; local and Homelab health pass with pinned Parakeet.
[Evidence, private receipt and rollback](docs/shared-whisper-keeper-20261016.md).

Next verification: inspect `launchctl print gui/$(id -u)/com.penny.shared-whisper-keeper`
and check `http://127.0.0.1:10311/health` locally and
`http://omars-mac-mini.deer-panga.ts.net:10311/health` from Homelab. Real
outage/reboot recovery is unexercised; do not disrupt ASR to manufacture it.
This acceptance publication uses the same clean checkout on a fresh docs branch
from fetched main. No new worktree was created; existing worktrees, state and
other Penny labels were preserved.

## Current repository-plan checkpoint — October 11, 2026

The owner requested one owning plan for every open TODO, issue and PR. [docs/REPO_PLAN.md](docs/REPO_PLAN.md) maps 2 unchecked source references and 6 open native records observed from `cfcae61fd36bb9ac0cf573d76d6f57493c59b536`. G2K is the executor; coordinator116 tracks project-owned acceptance. Previous source prose below is retained as dated evidence, not refreshed runtime attestation.

This source proposal requires trusted exact-head review, native CI and normal merge before audit117 is closed or finite sequencing is applied. Source, installation, ordinary receipt and downstream effect remain separate. Next: verify this PR’s current head and accepted native merge, then update the existing coordinator; resolve the explicitly listed next review/receipt/decision in plan order. No busy worker, host service, access policy or retry state was changed.

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

In flight: [PR115](https://github.com/Khamel83/penny/pull/115) publishes explicit
skipped-count reporting and this record;
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
