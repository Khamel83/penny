---
name: apple-effects-reliability
description: Diagnose macOS Notes or Reminders automation failures and verify delivery receipts before recovery or retries. Use when Apple Events timeouts, permission errors, or Penny Apple-effect readiness failures need investigation.
---

Separate live provider reachability, durable delivery state, and actual item readback.
A failed effect ledger can keep Penny Doctor unready after the provider recovers.
An app's running PID, responsive UI, or successful account query is insufficient
proof that a particular note or reminder was delivered.

1. Run `python3 scripts/probe_providers.py --apps notes reminders --output <new-private-receipt.json>`
   from this skill's directory. The helper sends bounded read-only AppleScript
   queries and prints safe status codes. It may launch an app or show a macOS
   Automation prompt. It creates no notes/reminders and changes no permissions.
   Record caller context; a shell probe does not establish launchd/SSH permission.
2. Identify the real caller executable, launchd owner, target account/folder/list,
   and existing delivery ledger. Recheck from an equivalent installed caller
   context if results differ. Loading environment variables alone does not
   reproduce its Automation identity. Keep credentials and provider content local.
3. For an outstanding effect, read its existing marker/provider ID in its original
   target and compare stored payload identity. Preserve success, failed-cap,
   uncertain, and quarantined history. An absent marker is not a delivery receipt;
   a different account or folder can give a false absence. Do not write a test
   item into personal data unless that narrow action is authorized.
4. Choose recovery from the measured failure. `permission_denied` (-1743) calls
   for inspection of the actual caller's Automation grant. A process timeout or
   Apple-event timeout (-1712) is not evidence of denied permission. Check an
   independent target before blaming system-wide transport. Use ordinary app
   quit/reopen only when active work is safe; then rerun the same probe.
   The protected system Apple Events kickstart is rejected with error150 under
   SIP on this Mac even after sudo authentication. Do not recommend disabling
   SIP, resetting TCC, or killing protected daemons to bypass that failure.
   A normal Mac restart is a candidate for persistent transport failure, after
   coordinating shared ASR jobs and other active work; it is not a proven fix.
5. Retry only the particular effect when its caller permission, exact target,
   payload identity, absence/presence, idempotency policy, and existing task
   authorization support it. Never reset a retry cap or uncertain/quarantined
   row merely to make readiness green. Do not replay a capture to repair one
   projection. Confirm provider ID/marker readback and durable receipt separately.

Report app-by-app live probe results, caller context, ledger disposition, item
readback, mutations performed, and the next unresolved boundary. For Penny,
update TODO.md, CONTEXT.md and HANDOFF.md with fresh evidence; preserve dirty files.
Use existing `reminders.find_note_by_marker` / `find_reminders_by_marker` and the
Apple-effect ledger instead of creating a second delivery integration.

Validate reachability with the same bounded probe after recovery. Close delivery
only after the requested target/item and durable receipt agree. Do not generalize
one successful probe to permanent macOS reliability.

References: [Apple SIP](https://support.apple.com/en-gb/102149),
[Apple Automation permissions](https://support.apple.com/en-ph/guide/mac-help/mchl07817563/mac),
[normal restart](https://support.apple.com/en-au/guide/mac-help/mchlp2522/mac).
