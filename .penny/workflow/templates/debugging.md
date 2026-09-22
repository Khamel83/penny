# Systematic debugging artifact

Plan ID: <PLAN_ID>
Stage: debugging
Status: draft

## Inputs

- Symptom or failing check: <REDACTED_SYMPTOM_CLASS>
- Affected task: <TASK_ID>
- Relevant revisions/config metadata: <REDACTED_METADATA>
## Outputs

- Reproduction and root-cause record with a bounded fix boundary.
- Handoff: root-cause evidence for implementation and red/green evidence for review.


## Phase 1 — reproduce and investigate

- Reproduction command/scenario: `<COMMAND_OR_SCENARIO>`
- Reproduction count/result: <BOUNDED_METADATA_RESULT>
- Complete error class/code: <ERROR_CLASS_NOT_PRIVATE_MESSAGE>
- Evidence gathered at each boundary: <BOUNDARY_EVIDENCE_REFS>
- Data-flow origin: <FIRST_BAD_STATE_OR_INPUT_CLASS>

## Phase 2 — pattern analysis

- Working analogue: <PATH_AND_SYMBOL>
- Difference list: <CONCRETE_DIFFERENCES>
- Dependency/config assumptions: <ASSUMPTIONS>

## Phase 3 — hypothesis

- Single hypothesis: <ROOT_CAUSE_AND_WHY>
- Minimal experiment: `<COMMAND_OR_SCENARIO>`
- Result: <OBSERVED_METADATA_RESULT>

## Phase 4 — fix and regression evidence

- Root-cause fix boundary: <ALLOWED_FILES_AND_SYMBOLS>
- RED evidence: <TDD_RED_EVIDENCE_REF>
- GREEN evidence: <TDD_GREEN_EVIDENCE_REF>
- Remaining uncertainty: <NONE_OR_BOUNDED_UNCERTAINTY>

## Handoff

Set `Status: complete` only after the root cause is supported by reproduction and a minimal
experiment. The implementation plan receives the fix boundary; TDD and code review receive the
red/green evidence. Do not propose a symptom-only workaround.
