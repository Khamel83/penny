## Penny Note reconciliation — October 2, 2026

PR94 and PR95 are merged. The retry selector and operator repair were installed
as a scoped three-caller update at `946a4ac`; shared ASR and export were not
restarted. Protected owner files and the runtime Git checkout were preserved.
Private deployment receipt: `~/.penny/deployments/20261002T1926Z-note-repair/`.

The authorized repair created exactly one Note for row 770 on attempt six.
Notes rejected its advertised `container` getter, so full readback failed and
the ledger correctly retained `uncertain`. The corrected folder-membership
readback now verifies the existing Note's exact marker and full normalized
payload. No second Note was created. Source adds an explicit reconciliation-only
claim: exact expected count, no creation, no cap reset, no quarantine override.

Validation: 765 passed, 2 skipped, 60 subtests; trust check 497 tests, 2 skipped, PASS.

Next: merge and install this correction, reconcile the existing Note at expected
attempt six, then verify ordinary routing and installed `/ready`. Private first
attempt: `~/.penny/recovery/20261002-note-770-repair/`. Historical quarantine and
held row 769 remain untouched. Natural post-Parakeet capture acceptance still
requires a new ordinary recording; no new capture has arrived.

## Historical checkpoints (superseded by the current state above)

## Penny finalization — October 2, 19:15 UTC

This task is Penny only. The unrelated Drop closeout does not establish any
Penny acceptance. Current `/ready` confirms shared Parakeet, capture, archive,
backup and delivery queues are healthy; the one capped real Note keeps Apple
effects unready. Synthetic quarantine and historical exceptions are preserved.

Fresh installed runtime is `c341598c`. Shell-only Doctor omits installed
configuration; use `/ready` or the installed caller environment. Source repair
is in `fix/penny-finalize-20261002`, based on fetched `0fdc5ed`; protected dirty
runtime documentation remains untouched. Local suite: 763 passed, 2 skipped,
56 subtests; trust check passed. The operator dry run verifies row 770's stored
payload and absence in the unique target folder. Live mutation is not yet done.
See [the repair procedure](docs/capped-note-repair.md). Next: publish reviewed
source, perform the one authorized repair, then record exact runtime/readback.

### Earlier retry-selector checkpoint

## H02 capped retry selector source repair — October 2

Source prepared for review; deployment and installed Doctor verification remain open.
Working tree changes are limited to `transcript_log.py`,
`tests/test_transcript_log.py`, `TODO.md`, `CONTEXT.md` and `HANDOFF.md`.
Parent source requested and locally present:
`0fdc5ed653b5cb3bf4ab7b801bd07855d68c4785`. The parent fetched origin and
independently verified that exact default-branch SHA before publication.

Implemented repair: `get_pending()` now excludes only current rows with
`status='failed'` and current `error_message='attempt_cap'`. It intentionally
does not inspect or join `apple_effects`; historical succeeded/quarantined
effects do not suppress an ordinary current routing failure. No provider calls,
Apple RPC/writes, production ledger reads, live ledger changes, deploy, commit,
push or secret reads were performed.

Validation completed with fake fixtures:

- `python3 -m pytest -q tests/test_transcript_log.py` — 114 passed, 11 subtests
  passed.
- `python3 -m pytest -q tests/test_apple_effects.py tests/test_apple_effects_integration.py tests/test_apple_provider_probe.py tests/test_reminders.py`
  — 46 passed.
- `HOME=/tmp/penny_test_home PYTHONPATH=/Users/macmini/Library/Python/3.14/lib/python/site-packages PENNY_INGEST_TOKEN=test-token python3 -m pytest -q tests/test_watcher.py -k 'retry_pending_routes or get_pending or pending_route or retry_logs or maya_origin_retry or ingest_pass or slack_outbox or maya_outbox or maya_worker or two_maya_workers or voice_memo_retry or failed_transcription_schedules_safe_retry or local_only'`
  — 17 passed, 72 deselected.
- `HOME=/tmp/penny_test_home PYTHONPATH=/Users/macmini/Library/Python/3.14/lib/python/site-packages PENNY_INGEST_TOKEN=test-token python3 -m pytest -q tests/test_drop_outbox.py tests/test_drop_delivery.py tests/test_export_drop.py tests/test_slack_delivery.py tests/test_transcript_contract.py -k 'not checked_maya_schema_uses_full_json_schema_and_format_validation'`
  — 69 passed, 2 skipped, 1 deselected, 6 subtests passed.
- `python3 -m py_compile transcript_log.py tests/test_transcript_log.py` passed.

Known local validation gap: the full Drop/Slack/Maya run has one unrelated
environment failure in
`TranscriptContractTests.test_checked_maya_schema_uses_full_json_schema_and_format_validation`
because this Python environment has `jsonschema` but not its date-time
format extras (`rfc3339_validator`, `rfc3987`, `isoduration`). `ruff` on the
changed paths also remains red on pre-existing issues in these files
(`importlib` unused, two unused Apple-effect test locals, and two placeholder
f-strings in `transcript_log.py`).

Next: review/CI/merge/deploy this source repair, then verify installed runtime
selector behavior and rerun Doctor from the authorized runtime path. Current
Doctor remains expected unready at the existing Apple-effect delivery boundary
until the separate capped Note repair is completed. Preserve the synthetic
quarantine and do not replay or reset Apple effects from this source repair.

## Portable Apple app skills — October 2, 07:12 UTC

Owner requested reusable Apple app workflows across projects. Four skills are
versioned under `.agents/skills/` and installed under `~/.codex/skills/`:
`apple-apps`, `apple-notes`, `apple-reminders`, `apple-effects-reliability`.
Their shared contract binds each project to its own caller, exact target,
operation ID and private receipt. Existing Penny ledger/transport/markers remain
a project-specific binding. Native app access needs OS grants, not a shared API
secret. Copying configuration does not transfer caller permission.

All four skill validators and bundled reference-link checks pass; eight existing
read-only probe regressions pass. Installed files match source hashes. Installed
probe: Notes responding0.304s, Reminders responding0.455s. Private installation
and reachability receipts: `~/.penny/recovery/20261002-apple-skills/`.
Notes/Reminders scripting terms were checked against the installed dictionaries.
This is operator-skill installation, not a new app write backend or Penny deploy;
no item, grant, ledger or pipeline configuration was changed. New projects still
need their own caller-context and authorized write/readback acceptance. Other
apps route to computer use; no tested Calendar/Mail/Messages adapter is claimed.

Next: invoke `$apple-notes` or `$apple-reminders` from a new project session,
with its confirmed target and receipt location; use `$apple-apps` for first setup.
Recheck access: `python3 ~/.codex/skills/apple-effects-reliability/scripts/probe_providers.py --apps notes reminders`.
A new natural Penny capture/archive/delivery check and capped-Note repair remain
separate open acceptance items; preserve existing held captures and quarantine.

