# Bounded subagent task artifact

Plan ID: <PLAN_ID>
Stage: subagent-task
Task ID: <TASK_ID>
Status: assigned

## Inputs

- Requirements: `.penny/workflow/plans/<PLAN_ID>/requirements.md`
- Design: `.penny/workflow/plans/<PLAN_ID>/design-review.md`
- Plan task: `.penny/workflow/plans/<PLAN_ID>/implementation-plan.md#<TASK_ID>`
- Prior handoff: <PLAN_SCOPED_ARTIFACT_OR_NONE>
## Outputs

- Bounded task result containing changed paths, behavioral evidence, and remaining risks.
- Handoff: next-stage artifact path and metadata-only evidence references.


## Scope contract

- Allowed files: `<PATH_1>`, `<PATH_2>`
- Allowed symbols/behavior: <EXACT_BOUNDARY>
- Required behavioral check: `<COMMAND_OR_SCENARIO>`
- Out of scope: <EXPLICIT_NON_GOALS>
- No subdelegation: <yes>

## Privacy and permissions

The worker may use only redacted metadata needed for this task. It must not access, print, transmit,
or persist raw audio, transcript text, provider response bodies, credentials, tokens, private URLs,
or personal identifiers. It has no permission to send external effects, change credentials, deploy, push,
or merge. Use `<CAPTURE_ID_REDACTED>` and `<EVIDENCE_REF>` placeholders.

## Required handoff

- Changed paths: <PATHS_ONLY>
- Behavioral evidence: <RED_GREEN_OR_SMOKE_EVIDENCE_REF>
- Remaining risks: <NONE_OR_BOUNDED_RISKS>
- Next artifact/stage: <NEXT_STAGE_AND_INPUTS>

Set `Status: complete` only after the allowed-scope check and behavioral evidence are recorded.
The coordinator must inspect the diff and evidence; a worker's completion message is not proof.
