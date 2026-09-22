# Drop delivery operations

## Production status — 2026-09-22

Penny implementation `f915d99` is pushed and installed in all five launch
agents. Drop's supervised Slack reader is installed. Capture ownership remains
disabled: existing live memos still use Penny's existing delivery path. No real
transcripts have been transferred through the new outbox.

Two synthetic artifacts (418 and 364,331 bytes) received intake acceptance,
matching OCI archive hashes, and Maya source-event receipts. The live checks
found and fixed the intake's named User-Agent requirement and Slack file
metadata form encoding. Tests after these changes: Penny 670 passed, 2 skipped;
Drop 187 Python and 30 Worker tests passed.

**Do not run `--activate` or historical `--apply` yet.** Maya's existing
`/ingest/drop` classifier treats the metadata-line/text envelope as malformed
JSON, stores it as `needs_attention` with action route `none`, and queues a
`maya.notice`. Historical flags suppress the Drop Slack reader, not Maya's
independent notices. A backlog import would therefore violate the quiet-import
contract. The approved plan excluded Maya ingestion changes; extend that scope
before changing its API/runtime. Required behavior is verified envelope-aware,
store-only ingestion, with no actions or notices, retaining exact original
bytes and replayable source receipts. Do not strip metadata as a workaround.

Historical inventory: 320 actual-text iCloud records eligible; 167 missing-text
or error records excluded. This is an inventory, not an import receipt.
Existing Apple/Maya/source-history readiness exceptions remain separate from
the new Drop handoff. Synthetic proof is not a newly captured real-memo proof.

## Operation after the production gate

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
Run bounded passes until counts reconcile. Historical records suppress the
Drop-owned Slack notification. Maya must first meet the quiet-storage gate
above; do not assume the historical flag alone prevents its side effects.

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
