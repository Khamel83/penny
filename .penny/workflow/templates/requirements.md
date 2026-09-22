# Requirements artifact

Plan ID: <PLAN_ID>
Stage: requirements
Status: draft
Risk: <low|medium|high|critical>

## Inputs

- Request or issue: <ISSUE_OR_REQUEST_ID>
- Current contract read: `README.md`, `docs/reliability.md`, and <OTHER_RELEVANT_DOCS>
- Existing behavior/evidence: <METADATA_ONLY_REFERENCE>
## Outputs

- Approved requirements artifact with risk, invariants, acceptance checks, and privacy boundary.
- Handoff: requirements path plus acceptance IDs for design review.


## Required behavior

- Problem: <ONE_SENTENCE_PROBLEM>
- User-visible or operator-visible outcome: <OBSERVABLE_OUTCOME>
- Invariants that must remain true: <DURABILITY_PRIVACY_IDEMPOTENCY_INVARIANTS>
- Explicit non-goals: <NON_GOALS>

## Acceptance checks

| ID | Observable behavior | Check command or scenario | Evidence reference |
| --- | --- | --- | --- |
| R1 | <BEHAVIOR> | `<COMMAND_OR_SCENARIO>` | <EVIDENCE_REF> |
| R2 | <BEHAVIOR> | `<COMMAND_OR_SCENARIO>` | <EVIDENCE_REF> |

## Privacy boundary

- Sensitive inputs remain local: <YES_OR_NO_AND_BOUNDARY>
- Allowed metadata shared with tools/agents: <REDACTED_METADATA_ONLY>
- Forbidden data: raw audio, transcript text, credentials, tokens, provider bodies, and personal URLs.

## Handoff to design review

The design reviewer receives this approved artifact, its risk classification, the acceptance checks,
and the explicit non-goals. Set `Status: approved` only after the requirements are complete and
reviewable; otherwise the implementation gate must remain closed.
