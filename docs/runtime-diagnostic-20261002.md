# Penny / shared ASR / Atlas diagnostic — October 2, 2026 UTC

## Verdict

Do not certify end-to-end reliability yet. Core Penny capture/storage and the
shared model are ready in the installed launchd configuration. Actual Atlas
jobs reveal an ASR response-contract defect and repeated long-input quality
failures. Apple effects and slow MinusPod startup are independent problems.
This diagnostic used existing receipts; it performed no new recognition,
private replay, queue/effect reset, model switch, delivery or live deployment.

## Verified runtime boundaries

- All five installed Penny plists select ca6322b697a4bcea8de52849d975d7543a994970.
- Installed-context Doctor at03:11:57 UTC: capture/services, shared ASR, offline
  model verification, SQLite integrity/foreign keys, archive, backup, Drop and
  Slack ready. Canonical ledger519 rows/max ID771; verified backup matches.
- Overall Doctor is unready from Apple effects: one capped failed note and one
  quarantined uncertain note. Historical Maya dead letters9 and unavailable
  memo exceptions are separate degraded states. No current terminal capture
  failures, retry-due captures or source coverage gap.
- Plain terminal Doctor lacked installed configuration and falsely reported
  stale backup/offline model failure. Use the installed environment without
  displaying credential values. A shell-only result is not a service verdict.
- Shared health selects pinned Parakeet ed2b7e8c, Apple pilot disabled, one owner.
  Active worker physical footprint2.0 GiB/peak2.5 GiB; old large owner absent.
  This is a bounded measurement, not multi-day memory proof.
- Native MinusPod image ed39 is healthy/zero restarts; watchdog/readiness/drain
  user timers active; admissionsfalse. Both native APIs return200. HTTP health
  from inside its actual container to configured Mac endpoint returned200 in
  0.04–0.05 seconds. Earlier connection timeout still occurred; it is not
  established as a persistent outage.

## ASR-related failures proved from existing data

1. **Fallback response-contract mismatch.** Two completed Atlas Whisper retry
   receipts contain the same invalid segment interval: start361.88,
   end361.82000000000005 (about60 ms reversed), no word timing in that segment.
   Model identity is the pinned Whisper fallback. Native rejects the response
   with `Whisper success response has invalid time range`; Penny's decoder
   accepts the identical payload. No transcript text was displayed or changed.
   This proves inconsistent structural acceptance, not semantic inaccuracy.
2. **Repeated long-input quality failure.** Ten receipts from one105.09-minute
   input between01:54:22 and03:19:15 have
   `backwards_parakeet_token_time` / `quality_review_requires_bounded_excerpt`.
   They are repeated attempts of one hash, not ten independent accuracy cases.
   Review receipts preserve audio but do not stop repeated caller admission.
   These copies account for2.52 GB; nothing was deleted. An earlier33-minute
   failure is separate. The earlier fixed33-minute import is not proof that
   all long-input timestamp cases now pass.
3. **Failure locality is missing.** The held long-input receipt has no primary
   result or failed timing interval. An automatic five-minute Whisper repair
   cannot safely infer which excerpt to use from the current static reason.
   The explicit bounded excerpt CLI exists; automatic localization remains open.
4. Recent native runs at02:44:45,02:59:36 and03:08:38 ended `fail_job` in ASR
   without stage receipts. Queue snapshot:29 completed/5 failed. Native private
   logs include the exact static invalid-time-range error and a connect timeout.
   Do not assign every failed run to one cause from aggregate logs alone.

## Repeatable feedback loop

```bash
/Users/macmini/penny/venv/bin/python /Users/macmini/.penny/recovery/20261002-diagnostic/run-contract-repro.py
```

Observed exit1: `contract_disagreement=true`, `penny_accepts=true`,
`atlas_accepts=false`, `native_error=invalid_time_range`. The loop uses an
existing private saved response and a frozen native decoder snapshot; it loads
no model and sends no audio. It proves this contract defect, not future runtime
acceptance. Rebind the native snapshot to the reviewed release for a fix check.

Focused deployed-source checks:50 passed in2.29 seconds across adapter, shared
protocol/client/server/supervisor/worker tests. Their passing result plus the red
saved-response loop identifies an uncovered real-response boundary.

## Required repairs / acceptance

1. Give quality-held long inputs a durable nonretry disposition, preserving
   source/checkpoint/review receipts; do not repeatedly retranscribe whole audio.
2. Validate equivalent timing contracts before declaring primary/fallback
   responses successful. Characterize small Whisper alignment reversals from
   saved output before a repair policy; do not blindly relax Atlas validation,
   discard/reorder text, or fall back over an entire long recording.
3. Capture bounded numeric timing context at the Parakeet failure, without text
   or raw SQL logging, so a reviewed excerpt can target the actual bad interval.
   Keep serial ownership and pinned identities; meaningful regressions must
   replay the existing failure through both producer and consumer contracts.
4. Separately optimize measured stock database startup scans before activating
   Atlas PR170. That merged correction is not live and does not fix the above
   primary/fallback output problems.
5. Corrected October 2: the suggested protected Apple Events kickstart is blocked
   by SIP even after authentication. Do not retry it or disable SIP. Recheck
   exact provider receipts first; coordinate a normal Mac restart only if target
   calls remain stuck. Preserve capped/quarantined history; no blind redelivery
   or TCC reset. See docs/workflow-recovery-20261001.md.
6. Observe a future ordinary Penny capture through actual Parakeet identity,
   canonical ledger, archive and independent downstream receipts. Latest audio
   ledger rows still identify pre-cutover Whisper; natural post-cutover capture
   acceptance is not yet observed. No artificial recording was inserted.

## Private evidence

Mac: `~/.penny/asr-retries/` and
`~/.penny/recovery/20261002-diagnostic/` (private frozen decoder and reproduction).
Homelab: `/mnt/fast-storage/appdata/minuspod/penny-diagnostic-20261002-errors.json`
and `penny-diagnostic-20261002-native.log` (0600). Existing publication and
rollback proof paths remain in HANDOFF. Raw audio/transcripts remain local.
