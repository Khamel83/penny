# Penny native ingest on macOS 27 Golden Gate

**Research date:** 2026-08-09
**Target:** macOS 27 Golden Gate Beta 4
**Scope:** supported, unattended ingestion and Apple-native transcription; paid OpenAI voice/transcription models are excluded.

## Executive answer

Penny cannot currently obtain a Voice Memos recording or its transcript fully unattended through a supported Apple interface.

Apple documents Voice Memos sync, manual Share/drag export, and manual transcript viewing/copying. It does not document a Voice Memos API, a “recording finished” automation trigger, an audio-file output action, or a transcript-output action. Current first-party Voice Memos App Intents metadata on macOS 26.6 likewise exposes recording, playback, search/selection, deletion, import, and a recording entity with name/date/duration—but no audio or transcript property.

The recommended path is therefore:

1. Build a signed Swift Penny bridge that owns its inbox, ledger, App Intent, share target, and background lifecycle.
2. Use `SpeechAnalyzer` plus `SpeechTranscriber` as the default on-device transcription backend, with models provisioned through `AssetInventory` before unattended operation.
3. Use EventKit for Reminders. Keep Notes AppleScript as a separately monitored compatibility adapter because Apple says Notes has no client API.
4. Accept manually shared Voice Memos as the supported near-term Apple Watch handoff.
5. Keep the private Voice Memos SQLite watcher only as a read-only, fail-loud compatibility adapter—not the durable architecture.
6. For genuinely supported, zero-touch capture, record into a Penny-owned app/container. Preserving one-tap Apple Watch capture ultimately requires a Penny watchOS recorder or another source that exports to Penny through a public interface.

Apple states that `SpeechAnalyzer` powers transcription in Voice Memos, Notes, and Journal. That establishes the same public framework/technology family, but Apple does **not** promise that Voice Memos uses the identical public `SpeechTranscriber` model revision, configuration, language assets, punctuation, or post-processing. Penny must benchmark its own output rather than assuming transcript parity.

## What “unattended” means here

“Unattended” means no action for each memo after one-time user approvals, while the Penny user is logged in. A per-user LaunchAgent is not a login-window daemon, and privacy prompts cannot be granted in a headless session. A manual Share action is supported but is not unattended.

## Voice Memos surface audit

| Surface | What Apple supports or exposes | Audio output | Transcript output | Unattended verdict |
|---|---|---:|---:|---|
| Public developer API | No Voice Memos client API was found in Apple documentation | No | No | No |
| Voice Memos App Intents / Shortcuts | Record, stop/toggle, playback, search/select, delete, import, folders, playback settings in current first-party metadata | Import accepts audio; no export property | No | No supported extraction path |
| Share sheet | User selects a recording and invokes Share | Yes | Not documented as a structured transcript payload | Supported, manual |
| Finder export | User drags an individual recording to Finder | Yes | No | Supported, manual |
| Voice Memos transcript UI | View, search, select, and copy transcript | No | Copy by user | Supported, manual |
| AppleScript | Current Voice Memos app has no scripting dictionary (`sdef` returns error `-192`) | No supported terminology | No | No |
| Private group container / SQLite | Current Penny reads undocumented files and `CloudRecordings.db` | Yes, while access/schema happen to work | Private schema only | Fully automatic but unsupported and high-risk |
| File picker grant | Apple DTS demonstrates user selection of an individual memo using `NSOpenPanel`/`fileImporter` | Yes, selected file | No | Supported per selection, not automatic |
| Security-scoped folder bookmark | General macOS mechanism; not validated for new Voice Memos children | Possibly | No | Experiment only; storage layout still private |

Primary Voice Memos evidence:

