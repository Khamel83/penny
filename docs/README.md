# Docs

Canonical docs for Penny live here.

## Start Here

- `../README.md` — product overview, architecture, setup, deploy basics
- `reliability.md` — operational model, failure modes, health signals
- `macmini-deployment.md` — Mac mini layout, launchd deployment, runtime locations
- `troubleshooting.md` — concrete recovery steps for Voice Memos/iCloud issues
- `ios-shortcut-setup.md` — optional alternate ingest path, not the primary flow

## Current Product Shape

- Primary ingest path: `Apple Watch Voice Memos -> iCloud/Voice Memos sync -> Mac mini -> Penny`
- Reliability is prioritized over raw speed.
- Short ambiguous memos go to `Notes` and also create an `Inbox` reminder with timestamp + excerpt.

## Not Canonical

- `docs/sessions/` is historical session output from tooling, not product documentation.
- `docs/archive/` is the holding area for retained but non-current project material.
- Assistant-specific context files are intentionally not kept here unless they are actively maintained.
