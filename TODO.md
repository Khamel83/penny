## Portable Apple app skills — October 2

- [x] Generalize Apple workflows across projects: separate Notes/Reminders skills,
  shared Mac access and receipt contract, scoped failure recovery, and Penny-only
  adapter reference. AGENTS.md routes tasks to these skills.
- [x] Validate and install all four skills; source/install hashes agree, relative
  references resolve, eight probe regressions pass. Fresh installed Notes and
  Reminders access passes. Private receipts:20261002-apple-skills.
  Source: [Penny PR91](https://github.com/Khamel83/penny/pull/91).
- [ ] Observe a first requested operation from another project's actual caller;
  verify that project's exact target, item fields and durable receipt. Generic
  skills do not imply new unattended adapter/write acceptance.

## Reminders recovery acceptance — October 2

- [x] Distinguish metadata response from blocked list access, inspect GUI/privacy
  gate, verify current Reminders-data grants, then prove recovered shell/launchd
  access and one existing item receipt. No data/security/runtime mutations.
- [x] Update installed/versioned skill with separate Reminders-data permission
  and native GUI/tool identity checks; no probe-code change.
- [ ] New natural Penny capture/write/archive/downstream receipt acceptance and
  separate capped-Note repair remain open. Finder window timeout is independent.

## Reusable Apple delivery procedure — October 2

- [x] Create, validate and install apple-effects-reliability skill with bounded
  read-only provider probe, privacy/error/receipt regressions (8 passed), and
  exact caller/target/durable receipt gates before any authorized retry.
- [x] Reminders recovery verified: shell and equivalent-launchd list access pass;
  one existing marker/ID/target matches its saved receipt. See docs/reminders-recovery-20261002.md.

## Apple Events SIP recovery correction — October 2

- [x] Withdraw protected-service kickstart instruction: authenticated attempt
  returns error150 under enabled SIP; basic Notes/local script probes pass,
  Finder/Reminders timeout. No security settings or effect state changed.
- [x] Exact Notes marker lookup passes in shell and equivalent launchd context;
  both outstanding effects return zero matches. Temporary diagnostic job removed.
- [ ] Prepare receipt-backed capped-effect repair; retain synthetic quarantine.
  A coordinated restart is only a candidate for still-stuck other provider calls.
  Evidence: docs/workflow-recovery-20261001.md; private20261002-sip-recovery receipts.

## ASR hardening activation closeout — October 2, 05:24 UTC

- [x] Deploy and verify Penny `c341598c`, legacy `0d75` and native `74f4cada`;
  original admission restored, three user timers active, generated hashes and
  cleanup marker verified. Final Homelab receipt: `asr-hardening-final-acceptance-20261002.json`.
- [x] Exact-head Atlas PR176 hosted syntax/tests passed in run `36966127524`;
  source review and local nonlive checks passed separately.
- [ ] Apple effect receipt-backed repair; protected restart instruction withdrawn.
- [ ] Observe a new natural Penny capture's actual model, ledger, archive and
  downstream receipt; synthetic canary does not prove this boundary.

Older unfinished deployment/CI checkpoints below are historical and superseded
by this closeout. Other provider, storage and publication tasks retain their scope.

## Historical: ASR hardening runtime checkpoint — October 2

- [x] Deploy Penny `c341598c` on five agents; verify saved-response agreement and public serial Parakeet/Whisper canary. Install legacy signature holds, restore scheduling and pass the component verifier. Evidence: docs/asr-hardening-20261002.md.
- [ ] Verify native activation receipt and queued Atlas hosted test. Administrator Apple Events recovery/reconciliation and new natural capture/archive/delivery acceptance remain separate open items.

## Historical: ASR timing hardening — October 2 source work

- [x] Reproduce saved malformed Whisper timing with synthetic text; strict producer/client validation and numeric Parakeet failure locality implemented.
- [x] Quality review becomes a held capture result; transient service failures remain retryable. Full suite:749 passed,2 skipped,53 subtests before the final added regressions.
- [ ] Review/CI/merge/deploy exact final head and verify saved-response agreement, runtime identity and legacy hold skip.

## Shared runtime diagnostic — October 2, 2026

- [x] Diagnose installed Penny/ASR/Atlas boundaries from existing metadata and receipts; fifty focused checks pass. Report:docs/runtime-diagnostic-20261002.md. No new inference/private replay or live change.
- [ ] Repair producer/consumer timing-contract disagreement proved by the same saved Whisper response; establish reviewed small-alignment policy without discarding or reordering text.
- [ ] Hold repeated long Parakeet quality failures durably and capture numeric failure locality for bounded excerpt retries. One105-minute input repeated ten times; review receipts alone did not halt admission.
- [ ] Verify a new ordinary post-cutover Penny capture's actual model, ledger/archive and downstream receipts; health and public canaries do not prove this.

## Native startup follow-up — October 2, 2026

- [x] Merge all originally open Penny research PRs (66,72,73,74), configuration PR85 and recovery documentation PR84 with passing checks; original conflict backlog is closed.
- [x] Verify Atlas native publication from its original ASR checkpoint; retain the independent private publication receipt.
- [x] Restore the previous healthy MinusPod image, original admission=false and user watchdog/readiness/drain timers after the candidate startup deadline; zero active/processing jobs at restoration and other SQL settings unchanged; normal scheduler later admitted a new job.
- [ ] Activate Atlas PR170 preventive local-slot deferral image after diagnosing stock cold-database startup; candidate failed its1020-second startup bound and was rolled back. Source merge is not runtime activation.
- [x] Identify stock startup bottlenecks from existing private timing logs: search-index counts197.0/240.9 seconds and legacy marker cleanup370.4 seconds. No SQL/transcript content transferred.
- [ ] Review safe gating/optimization of those measured existing-database scans, then repeat bounded rollback-capable activation.

## PR and workflow recovery — October 2, 2026

- [x] Reconcile and merge PR66,72,73,74 with fresh Python3.11/3.12 CI and final-head Standards/Spec reviews. Merge receipts:9331227,aa8d70d,c269ab3,f492c33; the four original open PRs are closed.
- [x] Enforce private permissions before research artifact writes, including pre-existing0644 files and reused atomic temp files; regressions verify write-failure privacy. No extra recognition/private replay.
- [x] Verify native postprocess completion/publication:02:02:52 complete_job, original ASR receipt retained, current RSS enclosure HTTP200/hash matches canonical24,686,598-byte output. Private Atlas publication receipt owns proof.
- [ ] Finish already reviewed Atlas PR170 image deployment/startup acceptance and restore original admission; source5086c022 merged with passing CI, native cold startup in progress.
- [ ] Recheck exact Apple Notes provider receipt after owner-authenticated Apple Events restart, then determine bounded retry; preserve capped and quarantined history.

## Maya core caller cutover — October 2, 2026 02:02 UTC

- [x] Repoint installed watcher, webhook and tasks `MAYA_TRANSCRIPT_URL` to
  `https://maya.khamel.com/ingest/transcript` and verify each loaded job uses it.
  Existing ingest tokens match the Homelab core. Runtime source remains
  `ca6322b697a4bcea8de52849d975d7543a994970`; no credential or grant changed.
  Private before-images, backup and receipts remain under
  `~/.local/state/maya-penny-core-route-20261002/`. Configuration receipt SHA256
  `f4871aaeb93e7535267c17cd4dbfadbd873c71915a1cc5d447e1ff2dde222951`.
- [ ] Verify the next ordinary direct Maya delivery with a durable v2 receipt
  and independent core readback. There was no pending direct delivery during
  the cutover; nine dead letters, 481 ineligible and 29 sent rows stayed equal.
  Preserve the separately verified store-only receipts; do not resend dead
  letters to create acceptance evidence. Voice Memo Drop routing stays active.

Only those three callers were reloaded, with no active delivery/effect claims.
The shared transcription service PID and export job stayed equal. Doctor
remains unready for the previously recorded Apple provider failure; configuration
readback does not prove a fresh Maya receipt or Apple recovery.

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

- [x] Deploy reviewed ca6322b and recover the real33-minute queued import; one-owner1.5G/2.0G peak verified.
- [x] Restore Atlas final readiness200 and prove natural postprocess checkpoint reuse/forward progress.
- [ ] Verify full native feed publication after that resumed job (Atlas-owned).
- [ ] Owner authenticates Apple Events service restart; agent then reconciles exact capped effect. Keep synthetic quarantine untouched.

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

- [x] Build/test private long-quality review preservation; full 715 passed, 2 skipped, 53 subtests; 17 focused adapter cases and trust check pass.
- [ ] Deploy reviewed source after ASR producer quiescence; inspect one deferred request and complete bounded recovery.

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

- [x] Verify nine historical Maya items in current store-only storage; no resend needed.
- [x] Inspect two historical audio failures in actual runtime context; neither has decodable audio.
- [ ] Restore responsive Apple Events automation, then reconcile exact capped Notes effect before any bounded retry.
- [ ] Finish Atlas typed-deferral deployment and resolve actual code; verify fresh final readiness.

## Shared Parakeet live activation — October 1, 2026

Penny runtime is deployed at `f4909d33d0a15db660c9eec35a02318aab297ca2` (merged PRs 75–77). Five launch agents carry that revision; watcher/webhook are resumed. Authenticated production Parakeet input passed Penny and Atlas/MinusPod identity/timestamp validation. Apple pilot remains disabled. The ten-minute public staging input took 14.984 seconds including cold load (1.4 GB physical footprint, 1.9 GB peak); bounded five-minute Whisper fallback took 45.509 seconds (1.8 GB, 2.4 GB peak), followed by successful Parakeet return and idle unload. The installed excerpt command separately verified original-audio timestamp offsets. No simultaneous model owners were observed.

Durable private receipts: `~/.penny/deployments/20261001T234710Z/receipt.json` and `/Volumes/2TB_SSD/penny-asr-runtime/cutover-20261001/{cutover-receipt,stage-canary-receipt,live-canary-receipt}.json`. Protected owner files remain intact; the preservation stash is retained. Source review, CI and deployment trust check passed. This is service activation evidence; no new natural Penny canonical capture/archive/downstream delivery has yet been observed. Existing held recordings were not released or replayed. Next: read a new normal capture's actual model, ledger, archive and delivery receipt separately; observe sustained workloads. Atlas/MinusPod controlled cutover receipt is tracked separately. The checked-in primary selector and all five agents now select Parakeet; CLI/Doctor agree with the installed runtime.

- [x] Reviewed/merged implementation and loader correction; live Penny adapter and serial fallback canaries passed.
- [ ] Verify next natural Penny ledger/archive and independently observe downstream effect; monitor sustained memory.


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

- [x] Complete ten full public podcast/reference pairs and publish measured resource/content evidence in [PR #74](https://github.com/Khamel83/penny/pull/74).
- [ ] Integrate the selected shared adapter and verify Penny/Atlas canaries, timing compatibility and rollback before primary adoption (#70).

## Apple pilot paused by owner — October 1, 2026

All 32 held Penny recordings completed (43.2 hours), plus seven historical Atlas and ten natural Atlas inputs. Owner stopped further recognition. Sidecar is unloaded, autostart plist retained with .paused suffix, live capture disabled and normal five-label runtime verified at ec0f51a. All canonical Penny baseline text/status pairs remain unchanged. Binary repetition flags are not accuracy measurements: Apple repeated-run token share was 0.285% versus Whisper 0.725%, and severe runs were fewer. No first-party or independent reference comparison has been performed. Next is evaluation of existing outputs against references and flagged context, not more transcription; issue #70 owns the conditional primary gate. See docs/apple-pilot-live-receipt-20261001.md.

Apple launchd correction resolved (October 1): PR #69 binds diskutil to /usr/sbin. Corrected source ec0f51a activated all six labels, fresh pilot health and optional live capture. All 40 historical cohort inputs were admitted without errors, and natural Atlas requests have produced private Apple/Whisper comparison receipts. The first activation failure did not affect canonical Whisper. See docs/apple-pilot-live-receipt-20261001.md for acceptance facts.

Apple pilot review fixes (October 1): live snapshot disk work now runs in at most two daemon admission threads; overflow is refused without waiting. Only committed queue rows prove durability. Subprocess launch/register is synchronized with shutdown, including signal re-entry. Regression tests cover stalled storage and shutdown races. Corrected activation and real cohort admission are verified; recognition-quality acceptance remains open.

## Apple workflow pilot — October 1, 2026

- [x] Inventory actual work: 32 quality-held Penny recordings with local audio; Atlas live queue two pending/two processing; 264 retained Atlas files are a historical corpus, not live backlog.
- [x] Implement opt-in real-request shadow capture, private bounded queue, two Apple sessions, native modern API, deadlines and source-bound deployment. Focused tests and trust check pass; real generated-audio pilot receipt completed locally.
- [x] Review and merge PR #68 plus launchd correction #69; deploy ec0f51a to all six labels, admit all 32 held Penny plus eight historical Atlas recordings, and verify fresh health and natural Atlas shadow completion. No canonical replacement or candidate delivery. See docs/apple-pilot-live-receipt-20261001.md.
- [x] Run bounded official-reference check with three public Lex clips; evidence and limits are in docs/research/2026-10-01-apple-reference-results.md.
- [ ] Adjudicate consequential reference disagreements / verify broader domain and total resource gate before conditional primary ownership (#70). Bulk recognition remains paused.
- [ ] Validate representative transcript quality, Atlas timing semantics and sustained total system memory before primary Apple ownership. See `docs/apple-speech-pilot.md`.

## Historical ASR replacement research — October 1, 2026

- [x] Compare primary Apple/Phonon sources and execute isolated local M4 probes: synthetic hour, two simultaneous Apple hours, four Apple short sessions, Phonon CPU/GPU/cache controls, and private 93-minute memo. See `docs/research/2026-10-01-asr-local-benchmarks.md`.
- [x] Preserve production, canonical row 769 and existing dirty checkout; no candidate output routed or delivered.
- [ ] Before any replacement: fixed human-reference quality set, sustained independent Penny/Atlas sessions, total system peak RAM and integration/rollback acceptance. Both candidates still fail repetition checks on the difficult memo. Research completion is not backend acceptance.

## Shared Whisper memory acceptance — September 30, 2026

- [x] Identify Penny ownership and implement unchanged-model cache retention fix with regression coverage.
- [x] Merge PR #62 and deploy `63591bed`; authenticated generated-speech canaries show stable 1.7 GiB post-request footprint and identical short-canary text hashes.
- [ ] Observe a natural Atlas/Penny completion and sustained busy-workload memory; no multi-day stability claim yet.
- [ ] Complete approved simulator deletion through Apple management path; protected internal assets remain.

## Current Voice Memo recovery — September 29, 2026

- [x] Merge and deploy the long live memo chunk path. PR #57 merged at `61f88908`; the installed Mac watcher reports that exact revision. Focused and hosted tests passed.
- [x] Recover exact failed Voice Memo PK 440 locally. Transcript row 769 is linked, routing suppressed, archived and included in a verified backup; there are zero Drop, Slack, quality-alert, or Maya delivery rows for it. Mac Doctor is `degraded`, with no current terminal source failure; supervised OCI Doctor receipt is also `degraded` and its service succeeds.
- [ ] Keep transcript row 769 in private `needs_review`: 15 of 19 chunks triggered consecutive-token repetition. Do not send it downstream on source recovery alone. Verify the next natural OCI health timer after this recovery.
- [x] Retire the queued public-repository `oci-dev` GitHub health workflow. PR #58 merged as `873f5be7` after hosted Python 3.11/3.12 CI and exact-head review; the merged-main CI passed. Historical queued Health Check run 36589491752 and AI Review run 36491923787 were canceled. The separate next natural OCI timer and Doctor readiness gates remain open above.

## Active synchronized task: Atlas/MinusPod shared-Whisper cutover

This Penny queue is synchronized with the Atlas execution authority at
`/Volumes/2TB_SSD/GitHub/atlas/.worktrees/minuspod-reliability-fix/docs/superpowers/plans/2026-09-17-shared-whisper-cutover-handover.md`.
The user authorized the live cutover. The Penny source is locally integrated
on `main` at `f6e531d7919d19e61b7a65d73f5073e39a23e4e3`.

- [x] Shared protocol, authenticated server, one-worker supervisor, worker
  isolation, Penny client, launchd template, and Doctor probe implemented.
- [x] Focused shared-Whisper suite after the timestamp change: `16 passed`,
  Ruff clean, and `python3 -m compileall -q shared_whisper` passed.
- [ ] Penny full suite is not fully green: `602 passed, 2 skipped, 1 failed`.
  The remaining failure is the pre-existing malformed RFC3339 timestamp
  contract test (`TranscriptContractTests.test_checked_maya_schema_uses_full_json_schema_and_format_validation`).
- [x] Merge the validated source into local Penny `main` without pushing.
- [x] Render and back up the `com.penny.shared-whisper` plist with the
  internal token supplied only through the local runtime configuration.
- [x] Capture source/runtime/process/memory evidence, replace the old
  `com.atlas.minuspod-whisper` owner on port 10311, and preserve rollback.
- [x] Verify authenticated MagicDNS health, one worker at most, pinned model
  identity, SSD temp state, and unchanged `com.wyoming.whisper`.
- [x] Disable shared-Whisper word timestamps by default; explicit
  `word_timestamps=true` remains supported. Live idle memory after restart:
  33.3M physical footprint with zero loaded model workers.
- [x] Keep Penny's quality retry path and Atlas's whole-chunk retry path
  separate from process liveness; record durable and downstream receipts in
  the synchronized Atlas cutover receipt.
- [x] Observe one current MinusPod episode through durable finalization: one
  post-cutover processing-history row completed at `2026-09-18T03:52:05Z`,
  with zero post-cutover Whisper-unreachable or generic worker-error rows.
- [x] Run the tracked non-private Penny canary against the local shared owner;
  it returned HTTP 200 with nonempty validated metadata and the pinned model.
- [ ] Continue observing the remaining repaired backlog; the live queue at
  2026-09-18T19:31 PDT was 55 completed, 22 pending, and 1 processing. The
  episode interrupted during restart completed durably with 2 review markers.
- [x] Atlas overlay `91ce1f08` makes shared-Whisper chunk failures fail closed
  instead of returning a partial transcript; Homelab image `2.96.24` is
  built and deployed, with the patched source verified in the container.
- [x] Keep rollback artifacts ready and synchronize this TODO/HANDOFF with
  Atlas after this bounded task. A live Penny-preemption contention receipt
  remains explicitly unexercised because no real Penny capture arrived.
- [ ] Exercise rollback in a disposable or separately approved maintenance
  window; do not disturb the healthy production owner solely to create proof.

The stale Phase A items below are historical generated signals. They do not
override this active shared-Whisper cutover queue.

<!-- janitor:begin:todo -->
## Portable Apple app skills — October 2

- [x] Generalize Notes and Reminders workflows across projects, with shared access and receipt contracts and a Penny-specific adapter reference. Source: [Penny PR91](https://github.com/Khamel83/penny/pull/91) at `b8a29e40a0482ec708afa880ee60d53707c91de6`.
- [x] Validate and install all four skills; source/install hashes agree, references resolve, eight probe regressions pass, and fresh installed Notes/Reminders probes pass. Private receipts: `~/.penny/recovery/20261002-apple-skills/`.
- [ ] Observe a first requested operation from another project's actual caller and verify that project's exact target, item fields, authorization, and durable receipt.

## Apple recovery and repair — October 2

- [x] Verify Reminders shell/launchd list access and reconcile one existing marker/provider ID/target with its canonical succeeded receipt. Evidence: `docs/reminders-recovery-20261002.md`.
- [x] Install the evidence-backed delivery procedure and withdraw the protected-service kickstart instruction after error 150 under enabled SIP. Keep SIP/TCC unchanged.
- [ ] Observe a new natural Penny capture/write/archive/downstream receipt; probes and synthetic acceptance do not prove this boundary.
- [ ] Prepare a separate receipt-backed capped-Note repair decision. Preserve the synthetic quarantine and failed receipt; do not replay, reset the cap, or mark delivery successful from marker absence.
- [ ] Track Finder window-count timeout independently; no Calendar, Mail, or Messages adapter is accepted.

## ASR hardening closeout — October 2, 05:24 UTC

- [x] Deploy and verify Penny `c341598c`, legacy `0d75`, and native `74f4cada`; restore original admission, activate timers, and verify hashes/cleanup. Receipt: `asr-hardening-final-acceptance-20261002.json`.
- [x] Pass Atlas PR176 exact-head hosted syntax/tests, review, and local nonlive checks. Source closeout: `0d2c8196251275c332b3038ce6fb777ee6495173`.
- [ ] Observe a new natural Penny capture's actual model, ledger, archive, and downstream receipt independently.

## Historical recovery checkpoints

Older unfinished deployment/CI checkpoints are superseded by the ASR closeout above. Other provider, storage, publication, and runtime-acceptance tasks remain separate; source merges or canaries do not resolve them.
<!-- janitor:end:todo -->
## OCI GitHub worker path — 2026-09-29

- [ ] Retire the queued legacy `oci-ts` AI Review workflow after exact-head
  review. The separate OCI reviewer handled Penny PR #53; the old lane is
  retired. Its issue-triage job has no replacement receipt here.
- [ ] Move the scheduled Mac Doctor check off its unmatched public-repository
  `oci-dev` runner label. OCI's SSH alias now reaches the Mac with a verified
  host key, but GitHub run 36457387408 remains queued. A direct OCI-to-Mac
  Doctor run returned `unready` (`launchd_unavailable`, Voice Memos
  `terminal_failure`); restore the Doctor path and prove a natural schedule
  before calling it healthy.
- [x] Align native runtime with reviewed main `ce48505f`: controlled deployment,
  verified backup, five loaded revisions and follow-up current check passed
  September 30. `/ready` reports the same revision and remains degraded.
- [ ] Verify Homelab's corrected Penny monitoring observes real Doctor/readiness
  degradation and the next natural OCI Doctor receipt; source alignment alone
  does not close health or downstream delivery acceptance.
