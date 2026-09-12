<!-- janitor:begin:branches -->
## Branch and Worktree Review
Base: refs/remotes/origin/main @ 162737609afc0a62cde4381887d8f016f81ce6a0
Freshness: current

| Branch | Class | Sources | Merged | Ahead/behind | Worktree | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| auto-wip/20260912-210900 | abandoned_auto_wip | local | yes | +0/-4 | unattached | subject: fix: scope Voice Memos daemon health to user |
| codex/penny-quality-fix-20260811 | active | local | no | +3/-13 | dirty | subject: fix: narrowly allow natural no emphasis; paths: scripts/re_evaluate_quality_review.py, tests/test_quality_review.py, tests/test_transcript_quality.py, transcript_log.py, transcript_quality.py |
| codex/penny-apple-actions | active | local, origin/codex/penny-apple-actions | no | +1/-78 | dirty | subject: feat: add structured Apple action routes and a completion reader; paths: reminders.py, tests/test_reminders.py, tests/test_webhook.py, webhook/server.py |
| codex/foundational-agent-tooling-2026-08-26 | aging | local | no | +1/-1 | unattached | subject: docs: standardize foundational agent tooling; paths: AGENTS.md |
| codex/agy-cli-operational-rules-2026-08-24 | aging | local, origin/codex/agy-cli-operational-rules-2026-08-24 | no | +1/-1 | missing | subject: docs: add agy CLI operating contract; paths: AGENTS.md |
| codex/penny-apple-effect-final3-20260812 | stale | local | no | +1/-13 | clean | subject: fix: make Apple effect reconciliation fail closed; paths: apple_effects.py, reminders.py, tests/test_apple_effects.py, tests/test_reminders.py, tests/test_transcript_log.py |
| codex/penny-apple-effect-final2-20260812 | stale | local | no | +1/-13 | clean | subject: fix: make Apple effect readback fail closed; paths: apple_effects.py, reminders.py, tests/test_apple_effects.py, tests/test_reminders.py, tests/test_transcript_log.py |
| codex/penny-apple-effect-final-20260812 | stale | local | no | +1/-13 | clean | subject: fix: make Apple Notes effects marker-safe; paths: apple_effects.py, reminders.py, tests/test_apple_effects.py, tests/test_reminders.py, tests/test_transcript_log.py |
| codex/penny-apple-effect-fix-20260812 | stale | local | no | +2/-13 | clean | subject: fix: preserve createability after marker probe timeout; paths: apple_effects.py, reminders.py, tests/test_apple_effects.py, tests/test_reminders.py, tests/test_transcript_log.py |
| codex/penny-august-2026 | stale | local | yes | +0/-15 | unattached | subject: fix: make source completion recoverable |
| deploy/pre-phase-a-20260810 | stale | local | yes | +0/-75 | unattached | subject: chore: ignore local worktrees |
| codex/penny-voice-memo-watchdog-main | stale | local | no | +1/-94 | clean | subject: Harden Voice Memos sync and Slack delivery; paths: README.md, docs/macmini-deployment.md, docs/reliability.md, docs/troubleshooting.md, tests/test_watcher.py |
| codex/penny-legacy-slack-schema | stale | local | no | +2/-95 | clean | subject: Harden Penny schema migration invariants; paths: tests/test_transcript_log.py, transcript_log.py |
| codex/penny-init-db-race | stale | local | no | +3/-96 | clean | subject: fix: harden SQLite migration race handling; paths: tests/test_transcript_log.py, transcript_log.py |
| codex/penny-slack-delivery-idempotency | stale | local | no | +19/-97 | unattached | subject: Clarify notification table and Maya state result; paths: README.md, core.py, docs/reliability.md, launchd/com.penny.tasks.plist.template, launchd/com.penny.watcher.plist.template |
| codex/maya-59a1fc6f215f | stale | local, origin/codex/maya-59a1fc6f215f | no | +4/-98 | clean | subject: fix: sanitize Slack delivery failures; paths: README.md, launchd/com.penny.watcher.plist.template, secrets.env.example, slack_delivery.py, tests/test_slack_delivery.py |
| codex/penny-voice-memo-watchdog | stale | local, origin/codex/penny-voice-memo-watchdog | no | +2/-101 | unattached | subject: stuff; paths: README.md, core.py, docs/macmini-deployment.md, docs/reliability.md, docs/superpowers/plans/2026-07-09-penny-maya-clio-pipeline.md |
| codex/penny-maya-contract | stale | local | no | +3/-101 | clean | subject: fix(maya): floor fractional voice memo span bounds; paths: README.md, core.py, docs/macmini-deployment.md, docs/reliability.md, docs/troubleshooting.md |
| fix/deliver-insert-race | stale | local | no | +1/-106 | unattached | subject: Fix /deliver race where insert_transcript's None row_id skipped the duplicate check; paths: tests/test_webhook.py, webhook/server.py |
| claude/gracious-babbage-36729b | stale | local | yes | +0/-106 | unattached | subject: Penny /deliver endpoint + Maya env config (#11) |
| feat/maya-deliver-endpoint | stale | local | no | +3/-108 | unattached | subject: feat(config): env-var overrides for Maya transcript routing; paths: config.py, config.toml, core.py, tests/test_config.py, tests/test_core_and_classifier.py |
| clio-agent/issue-6 | stale | local | no | +1/-110 | unattached | subject: fix: Housekeeping: wire deployments to git, then add Penny to Maya's fleet; paths: path |
| claude/improve-memo-parsing-IT4m2 | stale | origin/claude/improve-memo-parsing-IT4m2 | no | +2/-141 | unattached | subject: Detect and discard repetitive Whisper hallucination transcripts; paths: classifier.py, core.py |
| archive | stale | origin/archive | no | +1/-175 | unattached | subject: chore: Archive full Penny codebase before simplification; paths: .claude/skills/front-door/SKILL.md, .claude/skills/remote-exec/SKILL.md, .claude/skills/visual-iteration/SKILL.md, node_modules/.bin/mime, node_modules/.bin/sshpk-conv |
| codex/penny-voicememos-sync-proof-20260812 | stale | local | yes | +0/-4 | clean | subject: fix: scope Voice Memos daemon health to user |
| main | stale | local, origin/main | yes | +0/-4 | clean | subject: fix: scope Voice Memos daemon health to user |
| codex/penny-phase-a | stale | local, origin/codex/penny-phase-a | yes | +0/-13 | clean | subject: test: isolate Voice Memo watermark leak check |
| codex/penny-v2-slack-delivery | stale | local | yes | +0/-79 | clean | subject: fix: close Penny final delivery review |
| claude/voice-memo-reminders-sync-Q6JoX | stale | origin/claude/voice-memo-reminders-sync-Q6JoX | yes | +0/-159 | unattached | subject: feat: Add LLM classification, Apple Reminders routing, and Google Tasks sync |

Detached worktrees:
- /private/tmp/penny-task9-rereview.kmU0md (missing @ 14e0d7467429d55f5edd06a1c7e3f1f220918595)
- /private/tmp/penny-task9-review.bS2wyc (missing @ 9948d2b701a8bf53d548afa74114ff620b42b57d)
<!-- janitor:end:branches -->
