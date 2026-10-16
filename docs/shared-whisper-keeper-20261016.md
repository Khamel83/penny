# Shared ASR keeper repair — October 16, 2026

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
