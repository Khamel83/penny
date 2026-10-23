## Issue #138 — worktree-only handoff, October 22, 2026

Local edits complete: existing deadline policy retained; supervisor logs
`worker_deadline_exceeded`, exposes epoch start/monotonic age, and keeper treats
age above 1800 seconds as a failed health check using its two-strike logic.
Regression coverage executes the supervisor with a never-completing fake
worker, verifies termination, then succeeds on a replacement. Keeper shell
tests execute the template with host commands stubbed and real private state.

Review correction: `caplog.set_level(logging.WARNING,
logger="shared_whisper.supervisor")` enables deadline warning capture even when
other test modules call `logging.disable(logging.CRITICAL)` during collection.
No production logging change or weakened assertion was needed.

Verification: 37 supervisor/keeper/server tests passed in 4.19 seconds with
global logging disabled before pytest started; the original disabled state was
restored afterward. Host Python lacked pytest, so verification used a disposable
worktree-only virtualenv with pytest, Flask and requests. Recheck in a Python
environment with those dependencies installed:

```sh
python -c 'import logging, pytest; logging.disable(logging.CRITICAL); result = pytest.main(["-q", "tests/test_shared_whisper_supervisor.py", "tests/test_shared_whisper_keeper.py", "tests/test_shared_whisper_server.py", "--basetemp=.pytest-tmp"]); assert logging.root.manager.disable == logging.CRITICAL; raise SystemExit(result)'
```

A threaded loopback HTTP service with generated silent WAV audio and fake
workers returned 503 for the hung request, terminated its worker, and emitted
`worker_deadline_exceeded client=atlas age_seconds=901.0 deadline_seconds=900.0`.
The next request on a replacement returned 200 with `recovered`; `/health`
returned idle with both timing fields null. No MLX model or real audio was used.

Blocker: this unattended worker is restricted to this worktree; no deployment,
credentials, Mac runtime, MinusPod or Kuma access is permitted. Orchestrator
must inspect/publish the edits, deploy the reviewed supervisor and keeper via
the established deployment procedure, then verify a synthetic hang recovers,
MinusPod resumes transcription, and Kuma `atlas.mac-asr` records the outage.
No push or merge performed. No ledger/archive/provider/delivery state changed.
The supplied dirty checkout was preserved; remote source freshness was not
checked within the worktree-only boundary.

## Shared ASR TCC containment — October 19, 2026 local

Current runtime is intentionally contained. The shared ASR LaunchAgent failed
before application startup with `Fatal Python error: Failed to import encodings
module` and `InterruptedError: [Errno 4] Interrupted system call` while
touching `/Volumes/2TB_SSD/penny-runtime`. Unified logs record 955
`kTCCServiceSystemPolicyRemovableVolumes` watchdog-expiry events across 101
PIDs in the fixed 20:17:00–20:29:38 PDT window. A manual same-environment
alternate-port run stayed healthy for 15 seconds.

At about 20:31:33 PDT, only `com.penny.shared-whisper-keeper` and
`com.penny.shared-whisper` were booted out. Both are unloaded; local and
tailnet health are down and port 10311 is absent by design. The four peer
labels (`export`, `tasks`, `watcher`, `webhook`) remain loaded and untouched.
Original ASR/keeper plist bytes and hashes are preserved. No source, data,
model, provider, privacy grant or TCC state changed. Private receipt and
capture hashes are recorded in
[the dated incident evidence](docs/asr-tcc-containment-20261019.md).

Owner-only blocker: resolve the supported macOS removable-volume
authorization/runtime identity condition. Then bootstrap the unchanged ASR
plist first, require stable local health and no rapid respawn, bootstrap the
unchanged keeper plist second, and verify the keeper run plus local, tailnet and
Kuma health independently. Do not use an unmanaged daemon, reset TCC, move SSD
state or claim recovery from a process-presence check.

## Recheck after owner gate

```sh
uid=$(id -u)
launchctl bootstrap "gui/$uid" "$HOME/Library/LaunchAgents/com.penny.shared-whisper.plist"
curl -fsS http://127.0.0.1:10311/health
launchctl print "gui/$uid/com.penny.shared-whisper"
launchctl bootstrap "gui/$uid" "$HOME/Library/LaunchAgents/com.penny.shared-whisper-keeper.plist"
launchctl print "gui/$uid/com.penny.shared-whisper-keeper"
curl -fsS http://omars-mac-mini.deer-panga.ts.net:10311/health
```

## Penny health green — October 18, 2026 local / October 19 UTC

