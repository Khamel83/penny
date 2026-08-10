# Penny troubleshooting

Use this order: run the read-only Doctor, identify the component/reason code,
inspect the canonical ledger and receipt metadata, then make the smallest
evidence-preserving change. Do not use process presence, log freshness, or a
successful HTTP request as proof of durable work.

## First check

```bash
venv/bin/python scripts/penny_doctor.py
curl -fsS http://127.0.0.1:5678/health
curl -i http://127.0.0.1:5678/ready
```

Doctor exit `0` is ready, `1` is degraded, and `2` is unready. `/health` is
liveness; `/ready` reflects the readiness report. The output contains bounded
metadata only. Never paste transcript text, audio, secrets, URLs, or raw errors
into an incident report.

## New Watch recording is missing

Confirm the recording exists on the paired iPhone/Watch and that Voice Memos is
enabled in iCloud on both devices. Keep the app open long enough for sync, and
confirm the device has network and iCloud capacity. The private Voice Memos
reader may be denied by macOS privacy controls; grant the approved runtime the
required permission through System Settings, then let the normal watcher retry.

On the Mac, check Doctor's `voice_memos` component for the Penny discovery
cursor, awaiting-file, retryable, and terminal-failure metadata. Doctor does not
probe Apple's source query, TCC/container permission, or source schema; those
remain watcher diagnostics/manual Apple recovery, and an unobserved condition is
unknown. Use the canonical SQLite row and source receipt to decide whether the
memo is absent upstream, staged locally, retryable, or `failed_terminal`.
`watcher.system.log` is diagnostic context only; do not tail it as a health check.

If Voice Memos remains unavailable, use the supported Share/Finder export path.
It must enter the same authenticated ingest and persistence pipeline; it must
not bypass provenance, archive publication, policy, or receipts.

## Capture is pending or retrying

Inspect the Doctor reason and bounded age/counter fields. A changing source file
or missing audio is expected to remain retryable. A database failure prevents the
discovery cursor from advancing past an undurable upsert. Processing failures
remain in `voice_memo_ingest` as retryable or `failed_terminal`; there is no
separate completion watermark. A terminal failure is visible state and needs a
specific operator decision; do not repeatedly replay it.

If a capture is persisted but not routed, verify local routing, Apple receipt,
independent Slack, and independent Maya v2 separately. One failure does not
erase the local row or imply that another stream failed.

## Archive or iCloud mirror is degraded

For audio-bearing rows, the local immutable object is authoritative for archive
recovery. Check that the
audio, `.md`, and `.json` files share a basename and that the manifest is last
and hash-valid. iCloud `Penny Archive` is a mirror and may be delayed or
rebuildable; it is not a database or backup.

Do not move, rename, edit, or delete files in an approved iCloud inbox/mirror as
a troubleshooting shortcut. Preserve invalid or partial objects for quarantine
and let the archive worker retry after the source is stable.

## Apple Notes or Reminders effect is uncertain

Use the Apple-effect receipt ledger. A pending state is safe to retry; a
provider identifier plus read-back receipt is evidence of success. Permission
denial is an explicit failure. For an ambiguous timeout, reconcile the durable
effect key before another attempt. Never infer success from an AppleScript exit
code alone and never bulk replay the outbox from a health check.

## Slack or Maya delivery is unhealthy

Slack and Maya are independent outboxes. Check their Doctor component and the
row's bounded state, attempt age, and terminal/dead-letter counters. Slack
requires its dedicated runtime credential and has its own retry window. Maya v2
requires its dedicated authenticated endpoint/token, has a 20-attempt/seven-day
bound, and uses claims so only one worker owns a delivery at a time.

Do not print credentials or provider responses. Do not turn a network timeout
into `sent`; require an identity-matching durable receipt. A disabled optional
Maya route is degraded, while partial configuration, ledger errors, or invalid
receipts are unready.

## Transcription/model is unready

Doctor requires `mlx-whisper==0.4.3`, model revision
`a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb`, and the absolute default model path
`/Users/macmini/.penny/models/whisper-large-v3-turbo/a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb`,
plus `HF_HUB_OFFLINE=1`. It verifies the local model manifest/weights receipt.
If the model is missing or tampered, stop transcription, preserve staged audio, and
run the approved provisioning/verification procedure separately. Provisioning
is the only network boundary. Apple Speech and MacWhisper are challengers, not
automatic fallbacks.

## Backup is unverified or stale

The backup worker must publish a versioned set and verify it in a scratch
directory. Doctor requires a valid metadata-only receipt bound to the latest set,
catalog hash, row count/max ID, and remote catalog verification. A failed verify
or sync leaves the prior good receipt unchanged. JSON exports are readable aids,
not restorable backups.

For recovery, stop writers, verify a set in scratch, restore the whole database,
reconcile archive hashes, and rerun Doctor before resuming. Preserve prior sets;
never replace the live database or delete evidence to make readiness green.

## Ingress returns 401/413/503

- `401`: missing/incorrect dedicated ingest credential; `/deliver` uses a
  separate callback credential.
- `413`: request exceeds the configured content or text limit; no transcription
  or routing should have run.
- `503`: persistence or readiness boundary is unavailable; retry only after the
  canonical state is inspected.

The target webhook policy is loopback. Tracked/runtime templates must converge
to loopback or an explicitly protected non-loopback policy; Doctor reports an
unprotected bind as unready. Authentication and content limits still apply.

Missing or wrong credentials must produce `401`; valid-token routing is covered
by hermetic tests. No live canary is implied by this document.

## What not to do

Do not delete or replace SQLite or Apple databases, remove archive objects, erase
backup sets, restart providers from automation, replay all pending work, or
change credentials from a health check. Keep all raw and derived evidence until
a verified restore and retention window are complete.
