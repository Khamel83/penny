# Penny health audit — October 18, 2026 local / October 19 UTC

## Owner decision and current scope

After reviewing the findings, the owner explicitly directed: get Uptime Kuma
 green, treat missing history as past, and focus on working current operation.
Historical recovery is retired from the active queue. Preserve all old bytes,
receipts and terminal states; do not replay historical external deliveries.

The fix acknowledges a finite set of exact terminal-record metadata hashes in
SSD-backed `~/.penny/health-history.json`. Doctor keeps raw exception counts and
adds acknowledged counts, so reviewed history no longer lowers readiness.
A new or changed failure does not match the saved set and still alerts.
Invalid acknowledgement data fails closed. Current terminal capture failures,
failed/uncertain effects, stale evidence, backlog and storage checks are unchanged.
The operator command previews by default; `--apply` creates the set exclusively
and refuses to overwrite it. No date cutoff or moving age window is used.

Source validation: the three new regression tests first failed; after the fix,
all 39 focused Doctor/history checks pass; full suite851passed/two skipped/
60subtests and trust497tests/two skipped pass. Trust first identified an SQLite
connection-close omission, corrected before the passing run. Installation receipt
will be recorded after execution. Source merge alone does not prove deployment
or a persisted Kuma heartbeat.

## Diagnostic verdict before acknowledgement

Installed `/ready` returns HTTP 200/degraded at source `64d32534`.
There are no unready components, current terminal capture failures, source
coverage gaps, pending/failed/uncertain Drop handoffs, or Slack backlog.
SQLite integrity/foreign keys, archive publication, verified backup, offline
model assets, source access and running services pass. These probes do not
prove a new capture or independent downstream delivery.

Shared ASR health passes locally and from Homelab with pinned Parakeet.
Keeper has 784 runs, last exit 0, and a 120-second interval. Real outage/reboot
recovery remains unexercised. No service was restarted or redeployed.

## Exact degraded records

- Apple: one synthetic quarantined Note effect, transcript 493, unchanged since
  August 12; zero failed, uncertain or stale in-flight effects. Preserve it.
- Maya: nine legacy direct-delivery dead letters (735–738, 740–741, 744, 754–755),
  all exhausted 20 transient-error attempts in September. Their delivery remains
  unproven. New Voice Memos use Drop. No replay or waiver was performed.
- Voice Memos: source 112 has no staged audio and a zero-duration source entry;
  source 135 has corrupt audio; source 293 is already classified unavailable
  and absent from the current source inventory. All are historical exceptions.

## Bounded recovery and rollback

Source 135 / canonical 336 contains a migration placeholder. Its original and
staged audio are each 1,586 bytes; ffmpeg exits 69 with invalid AAC packets and
`partial file` on both. Local-only historical recovery returned ASR HTTP 503 /
`WhisperUnavailable`. This is failed recovery of a corrupt input, not proof
that normal current recordings fail transcription. No replacement words were
stored. No ASR configuration, model, privacy grant or source code was changed.

Before the attempt, SQLite was backed up to the SSD private receipt directory
`~/.penny/recovery/20261019T060727Z-health-repair/`. The failed attempt's row and
bounded error stack are retained there. Only source 135's source-ledger row was
restored from its before-image after an exact state/attempt guard; every field
matched afterward. The canonical placeholder remains unchanged. Downstream
row counts before/after match: Slack47, quality notices4, Apple56, GitHub0,
Drop340. Original and staged audio remain intact.

## External observation and remaining work

OCI's existing `penny-health.service` was run through its normal unit. Its
retained observation at 06:07:39 UTC and health projection agree: degraded,
source `64d32534`. The monitor is correctly reflecting Penny, not a separate
current outage. No monitoring threshold was relaxed.

Historical recovery is retired by the owner decision above. If explicitly
reopened, a valid independent audio copy is required for sources 112/135/293;
repeating transcription against absent/corrupt bytes will not repair them.
Legacy Maya recovery requires read-only identity/hash/receipt verification at
the destination before any separately authorized replay. Preserve synthetic
Apple quarantine493. Acknowledgement records the owner decision; it does not mark deliveries
complete or repair missing content.

Next verification: check `curl -s http://127.0.0.1:5678/ready`, local and Homelab
`:10311/health`, and keeper `launchctl print`; inspect receipts for the next
ordinary recording independently. No manufactured capture is needed.

## Source isolation

Fetched default `main` was `1ca40c23b4104f3c879d966d63f507a9fb21fcdf`.
The runtime checkout's four existing modified modules were preserved.
Documentation uses `.worktrees/health-repair` on
`docs/penny-health-repair-20261018`, created from fetched default because the
runtime checkout is protected. Retain this worktree through source review;
remove only after publication/merge with no unpublished or dirty work.
