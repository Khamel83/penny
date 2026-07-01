# Penny Handoff

This file is the assistant-facing entry point for Penny.

## What Penny Is

Penny is voice capture middleware for Apple's native apps. The primary flow is:

`Apple Watch Voice Memos -> Mac mini -> Whisper classification -> Apple Reminders / Apple Notes`

## Canonical Docs

- [README.md](/Volumes/2TB_SSD/GitHub/clio/.worktrees/penny-issue-6-opencode/README.md)
- [docs/README.md](/Volumes/2TB_SSD/GitHub/clio/.worktrees/penny-issue-6-opencode/docs/README.md)
- [docs/reliability.md](/Volumes/2TB_SSD/GitHub/clio/.worktrees/penny-issue-6-opencode/docs/reliability.md)
- [docs/macmini-deployment.md](/Volumes/2TB_SSD/GitHub/clio/.worktrees/penny-issue-6-opencode/docs/macmini-deployment.md)
- [docs/troubleshooting.md](/Volumes/2TB_SSD/GitHub/clio/.worktrees/penny-issue-6-opencode/docs/troubleshooting.md)

## Operational Shape

- The live deployment is expected to be a git checkout on the Mac mini.
- Keep local machine state out of git: `.env`, `secrets.env`, `venv/`, `~/.penny/`, and launchd plist outputs are runtime artifacts.
- `config.toml` holds non-secret, repo-managed settings.
- `launchd/*.plist.template` are the source templates; the real plists are machine-local.

## Validation

Before shipping repo changes:

1. Run `python3.12 scripts/trust_check.py`.
2. Run `uv run python -m pytest tests/ -v`.
3. Restart the affected launchd agents on the Mac mini.
4. Confirm the webhook health endpoint on port `5678`.

## Fleet Watchlist Note

If this repo is added to Maya's fleet watchlist, the registered repo name should be `penny`.
