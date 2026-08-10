# Apple Watch Ultra capture options for Penny

**Research date:** 2026-08-09
**Scope:** Apple Watch Ultra capture and delivery into Penny; facts below are limited to the cited Apple and Just Press Record documentation supplied for this report.

## Executive answer

The recommended pilot is **Just Press Record (JPR) on Apple Watch + a Penny-owned folder adapter**. JPR provides one-tap local Watch recording and later phone transfer, while Penny retains its current local MLX Whisper transcription and can make the folder adapter a durable, testable boundary. Watch cellular is not required: recording is local and transfer can occur later through the paired phone.

If JPR cannot meet the reliability or privacy gates, harden the current Voice Memos path as a free fallback. The longer-term supported alternative is a custom Penny Watch/iPhone recorder using `AudioRecordingIntent` and `WatchConnectivity`.

This is a capture-source recommendation, not an authorization to buy or install anything. Do not purchase or install JPR as part of this report.

## What Apple Watch supports

- The Ultra Action button can directly start/stop Voice Memos and can launch a selected Shortcut ([Apple Watch User Guide: Action button](https://support.apple.com/en-au/guide/watch/apda005904ef/26/watchos/26)).
- Apple Watch can run compatible Shortcuts ([Apple Watch User Guide: Shortcuts](https://support.apple.com/en-ie/guide/watch/apd99050d435/26/watchos/26)).
- Voice Memos documentation exposes manual transcript viewing/copying and manual sharing, but no audio or transcript output through App Intents ([View a transcription of a recording](https://support.apple.com/guide/voice-memos/view-a-transcription-of-a-recording-vm4a03609f0d/mac)). Therefore, the Watch control surface alone does not establish an unattended, structured Voice Memos handoff into Penny.
- Apple’s `AudioRecordingIntent` supports recording, but requires a Live Activity ([AudioRecordingIntent](https://developer.apple.com/documentation/appintents/audiorecordingintent)).
- `WatchConnectivity` queues background file transfers when the phone is unavailable and transfers them when connectivity returns ([Transferring data with Watch Connectivity](https://developer.apple.com/documentation/watchconnectivity/transferring-data-with-watch-connectivity)).

## Options

| Option | Capture and handoff | Cost / dependency | Role |
|---|---|---|---|
| **JPR pilot + Penny folder adapter** | One-tap Action Button/Shortcut/Siri start/stop; independent Watch recording; later Watch→iPhone transfer and file export | Current App Store listing: $6.99 universal; no developer data collection is declared | **Recommended pilot** |
| **Voice Memos hardening** | Keep the current Voice Memos private-DB reader as fallback | Free; unsupported private database remains a compatibility risk | Fallback only |
| **Custom Penny Watch/iPhone app** | Penny-owned recording and file path, with `AudioRecordingIntent` + `WatchConnectivity` | Engineering and Apple platform lifecycle work | End-state if JPR fails |

### Just Press Record facts and limits

The current [App Store listing](https://apps.apple.com/us/app/just-press-record/id1033342465?platform=watch) states that JPR is a $6.99 universal app with one-tap start/stop from the Action Button, Shortcuts, and Siri; supports independent Watch recording with later sync; and can write to iCloud Drive or local files. It declares no developer data collection. Developer support states that Watch recordings automatically transfer to iPhone over Bluetooth and then to iCloud Drive ([How are recordings synced between devices?](https://openplanet.zendesk.com/hc/en-gb/articles/115004471393-How-are-recordings-synced-between-devices)).

JPR’s privacy support page says transcription may use Apple servers depending on device and language ([privacy FAQ](https://openplanet.zendesk.com/hc/en-gb/articles/115004616154-I-worried-about-privacy-Will-my-data-leave-my-device)). Penny must ignore or disable that transcription path and run its existing local MLX Whisper/Speech pipeline instead. The folder adapter must treat the incoming file as untrusted input until copied, hashed, deduplicated, and recorded in Penny’s ledger. The current Voice Memos private database remains a fallback source, not an authority or durable contract.

## Penny integration boundary

The adapter should watch a Penny-owned folder and separate these states:

1. file observed;
2. durable copy completed;
3. hash and source identity recorded;
4. local transcription completed;
5. interpretation and downstream delivery completed.

Capture source is provenance, not authority for sensitive effects. Any action that changes sensitive state must use an authenticated source and the exact Slack step-up approval flow already required by Penny. A Watch recording or JPR file must never bypass those approvals.

## Testing gates

Before treating any option as production-ready, run at least 20 synthetic captures across:

- phone present and phone absent;
- offline recording and delayed reconnection;
- Watch and phone reboot;
- iCloud transfer delay;
- duplicate files;
- partial or interrupted files;
- p95 capture-to-ingest latency; and
- zero-loss verification against the synthetic source set.

Record source receipt, durable file hash, transfer timing, adapter outcome, and downstream receipts separately. A successful recording gesture is not proof of transfer, transcription, authorization, or delivery.

## Decision

Proceed to a separately approved JPR pilot design centered on a Penny folder adapter and local MLX Whisper/Speech. Keep Voice Memos hardening available as the free fallback. Build the custom Watch/iPhone recorder only if JPR fails the reliability, offline, privacy, or provenance gates.
