# Reminders automation recovery — October 2, 2026 UTC

## Current verified state

The original read-only list query timed out after10/12 seconds while Reminders
name/version queries returned in0.05s. Computer use showed a What's New dialog;
the owner then reported fixing the app. The dialog disappeared, but the next
shell and equivalent-launchd list queries still timed out. Dismissal alone was
not established as the repair.

TCC metadata showed a pending `kTCCServiceReminders` prompt attributed to Ghostty,
without a completed result in that observation. System Settings later showed
Ghostty and Python Reminders-data grants enabled. No agent privacy toggle was
changed. Subsequent privacy metadata recorded a completed authorization result;
the exact owner's action is not known, so do not claim which click caused recovery.
The evidence supports a pending Reminders-data permission gate over the earlier
system-wide Apple Events outage theory. Metadata queries are not a data-access test.

At06:50:47 the identical shell list query returned in0.242s. Equivalent launchd
job using the installed watcher executable/environment returned in0.135s at
06:51:57; Notes also passed0.142s, while Finder window count still timed out12s.
The temporary diagnostic LaunchAgent was removed. A read-only native EventKit
comparison had existing full access and returned12 calendars without requesting
permission. No EventKit replacement or alternate delivery adapter was installed.

One existing successful reminder was read back through Penny's actual marker
helper: one marker match with the same provider ID and actual target as its
canonical succeeded receipt. The ledger contains9 succeeded reminder effects
and zero reserved/in-flight reminder effects at the pre-recovery observation.
No reminder/note was created, deleted, marked complete, replayed or reset.
This is current reachability and one existing-item receipt evidence; a new
natural capture/write/archive/downstream acceptance remains a separate boundary.
Penny's capped failed note and synthetic note quarantine remain unchanged.

## Tools and learning

Native CUA accessibility exposed the dialog and privacy panel; the agent only
navigated settings and changed no grants. UI input followed the owner's handover.
Peekaboo is installed and its Bridge query succeeds. Its forced-local CLI probe
reported ungranted local screen/accessibility permissions while the corresponding
host app grants were enabled: local, Bridge-host and CUA identities must be
checked separately. screenctl's AppleScript enumeration timed out(-1712); native
accessibility inspection still worked. No system/app process restart, SIP/TCC
reset, shared ASR change or machine reboot was needed or performed.

The installed/versioned apple-effects-reliability skill now includes separate
Reminders-data/Automation gates, privacy prompts as a timeout cause, metadata
versus data query distinction, equivalent caller testing, and GUI tool identity.
No new monitoring timer was installed. The core probe code is unchanged.

## Recheck

```sh
python3 ~/.codex/skills/apple-effects-reliability/scripts/probe_providers.py --apps notes reminders
venv/bin/python ~/.penny/recovery/20261002-reminders-diagnostic/receipt-readback.py
```

The original receipt-readback script refuses to overwrite its saved receipt;
use a fresh output filename if repeating it. Do not mistake that safeguard for
provider failure. Safe private evidence/scripts live under
`~/.penny/recovery/20261002-reminders-diagnostic/`: differential-probes,
after-owner-action, after-privacy-panel-inspection, launchd-provider-probe,
launchd-recovery-probe, eventkit-readonly, receipt-readback and TCC metadata.
Raw personal UI/item content is not committed.

[Apple Reminders-data permission guidance](https://support.apple.com/en-nz/guide/mac-help/mchlac845f4c/mac)
is separate from [Automation permission](https://support.apple.com/en-ph/guide/mac-help/mchl07817563/mac).
