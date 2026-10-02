# Notes scripting

The installed dictionary is normally at
`/System/Applications/Notes.app/Contents/Resources/Notes.sdef`. Read it for the
current app when changing a scripted operation. Reading this file works with
Command Line Tools even when `sdef` requires full Xcode.

Useful dictionary terms: application `accounts`, account `id`/`name`/`folders`,
folder `id`/`container`/`notes`, note `id`/`container`/`body`/`plaintext`/
`password protected`/`shared`. The note body is HTML; plaintext is read-only.
The name is normally the first line of the body. Nested folders need an account
and full parent path when resolving a human-readable target.

For a plain-text create, HTML-escape the title and content locally, convert
line breaks to HTML, and include the escaped title at the start of the body.
Keep an operation marker in visible text; an HTML comment alone may be stripped.
Use `make new note at targetFolder with properties {body: preparedHTML}` after
resolving that exact folder. Record the returned ID, then independently read
its container and plaintext. Compare meaningful text, since Notes may normalize
HTML and formatting. Preserve a pre-edit body hash for conflicting edits.

Pass dynamic inputs through AppleScript `on run argv` arguments or private
UTF-8 files, using a subprocess argument list. Do not interpolate note content
into shell commands or AppleScript source. Bound each call with a subprocess
timeout; a timed-out write remains uncertain. Keep output containing note bodies
in private files rather than the public tool transcript.

This skill provides a workflow, not a separately installed Notes write backend.
Use the existing project transport or an operation-specific script derived from
the current dictionary. A new adapter needs its own authorized write/readback
acceptance before unattended use. In Penny, see
[the existing adapter binding](../../apple-effects-reliability/references/penny.md).
