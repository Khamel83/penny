# Implementation plan artifact

Plan ID: <PLAN_ID>
Stage: implementation-plan
Status: draft

## Inputs

- Requirements: `.penny/workflow/plans/<PLAN_ID>/requirements.md`
- Approved design: `.penny/workflow/plans/<PLAN_ID>/design-review.md`
- Base revision: <BASE_COMMIT_SHA>
## Outputs

- Executable task list with concrete files, behavioral checks, and handoffs.
- Handoff: task brief paths, approved inputs, and base revision for execution.


## Global constraints

- Preserve Penny's local-first ledger-before-work ordering.
- Keep capture content, credentials, provider responses, and private paths out of artifacts and tool prompts.
- Do not alter runtime behavior outside the approved acceptance criteria.
- Every task has one bounded scope, one behavioral check, and one explicit handoff.

## Executable tasks

| Task ID | Files allowed | Behavior to change | Check | Handoff |
| --- | --- | --- | --- | --- |
| <TASK_ID> | `<PATH_1>`, `<PATH_2>` | <OBSERVABLE_BEHAVIOR> | `<TEST_OR_SMOKE_COMMAND>` | <NEXT_ARTIFACT_AND_DATA> |
| <TASK_ID> | `<PATH_1>` | <OBSERVABLE_BEHAVIOR> | `<TEST_OR_SMOKE_COMMAND>` | <NEXT_ARTIFACT_AND_DATA> |

For every task, write a `tasks/<TASK_ID>.md` artifact from the subagent template before dispatch.
A task is not executable if its files, behavior, check, or handoff is a placeholder.

## Verification sequence

1. Run the required RED check before implementation.
2. Implement the smallest change allowed by this plan.
3. Run the GREEN check and relevant focused suite.
4. Review the plan-scoped diff and evidence.
5. Run final verification only after code review is approved.

## Handoff to execution

The executor receives this file, the approved requirements/design paths, task briefs, and the base
revision. Set `Status: executable` only after all tasks contain concrete paths, behavioral checks,
and handoffs; high-risk `gate` refuses any other status.
