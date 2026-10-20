# Shared ASR TCC containment — October 19, 2026

## Incident

The Penny shared ASR LaunchAgent could not start on the Mac mini. A private
temporary launchd projection captured five Python startup failures (46 lines,
2,973 bytes): `Fatal Python error: Failed to import encodings module`, followed
by `InterruptedError: [Errno 4] Interrupted system call` while touching the
SSD-backed runtime at `/Volumes/2TB_SSD/penny-runtime`.

Unified logs show the matching macOS boundary. Between
`2026-10-19T20:17:00-0700` and `2026-10-19T20:29:38-0700`,
`kTCCServiceSystemPolicyRemovableVolumes` produced 955 watchdog-expiry events
across 101 unique PIDs. The first event was at `20:17:40.843`; the last was at
`20:29:37.906`. The same signal appeared for other Python launchd jobs, so
this is a removable-volume authorization/runtime condition, not a Penny model
or port defect. A manual launch with the same environment on port 10312 stayed
healthy for 15 seconds.

The private evidence receipt is
`/Users/macmini/Library/Logs/penny-shared-whisper-debug.Y1JDia/containment-receipt.json`,
mode 0600, SHA-256
`cfbb4e74f989760659bfd061ca342c85c367f41fc2ae3dac67f6fbf1d98fef1c`.
The startup stderr capture is
`/Users/macmini/Library/Logs/penny-shared-whisper-debug.Y1JDia/stderr`,
mode 0600, SHA-256
`62ac68d4cd3be4882858c57ca2c6a34a4a771e7e53834f95f0804cc5203bfd42`.
No transcript, audio, credential, provider response or raw personal content is
in the incident record.

## Bounded containment

At approximately `20:31:33 PDT`, only these two labels were booted out, in this
order, using the existing per-user launchd path:

1. `com.penny.shared-whisper-keeper`
2. `com.penny.shared-whisper`

Both labels now report unloaded (`launchctl print` return code 113). Local and
tailnet `/health` checks fail as expected, and TCP port 10311 has no listener.
The other Penny labels remain loaded and untouched: `com.penny.export`,
`com.penny.tasks`, `com.penny.watcher` and `com.penny.webhook`. Uptime Kuma's
ASR monitor is intentionally left red; containment is not a health claim.

The original installed plist bytes were not edited:

| plist | path | mode | SHA-256 |
| --- | --- | --- | --- |
| shared ASR | `~/Library/LaunchAgents/com.penny.shared-whisper.plist` | 0600 | `3e918d37e37641fa37993901aa6a50b04ad956718391675ee9e9a02c151293f1` |
| keeper | `~/Library/LaunchAgents/com.penny.shared-whisper-keeper.plist` | 0600 | `e053aeb9509472fc32bcdb66d6d3b0ecbef48d5851002401bb3eee41f1cbfb04` |

No TCC/security grant, source, model, provider, ledger, audio, database,
backup, consumer or other launchd label changed. The repository's existing
dirty worktree and installed source remain preserved; `storage_guard.py` was
not edited (SHA-256
`eeba2d4b5fcc46b8efe328d85784a9c5d8a34ffd74d27c398133fa614b8dc0ff`).

## Owner-only blocker and re-enable gate

The labels must remain unloaded until the owner resolves the macOS
removable-volume authorization/runtime boundary through a supported path. No
TCC database reset, security-grant change, SSD relocation, source workaround,
manual unmanaged daemon or model/provider fallback is authorized by this
incident record.

After that owner action, reload the unchanged original plists only after a
fresh bounded check that the source/interpreter can start without the TCC
watchdog. Bootstrap ASR first and require a stable local health response with
no rapid respawn; then bootstrap the keeper and verify its scheduled exit. Use:

```sh
uid=$(id -u)
launchctl bootstrap "gui/$uid" "$HOME/Library/LaunchAgents/com.penny.shared-whisper.plist"
curl -fsS http://127.0.0.1:10311/health
launchctl print "gui/$uid/com.penny.shared-whisper"
launchctl bootstrap "gui/$uid" "$HOME/Library/LaunchAgents/com.penny.shared-whisper-keeper.plist"
launchctl print "gui/$uid/com.penny.shared-whisper-keeper"
curl -fsS http://omars-mac-mini.deer-panga.ts.net:10311/health
```

Each loaded service, local health result, tailnet result, Kuma heartbeat and
downstream transcription effect remains a separate acceptance fact.
