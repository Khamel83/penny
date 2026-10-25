# Shared ASR keeper acceptance — October 16, 2026

PR119 is merged as `6330b39844903e8e3a7c9b1e03307ec14cfeaf1c` and its keeper
is installed. The earlier repair checkpoint below is retained as dated source
history. Automatic recovery during a real outage or reboot was not exercised.

## Merged source and independent receipt

- Exact accepted head: `e14adbea944da1d93ab4d541af55704c002ce7dc`.
  Trusted Bot review [5544379490](https://github.com/Khamel83/penny/pull/119#pullrequestreview-5544379490)
  is PASS for that head, submitted 07:29:14 UTC.
- [Native CI38867505542](https://github.com/Khamel83/penny/actions/runs/38867505542)
  completed successfully on Python 3.11 and 3.12: each had 807 passed, 2 skipped,
  60 subtests and trust PASS (497 tests, 2 skipped). Native merge occurred at
  07:30:50 UTC; separate PR endpoint, timeline and fetched default branch agree.
  Accepted keeper template and tests match the merged bytes.
- OCI `/home/ubuntu/.local/state/janitor/merge-receipts.jsonl` has successful
  merge run `merge-fb4e2b1a8d254bd18067d56c60167755`, retaining that reviewed
  head, review ID, both successful native checks and merge SHA. The installed
  worker's source reads back GitHub merged/head/SHA before this success receipt.

## Keeper-only installation

At 07:32:46 UTC, the existing installed keeper plist was backed up on SSD;
merged template bytes were rendered with exact source revision, linted and
installed atomically. Only `com.penny.shared-whisper-keeper` was unloaded and
bootstrapped. The ASR daemon PID remained unchanged; installed bytes and loaded
script/revision match the rendered plist. Initial keeper run exited 0 with its
120-second interval registered. Local and independent Homelab health checks
returned the expected pinned Parakeet service and one idle worker. The first
ordinary scheduled tick was observed at 07:34:46 UTC: keeper runs=2, last exit=0,
and the ASR daemon PID still unchanged. This verifies natural healthy probing.

Private SSD deployment receipt and before-image:
`/Volumes/2TB_SSD/AI/Penny/state/deployments/20261016T073246Z-shared-whisper-keeper/receipt.json`.
Installed plist SHA-256:
`e053aeb9509472fc32bcdb66d6d3b0ecbef48d5851002401bb3eee41f1cbfb04`.
No ledger, credentials, privacy grants, providers, audio or outboxes changed.
No live failure/reboot was induced. Registration and healthy checks establish
normal operation, while outage recovery remains covered by stubbed tests only.

## Rollback

Restore `keeper-before.plist` from the same private deployment directory to
`~/Library/LaunchAgents/com.penny.shared-whisper-keeper.plist`, lint it, and
reload only that keeper label with the documented `bootout`/`bootstrap`
commands. Check local and Homelab ASR health. Do not restart the ASR daemon or
change other Penny jobs as a keeper rollback.

## Earlier source repair checkpoint

Checkpoint: 2026-10-16T07:28:06.913054+00:00. This is source and read-only runtime evidence. It does
not attest a merged repair, installed repair, or an actual recovery event.

## Source and findings

- Fetched default `main`: `6e975d7fb7e2d67a49c544b138bd353f6d98e53e`.
- [PR119](https://github.com/Khamel83/penny/pull/119) remained open at head
  `6aeefe2f4310eb567d9608a1442f0d26b5020714`. Hosted 3.11 CI failed and
  3.12 was cancelled. Exact-head trusted review reported shared `/tmp` marker
  clobbering and JSON whitespace rejection; no trusted PASS or merge receipt.
- CI failure reproduced: keeper template lacked `KeepAlive`,
  `WorkingDirectory`, `PATH`, and `SoftResourceLimits`. It now follows the
  existing timed export template contract with `KeepAlive=false`; the trust
  check is unchanged.
- The repair validates Darwin's per-user temporary root, keeper state, and
  strikes as non-symlink directories owned by the current UID with mode 0700.
  Strikes use atomic `mkdir` and `rmdir`; no marker file is opened or truncated.
  Health checks accept JSON separator whitespace. Recovery logs distinguish a
  launch request from a failed kickstart/bootstrap and return nonzero on failure.

## Verification

- Before repair: keeper tests 4 passed; trust check exited 1 at missing keys.
  Expanded regression tests exposed 12 failures against old source.
- `venv/bin/python -m pytest -q tests/`: exit 0, 805 passed, 2 skipped,
  60 subtests. Two further wrong-service cases were then added.
- `venv/bin/python -m pytest -q tests/test_shared_whisper_keeper.py` on final
  source: exit 0, 15 passed. Includes busy/spaced/multiline health responses,
  wrong service identity, symlink/writable state, fallback, and failed recovery.
- `venv/bin/python scripts/trust_check.py`: exit 0, PASS; 497 hermetic tests,
  2 skipped, 6 launchd templates validated.
- `git diff --check`: exit 0.
- `plutil -lint launchd/com.penny.shared-whisper-keeper.plist.template`:
  exit 0, OK.

## Runtime and downstream boundaries

- Installed keeper is registered on a 120-second schedule, idle between runs;
  last observed exit 0. Its loaded script is the older `/tmp` implementation.
  No keeper reload or ASR restart was performed by this verification.
- Local `127.0.0.1:10311/health` and Homelab request to
  `omars-mac-mini.deer-panga.ts.net:10311/health` returned the expected service,
  pinned Parakeet revision `ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15`, idle state,
  one worker, and no active client. Current tailnet IP is `100.89.194.46`.
- Penny `/ready` reports no unready components. Its degraded components are
  historical quarantine, legacy Maya dead letters, and historical unavailable
  Voice Memos. Drop pending/failed/uncertain counts are zero. This does not
  resolve any unrelated source-record reconciliation or prove a new delivery.
- No raw audio, transcript, provider write, outbox replay, or manufactured
  capture was used. No live failure/reboot was induced; automatic recovery
  remains unexercised outside host-call-stub tests.

## Next gate

Review the repair diff, push this same PR branch after authorization, then
require successful native CI and a trusted PASS for the exact new head. Verify
native merge and its independent receipt. Before keeper-only installation,
retain the old installed plist in an SSD deployment receipt, stamp the accepted
source revision, lint the rendered plist, reload only the keeper label, and
check loaded revision/bytes plus local and Homelab health. Do not restart ASR
or use a live failed-health canary to create acceptance evidence.

This work reused the existing clean `feat/shared-whisper-keeper` checkout at
`/Volumes/2TB_SSD/penny-runtime` (the project folder resolves there). No new
worktree was created; existing worktrees and runtime files were preserved.
