# Penny → Drop → Slack: delivery research

Research date: 2026-09-21 (session date). Scope: official public documentation and
repository contracts only; no private runtime inspection, authenticated API
calls, delivery, deployment, or code changes. This is input to the parent's
implementation plan, not evidence that the current pipeline implements it.

Sources below describe the documentation retrieved for this September 2026
review. They are mutable pages, not a versioned historical snapshot or a promise
about later behavior. No Slack behavior was tested empirically. Proposed policies
are explicitly recommendations, not vendor guarantees.

## Recommended small scope

Keep Penny's canonical ledger, the existing Drop ingress/reader, and one owner
for Slack delivery. Reuse their persistence and polling mechanisms. Recommend
short text messages for small payloads; one UTF-8 `.txt` attachment with a short
introduction for long payloads. Keep the existing Drop reader link in either
form. The parent must verify reader access and whether a full-text Slack copy is
authorized. This research does not authorize a transfer.

The current [README](../README.md) and [reliability contract](reliability.md)
require independent receipts. The latter describes Slack chunking and also
limits Slack quality receipts to metadata. A proposed full-text/file projection
needs an explicit policy reconciliation; do not silently treat it as already
approved or replace existing delivery until the parent maps ownership.

Use existing Python stdlib facilities: `urllib.request` supports HTTP requests
with byte bodies and timeouts, and `sqlite3` provides transactions and backup.
Recommendation: a small explicit adapter is sufficient; no new queue service,
Slack SDK, or reader UI is required by this research. Set bounded request times,
keep secrets/upload URLs out of logs, and retain sanitized failure codes.
[Python HTTP](https://docs.python.org/3/library/urllib.request.html),
[Python SQLite](https://docs.python.org/3/library/sqlite3.html).

## Slack text and throttling

- Slack recommends at most 4,000 characters in `text`; it truncates messages
  above 40,000. These are different thresholds. Recommendation: keep the entire
  rendered message, including provenance/link, within 4,000; use a file beyond
  that. Check truncation warnings rather than recording complete content delivery
  from an acknowledgement alone.
  [chat.postMessage](https://docs.slack.dev/reference/methods/chat.postMessage/).
- Posting generally permits one message per second per channel, plus a
  workspace-wide limit. Burst capacity is not a dependable operating budget.
  A 429 carries `Retry-After` in seconds; the indicated cooldown applies to that
  API method for that app/workspace, across its tokens. Recommendation: persist
  `next_attempt_at` and shared method cooldowns; pace channels and avoid sleeping
  inside the capture path. Never cap a valid server delay downward. Add bounded
  backoff/jitter when a retry is safe and no usable header exists.
  [Slack rate limits](https://docs.slack.dev/apis/web-api/rate-limits/).
- Generic HTTP `Retry-After` also accepts an HTTP-date. Support both forms in a
  shared HTTP helper; Slack's documented form is seconds.
  [RFC 9110 §10.2.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.3).
- Check JSON `ok`, not HTTP status alone. Successful posting returns `channel`
  and `ts`; persist them as strings. Recommendation: bind that receipt to the
  intended destination and immutable payload version. It proves API acceptance,
  not human reading or permanent retention.
  [chat.postMessage](https://docs.slack.dev/reference/methods/chat.postMessage/).

## Modern file delivery and uncertain completion

Slack's published retirement date for legacy `files.upload` is November 12,
2025; use the external upload lifecycle for a September 2026 implementation.
This is a documented retirement, not an authenticated probe of the old endpoint.
[Slack migration notice](https://docs.slack.dev/changelog/2024-04-a-better-way-to-upload-files-is-here-to-stay/).

1. Call `files.getUploadURLExternal` with filename and **UTF-8 byte length**.
   It requires `files:write` and returns `file_id` plus `upload_url`. Persist the
   file ID and local payload identity before uploading. POST raw bytes to that
   URL; HTTP 200 acknowledges the byte upload. Processing is asynchronous.
   [Upload allocation](https://docs.slack.dev/reference/methods/files.getUploadURLExternal/).
2. Persist the completion attempt, then call `files.completeUploadExternal`
   with the saved file ID, intended `channel_id`, and short `initial_comment`.
   Without a channel the file stays private; without completion the upload is
   discarded. Slack documents completion as callable only once. Its success
   response identifies files but does not itself include a channel message `ts`.
   Persist completion acceptance separately from observed channel sharing.
   [Upload completion](https://docs.slack.dev/reference/methods/files.completeUploadExternal/).
3. If completion times out, the response is lost, or the process crashes before
   saving it, retain the same `file_id` in `completion_uncertain`. Recommendation:
   reconcile before any replacement allocation or completion replay. Do not
   interpret a repeated-call error as a successful channel delivery. Slack's
   completion errors explicitly allow partial success before an internal error.
   [Upload completion](https://docs.slack.dev/reference/methods/files.completeUploadExternal/).
4. Proposed read-back: use `files.info(file_id)` with `files:read`, then inspect
   visible share metadata for the exact target channel and share `ts`. File
   existence, a permalink, or a private file alone is insufficient. Share data
   can be incomplete (`has_more_shares`/`skipped_shares`); absent data is not proof
   of non-delivery. Retain uncertainty on inaccessible, missing, or inconclusive
   reads; use bounded reconciliation and then visible operator review.
   [files.info](https://docs.slack.dev/reference/methods/files.info/),
   [File object](https://docs.slack.dev/reference/objects/file-object/).

Recommendation: use an ordinary `.txt` attachment without opting into snippet
rendering. Slack documents a 1 MB snippet ceiling and workspace file-policy
errors; this is not a universal guarantee that every text upload size is allowed.
Choose an explicit local byte ceiling and preserve reader access when a payload
cannot be uploaded. Record link-only delivery separately from full-content
delivery. The fetched upload docs do not establish a reliable upload-URL expiry,
byte-POST replay guarantee, or a maximum reconciliation visibility delay; do not
invent them. [Upload allocation](https://docs.slack.dev/reference/methods/files.getUploadURLExternal/).

## Retry semantics: no exactly-once claim

HTTP discourages automatic retries of non-idempotent requests unless the client
knows the operation is idempotent or can determine it was never applied. A lost
POST response is an unknown result, not proof of failure.
[RFC 9110 §9.2.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2).

The inspected `chat.postMessage` reference mentions `client_msg_id` in duplicate
errors but supplies no end-to-end exactly-once contract or durable deduplication
window. A deterministic local key is useful but cannot establish those server
guarantees. [chat.postMessage](https://docs.slack.dev/reference/methods/chat.postMessage/).

Recommendation: represent `pending`, `retryable`, `in_flight`, `uncertain`,
`acknowledged`, and `failed/review` explicitly, with upload substeps where needed.
For text ambiguity, a bounded destination-history lookup with a stable opaque
delivery marker may find a positive match; no match is not conclusive. History
requires appropriate scopes/membership. Its current docs distinguish internal
apps (Tier 3) from certain commercially distributed non-Marketplace apps
(one request/minute and 15 results); do not apply that commercial rule to every
bot or assume this installation's category.
[conversations.history](https://docs.slack.dev/reference/methods/conversations.history/).

Prefer the claim **durable intent with bounded retries, duplicate suppression,
and explicit uncertainty**. Even “at least once” is an objective conditional on
continued retry, availability, and authorization; bounded attempts or unresolved
ambiguity cannot guarantee eventual delivery. This is a design conclusion from
the HTTP semantics above and the outbox duplicate caveat below.

## Transactional outbox and local durability

The outbox pattern commits the business record and delivery intent in the same
database transaction, then sends committed work separately. It closes the
database/update-to-enqueue gap, but relays can still produce duplicates.
[AWS's first-party pattern guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html).

Recommended contract, subject to the parent's code mapping:

- Penny atomically commits eligible transcript state plus a uniquely keyed Drop
  intent. Drop atomically commits its capture plus Slack intent before returning
  a durable receipt. Match stable source ID and payload hash; the same key with
  different bytes is a conflict. Keep Penny acceptance, Drop acceptance, Slack
  acceptance, and Slack share observation as distinct receipts. This applies
  the outbox pattern separately at each database boundary; it is not a distributed
  transaction. [Outbox guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html).
- Claim work in a short transaction, commit, perform HTTP, then save the result
  in another transaction. SQLite allows one writer; `BEGIN IMMEDIATE` can fail
  with `SQLITE_BUSY`. Use bounded contention handling. Persist claim ownership
  and expiry; an expired lease after a possible send needs reconciliation, not
  automatic retransmission. Leases alone cannot fence a stale remote request.
  [SQLite transactions](https://www.sqlite.org/lang_transaction.html),
  [HTTP retry semantics](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2).
- Verify effective settings in the eventual implementation. WAL with
  `synchronous=NORMAL` can lose committed transactions after power loss/system
  crash. Recommend WAL with `synchronous=FULL` where power-loss durability is
  required, subject to storage honoring synchronization. On macOS, review
  `fullfsync` explicitly; it is off by default. These are recommendations, not
  observations of Penny's current settings or proof against disk failure.
  [SQLite synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous),
  [SQLite fullfsync](https://www.sqlite.org/pragma.html#pragma_fullfsync).
- Preserve the existing verified backup path. Copying only a live WAL database's
  main file can omit committed state; use a consistent backup snapshot and
  separately verify referenced payload bytes. The SQLite backup API produces a
  consistent snapshot. [WAL persistence](https://www.sqlite.org/wal.html#the_wal_file),
  [SQLite backup](https://www.sqlite.org/backup.html).

## Parent-plan acceptance checks and open questions

Parent reconciliation: this research recommendation does not require changing
Drop's ingress to atomically create a Slack job. The existing immutable archive
and replayable reader cursor already retain the source work; the new Slack
reader persists its delivery intent before an external send. The approved user
scope permits transcript text and metadata to Drop/Slack/Maya, never audio.
The parent independently verified Slack scopes and penny-channel membership;
that proves access, not delivery. Implementation and live receipts remain pending.

Use synthetic data for crash/failure tests at: commit-before-send; server success
before receipt commit; each file-upload boundary; 429 cooldown plus restart;
stale claim; duplicate key/hash conflict; missing read permission; and Unicode
length/truncation thresholds. Check that uncertain work stays visible and a
positive reconciliation prevents a replacement send. These are proposed checks,
not executed results.

Still unverified: actual Drop ingress/receipt contract and reader URL, worker
ownership, policy-approved payloads, app scopes/category, channel membership,
retention/file restrictions, effective SQLite settings, and live delivery.
Resolve these in the parent plan and a separately authorized synthetic canary.
No raw-data transfer or permission change is authorized by this note.
