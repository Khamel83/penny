# Penny binding

Use this reference only in a Penny checkout. Keep Penny's canonical Apple-effect
ledger, reserved operation keys, marker format and installed caller identity.
Do not import its secrets or transcript database into another project.

Existing `reminders.find_note_by_marker` and `find_reminders_by_marker` support
item reconciliation. The latter searches requested and configured fallback lists
and returns actual target/provider identity. Creation helpers and the
`apple_effects.py` orchestrator retain the existing delivery policy. Generalized
skill instructions do not alter legacy markers or authorize a ledger migration.

Penny Doctor's provider_failure can derive from failed historical effect rows;
it is not a live provider RPC check. Verify live access and existing item/receipt
separately, preserving failed-cap, uncertain and quarantined rows until a specific
repair is authorized. Update TODO.md, CONTEXT.md and HANDOFF.md with fresh evidence.
