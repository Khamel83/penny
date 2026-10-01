Apple pilot review fixes (October 1): live snapshot disk work now runs in at most two daemon admission threads; overflow is refused without waiting. Only committed queue rows prove durability. Subprocess launch/register is synchronized with shutdown, including signal re-entry. Regression tests cover stalled storage and shutdown races. Deployment remains pending.

## Approved Apple pilot — October 1, 2026

The owner approved Apple as the first workflow pilot after local benchmark research. Sharing Penny and Atlas was only a RAM workaround; separate Apple sessions are valid if total memory and quality acceptance support them. The first deployed step will be a shadow pilot on real requests plus a bounded local cohort. Canonical response and all delivery ownership remain the existing Whisper path during this comparison.

Verified inventory: 32 held Penny recordings have local audio, with no ordinary waiting Penny queue. Atlas's live auto-process queue has two pending and two processing episodes; its large discovered catalog is not queued transcription work. Retained Mac Atlas audio is a separate 264-file historical corpus. The initial pilot cohort selects all 32 held Penny recordings and eight recent retained Atlas MP3s without modifying either application queue.

Implementation/test evidence precedes deployment. `docs/apple-speech-pilot.md` owns the workflow/acceptance contract; `INFRA.md` records proposed placement. Candidate quality-rule passes do not establish word accuracy or permission to release held rows.

## Shared Whisper memory deployment — September 30, 2026

PR #62 merged and deployed `63591bed`; all five labels activated. Post-request footprint fell from 2.3 GiB to 1.7 GiB on identical generated speech with identical transcript hashes; four varying-length requests also retained 1.7 GiB. See `docs/research/2026-09-30-shared-whisper-live-memory-receipt.md`. Natural application completion and multi-day busy-workload stability remain unproven. Internal simulator deletion remains blocked by protected assets; 14.8 GiB is still present, with Recovery the next coordinated step. Only the external 8.9 GiB cache was removed. Existing dirty Mac files were restored byte-for-byte after deployment.

# Shared Whisper memory work — September 30, 2026

Penny owns the shared MLX worker; Atlas calls its API. The owner authorized a memory fix, PR and live verification while retaining transcription quality. The first change bounds free GPU cache to 100 MiB and clears it after each request with the same pinned FP16 turbo model. See `docs/research/2026-09-30-shared-whisper-memory.md`. Source tests do not establish runtime memory reduction.

Long live Voice Memos use the local shared-Whisper owner with Penny priority
and private audio-hash-bound chunk checkpoints. Historical backfill uses its
separate backfill priority and existing checkpoint location. Chunk completion
does not prove a canonical ledger link, archive, backup or downstream effect.

OCI owns the scheduled, read-only Mac Doctor observation through its native
`penny-health.timer` and private receipt. A public Penny GitHub Actions worker
is not an authorized health-check execution path. Doctor `degraded` remains a
valid observed capability state; it does not authorize delivery of a
`needs_review` transcript.

<!-- janitor:begin:branches -->
## Branch and Worktree Review
Base: refs/remotes/origin/main @ c3d517c2fee291c2e066e69ece2fb5ac55894de7
Freshness: current

