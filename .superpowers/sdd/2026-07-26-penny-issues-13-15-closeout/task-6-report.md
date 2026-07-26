# Task 6 report — explicit Penny notification policy

Date: 2026-07-26
Worktree: `/Volumes/2TB_SSD/GitHub/.codex-worktrees/penny-slack-delivery-idempotency`
Base reviewed context: `862d015d6130656a8e66380ea131ad6fd82e59f3`

## Scope followed

- Worked only in the requested worktree.
- Did not touch live files, databases, launchd state, Slack write tools, GitHub state, push, merge, or deploy.
- Preserved existing branch work from prior reviewed tasks.

## Repository inventory of notification controls

### 1. Telegram control

- `config.toml` sets `[notifications].telegram_enabled = false`.
- `config.py` reads that value into `cfg.notifications.telegram_enabled`.
- `core.py::send_telegram()` exits early when the toggle is false.
- `watcher.py::check_dependencies()` only requires `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` when Telegram is enabled.

Conclusion: Telegram is explicitly disabled by repository configuration unless someone deliberately flips the toggle.

### 2. Slack transcript delivery control

- `launchd/com.penny.watcher.plist.template` wires `PENNY_SLACK_BOT_TOKEN` and `PENNY_SLACK_CHANNEL_ID`.
- `transcript_log.py` enqueues Slack delivery rows only for eligible `source == "iCloud"` transcripts.
- `transcript_log.py::_slack_channel_id()` defaults to `C0BKS0QT7FU` when no Slack channel env var is provided.
- `slack_delivery.py` reads `PENNY_SLACK_BOT_TOKEN` / `SLACK_BOT_TOKEN` and posts verbatim transcript text to Slack.
- `watcher.py` processes the Slack outbox independently of the Telegram toggle.

Conclusion: successful iCloud Voice Memo verbatim Slack delivery remains enabled through Slack runtime environment variables and is not governed by the Telegram config toggle.

### 3. Slack mention / notification behavior

- No repository config, code path, or settings endpoint controls Slack mentions, badges, or user notification preferences.
- That behavior is external to Penny and must be verified in Slack itself.

Conclusion: Slack notification preference must not be inferred from Telegram state and should not become a repository setting.

## Changes made

### Documentation

- Updated `README.md` configuration comments to say the Telegram toggle does not disable Slack transcript mirroring.
- Added a `Notification policy` section to `README.md` that separates:
  - Telegram enablement
  - Slack transcript mirroring
  - External Slack notification preference
- Added explicit separation notes near the runtime environment variable inventory in `README.md`.
- Updated `docs/reliability.md` to record that Slack transcript delivery is independent from the Telegram toggle and that Slack-side notification behavior is external.
- Added a `Notification control inventory` section to `docs/reliability.md` for operational answers to “are notifications enabled?”

### Regression coverage

- Added `tests/test_config.py::test_telegram_toggle_is_false_without_requiring_slack_env_here` to lock in the current Telegram-disabled config posture without inventing a Slack config setting.
- Added `tests/test_transcript_log.py::test_icloud_transcript_uses_default_slack_channel_without_telegram_dependency` to prove eligible iCloud transcripts still queue Slack delivery using the default channel even with no Slack channel env override and regardless of Telegram state.

## Focused verification run

Command:

```bash
python3 -m pytest tests/test_config.py tests/test_slack_delivery.py tests/test_transcript_log.py
```

Result:

- `43 passed in 0.29s`

## Full suite verification run

Command:

```bash
python3 -m pytest
```

Result:

- `122 passed in 0.51s`

## Diff review

Reviewed the final diff for:

- accidental runtime behavior changes
- introduction of a repo-level Slack preference toggle
- secret leakage in docs/comments/tests
- drift from the task’s intended policy

Result: diff is limited to docs plus focused regression tests. No live/runtime mutations were made.

## Commit

Created local commit after verification:

- commit message: `docs: make Penny notification policy explicit`

## Notes for controller follow-up

- Live Slack read verification remains outstanding by design and should be performed by the controller outside this task.
- Issue comment / closure should cite the documented separation:
  - Telegram disabled by `config.toml`
  - Slack transcript mirroring controlled by Slack runtime env
  - Slack mention behavior is an external Slack preference, not a Penny repository setting

## Concerns

- No repository-local evidence can prove the current live Slack workspace/channel notification preference; that remains an external verification step for the controller.

---

## Fix round 1 — 2026-07-26

### Finding 1 fix

Replaced the weak config-only harness assertion with coverage that exercises Penny's actual policy boundaries:

- `tests/test_config.py::test_config_loads_telegram_disabled_from_config_toml` now proves the repo default loads `config.toml` `[notifications].telegram_enabled = false`.
- `tests/test_core_and_classifier.py::test_send_telegram_is_suppressed_by_repo_default_config` now proves the loaded repo default suppresses Telegram sends without patching the toggle.
- Kept the transcript-log Slack regression in `tests/test_transcript_log.py::test_icloud_transcript_uses_default_slack_channel_without_telegram_dependency`, which proves an eligible iCloud transcript still queues Slack delivery to `C0BKS0QT7FU`.

This matches the chosen policy without inventing any Slack notification config field.

### Finding 2 fix

Added an operator-ready live verification sequence to `docs/reliability.md` that:

- uses Penny's real `GET /health` endpoint (`http://127.0.0.1:5678/health`)
- checks watcher health via `~/.penny/health.txt`
- verifies Slack runtime wiring without printing secrets
- expects `slack_configured=True`
- expects `slack_channel_id=C0BKS0QT7FU`
- instructs the operator to verify the exact controller-run canary text in `#penny`
- explicitly states that Slack mention/badge/push preferences are external and not configurable or inspectable from Penny

### Focused verification run after fixes

Command:

```bash
python3 -m pytest tests/test_config.py tests/test_core_and_classifier.py tests/test_transcript_log.py tests/test_slack_delivery.py
```

Result:

- `83 passed in 0.24s`

### Concerns after fix round 1

- The live Slack canary and Slack-side read verification remain controller-owned steps by design.

---

## Fix round 2 — 2026-07-26

### Finding 2 correction

Updated `docs/reliability.md` to include the exact already-verified live canary string verbatim:

`Penny health canary 20260726T205704Z: receipt test only; no action required.`

The docs now tell the operator to:

- run the exact read-only command `curl -fsS http://127.0.0.1:5678/health` on the Mac mini and confirm `status=ok`
- run the existing read-only watcher-runtime wiring check and confirm `slack_configured=True` and `slack_channel_id=C0BKS0QT7FU`
- read `#penny` / `C0BKS0QT7FU` and match the exact canary text verbatim

The note now explicitly says this proves transcript delivery is not suppressed by `telegram_enabled = false`, but does not prove or change external Slack mention, badge, or push-notification preferences.

### Report correction

Clarification: `README.md` changed in the original Task 6 commit (`a1089c3602f8306d7086627292c91acda2cf0203`). This fix round changes `docs/reliability.md` and the appended report only.

### Focused verification run after fix round 2

Command:

```bash
python3 -m pytest tests/test_config.py tests/test_core_and_classifier.py tests/test_transcript_log.py tests/test_slack_delivery.py
```

Result:

- `83 passed in 0.24s`