- [Voice Memos iCloud sync](https://support.apple.com/en-ca/guide/voice-memos/vma6cc4d0571/mac) keeps recordings available *inside Voice Memos* across devices signed in to the same Apple Account.
- [Share a recording](https://support.apple.com/en-ca/guide/voice-memos/vm05f9fa82d4/mac) documents selecting Share or dragging an individual recording to Finder. Both are user gestures.
- [View a transcription](https://support.apple.com/guide/voice-memos/view-a-transcription-of-a-recording-vm4a03609f0d/mac) documents viewing, searching, selecting, and copying transcript text, not retrieving it through an API.
- In [Apple DTS guidance for the Voice Memos container](https://developer.apple.com/forums/thread/768040?answerId=813217022), mandatory access control blocks direct access; the supported workaround shown is user selection of an individual memo with a file picker and, for a sandboxed app, a user-selected-file entitlement plus security-scoped access.
- Apple’s [scripting terminology guide](https://developer.apple.com/library/archive/documentation/LanguagesUtilities/Conceptual/MacAutomationScriptingGuide/AboutScriptingTerminology.html) explains that supported AppleScript commands come from an app’s scripting dictionary and that not all apps are scriptable.

The absence of a public surface is not proof that no private mechanism exists. It is proof that the private database watcher cannot be treated as a supported contract.

## macOS 27 Beta 4 changes that matter

The official [macOS 27 release-notes page](https://developer.apple.com/documentation/macos-release-notes/macos-27-release-notes?changes=latest_minor) is JavaScript-backed; Apple’s [release-notes JSON](https://developer.apple.com/tutorials/data/documentation/macos-release-notes/macos-27-release-notes.json) identifies itself as **macOS 27 Golden Gate Beta 4 Release Notes** and contains the precise entries below:

- Cross-team app and app-group container access no longer prompts; it is denied by default and can be managed by the user in Privacy & Security (161835690).
- XProtect may restrict access to app data commonly targeted by malicious software; access to files created by other developer teams may be denied by default and user-managed (178668601).
- Apps can no longer read the local TCC database directly (90775556).
- A resolved Launch Daemons and Agents issue says `launchd` no longer loads a `launchd` property-list file carrying the quarantine extended attribute (166415497).
- Battery Level and Charger Shortcuts automations might not work on macOS (180337087), evidence that beta automation behavior still needs trigger-by-trigger testing.

Consequences:

- Signing a Swift bridge improves identity, permission attribution, and background-service management. It does **not** grant a supported right to read Apple’s Voice Memos container.
- Full Disk Access or a new Privacy & Security control may make a private reader work on a particular build, but Apple exposes no TCC API and gives no stability guarantee. Do not silently instruct users to broaden access as the normal design.
- Reading the raw `.m4a` files instead of SQLite reduces schema coupling but still depends on undocumented storage and cross-team container access.
- A quarantined raw LaunchAgent plist is now a concrete failure mode. A productized bridge should use `SMAppService` and surface approval/status instead of relying only on copied plist files.

Apple DTS’s [file-system permissions explanation](https://developer.apple.com/forums/thread/678819) is the controlling model: mandatory access control can apply even to root; open-panel grants and security-scoped bookmarks are the supported user-consent mechanisms; there is no TCC API; and a stable signed native executable is a better permission principal than a script interpreter.

## Apple-native transcription

`SpeechAnalyzer`, `SpeechTranscriber`, and `AssetInventory` were introduced on macOS 26 and remain the supported native path for macOS 27:

- Apple’s [WWDC25 “Bring advanced speech-to-text to your app”](https://developer.apple.com/videos/play/wwdc2025/277/) says SpeechAnalyzer powers transcription in Voice Memos, Notes, and Journal and demonstrates recorded-file and live-audio analysis.
- [`SpeechAnalyzer`](https://developer.apple.com/documentation/speech/speechanalyzer) coordinates modules and accepts analyzed audio.
- [`SpeechTranscriber`](https://developer.apple.com/documentation/speech/speechtranscriber) exposes availability and supported locales; Penny needs an explicit unsupported-locale path, optionally using `DictationTranscriber` where appropriate.
- [`AssetInventory`](https://developer.apple.com/documentation/speech/assetinventory) downloads and manages the Apple speech assets shared by the system. Model download/reservation must complete before offline unattended processing.
- Apple’s [speech-permission documentation](https://developer.apple.com/documentation/speech/asking-permission-to-use-speech-recognition) distinguishes older recognizer behavior from SpeechAnalyzer modules, which do not send audio to Apple servers.
- For finished memo files, prefer [`start(inputAudioFile:finishAfterFile:)`](https://developer.apple.com/documentation/speech/speechanalyzer/start%28inputaudiofile%3Afinishafterfile%3A%29) over a synthesized streaming pipeline.

This removes paid OpenAI transcription as a design dependency. It does not solve acquisition of Voice Memos audio.

## Shortcuts, App Intents, and background work

- [WWDC25 Shortcuts](https://developer.apple.com/videos/play/wwdc2025/260/) introduced personal automations on Mac, including time and Mac-specific folder/external-drive triggers.
- [WWDC26 Shortcuts](https://developer.apple.com/videos/play/wwdc2026/310/) adds editor-integrated automations and new triggers. None is documented as “Voice Memo finished.”
- The [Shortcuts command-line tool](https://support.apple.com/en-ca/guide/shortcuts-mac/apd455c82f02/mac) can run a shortcut with file input/output and an observable exit status, but actions that display alerts or request input pause the run.
- [Share-sheet and Quick Action shortcuts](https://support.apple.com/guide/shortcuts-mac/launch-a-shortcut-from-another-app-apd163eb9f95/mac) are valid manual ingestion surfaces.
- An [`AppIntent`](https://developer.apple.com/documentation/AppIntents/AppIntent) can expose Penny’s own ingestion operation. [`supportedModes`](https://developer.apple.com/documentation/appintents/appintent/supportedmodes) can allow Penny’s intent to run in the background. Neither feature grants access to another app’s private data.

A scheduled or folder-triggered Shortcut becomes useful **after** audio reaches a Penny-owned inbox. It is not a bridge out of Voice Memos by itself.

## Outputs: Reminders, Notes, and lifecycle

### Reminders

Use EventKit. Apple documents requesting [full Reminders access through `EKEventStore`](https://developer.apple.com/documentation/eventkit/accessing-the-event-store) and [creating and saving `EKReminder` objects](https://developer.apple.com/documentation/eventkit/creating-events-and-reminders). This provides stable identifiers and supports receipt/readback logic. A sandboxed Mac app needs the relevant personal-information entitlement and the user’s authorization.

### Notes

Apple DTS answered [“Is there an API for Apple Notes?”](https://developer.apple.com/forums/thread/813810) with “No.” Notes AppleScript works on Mac, but it is an Automation/TCC-mediated compatibility path, not a Notes API. A signed sandboxed bridge needs the [`com.apple.security.automation.apple-events`](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.automation.apple-events) entitlement and user approval. Retain idempotency markers and readback receipts, and fail loudly if the grant is revoked.

### Background lifecycle

[`SMAppService`](https://developer.apple.com/documentation/servicemanagement/smappservice?changes=_4) is the supported way to register bundled LoginItems, LaunchAgents, or LaunchDaemons. Registration is [subject to user approval](https://developer.apple.com/documentation/servicemanagement/smappservice/register%28%29), and the app must handle [`requiresApproval`](https://developer.apple.com/documentation/servicemanagement/smappservice/status-swift.enum/requiresapproval) and disabled/revoked states. Penny should expose last successful ingest, current service status, and permission-specific errors instead of treating process liveness as health.

## Architecture comparison

| Architecture | Supported acquisition | Per-memo gesture | macOS 27 durability | Role |
|---|---:|---:|---|---|
| Current private SQLite watcher | No | No | Low | Temporary compatibility adapter only |
| Scheduled Mac/iOS Shortcut over Voice Memos | No supported artifact source | No, if it had one | Low/unknown | Reject as Voice Memos extractor |
| Folder/time Shortcut over Penny inbox | Yes | No after file arrival | Medium-high | Useful orchestration layer |
| Voice Memos Share sheet to Penny | Yes | Yes | High | Recommended near-term Apple Watch handoff |
| Signed Swift bridge reading private DB | No | No | Low-medium | Better operations, same unsupported acquisition |
| Signed Swift bridge receiving shared/selected files | Yes | Yes | High | Recommended near-term bridge |
| One-time folder bookmark into Voice Memos storage | Not established | Setup only if it works | Unknown | Bounded experiment, not design assumption |
| Penny-owned Mac/iPhone/watchOS recorder + App Intent | Yes | Recording start/stop only | Highest | Recommended end-state for zero-touch ingest |
| Apple `SpeechAnalyzer` backend | Yes once Penny has audio | No | High | Recommended transcription backend |

## Recommended design

### Phase 1: supported ingestion shell

Create a stable, signed Penny Mac app containing:

- a Penny-owned inbox and append-only ingest ledger;
- a Share extension or share-sheet destination that copies audio before acknowledging success;
- an “Ingest Audio” App Intent with background support;
- a bundled LoginAgent registered by `SMAppService`;
- `SpeechAnalyzer` recorded-file transcription with explicit asset/locale readiness;
- EventKit Reminders delivery with saved identifiers and readback;
- a Notes AppleScript adapter with explicit Automation status and receipt verification;
- a health surface that separates source receipt, durable copy, transcript, interpretation, and each delivery target.

### Phase 2: isolate the legacy watcher

Run the current private reader behind a narrow interface. It must be read-only, deduplicate by content/source identity, quarantine malformed items, report container-denial separately from “no new memo,” and offer the manual Share route immediately on failure. Never make broad TCC access a silent prerequisite.

### Phase 3: own capture

For supported unattended ingest, write recordings directly into Penny-owned storage. A Mac/iPhone App Intent can start the flow; preserving Apple Watch convenience requires a Penny watchOS capture target or a supported third-party source. This is the only architecture here that removes Voice Memos private storage from the critical path.

## Field reports: useful but not authoritative

These reports are anecdotes, not Apple contracts:

| Report | Environment/date as available | Observation | Weight |
|---|---|---|---|
| [Golden Gate DB2 Shortcuts automations](https://www.reddit.com/r/MacOSBeta/comments/1udptia/golden_gate_db2_shortcut_automations/) | macOS 27 Developer Beta 2; post displayed as about one month old on 2026-08-09 | Users saw Mac triggers/automations; replies note automations already existed in macOS 26 and the trigger set changed | Confirms UI presence only |
| [OS 27 notification trigger](https://www.reddit.com/r/shortcuts/comments/1u0hpvs/os27_beta_new_automation_to_trigger_shortcuts/) | OS 27 betas 1–3; June–July 2026 comments | Several users saw the trigger fire with empty title/body or reported it still broken | Supports explicit trigger validation |
| [Voice Memos dictation quality](https://www.reddit.com/r/MacOSBeta/comments/1udukhb/improved_dictation_does_it_work_in_voice_memos/) | Golden Gate-era post; exact build not stated | One reply reports a cleaner transcript in the app, still copied manually | Quality anecdote; no API evidence |
| [Beta 3 `launchd` disk writes](https://www.reddit.com/r/MacOSBeta/comments/1upjg8s/macos_27_beta3_launchd_kept_writing_disk/) | macOS 27 Beta 3, M1/M5 reports | Users associated log/disk churn with quarantined helper plists; one reported clearing the quarantine flag | Consistent with official release note; not proof of cause generally |
| [Voice Memos audio/transcript Shortcut gap](https://www.reddit.com/r/shortcuts/comments/1r4puvz/any_way_to_move_voice_memo_recording_audio_files/) | iOS 26.3, February 2026 | User could search names but not retrieve audio/transcript automatically; replies describe inconsistent transcript-only behavior and bypassing Voice Memos | Indirect, platform differs |
| [Speech framework field reports](https://developer.apple.com/forums/tags/speech) | macOS 26.3 build 25D122, March 2026 | A user reports recorded-file transcription succeeds while replaying the same WAV through `start(inputSequence:)` fails with `_GenericObjCError`; Feedback FB22149971 | Reason to prefer file API and retest on Beta 4 |

No credible macOS 27 Beta 4 field report found in this research demonstrates stable unattended access to the private Voice Memos container, exported audio, or transcript retrieval. That absence must not be converted into either a guarantee of breakage or a guarantee of compatibility.

## Exact macOS 27 validation plan

Use synthetic recordings only. Do not rename, delete, or edit production Voice Memos from a beta system.

1. **Record the baseline.** Capture Beta number, full build, Xcode/SDK build, Voice Memos version and code signature, hardware, Apple Account state, and every relevant Privacy & Security grant.
2. **Inventory public surfaces.** Extract Voice Memos `Metadata.appintents`, list actions/parameters/output entities, run `sdef`, and save a Shortcuts UI screen recording. Pass only if an Apple-defined audio or transcript output actually exists; names/search results do not count.
3. **Test manual Share.** Share a uniquely named memo to the Penny prototype. Record the input UTType, filename, bytes/hash, duration, and copy receipt. Reboot and repeat.
4. **Test file and folder grants separately.** Select one memo with `NSOpenPanel`, persist a security-scoped bookmark, relaunch/logout/reboot, and verify read. Separately select the recordings directory if the picker permits it, create a later memo, and test whether the bookmark covers the new child. A pass proves access on that build, not a Voice Memos storage contract.
5. **Run the container matrix.** For the same synthetic memo, test current Python interactively, current LaunchAgent, signed Swift app interactively, and its `SMAppService` agent. Record exact `errno`, unified-log denial, responsible code identity, and Privacy & Security state. Never write to Apple’s DB/container.
6. **Test Shortcuts triggers.** Exercise Time of Day, Folder, login, and notification triggers while unlocked, locked, after logout/login, and after reboot. Each run writes a UUID/timestamp receipt to Penny-owned storage. Confirm whether input values survive; “notification displayed” is not success.
7. **Prove transcript non-exposure or exposure.** Inspect every Voice Memos action result and share payload. A supported pass requires a public action/property/UTType returning transcript text without Accessibility/UI scripting or private file reads.
8. **Validate SpeechAnalyzer offline.** Preflight `isAvailable`, locale support, asset installation/reservation and disk use. Transcribe fixed English and mixed-language audio with `start(inputAudioFile:finishAfterFile:)`, disconnect networking, reboot, and repeat. Record latency, real-time factor, word error rate, punctuation, timestamps, and asset failure behavior.
9. **Validate service lifecycle.** Register with `SMAppService`; capture status before/after approval, disabled state, app update, logout/login, reboot, and a quarantined-build test. A disabled or `requiresApproval` state must generate actionable health output.
10. **Validate outputs.** Create a disposable EventKit reminder, save/read it by persistent identity, then delete it. Create a disposable Notes note through AppleScript, verify marker/body by readback, revoke Automation permission, and confirm Penny reports failure without duplicate creation.
11. **Trace one physical Watch memo end to end.** Use a unique spoken canary. Record timestamps for Watch completion, iCloud appearance, source discovery, durable Penny copy, transcript, parsed actions, Reminders receipt, and Notes receipt. Repeat across reboot and a deliberately denied source permission.

### Promotion gates

- Do not call any Voice Memos route “supported” unless a public Apple surface provides the artifact.
- Do not call any route “unattended” until it completes without a per-memo gesture across reboot/logout-login and permission-denial recovery.
- Do not promote Apple-native transcription until assets survive an offline reboot and all required locales have an explicit fallback.
- Do not remove the current watcher until a supported capture route has completed the physical-device canary repeatedly and the ledger proves no duplicates or gaps.

## Best no-spare-Mac test lane

Use a separate APFS boot volume—preferably on an external SSD if available—for the decisive Beta 4 run. Apple explicitly documents [using more than one macOS version on separate APFS volumes](https://support.apple.com/en-us/118282) as a way to try a later version while retaining the current installation. Back up first: Apple warns that later macOS versions can install shared security changes that affect the older installation.

Create a separate local test user, keep the stable Penny volume untouched, and use only disposable memos. If Voice Memos iCloud/Watch behavior must be tested with the production Apple Account, make the beta-side procedure read-only because iCloud mutations can propagate.

A VM is a good preflight for compilation, App Intent discovery, Shortcuts UI, SpeechAnalyzer assets, EventKit, Notes automation, `SMAppService`, and the Beta 4 privacy error shape. Apple supports [macOS guests on Apple silicon](https://developer.apple.com/documentation/virtualization/virtualize-macos-on-a-mac) using restore images. However, a VM result is not dispositive for physical Apple Watch/iCloud synchronization, the host’s actual Voice Memos library, or the exact real-machine permission history. Also verify that a Beta 4 restore image is compatible with the macOS 26 host; Apple’s documentation does not promise every future beta guest will install on an older host.

**Decision:** VM first if it is immediately available and compatible; separate APFS boot volume for the go/no-go evidence.

## Evidence gaps

- Beta 4 was not installed for this research; all macOS 27 behavior remains to be measured on its exact build.
- Voice Memos App Intents metadata was inspected locally on macOS 26.6 build 25G72, not Beta 4.
- Apple has not documented whether a user-managed macOS 27 privacy control can persistently authorize this particular Voice Memos group container.
- Apple does not document a stable Voice Memos file layout, database schema, transcript schema, notification, or completion event.
- Apple does not promise parity between Voice Memos’ transcript pipeline and a third-party `SpeechTranscriber` configuration.
- A security-scoped bookmark to an individual memo is supported; access to a Voice Memos directory and future children is unproven.
- Shortcuts automation behavior and notification payloads are beta-sensitive.
- Notes remains without a supported client API; AppleScript durability must be revalidated on each major macOS release.

## Bottom line

Apple-native transcription is viable now. Supported unattended extraction from Apple Voice Memos is not. The safest architecture is to make Penny own the audio as early as possible, accept manual Voice Memos sharing during the transition, and quarantine the current private database watcher behind a health-monitored compatibility boundary.