Owner retired historical recovery and approved acknowledgement of the reviewed
past failures. [PR132](https://github.com/Khamel83/penny/pull/132) merged8606b497
after exact-head trusted PASS, both hosted checks and independent Janitor receipt.
Final validation:852passed/two skipped/60subtests; trust497tests/two skipped.
Exact merged Doctor/helper/operator bytes are installed; only webhook reloaded.
Fresh SSD/Homelab backup20261019T061523Z verified. Current `/ready` and OCI's
projection both report ready at8606b497; Homelab API reports Penny healthy.

The acknowledgement preserves ledger history and exposes raw/acknowledged
counts: Maya9, old capture failures2, unavailable1, test quarantine1. New or
changed failures still alert. Existing history and canonical placeholder336
match the before-image. Watcher636/tasks638/ASR650 and protected modules/peer
plists were preserved. [Evidence, private receipt and rollback](docs/health-audit-20261018.md).

Kuma parent22 and declared-check23 have ordinary saved UP heartbeats at
06:25:46UTC; readiness24 is UP at06:25:47. Parent reports all children up.
All three are green; historical uptime rows remain. No threshold was relaxed.
Next: normal monitoring. Recheck `/ready`, OCI's existing8793projection and
Kuma's latest22/23/24heartbeats when investigating a future new failure. No
historical recovery, missing-content chase or replay remains in flight.
The same `.worktrees/health-repair` was reused for source and acceptance;
retain clean for safe reuse after accepted publication. No sibling checkout
or separate acceptance worktree was created.

## Parakeet timing accepted — October 16, 2026 11:12 UTC

[#111](https://github.com/Khamel83/penny/issues/111) satisfies its original
contract. [PR126](https://github.com/Khamel83/penny/pull/126), exact
22904fa59d9c7ddd7f195cf9a5f82555fa582b61, received trusted Bot PASS5546707424;
actual hosted Python3.11/3.12 jobs116935466531/116935466875 succeeded in
[run38889557502](https://github.com/Khamel83/penny/actions/runs/38889557502).
Normal merge64d32534eff8d7b85202e1ca3b99529490aa299c and identical reviewed/merge
tree46e641bf25ed1725e355ae0b6772c5f06f601b0c are independently verified.
Janitor merge receipt runmerge-07eae535860a42bfac2fb53a37e3e65c is retained in
OCI `~/.local/state/janitor/merge-receipts.jsonl`.

The four reused code/test blobs came from retained effective treea0bdf579.
Only finite/nonnegative/overflow-safe timing validation and two regression cases
were added. Both new cases fail against the retained candidate and pass after
the guard; 92 focused checks pass. Full local suite:848passed/two skipped/
60subtests; trust:497tests/two skips. All62 sampled Whisper comparisons match
the baseline. The initial private fixture-environment failure and corrected
837-test baseline remain with the source proof; no production data or credentials
were used in those tests. Private source/test evidence:
`~/.local/state/g2k-observer/burndown-20261016/penny-candidate-rescue/111/` and
`/Volumes/2TB_SSD/AI/Penny/verification/20261016-issue111/`.

The separately reviewed two-module installation succeeded at11:11:53UTC;
independent readback at11:12:52 verified transcript_quality.py SHA256
167994fad3e40770666e4b843c66b14ff25f19a0212127af2dd641810ce74f98 and
shared_whisper/server.py SHA256
185bdcbe9863028a76ef24f5b9d353b27c492c64f9742e8845da710d79fb945e.
The real maintained reloader refreshed only ASR/watcher/webhook, now
PIDs67159/67194/67201 with component source64d32534. All56 other production
Python files, Doctor3210731d, retryc568bd45, keeper, tasks/export processes,
original interpreter/arguments and unrelated plist bytes/modes were preserved.
Primary HEAD65758e82 and its keeper branch remain; Doctor, retry helper and the
two installed modules are its four intentional tracked runtime deltas.

ASR health200/idle retains the pinned Parakeet identity; `/ready` is HTTP200
with13components/zero unready, overall degraded. Four installed-code synthetic
timing vectors pass with zero model calls or production writes. Ordinary serving
quality and downstream effects remain unobserved. Private SSD deployment root:
`/Volumes/2TB_SSD/AI/Penny/deployments/20261016-repetition111/`.
`deployment.json` SHA25639904e54c518f096659ec2134b2b46f34b2c5fa2f1ed1cffdcae91bf5c1bc8a5;
`independent-readback.json` SHA256de14da66a8ef8406862609df4a46d918424369a5ceccfe66e771a54fb2fb30b4.
The five source/plist before-images and activation intent remain. High deployment
reviewae3ae0bd-3916-41ac-bbec-40df6e0e77ad is SATISFIED; no rollback was needed.

Acceptance decision, October16: the original first four criteria are the timing
and existing-suite tests above. The fifth requires the PR description to tell
the operator to archive the held episode after deployment; PR126 does so. It
does not require executing that archive or waiting for readiness to clear.
The exact canonical recording/sidecar still match the retained receipt and
immutable112 backup, and its current Parakeet hold remains active. No audio,
sidecar, receipt, ledger or Atlas queue state was changed. Broader Atlas quality
work remains separate; no replay, retrospective quality pass or owner triage is
added to #111's completion contract.

Next: obtain trusted exact-head review, both native checks and normal merge for
this acceptance record, then under fresh canonical/lowercase RepoLocks recheck
issue111/peer/lease/source/receipts, close111 COMPLETED and remove only its
resolved needs-human/acceptance-pending labels. Preserve all other history and
work. Recheck both local health URLs and the named private readback; no redeploy
is needed for this documentation. Existing branches, candidate refs/bundles and
the same reused retained checkout stay; no new worktree or cleanup.

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
check `/ready` separately. #111's retained candidate is accepted in the current
checkpoint above; its earlier fixture/judge failures and private proof remain.
Infra owns #110 acceptance.

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
retain #111/#112 acceptance above. Infra owns
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
## Fleet CI cancellation - source checkpoint (October 16, 2026)

Prepared source on `feat/fleet-ci-cancellation-20261016` adds PR-only concurrency cancellation to `.github/workflows/test.yml`. Native CI, review, and normal merge remain pending. No runtime or deployment change is claimed.
