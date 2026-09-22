# Penny development workflow

This directory contains the Penny-specific, plan-scoped adaptation of the pinned
Superpowers lifecycle. It is a development control plane only: it does not
import Penny runtime code, read the capture ledger, or change capture,
transcription, routing, delivery, archive, backup, or readiness behavior.

Pinned source: `obra/superpowers` at `b36e0829c6d0140e93cfef2ca599b1b07d4a7797`.
Only the lifecycle ideas needed by Penny are represented here. Penny's privacy,
local-first durability, and provider-boundary rules take precedence over generic
workflow guidance.

## Plan-scoped state

Create one directory per plan:

```text
.penny/workflow/plans/<PLAN_ID>/
├── requirements.md
├── design-review.md
├── implementation-plan.md
├── tdd.md
├── debugging.md                 # required for bug, failure, or regression work
├── tasks/<TASK_ID>.md           # one bounded handoff per delegated task
├── code-review.md
└── verification.md
```

`<PLAN_ID>` is a non-sensitive identifier such as
`penny-20260919-webhook-receipt`. Every artifact starts with the same plan ID.
Do not put audio, transcript text, provider responses, credentials, tokens,
private URLs, or unredacted paths in this state. Use metadata-only placeholders
such as `<CAPTURE_ID_REDACTED>`, `<PROVIDER_RECEIPT_REDACTED>`,
`<COMMIT_SHA>`, and `<EVIDENCE_REF>`.

The plan directory is the only state consumed by the gate commands. A file in a
different plan directory cannot satisfy this plan's gate.

## Lifecycle and handoffs

| Stage | Artifact | Required handoff | Completion condition |
| --- | --- | --- | --- |
| Requirements discovery | `requirements.md` | Approved requirements and risk classification | `Status: approved`; observable acceptance criteria and privacy boundary recorded |
| Design review | `design-review.md` | Reviewed design linked to requirements | `Status: approved`; invariants, boundaries, failure handling, and review decision recorded |
| Implementation planning | `implementation-plan.md` | Executable task list linked to approved design | `Status: executable`; each task has files, behavior, check, and next handoff |
| Red/green TDD | `tdd.md` | Behavioral red/green evidence or approved smoke-test exception | `Status: complete`; red and green evidence are both recorded, or exception is justified and approved |
| Systematic debugging | `debugging.md` | Reproduction, root cause, hypothesis evidence, and fix boundary | `Status: complete`; required for bugs and failures; never a guess-first fix |
| Subagent execution | `tasks/<TASK_ID>.md` | Bounded task result for the next stage | `Status: complete`; scope, privacy constraints, changed paths, and evidence are recorded |
| Code review | `code-review.md` | Findings and disposition for this plan's revisions | `Status: approved`; base/head revisions and observable review evidence are recorded |
| Final verification | `verification.md` | Release decision with evidence for each boundary | `Status: verified`; commands/results and unresolved boundaries are recorded |

Use `scripts/penny_workflow.py` to enforce the plan-scoped readiness and
completion gates without printing artifact contents:

```bash
python scripts/penny_workflow.py gate \
  --plan-dir .penny/workflow/plans/<PLAN_ID> --risk high
python scripts/penny_workflow.py verify \
  --plan-dir .penny/workflow/plans/<PLAN_ID>
```

`gate` validates the high-risk prerequisite statuses and rejects an
`executable` plan whose task table still contains placeholders. `verify`
validates the complete stage chain, matching red/green behavioral checks,
approved smoke exceptions, concrete review and final evidence, every evidence
matrix boundary, and any delegated task artifacts under `tasks/`. It emits
only the plan ID and bounded reason codes.

For high- and critical-risk changes, `gate` refuses implementation readiness
unless requirements are approved, design review is approved, and the plan is
executable. `verify` additionally requires approved code review and verified
final evidence. A passing local gate proves only the recorded workflow state;
it does not prove launchd registration, macOS permissions, provider receipts,
or downstream delivery.

## Risk routing

- `low`: documentation or a mechanical change with no runtime or data-path effect.
- `medium`: isolated behavior with a local test and no durable-schema, auth,
  provider, archive, backup, or capture-boundary change.
- `high`: durable state, capture/transcription, routing, delivery, archive,
  backup, authentication, privacy boundary, or operational readiness change.
- `critical`: external delivery, credential/permission change, destructive
  migration, or live deployment.

The templates are commands for producing evidence, not claims that the evidence
exists. Replace every placeholder before marking an artifact complete; never
replace a privacy placeholder with sensitive content.
