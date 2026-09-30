# Shared Whisper live memory receipt — September 30, 2026

Penny PR #62 merged as `63591bed23f86347a3cf73d7db27a395d9d49836`. Existing deployment command passed trust checks and verified backup, then activated all five existing labels at that revision. Private receipt: `~/.penny/deployments/20260930T184118Z`. Five dirty/untracked files were copied, stashed, then restored with identical SHA-256 hashes; the preservation receipt and stash remain. Runtime source belongs to `/Users/macmini/penny`; Atlas is an HTTP caller.

Local authenticated service canary used generated non-private speech, sequentially through the backfill client. No second model owner, provider upload, canonical transcript row or downstream delivery was created by these requests.

| Probe | Before | After |
| --- | --- | --- |
| Three 7.7-second identical requests | 2.3 GiB each | 1.7 GiB each |
| Transcript hash on those requests | same hash each | identical to before |
| Warm request time | 1.60–1.64 s | 1.80–1.82 s |
| Alternating 38.4/192.1/38.4/192.1-second inputs | not measured | 1.7 GiB after every request |

Pinned FP16 model and options are unchanged. Measurements are post-request physical footprints including Metal, not active peaks. Longer probes are repeated generated speech, not a quality benchmark on real podcast audio. Evidence supports reduced retained memory; it does not prove elimination of all memory pressure, identical quality across all audio, or multi-day stability. Live activation, API response, persisted application result and downstream effects are separate: activation and canaries pass; a natural Atlas/Penny completion and sustained busy-workload observation remain next acceptance checks.

Full local suite: 680 passed, 2 skipped, 53 subtests passed. Changed Python passes Ruff. Both hosted Python 3.11/3.12 checks passed at PR head `c668b9518a09e787e96f02c9df639620a36232f0`.

## Simulator cleanup boundary

The external simulator dyld cache at `/Volumes/2TB_SSD/CoreSimulator/Caches/dyld` was deleted and absence verified; approximately 8.9 GiB was removed from the external SSD, not the internal disk.

Xcode.app is absent. The internal simulator assets remain approximately 7.8 GiB iOS, 3.4 GiB tvOS and 3.6 GiB watchOS. Administrator-authenticated exact-asset deletion returned Operation not permitted; restricted flags/SIP protect these paths. The installed standalone simctl runtime commands did not return within bounded observation and were terminated. System Settings does not expose these assets as a usable cleanup item. No internal reclamation is claimed.

Apple DTS describes booting into macOS Recovery and making the change there as an alternative, while warning that manually modifying system asset structures is unsupported: https://developer.apple.com/forums/thread/812992 . No SIP setting or reboot was changed. Next specific disk step requires a coordinated Recovery boot, unlock/mount of the Data volume, verification of these exact three asset directories on that volume, deletion of only those assets, then normal boot and `du`/`df` verification. Preserve Command Line Tools and other Apple model assets.

Exact authorized asset paths under the mounted Data volume's `System/Library/AssetsV2`:

- `com_apple_MobileAsset_iOSSimulatorRuntime/e4478b4b9014ff28fe3c265daca488f55a284f4c.asset`
- `com_apple_MobileAsset_appleTVOSSimulatorRuntime/48987f5cfa949eba753900245fcab03230deaff1.asset`
- `com_apple_MobileAsset_watchOSSimulatorRuntime/71b5619e1b29fefeed31f7c71d0485d849d942a3.asset`
