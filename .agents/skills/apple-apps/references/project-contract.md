# Project binding and receipts

Resolve these fields from the request and project configuration. Ask only for
missing information that changes the target or requested action.

| Field | Meaning |
| --- | --- |
| project | Stable project namespace; never inferred from Penny's defaults |
| operation_id | Stable ID for this action, reused when reconciling a retry |
| action | Read, create, append, update, complete or delete, as authorized |
| target | App, account and folder/list IDs; use confirmed names to discover IDs |
| item_id | Existing provider ID for an update, completion or deletion |
| payload | Requested fields; local file for private or multiline content |
| caller | Host/user, executable and shell/SSH/launchd/GUI route |
| receipt_path | Private project-owned state location, separate from credentials |

Native macOS grants follow the responsible caller and logged-in user, not the
project name or copied environment. A successful terminal call does not prove
an unattended caller can access the same app. Automation, Reminders data,
Accessibility and screen capture are distinct checks. Use only the grants the
chosen route needs; a missing grant remains an access boundary for the owner.
An account named "iCloud" on a second Mac is not proof of the same target ID.

## Mutation and recovery

For a queued operation, use the project's existing ledger/lock. Reserve the
operation before sending it. Keep one active writer per operation. For an
interactive one-off, retain a private request/receipt instead of installing a
queue or daemon. Skills do not supply a new background delivery engine.

Record project, operation ID, requested action/target, a hash of the requested
payload, caller, time, state, provider ID, actual target and readback result.
Keep payloads and full item bodies local. Public evidence can contain counts,
status, timing and source identity without personal content.

- For a marked create, use the project's existing marker format. A new project
  can use `apple-effect:<sha256(canonical JSON [project, operation_id])>` as a visible body marker.
  A marker helps reconciliation; it does not enforce a unique constraint.
- Reconcile the same ID/marker in the exact target before another create.
  One matching item with matching requested fields can close delivery. Multiple
  matches or conflicting fields require resolution before another write.
- Treat a timeout after sending a write as uncertain. Preserve the request and
  inspect the item before deciding whether a retry is safe. A bounded process
  timeout does not roll back an operation already received by the app.
- Use explicit failed/uncertain/verified states. A provider-returned ID is an
  acknowledgement; verify its target and requested fields separately. Save
  that result durably before declaring the operation delivered.
- Use the authorized action's scope for recovery. Permission to create one
  reminder is not permission to reset a project ledger or replay old captures.

## GUI route

Use the computer-use tool's supplied APIs and current accessibility state.
If the environment's desktop skill requires a handover, apply that requirement
before mouse/keyboard input. Existing task authorization covers its requested
app action; it does not grant permission to change privacy settings or accounts.
Inspect prompts first, then verify fresh calls after the owner resolves access.
CUA, Peekaboo local execution and Peekaboo Bridge may have different identities.
Do not substitute a failed System Events window query for the available native
accessibility tool's state.
