# Drop delivery operations

## Production status — 2026-09-22

Review decisions and deferred test coverage are in the
[release decision record](drop-release-decisions.md).

Penny's Drop implementation is pushed and installed in all five launch agents.
Capture ownership is active at canonical ID **755**: future iCloud Voice Memos
use Drop; older direct-delivery receipts remain intact. Drop's supervised Slack
and Maya readers are installed. Maya API and scheduler both run pushed commit
`36eb6b40f49c8468a2c4578238bea405e0a0bd2a` with healthy API/storage readiness.

Two synthetic artifacts (418 and 364,331 bytes) received intake acceptance,
matching OCI archive hashes, and Maya source-event receipts. The live checks
found and fixed the intake's named User-Agent requirement and Slack file
metadata form encoding. Final Penny suite: 674 passed, 2 skipped, 53 subtests.
Drop: 198 Python and 30 Worker tests passed; seven monitor fixture tests passed.

The initial canaries exposed unwanted Maya notices. The owner approved a narrow
Maya fix: strict envelope validation in the existing ingest endpoint, exact
original bytes and metadata, information/no-action classification, and a
replayable `capture_policy=store_only` receipt. No schema migration or second
reader was added. The original synthetic receipts remain unchanged evidence.

New live-style and historical synthetic notes both passed archive hashes and
Maya receipt/raw/file/object/extracted-text verification. Related notice/task
outbox and URL-acquisition counts were zero. Slack short-note read-back matched
text, emoji and bot; history was suppressed with no message. Replaying both
against an isolated copy of the Slack ledger made zero Slack API calls.
Both new synthetic files were also retrieved through Maya's authenticated
`/files/{id}/content` route with hashes matching Drop's archive.

Drop's existing Maya reader now refuses to advance past a Penny item without
the matching store-only receipt. Permanent refusals also hold the cursor. The
existing monitor exposes a stuck reader; Slack remains independent. A bad item
can delay later Maya items until repaired, rather than silently dropping one.

Historical import verified: **320/320** actual-text iCloud records accepted by
Drop, **320/320** archived with matching bytes/hashes, **320/320** verified in
Maya (receipt/raw/file/object/extracted-text/metadata), and **320/320** suppressed
in Slack. No related Maya notice/task outbox or URL-acquisition rows. Penny's
outbox has zero pending, sending, failed or uncertain rows. A final export dry-run
reports 320 already queued, 167 migration placeholders excluded, and zero new
live-owned rows. No new real memo arrived during verification; the real-capture
gate remains observational, separate from successful synthetic delivery proof.
The real-text rows retain 179 `passed`, 110 `pending`, and 31 `needs_review`
quality labels; importing text does not upgrade its transcription quality.
Existing Apple/Maya/source-history readiness exceptions remain separate from
the new Drop handoff. Synthetic proof is not a newly captured real-memo proof.

Maya's focused release checks passed (46 tests). Its full suite was **not green**:
4,125 passed, 28 failed, 48 skipped. Twenty-seven legacy Hermes/execution failures
were reproduced with unchanged ingestion; one subprocess timing failure passed
in isolation. Existing format/schema-drift exceptions are recorded in Maya's
`.audit/evidence/penny-quiet-storage-2026-09-22.json`. No retired behavior was
reactivated to satisfy old tests. Penny's global readiness also retains its
older terminal-source, Apple quarantine and direct-Maya dead-letter exceptions.

**Separate retrieval limitation:** a broad synthetic `/search` request timed out
after 30 seconds. Read-only `EXPLAIN` shows a parallel sequential scan that builds
text vectors over `ingested_files`; live index inventory contains only the primary
key and channel/Slack-ID/created-time indexes, not a full-text index. Direct
authenticated file retrieval succeeds. No search/index migration was attempted
under this narrow store-only ingestion approval. API `/readyz` reports healthy,
but that does not establish usable broad-search latency. A search performance fix
is a separate open item, not hidden by the successful ingestion receipts.

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
Drop-owned Slack notification. Maya's independent store-only receipt is required;
do not assume the historical flag alone prevents its side effects.

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

## Routine verification

Check the installed Penny `/ready` response, not a CLI process with missing
runtime environment. The `drop` component reports pending/uncertain counts and
age; old direct-Maya/source/Apple exceptions remain separate. In Drop, run
`python3 scripts/check_app_reading.py slack 10` and the same command for `maya`.
An active systemd unit alone is insufficient. The monitor fixtures verify stuck
and recovered states without breaking live credentials.

For a named item, compare Penny's frozen payload hash/intake receipt against
Drop's archived bytes; then check the Slack identity state and Maya's stable
source-event receipt. Maya requires matching bytes, metadata and `store_only`.
If an attempt is uncertain, investigate that identity only; never resend the
whole archive. Source code on main is not deployment: verify Penny's five loaded
source revisions, Drop's installed file hashes, and both Maya container images.
Deployment uses the installed export command and environment for its backup,
including the concurrent approved SSD mount guard and placement. It does not
recreate backup staging at the retired default path. See
[SSD backup placement](ssd-backup-placement.md). An earlier verification run
before this concurrent change was discovered left a verified default-path backup;
it is retained, not used as the active backup receipt or silently deleted.

Permission boundary: the owner approved transcript text and metadata to ordinary
Drop, Slack and Maya. Audio, credentials and local paths remain local. This
does not grant access to Drop private collections or authorize captured actions.
