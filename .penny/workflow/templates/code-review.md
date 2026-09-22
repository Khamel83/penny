# Plan-scoped code review artifact

Plan ID: <PLAN_ID>
Stage: code-review
Status: draft

## Review inputs

- Requirements: `.penny/workflow/plans/<PLAN_ID>/requirements.md`
- Design: `.penny/workflow/plans/<PLAN_ID>/design-review.md`
- Implementation plan: `.penny/workflow/plans/<PLAN_ID>/implementation-plan.md`
- Base revision: <BASE_COMMIT_SHA>
- Head revision: <HEAD_COMMIT_SHA>
- Changed paths: <PATHS_ONLY>
Review evidence: <METADATA_ONLY_REVIEW_REFERENCE>
## Outputs

- Approved or blocked review decision tied to this plan's base/head revisions.
- Handoff: review evidence and findings disposition for final verification.


## Observable review evidence

- Spec-compliance command: `<COMMAND>`
- Spec-compliance result: <METADATA_RESULT>
- Behavioral evidence: <TDD_OR_SMOKE_EVIDENCE_REF>
- Privacy/scope inspection: <METADATA_RESULT>
- Runtime behavior unchanged outside plan: <EVIDENCE_OR_EXCEPTION>

## Findings

| Severity | Finding | Evidence reference | Disposition |
| --- | --- | --- | --- |
| <critical|important|minor> | <CONCRETE_FINDING> | <EVIDENCE_REF> | <fixed|accepted_with_reason> |

No finding may be closed by asserting that files changed. Critical and important findings block
approval. Any plan conflict is recorded with a ruling and returned to the implementation task.

## Decision and handoff

- Decision: <approved|changes_requested|blocked>
- Reviewer: <REDACTED_REVIEWER_ID>
- Next stage: `.penny/workflow/plans/<PLAN_ID>/verification.md`

Set `Status: approved` only when the frozen base/head revisions, evidence, findings, and decision
are recorded. Final verification consumes this artifact, not an unscoped review comment.
