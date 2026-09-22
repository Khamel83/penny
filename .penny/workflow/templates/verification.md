# Final verification artifact

Plan ID: <PLAN_ID>
Stage: verification
Status: draft
Evidence command: <OBSERVED_COMMAND>
Evidence result: <OBSERVED_RESULT>

## Inputs

- Requirements: `.penny/workflow/plans/<PLAN_ID>/requirements.md`
- Approved design: `.penny/workflow/plans/<PLAN_ID>/design-review.md`
- Executable plan: `.penny/workflow/plans/<PLAN_ID>/implementation-plan.md`
- Approved review: `.penny/workflow/plans/<PLAN_ID>/code-review.md`
- Head revision: <HEAD_COMMIT_SHA>
## Outputs

- Plan-scoped release decision and evidence matrix with unproven boundaries called out.
- Handoff: verification artifact for the parent issue or next operator.


## Evidence matrix

| Boundary | Check | Observable result | Evidence reference |
| --- | --- | --- | --- |
| Requirements | `<COMMAND_OR_REVIEW>` | <RESULT> | <EVIDENCE_REF> |
| Behavioral | `<TEST_OR_SMOKE_COMMAND>` | <RED_GREEN_OR_EXCEPTION_RESULT> | <EVIDENCE_REF> |
| Repository | `<FOCUSED_TEST_OR_TRUST_COMMAND>` | <RESULT> | <EVIDENCE_REF> |
| Local receipt/archive | `<METADATA_ONLY_CHECK>` | <RESULT_OR_NOT_APPLICABLE> | <EVIDENCE_REF> |
| Runtime state | `<READ_ONLY_CHECK>` | <RESULT_OR_UNPROVEN> | <EVIDENCE_REF> |
| Provider state | `<READ_ONLY_CHECK>` | <RESULT_OR_UNPROVEN> | <EVIDENCE_REF> |
| Downstream delivery | `<READ_ONLY_CHECK>` | <RESULT_OR_UNPROVEN> | <EVIDENCE_REF> |

A passing local test does not prove launchd registration, macOS privacy permission, provider receipt,
or downstream delivery. Mark each unexercised boundary `unproven` or `not_applicable`; never infer
it from another receipt.

## Completion decision

- Decision: <verified|blocked|rollback_required>
- Unresolved risk: <NONE_OR_BOUNDED_RISK>
- Handoff: <NEXT_OPERATOR_OR_PARENT_PLAN_REFERENCE>

Set `Status: verified` only after every applicable row has an observable command/result and the
approved code review is linked. `scripts/penny_workflow.py verify` checks this plan-scoped state.
