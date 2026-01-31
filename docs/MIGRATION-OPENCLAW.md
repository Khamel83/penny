# Migration: Clawdbot → OpenClaw

**Date**: 2026-01-30
**Status**: Complete

## Overview

Renamed all "Clawdbot/ClawdBot" references to "OpenClaw" and clarified that Penny uses OpenClaw as an EXTERNAL dependency.

## Key Clarification

**Penny** is a voice assistant layer built on top of **OpenClaw**:
- **Penny** (this repo): Voice memo transcription pipeline
- **OpenClaw** (external): https://github.com/openclaw/openclaw - AI agent platform maintained by others

Penny is a CONSUMER of OpenClaw, not a maintainer. For OpenClaw issues, see the OpenClaw repository.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Penny (This Repository)                     │
│  • Voice memo transcription pipeline                            │
│  • @PennyMoltBot - Penny's Telegram bot for voice routing       │
│  • Classification and routing of voice memos                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (uses)
┌─────────────────────────────────────────────────────────────────┐
│                   OpenClaw (External Dependency)                │
│  • https://github.com/openclaw/openclaw                         │
│  • Agent orchestration, skills, build execution                │
│  • @PennyOCIBot - OpenClaw's bot (not Penny's)                │
└─────────────────────────────────────────────────────────────────┘
```

## What Changed

### 1. File Renames
| Old | New |
|-----|-----|
| `docs/ADR-002-clawdbot-security-hardening.md` | `docs/ADR-002-openclaw-security-hardening.md` |

### 2. Documentation Updates

**CLAUDE.md**
- Added "Relationship to OpenClaw" section clarifying OpenClaw is external
- Updated all Clawdbot/ClawdBot references to OpenClaw

**README.md**
- Added "Penny vs OpenClaw" section
- Updated architecture diagram

**LLM-OVERVIEW.md**
- Updated ClawdBot references to OpenClaw
- Clarified @PennyOCIBot is OpenClaw's bot

**TODO.md**
- Updated "OpenClaw Security Hardening" section

**docs/ADR-002-openclaw-security-hardening.md**
- Renamed and updated to reference OpenClaw

**docs/MIGRATION-OPENCLAW.md** (this file)
- New migration documentation

### 3. Security Enhancements (2026-01-30)

**Problem:** ADR-002 said "All requests logged with client IP" but the `pending_approvals` table wasn't storing client IP.

**Fixed:**
- Added `client_ip` and `resolved_from_ip` columns to `pending_approvals` table
- Updated `/api/ingest` to extract client_ip from X-Forwarded-For header
- Updated `/api/telegram/webhook` to extract client_ip for approval resolutions
- Passed client_ip through: ingest → router → handle_build → approval
- Added index on client_ip for audit queries

**Files Modified:**
- `penny/database.py` - Schema updates
- `penny/main.py` - Extract client IP
- `penny/router.py` - Pass client IP through routing
- `penny/integrations/claude_code.py` - Log client IP for approvals
- `docs/ADR-002-openclaw-security-hardening.md` - Updated schema docs

## Commits

```
6a51e5e feat: Add client IP logging to audit trail
f31f57b docs: Clarify Penny uses OpenClaw as external dependency
57bc2bf docs: Rename Clawdbot → OpenClaw and clarify architecture
```

## What Was NOT Changed

- **@PennyMoltBot** - Telegram bot name (correct - it's the actual bot handle)
- **@PennyOCIBot** - OpenClaw's bot (correct)
- Core Penny functionality (voice pipeline, classification, routing)
- Integration points (Penny still uses OpenClaw the same way)

## Verification

```bash
# Verify no old name references remain
grep -rn "Clawdbot\|ClawdBot" --include="*.md" --include="*.py" . | grep -v "OpenClaw"

# Should return empty (except @PennyMoltBot which is correct)
```
