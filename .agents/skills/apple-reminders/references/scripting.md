# Reminders scripting

The installed dictionary is normally at
`/System/Applications/Reminders.app/Contents/Resources/Reminders.sdef`. Inspect
it before adding fields to an adapter; full Xcode is not needed to read the XML.

Useful terms: account `id`/`name`/`lists`, list `id`/`container`/`reminders`, and
reminder `id`/`container`/`name`/`body`/`completed`/`completion date`/`due date`/
`allday due date`/`remind me date`/`priority`/`flagged`.

The current dictionary says `due date` sets date and time; `allday due date`
sets only the date. Do not collapse these or assume setting a due date proves
notification delivery. Use explicit date components/time zone handling rather
than locale-dependent string parsing. Read back every requested date field.
Recurrence and advanced subtasks are not exposed in this dictionary; inspect
and use the actual GUI for these features when requested.

After resolving the exact target list, a simple create uses
`make new reminder at end of targetList with properties {name: taskTitle, body: taskBody}`.
Retain the operation marker in the body. Return its ID and read the item back
independently. For edits, resolve the existing item by ID before setting only
requested properties. New fallback-list behavior requires a project decision;
it is not inherited from another project's Inbox policy.

Pass inputs via AppleScript `on run argv` or private UTF-8 files with a subprocess
argument list. Bound calls; do not interpolate content into shell or AppleScript
source. Keep task content and provider output local.

This skill does not install a new delivery engine. A new project's adapter
needs its own authorized write/readback acceptance before unattended use.
For Penny, see [the existing binding](../../apple-effects-reliability/references/penny.md);
its simple creation helper does not implement scheduling.