| Branch | Class | Sources | Merged | Ahead/behind | Worktree | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| auto-wip/20260912-210900 | abandoned_auto_wip | local | yes | +0/-6 | unattached | subject: fix: scope Voice Memos daemon health to user |
| auto-wip/20260912-210902 | abandoned_auto_wip | local | no | +3/-15 | unattached | subject: fix: narrowly allow natural no emphasis; paths: scripts/re_evaluate_quality_review.py, tests/test_quality_review.py, tests/test_transcript_quality.py, transcript_log.py, transcript_quality.py |
| auto-wip/20260913-100449 | abandoned_auto_wip | local | no | +3/-15 | unattached | subject: fix: narrowly allow natural no emphasis; paths: scripts/re_evaluate_quality_review.py, tests/test_quality_review.py, tests/test_transcript_quality.py, transcript_log.py, transcript_quality.py |
| auto-wip/20260914-100603 | abandoned_auto_wip | local | no | +3/-15 | unattached | subject: fix: narrowly allow natural no emphasis; paths: scripts/re_evaluate_quality_review.py, tests/test_quality_review.py, tests/test_transcript_quality.py, transcript_log.py, transcript_quality.py |
| codex/penny-quality-fix-20260811 | active | local | no | +3/-15 | dirty | subject: fix: narrowly allow natural no emphasis; paths: scripts/re_evaluate_quality_review.py, tests/test_quality_review.py, tests/test_transcript_quality.py, transcript_log.py, transcript_quality.py |
| codex/penny-apple-actions | active | local, origin/codex/penny-apple-actions | no | +1/-80 | dirty | subject: feat: add structured Apple action routes and a completion reader; paths: reminders.py, tests/test_reminders.py, tests/test_webhook.py, webhook/server.py |
| codex/foundational-agent-tooling-2026-08-26 | aging | local | no | +1/-3 | unattached | subject: docs: standardize foundational agent tooling; paths: AGENTS.md |
| codex/agy-cli-operational-rules-2026-08-24 | aging | local, origin/codex/agy-cli-operational-rules-2026-08-24 | no | +1/-3 | missing | subject: docs: add agy CLI operating contract; paths: AGENTS.md |
| codex/penny-apple-effect-final3-20260812 | stale | local | no | +1/-15 | clean | subject: fix: make Apple effect reconciliation fail closed; paths: apple_effects.py, reminders.py, tests/test_apple_effects.py, tests/test_reminders.py, tests/test_transcript_log.py |
| codex/penny-apple-effect-final2-20260812 | stale | local | no | +1/-15 | clean | subject: fix: make Apple effect readback fail closed; paths: apple_effects.py, reminders.py, tests/test_apple_effects.py, tests/test_reminders.py, tests/test_transcript_log.py |
| codex/penny-apple-effect-final-20260812 | stale | local | no | +1/-15 | clean | subject: fix: make Apple Notes effects marker-safe; paths: apple_effects.py, reminders.py, tests/test_apple_effects.py, tests/test_reminders.py, tests/test_transcript_log.py |
| codex/penny-apple-effect-fix-20260812 | stale | local | no | +2/-15 | clean | subject: fix: preserve createability after marker probe timeout; paths: apple_effects.py, reminders.py, tests/test_apple_effects.py, tests/test_reminders.py, tests/test_transcript_log.py |
| codex/penny-august-2026 | stale | local | yes | +0/-17 | unattached | subject: fix: make source completion recoverable |
| deploy/pre-phase-a-20260810 | stale | local | yes | +0/-77 | unattached | subject: chore: ignore local worktrees |
| codex/penny-voice-memo-watchdog-main | stale | local | no | +1/-96 | clean | subject: Harden Voice Memos sync and Slack delivery; paths: README.md, docs/macmini-deployment.md, docs/reliability.md, docs/troubleshooting.md, tests/test_watcher.py |
| codex/penny-legacy-slack-schema | stale | local | no | +2/-97 | clean | subject: Harden Penny schema migration invariants; paths: tests/test_transcript_log.py, transcript_log.py |
| codex/penny-init-db-race | stale | local | no | +3/-98 | clean | subject: fix: harden SQLite migration race handling; paths: tests/test_transcript_log.py, transcript_log.py |
| codex/penny-slack-delivery-idempotency | stale | local | no | +19/-99 | unattached | subject: Clarify notification table and Maya state result; paths: README.md, core.py, docs/reliability.md, launchd/com.penny.tasks.plist.template, launchd/com.penny.watcher.plist.template |
| codex/maya-59a1fc6f215f | stale | local, origin/codex/maya-59a1fc6f215f | no | +4/-100 | clean | subject: fix: sanitize Slack delivery failures; paths: README.md, launchd/com.penny.watcher.plist.template, secrets.env.example, slack_delivery.py, tests/test_slack_delivery.py |
| codex/penny-voice-memo-watchdog | stale | local, origin/codex/penny-voice-memo-watchdog | no | +2/-103 | unattached | subject: stuff; paths: README.md, core.py, docs/macmini-deployment.md, docs/reliability.md, docs/superpowers/plans/2026-07-09-penny-maya-clio-pipeline.md |
| codex/penny-maya-contract | stale | local | no | +3/-103 | clean | subject: fix(maya): floor fractional voice memo span bounds; paths: README.md, core.py, docs/macmini-deployment.md, docs/reliability.md, docs/troubleshooting.md |
| fix/deliver-insert-race | stale | local | no | +1/-108 | unattached | subject: Fix /deliver race where insert_transcript's None row_id skipped the duplicate check; paths: tests/test_webhook.py, webhook/server.py |
| claude/gracious-babbage-36729b | stale | local | yes | +0/-108 | unattached | subject: Penny /deliver endpoint + Maya env config (#11) |
| feat/maya-deliver-endpoint | stale | local | no | +3/-110 | unattached | subject: feat(config): env-var overrides for Maya transcript routing; paths: config.py, config.toml, core.py, tests/test_config.py, tests/test_core_and_classifier.py |
| clio-agent/issue-6 | stale | local | no | +1/-112 | unattached | subject: fix: Housekeeping: wire deployments to git, then add Penny to Maya's fleet; paths: path |
| claude/improve-memo-parsing-IT4m2 | stale | origin/claude/improve-memo-parsing-IT4m2 | no | +2/-143 | unattached | subject: Detect and discard repetitive Whisper hallucination transcripts; paths: classifier.py, core.py |
| archive | stale | origin/archive | no | +1/-177 | unattached | subject: chore: Archive full Penny codebase before simplification; paths: .claude/skills/front-door/SKILL.md, .claude/skills/remote-exec/SKILL.md, .claude/skills/visual-iteration/SKILL.md, node_modules/.bin/mime, node_modules/.bin/sshpk-conv |
| main | active | local, origin/main | no | +10/-6 | clean | subject: chore: label Penny watcher process; paths: CONTEXT.md, docs/superpowers/plans/2026-09-14-shared-on-demand-asr.md, docs/superpowers/specs/2026-09-14-shared-on-demand-asr-design.md, requirements.txt, tests/test_watcher.py |
| codex/shared-on-demand-asr-20260914-penny | active | local | no | +23/-6 | clean | subject: fix: use configured ASR request deadline; paths: .superpowers/sdd/task-3-report.md, CONTEXT.md, asr/__init__.py, asr/client.py, asr/protocol.py |
| codex/shared-on-demand-asr | active | local | no | +8/-6 | clean | subject: test: define shared ASR configuration and contract; paths: CONTEXT.md, asr/__init__.py, asr/protocol.py, config.py, config.toml |
| codex/penny-voicememos-sync-proof-20260812 | stale | local | yes | +0/-6 | clean | subject: fix: scope Voice Memos daemon health to user |
| codex/penny-phase-a | stale | local, origin/codex/penny-phase-a | yes | +0/-15 | clean | subject: test: isolate Voice Memo watermark leak check |
| codex/penny-v2-slack-delivery | stale | local | yes | +0/-81 | clean | subject: fix: close Penny final delivery review |
| claude/voice-memo-reminders-sync-Q6JoX | stale | origin/claude/voice-memo-reminders-sync-Q6JoX | yes | +0/-161 | unattached | subject: feat: Add LLM classification, Apple Reminders routing, and Google Tasks sync |

Detached worktrees:
- /private/tmp/penny-task9-rereview.kmU0md (missing @ 14e0d7467429d55f5edd06a1c7e3f1f220918595)
- /private/tmp/penny-task9-review.bS2wyc (missing @ 9948d2b701a8bf53d548afa74114ff620b42b57d)
<!-- janitor:end:branches -->

<!-- janitor:begin:recent -->
## Shared Whisper memory deployment — September 30, 2026

PR #62 merged and deployed `63591bed23f86347a3cf73d7db27a395d9d49836`; all five labels activated. Post-request footprint fell from 2.3 GiB to 1.7 GiB on identical generated speech with identical transcript hashes; four varying-length requests also retained 1.7 GiB. See `docs/research/2026-09-30-shared-whisper-live-memory-receipt.md`. Natural application completion and multi-day busy-workload stability remain unproven. Internal simulator deletion remains blocked by protected assets; 14.8 GiB is still present, with Recovery the next coordinated step. Only the external 8.9 GiB cache was removed. Existing dirty Mac files were restored byte-for-byte after deployment.

Documentation was synchronized at `5192654c2490d1500a7583a4413c31c4993cc37c` after recording the deployed memory results and protected simulator blocker in `23cf6f356744a88266f3dc2cef9b94d5f7ebe991`.

# Shared Whisper memory work — September 30, 2026

Penny owns the shared MLX worker; Atlas calls its API. The owner authorized a memory fix, PR and live verification while retaining transcription quality. The first change bounds free GPU cache to 100 MiB and clears it after each request with the same pinned FP16 turbo model. See `docs/research/2026-09-30-shared-whisper-memory.md`. Source tests do not establish runtime memory reduction.

Long live Voice Memos use the local shared-Whisper owner with Penny priority and private audio-hash-bound chunk checkpoints. Historical backfill uses its separate backfill priority and existing checkpoint location. Chunk completion does not prove a canonical ledger link, archive, backup or downstream effect.

OCI owns the scheduled, read-only Mac Doctor observation through its native `penny-health.timer` and private receipt. A public Penny GitHub Actions worker is not an authorized health-check execution path. Doctor `degraded` remains a valid observed capability state; it does not authorize delivery of a `needs_review` transcript.

# OCI review and Mac health boundary — 2026-09-29

The old `AI Review` workflow requested the retired `oci-ts` runner lane. The separate OCI PR reviewer reviewed Penny PR #53. Public fork code remains on GitHub-hosted CI; the private OCI runner fleet does not enroll public repos. OCI may reach the Mac by the current `macmini` MagicDNS alias for a bounded native Doctor check. SSH reachability does not assign Penny's GitHub job or prove Doctor readiness.

Runtime pins, retained Doctor observation, backup receipt and downstream delivery are separate evidence. Doctor source identity may remain unknown when its checkout is dirty; that does not erase independently verified installed pins. Monitoring observes degradation and has no capture replay or delivery authority.
<!-- janitor:end:recent -->
# OCI review and Mac health boundary — 2026-09-29

The old `AI Review` workflow requested the retired `oci-ts` runner lane. The
separate OCI PR reviewer reviewed Penny PR #53. Public fork code remains on
GitHub-hosted CI; the private OCI runner fleet does not enroll public repos.
OCI may reach the Mac by the current `macmini` MagicDNS alias for a bounded
native Doctor check. SSH reachability does not assign Penny's GitHub job or
prove Doctor readiness.

Runtime pins, retained Doctor observation, backup receipt and downstream delivery are separate evidence. Doctor source identity may remain unknown when its checkout is dirty; that does not erase independently verified installed pins. Monitoring observes degradation and has no capture replay or delivery authority.
