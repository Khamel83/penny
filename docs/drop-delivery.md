# Drop delivery operations

Penny hands one text artifact and allowlisted metadata to the existing Drop
intake. A matching `stored` receipt ends submission ownership; `retryable=true`
with `stored` means Drop owns queue reconciliation, not that Penny should resend.
OCI archival and Slack/Maya delivery remain separate evidence.

Runtime `PENNY_DROP_ENABLED=true` and `PENNY_DROP_TOKEN` enable the sender.
Neither activates capture ownership by itself. After a synthetic end-to-end
proof, `scripts/export_drop.py --activate --apply` atomically freezes a canonical
ID cutoff. Future iCloud Voice Memo rows belong to Drop; existing rows retain
their delivery owner. The operation is idempotent and does not move the cutoff.
Do not edit its database fields to perform an improvised rollback.

`scripts/export_drop.py` defaults to a read-only historical inventory.
`--apply --limit 50` queues a bounded historical batch without sending it.
`--drain --apply --limit 50` sends queued text through the runtime token.
`--reconcile --apply` looks for exact archived bytes for uncertain handoffs.
Run bounded passes until counts reconcile. Historical records always suppress
Slack notifications and never replay old Apple/Maya/Hermes actions.

Payloads and receipts persist in the canonical SQLite ledger. A send intent is
committed before network work. Lost/malformed responses and expired claims are
uncertain, not unsent. Automatic read-back can resolve a matching archived copy;
absence cannot prove failed edge acceptance. Unresolved attempts need operator
review, not a bulk resend. Doctor reports the count and age without raw text.

Drop uses the existing Maya reader and a separate supervised Slack reader.
Penny's old direct Slack sender remains available for an explicitly reconciled
fallback only. Before fallback, stop the Drop Slack reader and check its receipt
ledger. Never enable two senders for the same memo. Preserve every ledger,
archive and cursor during rollback.

Permission boundary: the owner approved transcript text and metadata to ordinary
Drop, Slack and Maya. Audio, credentials and local paths remain local. This
does not grant access to Drop private collections or authorize captured actions.
