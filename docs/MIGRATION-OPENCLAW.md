# Migration: Clawdbot → OpenClaw

**Date**: 2026-01-30
**Status**: Complete

## Overview

Renamed all "Clawdbot/ClawdBot" references to "OpenClaw" and clarified the architecture relationship between Penny and OpenClaw.

## What Changed

### 1. File Renames
| Old | New |
|-----|-----|
| `docs/ADR-002-clawdbot-security-hardening.md` | `docs/ADR-002-openclaw-security-hardening.md` |

### 2. Documentation Updates

**CLAUDE.md** (+72 lines)
- Added "Relationship to OpenClaw" section at top
- Updated "Project Overview" to clarify Penny is built on OpenClaw
- Updated "Security Architecture" reference

**README.md** (+72 lines)
- Added "Penny vs OpenClaw" section after Architecture
- Updated "Known Limitations" reference
- Added ASCII architecture diagram

**LLM-OVERVIEW.md** (+52 lines)
- Updated "IMPORTANT CONTEXT" section with OpenClaw architecture note
- Updated @PennyOCIBot description

**TODO.md** (+20 lines)
- Updated Done section header to "OpenClaw Security Hardening"
- Updated note about Penny/OpenClaw relationship

**docs/ADR-002-openclaw-security-hardening.md**
- Renamed and updated title/context
- Added "Architecture Note" section with ASCII diagram

**telegram-bot.js**
- Updated header comment to clarify Penny/OpenClaw relationship

## Architecture Clarification

```
┌─────────────────────────────────────────────────────────────────┐
│                     Penny (Voice Assistant Layer)               │
│  • Transcribe → Classify → Route voice memos                    │
│  • Background orchestrator (cheap probes + expensive reasoning) │
│  • Web UI (HTMX)                                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                     OpenClaw (AI Agent Core)                     │
│  • Agent orchestration                                          │
│  • Skill system                                                  │
│  • Integration framework                                        │
│  • Build execution (Claude Code)                                │
└─────────────────────────────────────────────────────────────────┘
```

**Key Points:**
- **Penny** = This repository (voice interface layer)
- **OpenClaw** = Separate project (AI agent platform)
- Think of Penny as a specialized "voice interface" that uses OpenClaw as its AI engine

## What Was NOT Changed

- **@PennyMoltBot** - Telegram bot name (correct - it's the actual bot handle)
- **@PennyOCIBot** - Separate OpenClaw bot (correct)
- Code functionality - only documentation/name changes
- Environment variables
- Database schema

## Next Steps for OpenClaw Foundation

### Completed
- [x] Rename documentation references
- [x] Clarify Penny/OpenClaw architecture relationship
- [x] Update ADR references

### Weekend Tasks (Connections/Foundation)
- [ ] **Review OpenClaw repository structure** - Ensure Penny's integration points are documented
- [ ] **Audit integration dependencies** - What does Penny expect from OpenClaw?
  - Build execution (Claude Code)
  - Service router
  - Agent orchestration
- [ ] **Update OpenClaw repo** - Does it have Penny documentation?
- [ ] **Test cross-repo links** - Ensure docs point to correct places
- [ ] **Consider split concerns** - Are there any OpenClaw features that should move to Penny?

### Open Questions
1. **Is OpenClaw a separate public repo?** If so, update links in README
2. **Are there OpenClaw-specific configs** that Penny needs to document?
3. **Should we add a "Contributing" section** for OpenClaw extensions to Penny?

## Verification

```bash
# Verify no old name references remain
grep -rn "Clawdbot\|ClawdBot" --include="*.md" --include="*.py" . | grep -v "OpenClaw"

# Should return empty (except @PennyMoltBot which is correct)
```

## Rollback

If needed, revert with:
```bash
git revert <commit-hash>
```
