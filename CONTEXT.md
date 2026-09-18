<!-- janitor:begin:branches -->
## Branch and Worktree Review
Base: refs/remotes/origin/main @ 5e1472602bfcda57a01a13e11d3deb5369be53e4
Freshness: current

| Branch | Class | Sources | Merged | Ahead/behind | Worktree | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| auto-wip/20260912-210900 | abandoned_auto_wip | local | yes | +0/-33 | unattached | subject: fix: scope Voice Memos daemon health to user |
| auto-wip/20260912-210902 | abandoned_auto_wip | local | no | +3/-42 | unattached | subject: fix: narrowly allow natural no emphasis; paths: scripts/re_evaluate_quality_review.py, tests/test_quality_review.py, tests/test_transcript_quality.py, transcript_log.py, transcript_quality.py |
| auto-wip/20260913-100449 | abandoned_auto_wip | local | no | +3/-42 | unattached | subject: fix: narrowly allow natural no emphasis; paths: scripts/re_evaluate_quality_review.py, tests/test_quality_review.py, tests/test_transcript_quality.py, transcript_log.py, transcript_quality.py |
| auto-wip/20260914-100603 | abandoned_auto_wip | local | no | +3/-42 | unattached | subject: fix: narrowly allow natural no emphasis; paths: scripts/re_evaluate_quality_review.py, tests/test_quality_review.py, tests/test_transcript_quality.py, transcript_log.py, transcript_quality.py |
| auto-wip/20260917-180248 | abandoned_auto_wip | local | no | +3/-42 | unattached | subject: fix: narrowly allow natural no emphasis; paths: scripts/re_evaluate_quality_review.py, tests/test_quality_review.py, tests/test_transcript_quality.py, transcript_log.py, transcript_quality.py |
| codex/penny-quality-fix-20260811 | active | local | no | +3/-42 | dirty | subject: fix: narrowly allow natural no emphasis; paths: scripts/re_evaluate_quality_review.py, tests/test_quality_review.py, tests/test_transcript_quality.py, transcript_log.py, transcript_quality.py |
| codex/penny-apple-actions | active | local, origin/codex/penny-apple-actions | no | +1/-107 | dirty | subject: feat: add structured Apple action routes and a completion reader; paths: reminders.py, tests/test_reminders.py, tests/test_webhook.py, webhook/server.py |
| codex/foundational-agent-tooling-2026-08-26 | aging | local | no | +1/-30 | unattached | subject: docs: standardize foundational agent tooling; paths: AGENTS.md |
| codex/agy-cli-operational-rules-2026-08-24 | aging | local, origin/codex/agy-cli-operational-rules-2026-08-24 | no | +1/-30 | unattached | subject: docs: add agy CLI operating contract; paths: AGENTS.md |
| codex/penny-apple-effect-final3-20260812 | stale | local | no | +1/-42 | clean | subject: fix: make Apple effect reconciliation fail closed; paths: apple_effects.py, reminders.py, tests/test_apple_effects.py, tests/test_reminders.py, tests/test_transcript_log.py |
| codex/penny-apple-effect-final2-20260812 | stale | local | no | +1/-42 | clean | subject: fix: make Apple effect readback fail closed; paths: apple_effects.py, reminders.py, tests/test_apple_effects.py, tests/test_reminders.py, tests/test_transcript_log.py |
| codex/penny-apple-effect-final-20260812 | stale | local | no | +1/-42 | clean | subject: fix: make Apple Notes effects marker-safe; paths: apple_effects.py, reminders.py, tests/test_apple_effects.py, tests/test_reminders.py, tests/test_transcript_log.py |
| codex/penny-apple-effect-fix-20260812 | stale | local | no | +2/-42 | clean | subject: fix: preserve createability after marker probe timeout; paths: apple_effects.py, reminders.py, tests/test_apple_effects.py, tests/test_reminders.py, tests/test_transcript_log.py |
| codex/penny-august-2026 | stale | local | yes | +0/-44 | unattached | subject: fix: make source completion recoverable |
| deploy/pre-phase-a-20260810 | stale | local | yes | +0/-104 | unattached | subject: chore: ignore local worktrees |
| codex/penny-voice-memo-watchdog-main | stale | local | no | +1/-123 | clean | subject: Harden Voice Memos sync and Slack delivery; paths: README.md, docs/macmini-deployment.md, docs/reliability.md, docs/troubleshooting.md, tests/test_watcher.py |
| codex/penny-legacy-slack-schema | stale | local | no | +2/-124 | clean | subject: Harden Penny schema migration invariants; paths: tests/test_transcript_log.py, transcript_log.py |
| codex/penny-init-db-race | stale | local | no | +3/-125 | clean | subject: fix: harden SQLite migration race handling; paths: tests/test_transcript_log.py, transcript_log.py |
| codex/penny-slack-delivery-idempotency | stale | local | no | +19/-126 | unattached | subject: Clarify notification table and Maya state result; paths: README.md, core.py, docs/reliability.md, launchd/com.penny.tasks.plist.template, launchd/com.penny.watcher.plist.template |
| codex/maya-59a1fc6f215f | stale | local, origin/codex/maya-59a1fc6f215f | no | +4/-127 | clean | subject: fix: sanitize Slack delivery failures; paths: README.md, launchd/com.penny.watcher.plist.template, secrets.env.example, slack_delivery.py, tests/test_slack_delivery.py |
| codex/penny-voice-memo-watchdog | stale | local, origin/codex/penny-voice-memo-watchdog | no | +2/-130 | unattached | subject: stuff; paths: README.md, core.py, docs/macmini-deployment.md, docs/reliability.md, docs/superpowers/plans/2026-07-09-penny-maya-clio-pipeline.md |
| codex/penny-maya-contract | stale | local | no | +3/-130 | clean | subject: fix(maya): floor fractional voice memo span bounds; paths: README.md, core.py, docs/macmini-deployment.md, docs/reliability.md, docs/troubleshooting.md |
| fix/deliver-insert-race | stale | local | no | +1/-135 | unattached | subject: Fix /deliver race where insert_transcript's None row_id skipped the duplicate check; paths: tests/test_webhook.py, webhook/server.py |
| claude/gracious-babbage-36729b | stale | local | yes | +0/-135 | unattached | subject: Penny /deliver endpoint + Maya env config (#11) |
| feat/maya-deliver-endpoint | stale | local | no | +3/-137 | unattached | subject: feat(config): env-var overrides for Maya transcript routing; paths: config.py, config.toml, core.py, tests/test_config.py, tests/test_core_and_classifier.py |
| clio-agent/issue-6 | stale | local | no | +1/-139 | unattached | subject: fix: Housekeeping: wire deployments to git, then add Penny to Maya's fleet; paths: path |
| claude/improve-memo-parsing-IT4m2 | stale | origin/claude/improve-memo-parsing-IT4m2 | no | +2/-170 | unattached | subject: Detect and discard repetitive Whisper hallucination transcripts; paths: classifier.py, core.py |
| archive | stale | origin/archive | no | +1/-204 | unattached | subject: chore: Archive full Penny codebase before simplification; paths: .claude/skills/front-door/SKILL.md, .claude/skills/remote-exec/SKILL.md, .claude/skills/visual-iteration/SKILL.md, node_modules/.bin/mime, node_modules/.bin/sshpk-conv |
| main | active | local, origin/main | no | +8/-0 | clean | subject: docs: separate Penny source and receipt revisions; paths: HANDOFF.md, TODO.md, config.py, config.toml, docs/macmini-deployment.md |
| feat/shared-whisper-preemption | active | local | no | +3/-0 | clean | subject: docs: synchronize shared Whisper cutover queue; paths: HANDOFF.md, TODO.md, config.py, config.toml, docs/macmini-deployment.md |
| codex/docs-contract-penny | active | local | no | +1/-0 | clean | subject: docs: add public-safe infrastructure contract; paths: AGENTS.md, CONTEXT.md, HANDOFF.md, INFRA.md, TODO.md |
| codex/shared-on-demand-asr-20260914-penny | active | local | no | +14/-24 | clean | subject: fix: use configured ASR request deadline; paths: .superpowers/sdd/task-3-report.md, asr/__init__.py, asr/client.py, asr/protocol.py, asr/server.py |
| codex/shared-on-demand-asr | active | local | no | +1/-26 | clean | subject: test: define shared ASR configuration and contract; paths: asr/__init__.py, asr/protocol.py, config.py, config.toml, tests/test_asr_config.py |
| codex/penny-voicememos-sync-proof-20260812 | stale | local | yes | +0/-33 | clean | subject: fix: scope Voice Memos daemon health to user |
| codex/penny-phase-a | stale | local, origin/codex/penny-phase-a | yes | +0/-42 | clean | subject: test: isolate Voice Memo watermark leak check |
| codex/penny-v2-slack-delivery | stale | local | yes | +0/-108 | clean | subject: fix: close Penny final delivery review |
| claude/voice-memo-reminders-sync-Q6JoX | stale | origin/claude/voice-memo-reminders-sync-Q6JoX | yes | +0/-188 | unattached | subject: feat: Add LLM classification, Apple Reminders routing, and Google Tasks sync |
<!-- janitor:end:branches -->

<!-- janitor:begin:recent -->
## Recent Changes

Active development focused on deploying the shared Whisper service cutover with Wyoming isolation guards, following the implementation of the GitHub delivery outbox pipeline for project-classified notes. Recent commits also separated Penny source and receipt revisions and synchronized live cutover state.

- **Shared Whisper Service & Protocol:** Defined shared Whisper protocol (`525456f`), added killable Whisper service supervisor (`33a4843`), filtered worker options (`cea41ff`), and excluded tiny Wyoming from the owner guard (`d0afcfc`) and Doctor blocker (`8e53c10`).
- **Cutover Tracking & Handoff:** Synchronized shared Whisper cutover queue (`7025c53`), recorded live cutover state (`d7d9a0d`), and updated `HANDOFF.md` to separate Penny source and receipt revisions (`7cbf7ae`).
- **GitHub Delivery Outbox Pipeline:** Created `github_deliveries` ledger table with claim and mark operations (`183d884`), added lease recovery and claim mismatch tests (`1715f5b`), established outbox stream with Slack thread replies (`db78378`, `2201ea3`), and hooked outbox draining into watcher ingest with rate limiting and malformed response handling (`b0cf690`, `fbb6700`, `9c0ee29`).
- **Note Classification & Triage Readiness:** Added project category classification while suppressing Reminder creation for project items (`73c75c7`, `6ddec6c`, `fc4bc18`), added local-only github-triage readiness probe to Doctor (`7c57e9f`, `1cd2526`), and documented `GH_TOKEN` launchd configuration requirements (`5444181`, `81811a8`).
- **Working Tree State:** Clean working tree on branch `main` at `7cbf7ae`.
<!-- janitor:end:recent -->