Source publication: [Penny PR91](https://github.com/Khamel83/penny/pull/91).
Installed operator artifacts are hash-verified separately from Penny runtime.

## Earlier verified checkpoint: Reminders reachability and receipt recovery — October 2, 06:52 UTC

Reminders list access now passes: shell0.242s and equivalent installed-launchd
context0.135s. One existing reminder marker/provider ID/actual target agrees
with its canonical succeeded receipt. TCC showed a pending Ghostty Reminders-data
prompt before recovery; current UI grants and later decision/probes passed.
The exact owner action is unspecified; What's New dismissal alone was not
proven sufficient. Agent changed no privacy grant, item, ledger state or runtime.

Updated installed/versioned apple-effects-reliability covers Reminders-data
versus Automation, pending prompts as timeouts, metadata/data separation and
CUA/Peekaboo caller identities. Both Notes/Reminders respond; Finder window-count
still times out and must not be generalized as a Notes/Reminders outage. The
failed real Note and synthetic quarantine remain separate unresolved receipts.
No new item-write canary or natural Penny acceptance is inferred.

Evidence/recheck: docs/reminders-recovery-20261002.md and private
`~/.penny/recovery/20261002-reminders-diagnostic/`. Temporary probe agent removed.
Next: one new natural Penny capture's model/ledger/archive/actual delivery proof;
prepare a separate receipt-backed capped-Note repair decision without replay.

## Historical: Reusable Apple delivery procedure — October 2

The requested `apple-effects-reliability` skill is versioned at
`.agents/skills/apple-effects-reliability/` and installed on this Mac under
`~/.codex/skills/apple-effects-reliability/`. Its read-only helper probes live
provider reachability with bounded calls and safe error codes; it explicitly
does not prove delivery or reproduce launchd/SSH caller identity. The skill
requires exact target/marker and durable receipt reconciliation before retries,
keeps SIP/TCC unchanged, and excludes capture replay and silent retry-cap resets.
Eight focused regressions and skill validation passed. AGENTS.md now points
Apple delivery investigations to this procedure. Installed helper smoke test
confirms Notes responding (0.218s), Reminders process_timeout (12.008s). No watcher, provider
routing, launch agent or live pipeline code is changed by installing the skill.

Recheck: `python3 ~/.codex/skills/apple-effects-reliability/scripts/probe_providers.py --apps notes reminders`.
This can show Automation prompts or launch apps; it creates no personal items.
Future operators can invoke `$apple-effects-reliability`. Skill discovery is for
future sessions; it does not install automatic monitoring or prove permanent uptime.

## Historical: Apple Events recovery correction — October 2, 2026

Owner-authenticated system kickstart failed with error150 under enabled SIP.
The prior password-only recovery instruction was wrong and is withdrawn.
Keep SIP and TCC unchanged. Fresh read-only probes: Notes account query and local
AppleScript pass; Finder-window and Reminders-list queries time out after12s.
The running appleeventsd PID proves presence only, not responsiveness.

Private receipts/scripts: `~/.penny/recovery/20261002-sip-recovery/`.
Doctor's Apple provider_failure derives from failed ledger rows; it does not
probe current provider RPC. Exact Notes marker readback succeeded in shell and equivalent launchd context,
with zero matches for both outstanding effects; this remains distinct from
delivery success. Preserve failed/quarantined effects without resend/reset.
A normal Mac restart is a recovery candidate if exact target calls remain stuck,
after coordinating active work and shared ASR consumers. No restart authorized
or performed. Supported owner action after drain/save: Apple menu > Restart.
Exact existing Notes marker lookups now succeed from both the agent shell and
an equivalent launchd job using installed watcher environment; both outstanding
note effects return zero matches in their requested folders. The failed row and
older synthetic quarantined row remain unchanged. This proves bounded marker
absence at these observations, not delivered content or recovery of other apps.
The temporary diagnostic LaunchAgent was removed. A Mac restart is not required
for the currently reachable Notes path. Do not mark failed delivery succeeded or
reset its cap merely because the provider responds.

Next: prepare a receipt-backed repair decision for the capped real effect.
Preserve the synthetic quarantine. No provider creation or ledger transition
was authorized or performed during these probes.
Source guidance: docs/workflow-recovery-20261001.md.

## Verified ASR activation — October 2, 2026, 05:24 UTC

Penny runtime `c341598c` and native Atlas/MinusPod `74f4cada` are healthy.
The native image is `atlas-minuspod:74f4cada-asr-hardening`, digest
`sha256:fe0b45965f9bd396ec5f4e256369302acb4c275752fff4a18cd12ad7dca6a0df`.
Both owned jobs completed naturally before activation; no forced shutdown occurred.
The gate reports `activated_admission_restored`, original admission is `false`,
and drain, watchdog and readiness user timers are active. Restart count is zero.
Installed transcriber, processing and schema hashes match the reviewed overlay
chain; the once-only cleanup success marker exists. Legacy `0d75` remains active.
Final private Homelab receipt:
`/mnt/fast-storage/appdata/minuspod/asr-hardening-final-acceptance-20261002.json`.

Atlas PR176 exact-head hosted syntax and tests passed in run `36966127524`
at 05:20 UTC; exact-head reviews and 2,221 local nonlive tests passed separately.
Earlier source-only, queued-CI and deployment-fence checkpoints below are historical.
Penny's installed-context Doctor still separates healthy core/ASR from unrelated
Apple Events provider failure, historical Maya dead letters and unavailable memos.
Apple effect receipt-backed repair and a new natural Penny ledger/archive/downstream
receipt remain open. The protected-service instruction is superseded by the
recovery correction above. No historical capture release, private replay or redelivery occurred.

## Historical: ASR hardening runtime checkpoint — October 2

Penny `c341598c` (PR88) is live on five agents. The saved malformed-response check is green; a public serial model canary passed without ledger or delivery mutation. Legacy projection `0d75eaba` is deployed with its timer active and full component verification passed. Seventeen prior failure receipts seeded one private hold; no additional same-input retries were observed.

The native candidate `74f4cada` is built and hash-verified. The gated updater waits for the owned postprocessing job, then records activation, rollback or deferral and restores original admission. Read `/mnt/fast-storage/appdata/minuspod/asr-hardening-native-gate-20261002.json` before claiming native activation. Atlas hosted tests remain capacity-queued at the checkpoint; hosted syntax and 2,221 local nonlive tests pass.

Apple Events needs the administrator command documented in docs/asr-hardening-20261002.md, followed by receipt reconciliation. Do not resend uncertain effects. Natural Penny capture/ledger/archive/downstream acceptance remains unobserved. Recheck commands and private receipt paths are in that report. Protected root files and their preservation stash remain intact.

## Historical: ASR hardening in progress — October 2

Isolated fix/asr-contract-hardening-20261002 preserves dirty primary checkout. Producer/client timing validation, child error locality, actual model error metadata and Penny needs_review handling implemented. Synthetic real-shape red tests now green; full suite749 pass/2 skip/53 subtests, focused43 pass plus8 new regression checks. Next: exact-head review/CI, merge, rollback-capable deploy, saved-response agreement and installed-context Doctor. Atlas legacy drain paused with private receipt at /mnt/fast-storage/appdata/minuspod/asr-hardening-drain-pause-20261002.json; restore only after hold deployment. Apple Events failure and natural capture acceptance remain separate.

## Runtime diagnostic — October 2, 2026 UTC

Installed-context Doctor verifies Penny capture/storage/shared offline ASR,
archive/backup/Drop/Slack ready at03:11:57; overall remains unready at Apple
effects with separate historical Maya/memo exceptions. Native health200 does
not establish job success: new ASR failures exposed a saved Whisper response
accepted by Penny but rejected by Atlas (segment end60ms before start), and one
105-minute input repeated the same Parakeet backward-timing hold ten times.
One-owner memory measured2.0GiB/peak2.5GiB; no old large owner. Fifty focused
checks pass while the existing-response reproduction goes red; no new ASR,
private replay, delivery, reset or production change was performed.

See docs/runtime-diagnostic-20261002.md for exact evidence, private loop and
acceptance limits. Next: unify structural response handling, stop repeated
whole-input quality retries, and retain numeric failure locality for bounded
excerpt repair. Slow native database startup and Apple Events are independent
repairs. Natural post-cutover Penny capture acceptance remains unobserved.
Earlier sections below remain dated historical evidence.

## Native image activation held — October 2, 2026

Atlas PR170 is source-merged at5086c022 with passing hosted checks and reviewed
source. Its candidate image did not become healthy within the1020-second startup
bound, so the installer restored the previous image/manifest. This preventive
fix is not live. Native publication at02:02:52 was independently proved on the
previous image; it does not prove this later image activation.

Old-image own health passed before the rollback wait expired. Parent readback
at02:46 UTC confirms running/healthy image ed39b04e and active user timers
atlas-minuspod-watchdog, atlas-readiness and atlas-podcast-whisper-drain.
Original admission=false was restored with zero active/processing jobs and
all other SQL settings unchanged. Fresh health/readiness were200 with no reasons.
The normal scheduler subsequently admitted a new native job; its completion is
an independent acceptance item. Private restoration proof remains at
/mnt/fast-storage/appdata/minuspod/atlas-local-slot-restored-proof-20261002.json. Queue/data and the original ASR receipt remain
preserved. The installer returned candidate failure with rollback evidence;
that exit is not a successful candidate deployment.

Both candidate and stock rollback showed slow existing-database startup, disk
wait and zero restarts. The956,526,592-byte SQLite database is on Homelab's hard
drive. Stock startup performs existing-database search-index count and transcript
cleanup scans. Existing private slow-query logs measured search-index counts
at197.0 and240.9 seconds and legacy marker cleanup at370.4 seconds. These
startup scans are measured bottlenecks; no new instrumentation or content transfer
was needed. Next: review safe migration gating/optimization, then repeat bounded
rollback-capable activation. No second candidate attempt was made.

## PR recovery — October 2, 2026

Historical snapshot before the activation attempt above; its in-progress startup
statements have been superseded by the rollback evidence.

Owner authorized completion of workflow recovery and repair/review/merge of open
Penny/Atlas PRs. Penny's four remaining PRs (66,72,73,74) conflicted only in
CONTEXT.md, HANDOFF.md and TODO.md after the deployment/recovery series advanced
main. Each was reconciled in a separate fresh worktree, with both historical
research and current runtime evidence retained. Both Python3.11/3.12 CI checks
and exact-final-head Standards/Spec reviews passed before each merge.

Research output permission gaps were repaired: pre-existing files and reused
atomic temporary files become0600 before writing; Apple probe directories become
0700. Synthetic regression cases cover existing0644 files and a failed write.
No research recognition or private capture replay was performed for these fixes.

All four are source-merged: PR66=9331227, PR72=aa8d70d, PR73=c269ab3,
PR74=f492c33. These are research/tooling changes; installed pipeline remains
ca6322b, with the pinned Parakeet primary. Final ASR health was idle, worker_count0
and no resident backend after normal idle unloading. Dirty runtime-root owner
files and original research checkouts remain preserved.

Atlas's earlier postprocess verification failure was local ASR-slot contention,
not a failed primary transcript or proven transport outage. Normal scheduling
resumed the same checkpoint and completed02:02:52 UTC. Episode/history completion,
canonical24,686,598-byte processed audio, ffprobe0, current-version RSS enclosure
and HTTP200 full readback matching its SHA256 are independently verified.
The original ASR receipt is unchanged. Private evidence remains at
/mnt/fast-storage/appdata/minuspod/atlas-native-publication-proof-20261002.json.
This closes that native publication gate, separately from the prior33-minute
legacy text import; no recognition or provider proof request was added.

Atlas PR170's preventive typed local-capacity deferral fix at b367c8f2 passed
both hosted checks and parent source review, then merged5086c022. The full
nonlive suite passed2,152 tests (159 skips/14 deselected), with163 focused MinusPod
tests. Its immutable image is built and hash-verified; the controlled deployment
is in progress at zero owners with admissions temporarily paused. Native startup
health/source acceptance and admission restoration remain required.
Seven obsolete queued Atlas CI runs were cancelled with no active jobs; the
current repair's tests then ran successfully. OCI admission uses one global
runner slot shared with Maya; no capacity/authentication policy changed.
The transient legacy drain failure recovered through its normal retry, with
Result=success and health/readiness200; its old inner cause remains unproven.

Maya caller configuration cutover is recorded in PR85, merged d29e6eb. Installed
and loaded watcher/webhook/tasks URLs match the core endpoint; the hashed private
configuration receipt and unchanged outbox counts are verified. New direct v2
provider receipt/core readback remains a future natural acceptance gate.
Apple Notes still requires owner authentication for the documented Apple Events
restart. No capped effect was replayed or TCC permission changed.


## Maya core caller cutover — October 2, 2026 02:02 UTC

Watcher, webhook and tasks are running with the Homelab endpoint
`https://maya.khamel.com/ingest/transcript`. Existing token equality was checked
privately against the core; neither credentials nor grants changed. Installed
runtime remains `ca6322b697a4bcea8de52849d975d7543a994970`. Only those callers were
reloaded after backup and zero active delivery/effect claims; shared transcription
PID and export job stayed equal. Before-images and private receipts are under
`~/.local/state/maya-penny-core-route-20261002/`; configuration receipt SHA256
`f4871aaeb93e7535267c17cd4dbfadbd873c71915a1cc5d447e1ff2dde222951`.

No direct outbox was pending. Nine dead letters, 481 ineligible and 29 sent rows
are unchanged. Do not resend historical rows; their independent store-only
proof is preserved. Drop routing remains active. Next: inspect one ordinary
new direct v2 acknowledgement and compare its identity/hash with the core.
The loaded URL proves configuration, not that future receipt. Doctor remains
unready at the previously recorded Apple provider failure. Protected root edits
in the canonical checkout were preserved; this evidence uses a separate worktree.

## Recovery deployed and real episode imported — October 2, 2026

Penny runtime is now `ca6322b697a4bcea8de52849d975d7543a994970` (PR82),
including PR81's private long-review preservation. Exact-head CI passed both
Python versions; full local suite719 passed, 2 skips,53 subtests. Existing trust,
backup and deployment checks passed; all five installed agents match ca6322b.
Protected root owner files were restored byte-identically; preservation stashes
and private rollback/plist backups remain retained. Apple pilot stays disabled.

The retained33-minute Atlas episode failed from wordpiece timing validation,
not a measured semantic word-error result. Native suffix/punctuation pieces can
align before other pieces while reconstructed word starts remain chronological.
The correction validates actual word starts without sorting, dropping, clamping
or changing text. Token bounds and genuinely backward words stay fail-closed.
The actual queued episode now passed: one success, zero failure/deferral,
canonical import01:21:12 UTC with independent PostgreSQL/file readback (35,410
bytes/6,257 words). Historical compatibility label macwhisper is not model
identity evidence. Shared service selects the pinned Parakeet primary; post-job
one-owner measurement is1.5G physical footprint,2.0G peak. No wholesale Whisper
fallback or held Penny replay occurred. Semantic first-party comparison is a
separate earlier benchmark, not inferred from successful import.

Atlas receipt-schema/manifest/queue-link and safe typed-helper repairs are
installed. Native dead-owner reconciliation preserved an exact ASR checkpoint;
next claim is postprocess_pending and skips ASR. The termination CLI returned2;
accepted termination was not claimed. Exact old-owner death was independently
proved before existing recovery exited0. Original native admissions and legacy timer are restored. Fresh01:24:30 UTC
health/readiness are200 with no reasons. A strictly new01:26:17 successor
reuses the same ASR receipt, staysASR0 and makes fresh splice-evidence progress;
full native feed publication remains pending in Atlas's current audit package; no manual
queue relabeling or extra provider/notification proof was performed.

Penny fresh Doctor verifies core capture/ASR/archive/backup/Drop/Slack ready.
Overall remains unready only at Apple provider failure; legacy Maya/Voice Memo
exceptions remain visible. Nine Maya store-only receipts/current canonical bytes
are verified and need no resend; two historical memo sources have no recoverable
audio. Notes/Finder/Reminders automation still times out. Owner authentication is
required for the bounded Apple Events service restart in the recovery guide.
No privacy grant, TCC reset, account change or capped/quarantined-effect replay
occurred. After that service restart, recheck exact provider receipt before any
bounded effect retry. New natural Penny capture and full native feed publication
remain independent acceptance gates.

Private evidence is in ~/.penny/recovery/20261001 and ~/.penny/deployments;
Atlas canonical import/native recovery receipts remain on Homelab. Public work:
Penny PR80/81/82 and Atlas PR167/168/169. Earlier headers below are dated history;
their f490/937 or pending-deployment statements do not describe current runtime.

## Parakeet word timing correction — October 2, 2026

Deployed937 long-review receipt identifies `backwards_parakeet_token_time` for
the retained33-minute Atlas input, with no accepted primary transcript. This is
adapter validation evidence, not a measured word-error rate or gibberish claim.
The proposed correction checks chronology when each word is reconstructed,
instead of rejecting a punctuation/suffix piece aligned before a preceding piece.
All individual token bounds and genuine backward word starts remain rejected.
No word is reordered, dropped or assigned a fabricated time.

Meaningful overlapping-piece fixture fails before the correction; the companion
backward-word fixture remains rejected. Full suite passed719 tests, 2 skips and53 subtests; deployment and
the actual queued episode's recovery are pending. Penny937 remains installed.
MinusPod admissions and legacy drain stay intentionally paused; native dead-owner
recovery preserves an ASR checkpoint for postprocess-only resume. The response
from termination CLI was not accepted (exit2); old-owner death was independently
verified before recover-stale exit0. No manual queue relabeling occurred.

Next: finish checks/review/merge, coordinated idle deployment, then one real
queued request to verify whether this addresses the observed adapter error.
Restore original producer scheduling only after readiness/queue receipts pass.
Notes still needs owner authentication for the documented Apple Events restart.

## Long ASR quality-review evidence repair — October 2, 2026

Atlas's reviewed helper now exposes `quality_review_requires_bounded_excerpt`
for a queued 2,001.92-second episode. This is a real >660-second safety guard,
not an availability failure. The legacy drain was paused only at MainPID zero
to prevent repeated whole-audio inference; queued media and MinusPod are intact.
Atlas current health is 200/readiness 503 for the intentional inactive drain.

This source change preserves a private review receipt before rejecting an
automatic long-recording fallback: original audio, primary text/timestamps when
available, and a fixed safe quality reason. Native worker failure reasons are
allowlisted; arbitrary exceptions/payloads remain private. Primary-invalid output
is distinct from a text repetition flag. The Whisper bound, serial model owner,
canonical ledger and all downstream delivery behavior stay unchanged. Explicit
full-length Whisper requests remain refused without starting Whisper.

Meaningful receipt regression was red before the change (no receipt preserved).
Full suite then passed 715 tests, 2 skips and 53 subtests. Two additional server
worker-failure/privacy cases bring the focused adapter suite to 17 passed. Source
review/deployment and recovery of the queued episode remain pending; this is not
live repair evidence. Installed Penny runtime is still f4909d33. Protected root
files remain untouched. Private recovery receipts stay under ~/.penny/recovery/20261001.

Next: review/merge, establish producer ASR quiescence, deploy source with existing
backup/credential-preserving script, then inspect one ordinary deferred request's
private receipt and repair only a bounded excerpt if needed. Two native MinusPod
owners were observed at00:59 UTC; their stages must be checked before any restart.
Notes automation still needs owner authentication for the previously documented
Apple Events service restart. No TCC change or capped-effect replay is authorized
by this diagnostic receipt alone.

## Workflow recovery checkpoint — October 1, 2026

Owner authorized remaining workflow diagnosis and repair. Penny installed code stays
`f4909d33`; fresh metadata-only Doctor at `2026-10-02T00:36:50Z` reports capture,
Parakeet, archive, backup, Drop, Slack and SQLite ready. Overall remains unready
from Apple provider failure, with historical Maya and Voice Memo degradation.

Nine legacy Maya dead letters have unique successful Drop `store_only` receipts;
all nine raw payload hashes/sizes and current canonical object bytes match. Zero
missing/conflicting receipts. Legacy flat-file paths are absent, so this is current
canonical storage proof, not proof of historical flat-file migration. Do not resend
or forge success for the original direct Maya failures.

Actual launchd-context inventory finds both historical Voice Memo source rows.
One has zero duration and no audio file. The other has a 1,586-byte AAC file with
3.285-second container metadata but decoding exits 69, emits zero samples and
reports invalid AAC data. Preserve originals/history; no ASR or canonical rewrite
was performed. Native-source inventory succeeds; agent-shell access denial does
not establish a capture failure. Temporary diagnostic LaunchAgents were removed.

Notes UI is responsive. Actual provider marker/account queries time out, including
from installed Penny launchd context; generic Finder-window and Reminders-list
queries also time out. Normal Notes quit/reopen did not fix it. UI exact-marker
search for the recent capped effect returned no results, but this does not replace
provider reconciliation. An older synthetic effect remains quarantined. There were
zero active Apple-effect leases. The bounded system Apple Events service restart
was attempted and blocked by `sudo: a password is required`; no privacy grants,
TCC reset, note recreation or account changes occurred.

Atlas receipt-schema, relative-manifest-entrypoint and missing canonical queue-link
repairs passed native verification. A following natural drain completed pull/import
but failed after typed ASR deferral; fresh readiness returned 503. PR167 exposes
only the safe typed code; final deployment/cause resolution is still in flight.
MinusPod has at least one natural completion after resume; identity/publication
remain distinct acceptance gates. See Atlas's current audit package.

Private receipts (0600) are under `~/.penny/recovery/20261001`; no personal content
is committed. Details and next commands: [workflow recovery](docs/workflow-recovery-20261001.md).

## Shared Parakeet live activation — October 1, 2026

Penny runtime is deployed at `f4909d33d0a15db660c9eec35a02318aab297ca2` (merged PRs 75–77). Five launch agents carry that revision; watcher/webhook are resumed. Authenticated production Parakeet input passed Penny and Atlas/MinusPod identity/timestamp validation. Apple pilot remains disabled. The ten-minute public staging input took 14.984 seconds including cold load (1.4 GB physical footprint, 1.9 GB peak); bounded five-minute Whisper fallback took 45.509 seconds (1.8 GB, 2.4 GB peak), followed by successful Parakeet return and idle unload. The installed excerpt command separately verified original-audio timestamp offsets. No simultaneous model owners were observed.

Durable private receipts: `~/.penny/deployments/20261001T234710Z/receipt.json` and `/Volumes/2TB_SSD/penny-asr-runtime/cutover-20261001/{cutover-receipt,stage-canary-receipt,live-canary-receipt}.json`. Protected owner files remain intact; the preservation stash is retained. Source review, CI and deployment trust check passed. This is service activation evidence; no new natural Penny canonical capture/archive/downstream delivery has yet been observed. Existing held recordings were not released or replayed. Next: read a new normal capture's actual model, ledger, archive and delivery receipt separately; observe sustained workloads. Atlas/MinusPod controlled cutover receipt is tracked separately. The checked-in primary selector and all five agents now select Parakeet; CLI/Doctor agree with the installed runtime.


Atlas/MinusPod are now healthy and resumed: reviewed consumer source `3f7bd51e233d13aa097daec2cc0fda86b3f72d97` is merged in Atlas PR164; image `atlas-minuspod:3f7bd51e-parakeet` and final legacy drain select the pinned Parakeet primary. Admission returned to its original false pause value; drain/watchdog/readiness timers are active. Homelab private receipt: `/mnt/fast-storage/appdata/minuspod/shared-parakeet-deploy-20261001.json` (`healthy_admissions_resumed`). A cold database read delayed readiness; graceful clean shutdown and post-stop transaction fence preserved the queue. Native completion under the new selector remains an independent acceptance item.

Doctor confirms shared ASR/transcription ready, actual model verified, one owner and safe memory. Overall Doctor remains unready from Apple effect provider failure, with Maya dead-letter and historical Voice Memos degraded; no delivery repair or replay was performed in this ASR task.

## Historical RAM fix and alternatives assessment — October 1, 2026

Cache cleanup reduced measured post-request Whisper physical footprint from 2.3 to 1.7 GiB with the same pinned model. It limits free allocator buffers and clears them after requests; it is not a total-RAM ceiling and does not reduce live weight memory. Existing single ownership and idle unloading avoid duplicate/resident idle models. Long-running stability and active peaks remain unproven. Health at that historical assessment: idle, one worker, Apple pilot disabled.

Apple reference result does not establish Whisper as the best available engine. Phonon-2 remains the leading next candidate for a bounded comparison; its official 164 MB download expands to a dense FP16 encoder under MLX, so runtime memory is unknown. Publisher M5 speed/accuracy are not local M4 evidence. Quantized Whisper and Parakeet/Core ML are alternatives. Next specific verification: reuse the three public clips/references for Phonon-2 quality, word-time compatibility, peak and retained physical memory, and elapsed time, if testing is undertaken. No new recognition/install/deployment in this assessment; primary Whisper stays unchanged and bulk pilot stays paused.

## Public reference check recorded — October 1, 2026

Three public Lex samples completed once per engine. Apple processed 18.22 minutes in 18.41s versus shared Whisper 95.77s (5.20x), but normalized first-party reference disagreement was higher on all three: weighted 8.23% versus 5.56%. Case/punctuation and cosmetic variants are ignored; edited references are not independently adjudicated ground truth. The requested non-worse accuracy gate is unproven, so no primary switch. Total Apple system-model RAM/energy remains unknown; speaker diarization, naming and TTS are separate. Bulk recognition remains paused; At that reference-run checkpoint, runtime was e997211 with the pilot hook disabled.

Research source/evidence: https://github.com/Khamel83/penny/pull/72 (draft). Research utility ran on this Mac, all required observed artifact hashes were verified, then results were rescored without further recognition. Source 4314c45 passed both standards/spec reviews; 708 tests passed, 2 skipped, 53 subtests; Ruff passed. Local artifacts: /Volumes/2TB_SSD/penny-asr-reference-20261001. Next: adjudicate consequential existing disagreements against audio if accuracy acceptance is pursued; do not resume the bulk cohort. Conditional adoption remains issue #70. No ledger/archive/provider/downstream ownership changed.

## Official-reference comparison complete — October 1, 2026

Owner authorized a bounded three-episode public reference check; the background cohort remains paused. Identical audio was recognized once per engine. Apple was about 5x faster, but normalized reference disagreement was 8.23% versus pinned shared Whisper 5.56%, higher for Apple on all three excerpts. Cosmetic/stutter sensitivity did not reverse the ranking; published text is edited and not independently adjudicated ground truth. No blanket switch: the requested accuracy condition is not met. Total Apple model RAM/energy remains unmeasured, and speaker labels/names/TTS are separate capabilities. Report: docs/research/2026-10-01-apple-reference-results.md. Next: adjudicate consequential existing disagreements or a separately authorized domain experiment; do not restart bulk recognition. GitHub #70 owns the conditional adoption gate. The research utility ran on the Mac; primary runtime and all delivery ownership are unchanged.

## Bounded public reference comparison — October 1, 2026

Owner authorized a few official-transcript comparisons and conditional Apple adoption if accuracy and resource acceptance support it. The background cohort remains paused. Isolated worktree research/apple-reference-check-20261001 starts from fetched e997211. Three first-party Lex audio/reference pairs are verified; scoring distinguishes transcript agreement from adjudicated accuracy. Artifacts stay local under /Volumes/2TB_SSD/penny-asr-reference-20261001. Next: prepare identical short clips, run deployed Apple binary and pinned shared Whisper as low-priority backfill, quantify reference edits and resource limits, then document the decision. Canonical capture/delivery remains unchanged.

## Live contender results published — October 1, 2026

Research utility and measured report are published in draft PR https://github.com/Khamel83/penny/pull/73 (not merged or deployed as a primary adapter). Four resource-observation regressions, Ruff and diff checks pass; monitor failures now stop the isolated benchmark visibly before they can silently remove its sampled abort. No extra recognition was run for the review fix. Full/short raw receipts remain preserved locally; the resource figures refer to observed runs before this guard correction.

Parakeet v3 BF16 is the stronger new candidate: roughly 7.7x faster on the three Lex clips than the existing shared Whisper baseline, complete 36.43-minute episode in 23.60s, 2.8 GiB process peak, and qubits/Bostrom preserved as published. Primary adoption remains unproven because first-party transcripts are edited; Dwarkesh cross-check is dominated by insertions for all engines and is not pooled as true accuracy. Next specific verification: adjudicate a few existing consequential Parakeet/Whisper differences against audio, then a bounded quantized Whisper/Core ML comparison if useful. At that model-comparison checkpoint, runtime was e997211 with one shared Whisper owner and apple_pilot_enabled=false. No production integration, private replay or downstream change is in flight. Conditional adoption stays GitHub #70.

## Bounded Phonon/Parakeet live comparison complete — October 1, 2026

Four reference clips are now available: three Lex excerpts reused with verified hashes, plus one Dwarkesh/Dario excerpt. Each new model also completed one full 36.43-minute Lex episode: Phonon 22.10s, unquantized BF16 Parakeet 23.60s. Physical process peaks were 3.5/2.8 GiB; MLX active allocations after short/full requests stayed at 1.21 GiB each. No growth toward the owner-reported old 11 GB spike was observed. These are bounded runs, not multi-day stability proof. Shared Whisper remained primary and the Apple background pilot disabled; canonical capture/archive/delivery unchanged.

Parakeet is the stronger new candidate: 12.44s for the three Lex clips versus prior shared Whisper 95.77s, and it matches published qubits/Bostrom where Phonon/Apple miss terms. Edited reference disagreement still favors Whisper: weighted Lex Whisper 5.56%, Apple 8.23%, Parakeet 10.63%, Phonon 12.78%. Dwarkesh all-engine disagreement is dominated by 87-90% insertions and is kept separate from pooled accuracy claims; audited extraction lost no paragraphs. No true-WER or primary-adoption claim. Report: docs/research/2026-10-01-phonon-parakeet-live-results.md. Exact environment, outputs, timings, hashes and memory samples remain local under /Volumes/2TB_SSD/penny-phonon-benchmark-20261001. Source review/publication pending; no production integration is in flight. Next: review the bounded utility/report, then adjudicate a few existing consequential Parakeet/Whisper differences; retain the small public corpus for future quantized Whisper/Core ML comparisons. No private backlog replay.

## Bounded model comparison in progress — October 1, 2026

Owner authorized a few first-party podcast comparisons, speed and RAM checks; reported earlier 11 GB spikes and current improved machine stability. Isolated research/phonon-reference-20261001 starts from fetched e997211; production dirty files preserved. Phonon-2 and Parakeet v3 BF16 each completed the three Lex comparisons (Phonon Musk first cold CLI) and full 36-minute Musk episode. New engines are fast but currently disagree more with the edited Lex references. Adding one short Dwarkesh reference comparison, then record results and the adoption decision. External isolated environment/artifacts: /Volumes/2TB_SSD/penny-phonon-benchmark-20261001. At that checkpoint, shared Whisper was primary and Apple pilot disabled; no canonical transcript/archive/delivery mutation. Next: finish Dwarkesh pair, verify output/source hashes and timestamps, publish evidence. No private backlog replay.

## Ten-episode Parakeet validation complete — October 1, 2026

All ten distinct full first-party podcast/audio pairs completed: five Tyler and five Dwarkesh, 12.75 hours in 737.82 recognition seconds (12.30 minutes, 62.2x realtime). Apple M4/16 GB; one persistent BF16 model. Whole-process lifetime peak 4.3 GiB; settled footprint 1.5–2.2 GiB; MLX retained allocations exactly 1.21 GiB after every request. All word timestamps bounded/nondecreasing and no decoder truncation flags. This establishes bounded full-input resource behavior in one session, not multi-day or concurrency proof.

All 30 preselected 350-token windows retained usable broad gist. Fillers/restarts and sponsor insertions are immaterial; localized names/terms, one numeric change and a missing qualification remain real limitations. One three-minute Whisper cross-check corroborated the reference qualification; native Parakeet overlap still missed it. Recommend Parakeet as the leading speed/RAM candidate, not universally more accurate than Whisper. Prior 7.7x speedup applies only to three matched Lex clips; superiority over Phonon remains small-sample evidence. No further broad batch is needed. Report: docs/research/2026-10-01-parakeet-ten-podcast-results.md. Hash-bound receipts and raw public artifacts remain local under /Volumes/2TB_SSD/penny-parakeet-corpus-20261001. Verified resume recognized zero new inputs; focused alignment/resource tests pass.

Production still has one shared Whisper worker with apple_pilot_enabled=false. No private replay, canonical ledger/archive/delivery change or primary deployment occurred. Next specific work is a shared Parakeet adapter with compatible timestamps/model identity, rollback and authenticated Penny/Atlas canaries; #70 remains the primary-adoption boundary. Published in draft PR https://github.com/Khamel83/penny/pull/74 from fetched e997211; Standards and Spec reviews passed the research implementation at 5dbf76a. The PR is not merged or deployed. Protected dirty primary files preserved.

## Apple pilot paused by owner — October 1, 2026

All 32 held Penny recordings completed (43.2 hours), plus seven historical Atlas and ten natural Atlas inputs. Owner stopped further recognition. Sidecar is unloaded, autostart plist retained with .paused suffix, live capture disabled and normal five-label runtime verified at ec0f51a. All canonical Penny baseline text/status pairs remain unchanged. Binary repetition flags are not accuracy measurements: Apple repeated-run token share was 0.285% versus Whisper 0.725%, and severe runs were fewer. No first-party or independent reference comparison has been performed. Next is evaluation of existing outputs against references and flagged context, not more transcription; issue #70 owns the conditional primary gate. See docs/apple-pilot-live-receipt-20261001.md.

Apple launchd correction resolved (October 1): PR #69 binds diskutil to /usr/sbin. Corrected source ec0f51a activated all six labels, fresh pilot health and optional live capture. All 40 historical cohort inputs were admitted without errors, and natural Atlas requests have produced private Apple/Whisper comparison receipts. The first activation failure did not affect canonical Whisper. See docs/apple-pilot-live-receipt-20261001.md for acceptance facts.

Apple pilot review fixes (October 1): live snapshot disk work now runs in at most two daemon admission threads; overflow is refused without waiting. Only committed queue rows prove durability. Subprocess launch/register is synchronized with shutdown, including signal re-entry. Regression tests cover stalled storage and shutdown races. Corrected activation and real cohort admission are verified; recognition-quality acceptance remains open.

## Apple pilot in flight — October 1, 2026

The owner approved a real Apple workflow pilot. Work is isolated in `pilot/apple-speech-20261001`, started from fetched default `origin/main` `c1b0b1d`; production checkout's dirty documents remain preserved. Implemented modern native Apple CLI, bounded private queue, two sessions, real-request shadow hook, cohort seeder and source-bound deploy script. Focused tests and trust check pass; an 84.46-second generated recording completed through the pilot ledger and private result file. Development execution preceded corrected launchd activation at ec0f51a.

Activation and all 40 cohort admissions are verified. Natural Atlas comparisons are completing. Next: finish corpus observations, check the next natural Penny live admission, and evaluate accuracy, Atlas timestamps and sustained memory before changing primary ownership. Current canonical row 769 stays held. Production response remains Whisper while Apple is evaluated. No pilot text may be replayed or delivered. See `docs/apple-speech-pilot.md` for private status commands, bounds and rollback.

## Historical ASR research checkpoint — October 1, 2026

Research/testing complete in isolated `research/asr-options-20261001`, based on fetched `origin/main` `c1b0b1d`. Source and probes are pushed in draft PR #66: https://github.com/Khamel83/penny/pull/66 . Production checkout dirty files are preserved. Reports: `docs/research/2026-10-01-asr-local-benchmarks.md` and `docs/research/2026-10-01-asr-backend-primary-research.md`. Standalone probes: `scripts/research/`.

Actual M4 results support Apple as first challenger: real 93-minute memo 61 seconds; two synthetic hours 53 seconds concurrently. Phonon GPU real memo 93 seconds, peak 3.9 GiB with cache controls; Phonon CPU synthetic hour 78 seconds, peak 2.9 GiB. Both memo candidates still fail quality rules. This is research, not an approved/deployed replacement. Owner permits separate Penny/Atlas sessions if measured RAM supports them.

Full audio/text receipts stay local under `/Volumes/2TB_SSD/penny-asr-research-20261001`; `private/` is mode 0700, files 0600. Public models/environment were downloaded to the SSD, Apple assets installed through AssetInventory; production dependencies, launchd and canonical target row 769 were unchanged. No downstream output was created. No research jobs remain running at handoff. Total Apple model RAM and sustained separate-worker performance remain unproven.

Next specific gate: fixed human-checked local reference snippets and candidate omission/repetition review, then sustained Penny+Atlas sessions with total system peak-memory sampling. Recheck source with `git fetch origin`; compile/check probes with `xcrun swiftc -parse-as-library -O -framework Speech -framework AVFoundation scripts/research/apple_speech_probe.swift -o /path/to/private/apple-speech-probe` and `python3 -m compileall -q scripts/research`. Report contains bounded execution commands. Do not replay or publish row 769 from shadow output; it remains `needs_review`.

## Shared Whisper memory deployment — September 30, 2026

PR #62 merged and deployed `63591bed`; all five labels activated. Post-request footprint fell from 2.3 GiB to 1.7 GiB on identical generated speech with identical transcript hashes; four varying-length requests also retained 1.7 GiB. See `docs/research/2026-09-30-shared-whisper-live-memory-receipt.md`. Natural application completion and multi-day busy-workload stability remain unproven. Internal simulator deletion remains blocked by protected assets; 14.8 GiB is still present, with Recovery the next coordinated step. Only the external 8.9 GiB cache was removed. Existing dirty Mac files were restored byte-for-byte after deployment.

# Shared Whisper RAM checkpoint — September 30, 2026

Isolated branch starts at fetched origin/main `4fe4f54`. The existing Mac checkout and its dirty documentation remain preserved. Cache limit/cleanup source and regression are implemented; focused tests pass. Deployment and real memory reduction are pending. Next: exact-head PR checks, merge, installed-source deployment, serial local canary and process footprint measurement. Internal simulator deletion is blocked by macOS restricted assets despite administrator authentication; do not claim reclaimed internal space.

# Penny handoff

## Verified runtime alignment — September 30, 2026 UTC

The approved infrastructure health work deployed reviewed remote main
`ce48505f1f2e81a924443e5cf878e41dd761fb46` with
`venv/bin/python scripts/deploy_penny.py --apply`. Trust checks and verified
backup passed; all five installed launchd labels report that revision. The
follow-up deployment check reports current. Private deployment receipt/plist
backups are under `~/.penny/deployments/20260930T061905Z`. Existing dirty
LLM-OVERVIEW.md and untracked CLAUDE.md were privately copied and stashed
temporarily, then restored with identical SHA-256 hashes; the stash is retained.
At 06:20 UTC, `/ready` reported the deployed revision and overall degraded.
This closes runtime revision drift, not application degradation or downstream
delivery. Homelab is implementing bounded monitoring from existing OCI Doctor
receipts. Next: verify natural 09:00 UTC receipt and truthful monitoring of
degradation; keep private transcript quality and historical items separate.

## Current checkpoint — Voice Memo recovery and OCI health — September 29, 2026

PR #57 merged at `61f88908`; the Mac checkout fast-forwarded to that main
without changing its unrelated dirty `LLM-OVERVIEW.md` or untracked
`CLAUDE.md`. The watcher-only launchd reload reports revision `61f88908`
and a private receipt under `~/.penny/deployments/20260929T184354Z-watcher-only/`.
Source verification was 91 watcher/historical tests with 10 subtests, Ruff,
the hosted Python 3.11/3.12 checks, exact-head reviewer pass, and the
installed-source trust check (491 tests, two skipped).

Exact Voice Memo PK 440, about 93 minutes, had a terminal failure after a
whole-file shared-Whisper request and retries. A first local-only recovery
attempt used a shell without the installed Whisper token and failed with a
protocol error; the token mismatch was then confirmed from the installed
launchd environment. It did not create a transcript or downstream row. With
the installed watcher
environment, a second scoped local-only pass completed 19 private 300-second
checkpoints and linked transcript row 769. Fifteen chunks failed the
consecutive-token-repetition quality rule, so row 769 remains `needs_review`
with routing suppressed. The archive is published and valid with receipt
`64f18bc8`; a fresh installed backup includes max transcript ID 769 and 517
rows. No Drop, Slack, quality-alert or Maya delivery was queued for that row.
No audio or transcript text was printed or sent.

Mac Doctor now exits 1 `degraded`, with services, transcription, backup and
archive ready and zero current Voice Memo terminal failures. OCI's supervised
`penny-health.service` ended success/exit 0 with mode-0600 receipt
`20260929T185944.154146+0000-3527be8927474e7a90f06c7fb3c2ec58.json`,
also `degraded`. Historical absences, Apple quarantine and old Maya dead
letters remain visible; this is not an all-ready claim. The obsolete GitHub
`health-check.yml` was removed by PR #58, merged as `873f5be7` after exact-head
review and hosted Python 3.11/3.12 CI; merged-main CI also passed. Historical
queued Health Check run 36589491752 and AI Review run 36491923787 were
canceled. The Mac source checkout fast-forwarded to that merge without changing
its dirty `LLM-OVERVIEW.md` or untracked `CLAUDE.md`; the watcher process was
not reloaded for this workflow-only change. Next: verify the first natural OCI
timer after recovery and keep row 769 private for quality review. Resolve the
remaining historical Doctor degradation separately.

## OCI review and Mac Doctor checkpoint — 2026-09-29

This branch removes the legacy `AI Review` workflow that requested the
retired `oci-ts` runner. The separate OCI PR reviewer passed Penny PR #53 at
its exact head. The old issue-triage job has no replacement proof.

OCI's live `macmini` and `macmini-ts` SSH aliases now target the current Mac
MagicDNS name; the verified host key matched the Mac and both aliases logged
in. A direct OCI-to-Mac invocation of the workflow's read-only Doctor command
ran, but returned `overall=unready`, `source_revision=unknown`, services
`launchd_unavailable`, and Voice Memos `terminal_failure`. GitHub scheduled
run 36457387408 remains queued on `self-hosted, oci-dev` with no matching
public runner. Next: move the scheduled check to a safe OCI-owned path, fix
Doctor readiness separately, and prove a natural receipt.

## Production closeout — 2026-09-22

The current Voice Memo path is local capture -> SQLite -> local shared Whisper
-> durable Drop handoff -> independent Slack delivery and Maya store-only storage.
See [Drop operations](docs/drop-delivery.md) for ownership, historical import,
real-memo proof, and downstream recovery. Legacy routing below applies to other
inputs and pre-cutover rows, not new Drop-owned Voice Memos.

Capture-health implementation `b9c3158802beafb174a2807b8515ac0f096759cd`
was pushed and verified in all five launchd services. The full suite at that
release passed 678 tests and 53 subtests, with two skipped. Documentation-only
closeout commits may follow; compare remote main and installed revisions with
`venv/bin/python scripts/deploy_penny.py` before making a fresh runtime claim.

At 2026-09-22T17:15:49Z, watcher, transcription, SQLite, archive, backup and Drop
were ready, with zero current terminal capture failures, zero source coverage
gap and zero pending/failed/uncertain Drop deliveries. Overall readiness was
degraded: two historical capture failures, one Apple quarantine and nine legacy
direct-Maya dead letters remain preserved. These are not new Drop delivery failures.
See [capture health](docs/capture-health.md); retain the fixed reporting boundary.

The available historical-text import and real-memo delivery gate are complete.
Missing audio, excluded placeholders and non-passed quality labels are not
recovered merely by indexing or importing them. Optional test permutations remain
listed in [release decisions](docs/drop-release-decisions.md), not as blockers to
normal capture. No new feature work or replay is required for this closeout.

Private evidence remains local in `~/.penny/capture-health-release-2026-09-22.json`
and `~/.penny/real-memo-762-verification-2026-09-22.json`. Recheck live health for
future incidents; this is a dated result, not a guarantee against future outages.

## Current Mac backup placement — 2026-09-22

[SSD backup placement](docs/ssd-backup-placement.md) records the owner-approved migration, installed mount-identity guard, matching export/webhook environment, fresh restore/remote proof, and retired internal staging. Preserve that placement in future plist rendering. The ledger and live audio were not moved; overall readiness remains separate from the passing backup checks.


## Historical synchronized shared-Whisper cutover — 2026-09-17

The following records that cutover's observations; its revision, test counts,
queue counts and readiness do not describe the current release above.

This is the Penny side of the Atlas handover plan:
`/Volumes/2TB_SSD/GitHub/atlas/.worktrees/minuspod-reliability-fix/docs/superpowers/plans/2026-09-17-shared-whisper-cutover-handover.md`.

- Source checkout: local `main`.
- Application source SHA: `f6e531d7919d19e61b7a65d73f5073e39a23e4e3`.
- Synchronized documentation commit: `d7d9a0d2c0818832b4ad193bcf8b953f1cffc1c3`.
- Source implementation: `shared_whisper/{protocol,client,server,supervisor,worker}.py`;
  `transcript_quality.py` calls the shared client and no longer owns MLX.
- Focused shared-Whisper verification: `16 passed`; Ruff and compileall passed.
  The full Penny suite is `602 passed, 2 skipped, 1 failed`; the remaining
  failure is the unrelated malformed RFC3339 timestamp contract test.
- Runtime completed: plist render/backup, old-owner removal,
  `com.penny.shared-whisper` bootstrap, authenticated MagicDNS verification,
  one-worker/memory checks, and Homelab shared-client deployment.
- Current live owner is `com.penny.shared-whisper` on 10311. The tiny Wyoming
  service remains on 10300/10301 and is outside this change.
- The tracked non-private canary returned HTTP 200 with nonempty validated
  metadata, one segment, and the pinned model identity; transcript text was not
  retained. It left one idle worker within the configured TTL and no second
  large owner.
- One post-cutover Atlas episode completed durably at
  `2026-09-18T03:52:05Z` after six chunks in each transcription pass. The
  post-cutover receipt has zero `Whisper API unreachable` rows and zero generic
  `Failed to transcribe audio` rows. The queue then continued naturally;
-  current queue state at the last read was 55 completed, 22 pending, and 1
  processing, with 2 historical terminal failures. The episode active during
  the Penny restart completed durably; it was not published with a missing
  Whisper chunk and has 2 review markers.
- Shared-Whisper word timestamps are now disabled by default; an explicit
  request still enables them. After restart the live Penny health response was
  authenticated and idle with `worker_count=1`, `worker_pid` present, and the
  supervisor's physical footprint was 33.3M with no loaded model workers.
- Atlas commit `91ce1f08` makes shared-mode chunk transcription fail closed
  (`max_failed_chunks=0`) and fixes the shared-worker assignment so it cannot
  be overwritten by the stock pool assignment. Homelab image `2.96.24` is
  deployed and the container source was checked for the exact patch.
- Read-only Penny Doctor at 2026-09-18T03:57:15Z reports the shared-Whisper
  component `ready` with `service_ok=true`, `model_verified=true`,
  `old_large_owner_present=false`, `legacy_tiny_present=true`,
  `memory_pressure_ok=true`, and zero loaded workers after the final idle-only
  restart. Overall Doctor remains `unready`
  for independent pre-existing reasons: one Voice Memos terminal failure,
  shell transcription offline mode not set, watcher freshness, one Apple
  quarantine, and Maya dead letters. Those are not attributed to this
  cutover.
- No token, audio, transcript, model file, or private content belongs in this
  handoff. The synchronized Atlas receipt is
  `thoughts/shared/receipts/2026-09-18-shared-whisper-live-cutover.md`.
  Runtime status must be re-read before each claim.

The shared service is designed to keep one killable `large-v3-turbo` worker,
use a literal 30-second Atlas grace window, discard partial Atlas output, and
allow Penny to retry through its existing quality path. Source/test evidence
does not imply launchd registration, live authentication, durable completion,
or downstream delivery.

This is the assistant-facing operating contract for Penny Phase A. It describes
the repository contract, not a claim that a particular Mac is currently
deployed. Confirm the exact source revision and runtime state before reporting
readiness.

## System shape

The legacy durable path (other inputs and pre-cutover captures) is:

```text
Apple capture -> local staging -> SQLite receipt -> offline MLX -> local routing
             -> Maya reasoning/policy -> Hermes -> provider receipts
```

Voice Memos is the Phase A compatibility source. Its private database is read
only and unsupported as a storage API; a manual Share/Finder export remains the
fallback. JPR is a Phase B pilot and must not be treated as active until its
capture matrix passes.

Penny's local SQLite database is canonical. Audio-bearing rows may have
immutable local archive objects and a same-basename `.md` transcript plus `.json`
manifest. Text-only, Maya, and Tasks rows may instead be `not_applicable` with
`no_raw_audio`. The iCloud Drive `Penny Archive` folder mirrors complete trios
only. A versioned homelab backup is independent of iCloud and is verified in a
scratch directory.
Apple Notes and Reminders are projections with durable effect keys and
read-after-write receipts.

The routing boundaries are deliberately separate: **local routing** is the
fallback and user-facing Apple projection; **independent Slack** delivery is a
durable outbox; **independent Maya v2** delivery is a separately acknowledged
outbox with bounded retries and `dead_letter` state. A receipt in one boundary is
not evidence of success in another.

## Doctor contract

`venv/bin/python scripts/penny_doctor.py` is the readiness entry point. It probes
SQLite integrity/foreign keys/schema, discovery cursor and retry state, archive
metadata, offline model verification, Apple-effect receipts, Slack/Maya
outboxes, backup verification receipt, launchd/health freshness, and ingress
configuration. It never reads transcript or audio bodies, contacts a provider,
reads TCC databases, repairs state, or prints raw paths, URLs, secrets, errors,
or process identifiers.

- exit `0`: all required components ready
- exit `1`: degraded (including an explicitly disabled optional Maya route)
- exit `2`: unready or unknown required state
- `/health`: liveness only, `200`
- `/ready`: `200` for ready/degraded, `503` for unready

The source revision is meaningful only when it is bound to the checked-out or
deployed runtime revision. A template, generated status line, or process presence is
not deployment proof.

## Durable state and retry rules

An ingest is acknowledged only after a typed persistence result is `inserted` or
`duplicate`. Voice Memos discovery advances the SQLite
`source_watermarks.last_discovered_id` cursor only after a durable
`voice_memo_ingest` upsert. Processing failures remain in that table with
retryable/backoff state or `failed_terminal`; there is no separate completion
watermark. Incomplete or changing audio remains `awaiting_file`/retryable until
the source is fully materialized; a terminal source row remains `failed_terminal`.
Retryable work uses bounded exponential backoff. Archive publication failures
remain pending through bounded retries and then become visibly `failed`;
published-mirror conflicts use recoverable conflict quarantine. Terminal or
conflicting Apple-effect failures use quarantine, ordinary failures remain
`failed`, and ambiguous timeouts remain `uncertain`. Maya terminal delivery
uses `dead_letter`.

Apple effects persist a deterministic key before attempting the side effect and
record provider identifiers plus a read-back receipt. An ambiguous timeout is
reconciled before another attempt. Slack and Maya delivery state is monotonic;
late failures cannot reopen a sent row.

## Operator evidence

For one capture, collect metadata in this order:

1. canonical SQLite row and source receipt;
2. archive trio and manifest/hash status;
3. local Notes/Reminders receipt, if applicable;
4. independent Slack outbox acknowledgement;
5. independent Maya v2 acknowledgement or bounded failure;
6. most recent verified backup set and catalog binding.

Use the launchd-owned `watcher.system.log` only as diagnostic context. Log text,
process presence, and a successful HTTP request do not replace a durable receipt.
Do not tail logs as a health check and do not paste transcript content into an
incident report.

## Safe recovery posture

Recovery is additive and evidence-preserving:

- run Doctor and inspect bounded reason codes;
- preserve staged objects, SQLite rows, outboxes, receipts, and dead letters;
- repair configuration or permissions through the normal macOS/operator path;
- use a verified backup only in a scratch restore first;
- stop writers before a planned restore, then re-run read-only integrity,
  archive, and backup checks before resuming;
- disable a failed new adapter and return to the known-good Voice Memos + MLX
  path while preserving all evidence.

Never delete or replace Apple's Voice Memos database, Penny's SQLite database,
archive objects, outboxes, or backup sets as a troubleshooting shortcut. Never
replay, send, share, purchase, deploy, or change credentials from a health check.

## Transitional gaps

Tracked/runtime webhook templates must converge to loopback or an explicitly
protected non-loopback bind; Doctor treats an unprotected bind as unready.
The callback uses `PENNY_WEBHOOK_SECRET`; Hermes uses the dedicated
`PENNY_HERMES_WEBHOOK_SECRET`. Selected provider/task/webhook logs use bounded
fields and redacted exception classes; this does not retroactively clean every
historical log artifact.

## Future gates

Phase B requires JPR installation and permission approval, at least 20 synthetic
captures, five physical Watch canaries, zero loss/duplicates, and complete
source-to-receipt traces. Maya must replace the transitional direct OpenRouter
classification path before that dependency is removed. macOS 27, Apple Speech,
EventKit, and MacWhisper remain shadow/challenger work until their separate gates
pass.

## Canonical references

- [README](README.md)
- [Reliability](docs/reliability.md)
- [Mac mini deployment](docs/macmini-deployment.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Approved design](docs/superpowers/specs/2026-08-09-penny-august-2026-design.md)
- [Phase A plan](docs/superpowers/plans/2026-08-09-penny-phase-a-hardening.md)
