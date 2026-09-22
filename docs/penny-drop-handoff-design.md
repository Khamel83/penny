# Penny to Drop production handoff

Status: proposed implementation contract; not deployed.

## Approved intent

Penny captures and transcribes locally. It submits transcript text and bounded
metadata to Drop through the existing intake. Audio, local paths and credentials
never enter the payload. Drop owns subsequent Slack and Maya delivery. Penny
retains its original audio, canonical ledger and backups.

## Minimal implementation

- Add a durable Penny Drop outbox using existing ledger/worker conventions.
  Persist canonical transcript identity, payload hash and exact outgoing bytes
  before sending. Include recording time when known, duration, quality state,
  producer and historical-import flag. Do not invent missing metadata.
- Use Drop's existing text intake and metadata contract. Validate its JSON
  receipt, not HTTP 200 alone. A successful intake proves durable edge staging,
  not OCI archival or Maya delivery. Record these boundaries separately.
- Retain ambiguous attempts for reconciliation; do not blindly resend after a
  timeout. Drop currently assigns a new identity to each submission. Use the
  producer identity and content hash to reconcile archived items before an
  operator-authorized retry when acceptance remains uncertain.
- Add one Drop-owned Slack reader using the existing reader helper and Home
  Lab vault-backed Slack credential. Read only Penny items, keep an independent
  cursor and durable per-item/per-part Slack receipts. Handle long text without
  truncation; keep failures visible and retryable. Uncertain Slack writes must
  be reconciled before replay, not assumed unsent.
- Reuse the existing Drop Maya reader. Do not add another Maya integration.

## Safe cutover and historical import

Prove a labeled synthetic transcript through intake, archive, Slack and Maya
first. Then use an explicit capture cutoff so each live memo has exactly one
Slack delivery owner. Retain Penny's old Slack sender as a disabled, controlled
fallback; do not run independent automatic senders for the same memo. Disable
new direct Maya deliveries at cutover while retaining existing receipts and
unresolved rows for reconciliation.

Import existing real voice-memo transcripts with the historical flag and their
quality labels. Exclude missing-text placeholders. Historical items enter Drop
and Maya but produce no Slack flood and never execute old instructions.

## Health and completion

Penny monitors pending/uncertain Drop handoffs and their ages. Drop monitors its
registered readers independently. A Maya failure must not block Slack or vice
versa. Report intake acceptance, archive receipt, Slack message receipt and
Maya receipt separately. No test result substitutes for live receipts.

Completion requires tests, pushed changes, verified installed revisions, a
successful live canary, reconciled historical import counts, and preserved
rollback state. Leave production unchanged if any required boundary is unproven.

## Verified prerequisites and constraints

The Home Lab Slack credential passed auth.test. conversations.info confirmed
membership in the active penny channel (C0BKS0QT7FU). Returned scopes include
chat:write, files:write, channels:history and channels:read. This establishes
access, not a successful transcript post. Both drop-maya-reader.service and
drop-watch.timer are active. Existing Drop Slack code sends health alerts;
there is no registered transcript Slack reader.

Drop's working tree contains unrelated in-progress access-control changes.
Do not modify, commit or deploy those changes with this work. Implement in an
isolated worktree and reconcile the current deployed contract before release.
