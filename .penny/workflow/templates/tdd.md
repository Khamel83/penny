# Red/green TDD artifact

Plan ID: <PLAN_ID>
Stage: tdd
Status: draft

## Inputs

- Task: <TASK_ID>
- Plan: `.penny/workflow/plans/<PLAN_ID>/implementation-plan.md`
- Behavioral requirement: <REQUIREMENT_ID_AND_BEHAVIOR>
## Outputs

- Plan-scoped red/green evidence, or an approved smoke-test exception.
- Handoff: behavioral evidence references for code review.


## RED — failing behavioral check

- Check: `<TEST_COMMAND_OR_SMOKE_COMMAND>`
- Expected observable behavior: <EXPECTED_BEHAVIOR>
- Observed failure: <REDACTED_FAILURE_CLASS_AND_ASSERTION>
- Why this proves the check is valid: <MISSING_BEHAVIOR_NOT_TYPO>
- RED evidence: <RED_EVIDENCE_REF>

Do not record capture bodies, transcript text, credentials, provider responses, or unredacted paths.

## GREEN — minimal fix

- Implementation boundary: <ALLOWED_FILES_AND_SYMBOLS>
- Check: `<TEST_COMMAND_OR_SMOKE_COMMAND>`
- Observed pass: <PASS_COUNT_OR_METADATA_RESULT>
- Focused regression suite: `<COMMAND>`
- GREEN evidence: <GREEN_EVIDENCE_REF>

## Smoke-test exception

Use this only when a permanent test is inappropriate (for example, an operator-only integration
boundary). Record why a test cannot safely or deterministically exist, the exact bounded smoke
scenario, its metadata-only expected/observed result, and approver <REDACTED_APPROVER_ID>.

- Exception approved: <yes|no>
- Approver: <REDACTED_APPROVER_ID>
- Reason: <JUSTIFICATION>
- Scenario: <COMMAND_OR_STEPS_WITHOUT_PRIVATE_DATA>
- Observed result: <METADATA_ONLY_RESULT>
- Smoke evidence: <SMOKE_EVIDENCE_REF>

## Handoff to review

Set `Status: complete` only when the same behavioral check has a recorded RED failure before the
fix and GREEN pass after it, or the documented smoke-test exception is approved. Code review
receives both evidence references and the plan/task IDs.
