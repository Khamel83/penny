# Design review artifact

Plan ID: <PLAN_ID>
Stage: design-review
Status: draft

## Inputs

- Requirements: `.penny/workflow/plans/<PLAN_ID>/requirements.md`
- Relevant Penny contracts: <DOC_PATHS>
- Reviewer: <REDACTED_REVIEWER_ID>
## Outputs

- Reviewed design decision with boundaries, failure handling, and invariant coverage.
- Handoff: approved design path and review evidence for implementation planning.


## Proposed design

- Components and ownership: <COMPONENT_BOUNDARIES>
- Data/state transitions: <METADATA_ONLY_FLOW>
- Interfaces and compatibility: <SIGNATURES_OR_CONTRACTS>
- Failure and retry behavior: <BOUNDED_FAILURE_POLICY>
- Rollback or recovery boundary: <RECOVERY_PLAN>
- Runtime behavior intentionally unchanged: <EXPLICIT_NON_RUNTIME_EFFECT>

## Review checklist

- [ ] Requirements acceptance IDs R1..Rn are each addressed.
- [ ] Canonical ledger, archive, receipt, and downstream boundaries remain distinct where applicable.
- [ ] No design step reads, emits, or transfers capture content or credentials.
- [ ] Durable state changes are additive and retry-safe, or the risk is explicitly escalated.
- [ ] Test or smoke evidence can observe behavior without asserting that files merely changed.
- [ ] The design does not add an unrequested provider, network call, permission, or deployment action.

## Decision

- Decision: <approved|revise|rejected>
- Review evidence: <METADATA_ONLY_REVIEW_REFERENCE>
- Open risks and owners: <NONE_OR_REDACTED_RISK_LIST>

## Handoff to implementation planning

The planner receives the approved design, its invariants, failure policy, and review decision.
Set `Status: approved` only when the reviewer has recorded the decision and every requirement is
mapped; otherwise high-risk implementation readiness remains blocked.
