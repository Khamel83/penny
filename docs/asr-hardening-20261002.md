# Shared ASR hardening — October 2, 2026 UTC

## Verified source

Penny PR88 merged at `c341598c484734ace251944f3f7ca56ab0bb0009`.
Standards/spec review passed for its exact head `e7a3384`; both hosted Python
checks passed. Full source tests:749 passed,2 skipped,53 subtests before the last
two added timing regressions; final focused eight passed and offline trust491
passed with2 skipped. No new long-audio accuracy benchmark was run.

The producer and Penny client now reject the malformed timing shape that Atlas
already rejected. Finite nonnegative ordered ranges and monotonic segment/word
starts are required; no timestamps are clamped and no transcript text is invented.
Structural failures return nonretryable quality_review with bounded numeric
locality and actual model identity. Penny records needs_review without a new
same-input request; busy/preemption/network failure semantics remain retryable.
A selected earlier text response retains its own actual model identity.

Atlas PR175 and review correctionPR176 merged, latest source
`74f4cada3c465219a0247f78b73d306d17672cfa`. Exact-head source reviews passed at
`76d09619`. Full nonlive suite2221 passed,159 skipped,14 deselected with external
SSD scratch;150 focused checks passed. Hosted syntax and tests passed in exact-head run `36966127524` at 05:20 UTC.
The earlier queue delay was OCI configured-memory admission, not a test failure.
Native API/chunk errors preserve typed false metadata through the existing
permanently_failed classifier instead of converting it to a generic transient
retry. Failure locality shifts once to original-audio coordinates. Private
legacy holds retain primary signature separately from actual failed-model
metadata; text, paths, arbitrary provider messages, bools and nonfinite values
are excluded from repair metadata. Original media remain intact.

## Penny installed runtime

Deployed `c341598c` using the ordinary deploy command after private backup/trust
checks. All five installed agents carry that revision; watcher/webhook/tasks/
shared service run, scheduled export is loaded/idle. Protected owner files
were restored byte-identically and their preservation stash retained.
Receipt: `~/.penny/deployments/20261002T044400Z/receipt.json`.

Saved private malformed-response reproduction now confirms Penny and Atlas both
reject the same response; contract_disagreement=false. No ASR was needed for
that check. A public synthetic canary passed actual Parakeet→Whisper→Parakeet,
each with one model owner, valid timestamps and both clients agreeing. Times
0.595/4.047/11.958seconds reflect this short canary and load state, not podcast
throughput. Canary bypassed the canonical ledger and downstream delivery.
Private evidence: `/Volumes/2TB_SSD/penny-asr-runtime/hardening-20261002/`.

Installed-context Doctor confirms services/transcription/shared ASR/SQLite/
archive/backup/Drop/Slack boundaries okay. Overall remains unready because Apple
effect provider failure, with independent historical Maya dead letters and
unavailable memo exceptions. No capture release, delivery reset, raw transfer,
TCC reset or private replay occurred. A new natural post-cutover canonical
capture/archive/downstream receipt remains a separate acceptance item.

## Atlas installed runtime

The legacy helper and drain are installed with a deployment projection
`0d75eaba22e574ee9f6c7dabd96bee8d61efa5c4`: exactly two script blobs from the
reviewed source applied to accepted legacy runtime `7a00a036`; every other
source blob stayed at its previous accepted revision. Other component selectors
were preserved. Full component verifier passed14,513tracked files with no
missing/drifted files; drain timer restored active and ordinary batch started.
Receipt: Homelab `/mnt/fast-storage/appdata/minuspod/atlas-quality-hold-deploy-v2-20261002.json`.

The first installer attempt failed its component-selector recheck and rolled back.
It reused the earlier protocol-detail receipt filename, replacing that historical
receipt's bytes. The earlier source/drop/manifest remain independently recheckable;
no capture/audio/ledger receipt was altered. The successful second attempt uses
a unique filename and passed both direct and service component verification.

Seventeen existing quality-failure receipts independently matched one105-minute
queued input. Its private0600 signature hold was seeded without ASR; duplicate
recording is byte-idempotent. Later readback still found17 receipts, zero new
same-input retries, and the installed helper hash matches reviewed source.
Private Mac receipt `known-loop-hold-seed.json` records hashes without changing
canonical queue rows. Never release this hold merely because the service is
healthy; repair the bounded excerpt first, then review before release.

Native image `atlas-minuspod:74f4cada-asr-hardening` is built and source-hash
verified. Startup patches replace FTS full count with bounded EXISTS and gate
historical cleanup only after successful savepoint completion. Rollback affects
only cleanup writes and preserves prior migrations. The actual pinned base,
hybrid,pass2,stage,startup,g2k overlay chain compiled; patched schema hash
`f2f1320b5f261a71cee1ff60e90367031357df34a312814bd4aedca728d384c0`.
Native activation completed at 05:20 UTC after both owned jobs finished naturally.
The gate reports `activated_admission_restored`; original admission is `false`.
At 05:24 UTC the new image was running healthy with zero restarts, all three user
 timers active, generated transcriber/processing/schema hashes matching the
independent overlay chain, and the cleanup success marker present.
Private Homelab receipts:
`asr-hardening-native-gate-20261002.json`,
`atlas-asr-hardening-deploy-20261002-asr-hardening.json`, and
`asr-hardening-final-acceptance-20261002.json`, all under
`/mnt/fast-storage/appdata/minuspod/`. The installer receipt records paused
admission at its intermediate boundary; the later gate and final acceptance
prove restoration. No forced shutdown or rollback was needed for this activation.

## Recheck and remaining owner boundary

```sh
curl -fsS http://127.0.0.1:10311/health
venv/bin/python ~/.penny/recovery/20261002-diagnostic/run-contract-repro.py
venv/bin/python /Volumes/2TB_SSD/penny-asr-runtime/hardening-20261002/run-installed-doctor.py
ssh homelab 'systemctl --user is-active atlas-podcast-whisper-drain.timer atlas-minuspod-watchdog.timer atlas-readiness.timer'
```

Read the native gate/deployment receipts and current own health/queue/admission
before claiming activation. Atlas PR176 exact-head hosted checks passed in run `36966127524`.
No natural capture or delivery result is inferred from a synthetic canary.

The earlier protected Apple Events kickstart instruction was invalid on this
SIP-enabled Mac: administrator authentication still returned error150. It has
been withdrawn. Keep SIP enabled and retain privacy grants and effect history.
Fresh basic Notes access succeeds, while Finder/Reminders queries time out;
exact Notes marker lookups also pass in shell and equivalent launchd context
with zero matches for both outstanding effects. Failed/quarantined ledger
states remain unchanged; marker readback does not prove successful delivery. See
[corrected recovery guidance](workflow-recovery-20261001.md#recovery-correction--october-2-2026).
A coordinated normal macOS restart is a recovery candidate only if target
provider calls remain stuck; do not interrupt active shared ASR jobs or blindly
resend uncertain effects. No machine restart or effect retry was performed.
