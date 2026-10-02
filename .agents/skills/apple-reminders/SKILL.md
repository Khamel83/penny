---
name: apple-reminders
description: Read, find, create, update or complete Apple Reminders on macOS for the requesting project, with exact list targeting and verified task fields. Use for native Reminders tasks and scheduling requests.
---

Read [the project contract](../apple-apps/references/project-contract.md) before
automated writes or binding a new project. Keep targets and receipts project-owned.

1. Resolve the account/list and existing reminder ID when editing or completing.
   Confirm list ID and account; names may repeat. A fallback list must be part
   of the project policy or request, and its actual identity goes in the receipt.
2. For a new caller, run the Reminders probe in
   [apple-effects-reliability](../apple-effects-reliability/SKILL.md), then read
   the exact target. Reminders-data permission is separate from Automation.
   App name/version success is not evidence of reminder/list access.
3. Use the project's existing adapter for its supported fields. For AppleScript,
   read [Reminders scripting details](references/scripting.md). Use computer
   use for fields absent from the dictionary, such as a requested recurrence;
   do not silently omit those fields or substitute a simple task.
4. Apply only the requested fields. Resolve date-only versus timed reminders
   and the intended time zone before setting a date. Complete or edit by ID,
   not by the first matching title. Preserve unrelated task fields.
5. Read the reminder by ID and verify actual list/account, title/body, completed
   state and all requested scheduling fields. Reconcile a create's operation
   marker and save the project receipt. A timeout after a write is uncertain;
   use the reliability skill before creating another copy.

Completion means the saved task and requested fields agree with the receipt.
A due date readback does not independently prove a notification will fire.
