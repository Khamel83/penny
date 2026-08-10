# Penny for Dummies: macOS 27 (Golden Gate) and a future-proofing plan

**Research date:** 2026-08-09

**Scope:** Penny's Voice Memos intake, local ledger, transcription, classifier, launchd services, and Notes/Reminders delivery.

**Source rule:** Product and API claims below are linked to first-party Apple or OpenAI documentation. “Inference” means an engineering recommendation derived from those facts and the checked repository, not a promise made by Apple or OpenAI.

## Executive summary

macOS 27 **Golden Gate is a real, announced release in developer beta**, not a hypothetical unreleased name. Apple's release-notes index currently exposes **“macOS 27 Golden Gate Beta 4 Release Notes”** and says the macOS 27 SDK ships with Xcode 27 ([release notes](https://developer.apple.com/documentation/macos-release-notes/macos-27-release-notes?changes=latest_minor)). Apple's product page calls it a preview “coming this fall” and says Siri AI is coming in English later this year ([macOS 27 preview](https://www.apple.com/os/macos/)). The final build, final API behavior, and final regional/language availability are therefore not yet fixed.

For Penny, the important distinction is this:

* **Apple's supported surface** is Voice Memos/iCloud sync as experienced through the Voice Memos app, privacy-controlled system APIs, Speech, EventKit, App Intents, and Service Management.
* **Penny's current implementation** is a Python launchd agent that opens Voice Memos' private `CloudRecordings.db`, reads an Apple-private schema, shells out to `osascript` for Voice Memos/Notes/Reminders, runs MLX Whisper, and serves a Flask endpoint on `0.0.0.0`.
* macOS 27 does not make the private SQLite path a supported API. The safest future is to keep that adapter isolated, add a native permission-aware bridge, and preserve the local ledger and idempotent routing contract while each new Apple API is proven.

## Live audit snapshot

The following is a read-only snapshot taken on **2026-08-09 at approximately 19:44 PDT**. It did not create a test memo, Apple Note/Reminder, Slack message, Maya Drop, or other external side effect.

| Check | Evidence | Assessment |
| --- | --- | --- |
| Host/runtime | Production host is macOS 26.6 (build 25G72), Apple Silicon `arm64`; Penny's venv Python and Homebrew ffmpeg are arm64 | Compatible with Apple's stated Mac mini 2020+ Golden Gate hardware floor; no present Rosetta dependency was found |
| Services | Penny watcher, webhook, and task poller plus Maya server/drop daemon are registered and running; export/watchdog jobs last exited 0 on their schedules | Processes are up, but process state alone is not the acceptance test |
| Source intake | Voice Memos DB and Penny health are readable; source and local watermarks both equal PK 407; no waiting/pending rows; Voice Memos answered an Apple Event probe | Current source is caught up |
| Local ledger | SQLite `integrity_check` and `quick_check` are `ok`; no foreign-key violations; 479 transcript rows | Canonical local state is structurally healthy |
| Slack | 22 delivery rows are `sent`; zero pending or failed | Durable Slack outbox is caught up |
| Maya v2 | All 16 eligible rows are `sent` with Drop IDs; Maya health returned HTTP 200 and its database reported healthy | Durable Maya handoff is caught up |
| Most recent physical evidence | Latest source memo was recorded 2026-08-07 06:20:20Z; the corresponding Penny route/Slack/Maya activity completed by 06:23:36Z | Strong recent evidence, but not a same-day physical canary |
| Backup/export | The 2026-08-09 16:05 PDT export contained all 479 rows and logged a successful homelab sync | Current export evidence is fresh; a restore drill was not performed |
| Tests | Repository venv suite: 197 passed, 2 skipped, exit 0 | Hermetic code verification passes |

This supports **“Penny is currently working and caught up.”** It does not support the stronger claim that every downstream Apple object still exists: the audit verified Penny's durable local route state without creating or reading private memo content, and the current AppleScript adapter has no provider receipt/read-after-write contract. One historical Voice Memos row from April remains `failed`, while the source watermark has advanced; the current headline health bit does not treat that as unhealthy.

## Penny for Dummies

1. You record on Apple Watch. iCloud makes that recording appear in Voice Memos on the Mac when the same Apple Account is used and Voice Memos is enabled in iCloud ([Voice Memos User Guide](https://support.apple.com/en-ie/guide/voice-memos/-vma6cc4d0571/mac)).
2. `watcher.py` looks at the Mac's Voice Memos recording directory and private SQLite database, finds new rows, and waits for the matching audio file.
3. Penny writes a durable row to `~/.penny/transcripts.db`, transcribes locally with MLX Whisper, and **classifies/routes locally first** with `allow_maya=False`. Notes go to the Penny folder; actionable items become Reminders; ambiguous short memos produce both a note and an Inbox reminder.
4. After the local route is durably recorded, independent Slack and Maya v2 outboxes retry in the background. Maya v2 receives a versioned envelope and durable receipt; it does not return the raw transcript through `/deliver`. `/deliver` is an authenticated legacy/exception path for content that already needs local Apple-side delivery.
5. A small Flask service accepts alternate audio/text uploads and Maya's authenticated `/deliver` callback.

The “future-proof” goal is not to replace this flow in one risky rewrite. It is to keep the ledger and routing behavior stable while replacing the fragile OS-bound edges one at a time.

## What is in this repository today

| Area | Current implementation | macOS 27 implication |
| --- | --- | --- |
| Voice Memos intake | `watcher.py`: `CLOUDRECORDINGS_DB` points at `~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/CloudRecordings.db`; direct `sqlite3` reads of `ZCLOUDRECORDING`; file polling | Private path/schema is an implementation detail. TCC/FDA and schema changes can stop the watcher before transcription. |
| Voice Memos health | `watcher.py` probes Voice Memos with `osascript` and recycles an unresponsive app | Apple Events are Automation-controlled; this is not a public CloudKit or Voice Memos SDK. |
| Persistence | `transcript_log.py` and `~/.penny/transcripts.db` | Keep this as the source of truth; a future native app/helper should use its own app or app-group container and migrate explicitly. |
| Outboxes | `watcher.py` runs `_process_slack_outbox()` and `_process_maya_outbox()` after local routing; `core.py` persisted paths call `classify_and_route(..., allow_maya=False)` | Local Apple delivery is canonical and durable first. Slack and Maya v2 are independent retrying outboxes; Maya v2 uses an envelope/receipt contract and does not round-trip raw transcripts through `/deliver`. |
| Transcription | `transcript_quality.py` calls `mlx_whisper.transcribe` at most twice with deterministic quality checks | Evaluate Apple's on-device `SpeechAnalyzer`/`SpeechTranscriber` as an optional backend; keep MLX fallback until quality and offline behavior are measured. |
| Notes/Reminders | `reminders.py` creates records with `osascript` AppleScript | Automation consent remains required. EventKit is a supported Reminders API; no equivalent public Notes database API was found. |
| Background execution | `launchd/*.plist.template`, per-user LaunchAgents, `KeepAlive` and `RunAtLoad` | Apple recommends Service Management/`SMAppService` for bundled helpers on macOS 13+; registration and background execution are user-visible/approval-controlled. |
| HTTP/network | `webhook/server.py` binds `cfg.webhook.host = "0.0.0.0"`; unauthenticated `POST /upload` and `POST /ingest` are reachable on every interface; `maya_delivery.py`/`core.py` use Python `requests` | **Present security gap:** any reachable client can submit audio/text and trigger transcription/routing. Treat all-interface listening and local-network egress as explicit security decisions; a future native client must account for local-network privacy and ATS. |
| AI/classification | `core.py`/`classifier.py` use configured OpenRouter model; no Apple Intelligence/App Intents target exists | Foundation Models/App Intents require a native Swift integration (or a separately proven bridge), and beta model behavior must be evaluated. |

## Reliability audit beyond macOS 27

These are current implementation risks, not predictions about Golden Gate:

| Priority | Finding | Why it matters | Planned correction |
| --- | --- | --- | --- |
| P0 | `POST /upload` and `POST /ingest` are unauthenticated while Flask binds to `0.0.0.0`; request size is enforced only after the body is written | Any reachable client can spend transcription/LLM resources and trigger Notes/Reminders | Bind loopback by default; require authenticated, size-limited ingress before any public/Tailscale exposure; prefer a Unix socket behind a native bridge |
| P0 | A Voice Memos processing failure can be marked `failed` while the source PK watermark advances; the automatic retry query excludes `failed` rows | A transient hash/transcription/file error can become a silent terminal capture gap | Separate discovery watermark from completion; retry eligible failures with bounded backoff; surface terminal quarantine as unhealthy |
| P0 | `insert_transcript()` returns the same `None` for a duplicate and a database error; the Google Tasks poller can then mark the source task complete | A database outage can acknowledge work that was never durably stored | Return a typed result (`inserted`, `duplicate`, `failed`) and acknowledge external work only after inserted/known-duplicate evidence |
| P1 | `watcher_ok` omits Voice Memos responsiveness, `voice_db_ok`, awaiting/failed source rows, and the true pending-local-route count; HTTP `/health` is only a process/config response | Today's green signal can coexist with broken intake | Add one aggregate readiness/doctor contract covering receipt, persistence, source watermark, local routing, both outboxes, and backup age |
| P1 | Notes/Reminders writes are non-idempotent AppleScript side effects; a successful Apple write followed by a local progress-write failure can duplicate on retry | Ambiguous timeouts/crashes can create duplicate user-visible objects | Use EventKit IDs for Reminders; add stable effect keys and verification receipts; retain a guarded Notes adapter until Apple offers a supported equivalent |
| P1 | Transient Maya retries have no terminal cap; three historical rows needed 128–187 attempts before eventually succeeding | Infinite retry preserves eventual delivery but can hide a long outage and create noisy load | Keep eventual delivery, but add attempt-age alerts, a circuit breaker, and an operator-visible quarantine state |
| P1 | The exporter logs sync failure but does not fail the job; the daily health workflow checks PIDs/log freshness rather than the durable state above | “No alert” is not positive proof of a restorable system | Make export failure affect job/health status and schedule a non-destructive restore verification |
| P2 | `HANDOFF.md`, `LLM-OVERVIEW.md`, README ordering/evidence text, and troubleshooting still describe parts of the legacy Maya/Telegram flow | An operator can repair the wrong architecture during an incident | Rewrite the operator docs around the current local-first plus independent Slack/Maya v2 contract |

One scope point needs to be made explicit in the design: **the canonical Voice Memos path receives the full local + Slack + Maya v2 guarantees; direct `/upload`, `/ingest`, and Google Tasks inputs do not all follow that same contract today.** If “everything Penny accepts must feed Maya” is the intended product rule, those inputs should converge on the same persisted envelope/outbox pipeline instead of being documented as equivalent when they are not.

## Confirmed facts from primary documentation

### 1. macOS 27 / Golden Gate status

* Apple labels the product **macOS 27 Golden Gate** and says it is “coming this fall”; Siri AI is “coming in English later this year” ([Apple macOS 27 preview](https://www.apple.com/os/macos/)).
* Apple's June 8, 2026 newsroom announcement says developer betas for macOS 27 and Xcode 27 are available, the release is a free update this fall, and features/regions/languages are subject to change ([WWDC26 announcement](https://www.apple.com/newsroom/2026/06/apple-unveils-next-generation-of-apple-intelligence-siri-ai-and-more/)).
* The release-notes index currently links **macOS 27 Golden Gate Beta 4 Release Notes** and identifies the macOS 27 SDK/Xcode 27 pairing ([macOS release notes](https://developer.apple.com/documentation/macos-release-notes/macos-27-release-notes?changes=latest_minor)).

**Engineering meaning:** use a beta test machine and pin the production Mac until a final build is available. Do not claim that a Beta 4 observation is a final macOS 27 contract.

### 1a. Beta 4 release-note changes that directly affect Penny

The following are **confirmed Beta 4 release-note entries** in Apple's [macOS 27 Golden Gate release notes](https://developer.apple.com/documentation/macos-release-notes/macos-27-release-notes?changes=latest_minor). The page is JavaScript-rendered and the search index may label the same evolving page Beta 3, so record the exact installed build when testing.

* **LaunchAgents/LaunchDaemons — confirmed:** `launchd` no longer loads a property-list file carrying the quarantine extended attribute. Apple's workaround is to remove that attribute from a trusted plist before loading it. **Penny inference:** a plist copied from a downloaded archive, GUI download, or quarantined artifact may silently fail to bootstrap. Add a deployment check for `com.apple.quarantine`, clear it only for the verified plist artifact, then run `plutil`/`launchctl` validation and a functional health probe. Do not weaken Gatekeeper or broadly strip quarantine from unrelated files.
* **System Integrity Protection / app data — confirmed:** access to another developer team's app-data or app-group containers no longer prompts and is denied by default; user management is in Privacy & Security. XProtect may also restrict access to app data commonly targeted by malicious software. **Penny inference (highest risk):** the Voice Memos group container is Apple-owned, not Penny-owned. A native Penny app-group container can protect Penny's own ledger but cannot be assumed to unlock or stabilize direct reads of Voice Memos' private container. Treat any macOS 27 denial as a privacy boundary, not a database-corruption signal, and preserve a supported share/upload fallback.
* **TCC — confirmed:** apps can no longer access the local TCC database directly. **Penny inference:** remove any future plan that inspects or edits TCC SQLite state to “pre-grant” FDA/Automation. Use the responsible signed executable, documented APIs, and a user-operated System Settings approval; health checks should report authorization outcomes, not read the TCC DB.
* **Rosetta/Intel — confirmed:** macOS 27 re-evaluates Rosetta compatibility; apps previously set to “Open using Rosetta” launch natively, Rosetta is not automatically restored after an upgrade, installer packages without `hostArchitecture` default to `arm64`, and all Intel software is scheduled to be incompatible with macOS 28 except legacy games. **Penny inference:** the checked runtime is already arm64 (`file venv/bin/python3` reports Mach-O arm64; `platform.machine()` is arm64), so Rosetta is not the current primary risk. Audit every bundled/native dependency (Python, MLX, ffmpeg, Swift helpers) for arm64/universal support and do not make macOS 28 a surprise migration deadline.

### 2. Voice Memos, iCloud, and CloudKit boundaries

* Apple's Voice Memos guide documents automatic appearance of recordings on Mac, iPhone, iPad, Vision Pro, and Apple Watch recordings when devices use the same Apple Account and Voice Memos is enabled in iCloud ([Voice Memos sync](https://support.apple.com/en-ie/guide/voice-memos/-vma6cc4d0571/mac)).
* CloudKit is an app-facing framework for moving an app's own records between an app's iCloud container and iCloud servers ([CloudKit overview](https://developer.apple.com/documentation/cloudkit)). Apple describes each app container as having public/private/shared databases and a schema chosen by that app ([designing a CloudKit database](https://developer.apple.com/documentation/cloudkit/designing-and-creating-a-cloudkit-database); [private database](https://developer.apple.com/documentation/cloudkit/ckcontainer/privateclouddatabase?changes=_7%2C_7)).
* CloudKit's documented access is through `CKContainer`/`CKDatabase` and app containers; those documents do not expose Voice Memos' private Core Data/SQLite store or a supported third-party Voice Memos-recordings API.

**Inference for Penny:** `CloudRecordings.db`, `ZCLOUDRECORDING`, and the Group Container path are private implementation details. Keep the reader in one module with a versioned adapter, never write to Apple's database, and add a supported alternate ingest (share/upload or a user-approved file handoff) before depending on a beta schema. Apple's documented sync promise is “recordings appear in Voice Memos,” not “third-party processes may query this SQLite file.”

### 3. TCC, Full Disk Access, App Sandbox, and app data containers

* macOS protects Documents, Downloads, Desktop, iCloud Drive, and network volumes with user consent; full internal-storage access, Accessibility, and Automation are managed in **System Settings → Privacy & Security → Privacy** ([Apple Platform Security: controlling app access to files](https://support.apple.com/guide/security/controlling-app-access-to-files-secddd1d86a6/web)).
* A sandboxed app gets unrestricted access to its own container, but outside files require entitlements, user-selected URLs/security-scoped bookmarks, app-group membership, or a user-granted privacy decision. Full Disk Access cannot be granted automatically by code ([Accessing files from the macOS App Sandbox](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox); [Protecting user data with App Sandbox](https://developer.apple.com/documentation/security/protecting-user-data-with-app-sandbox)).
* App-group containers are for related apps signed by the same team; `FileManager.containerURL(forSecurityApplicationGroupIdentifier:)` locates the shared container. On macOS 15+, app-group and app-data containers also receive System Integrity Protection, and an unrelated app can trigger a user authorization prompt ([configuring app groups](https://developer.apple.com/documentation/xcode/configuring-app-groups?changes=_8); [protecting local app data](https://developer.apple.com/documentation/xcode/protecting-local-app-data-using-containers?language=_1)).

**Repository evidence:** `HANDOFF.md` records a real launchd-vs-interactive TCC failure for the Homebrew Python executable reading Apple's Voice Memos DB. That incident is consistent with Apple's consent model; it is not evidence that the DB is corrupt.

**Inference for Penny:** keep production's current, explicitly granted FDA path as a named operational dependency; log the executable identity and permission failure without printing transcript contents; put Penny's own ledger/config/cache in a stable app-group or app-data container only after a signed native host exists. Moving `transcripts.db` does **not** grant access to Voice Memos' container.

### 4. Accessibility and Automation

* Apple Platform Security lists Accessibility and Automation (Apple events) as separate user-controlled privacy categories ([controlling app access to files](https://support.apple.com/guide/security/controlling-app-access-to-files-secddd1d86a6/web)).
* For a sandboxed native app that sends Apple events to other apps, the `com.apple.security.automation.apple-events` entitlement allows the app to prompt for permission; arbitrary inter-app events are otherwise restricted ([Apple Events entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.automation.apple-events); [Sandboxing and Automation](https://developer.apple.com/library/archive/qa/qa1888/)).

**Inference for Penny:** current `osascript` calls to Voice Memos, Notes, and Reminders need Automation approval for the responsible executable. Penny does not currently use Accessibility APIs; do not request Accessibility unless a future UI-automation fallback truly needs it. A native signed bridge should make the responsible identity stable so TCC grants do not silently attach to a changing Homebrew/venv path.

### 5. Background launchd and Service Management

* Service Management distinguishes Login Items, per-user LaunchAgents, and system LaunchDaemons; `SMAppService` manages bundled helper executables on macOS 13+ ([Service Management](https://developer.apple.com/documentation/servicemanagement/); [SMAppService](https://developer.apple.com/documentation/servicemanagement/smappservice?changes=_4)).
* `SMAppService.register()` registers a service subject to user approval. LaunchAgents bootstrap for the current and subsequent logins; LaunchDaemons require administrator approval and run in the system context ([register](https://developer.apple.com/documentation/servicemanagement/smappservice/register%28%29)).
* Apple's deployment guide says macOS 26 and later may prompt users when app-started background tasks remain active after the app quits ([Manage login items and background tasks](https://support.apple.com/guide/deployment/depdca572563/web)).
* Apple's older launchd programming guide remains explicit that per-user agents run only while that user is logged in and that jobs should not daemonize themselves ([Creating Launch Daemons and Agents](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)).

**Inference for Penny:** keep the current raw plist templates as the supported deployment until a native app wrapper exists. A future wrapper can register a bundled LaunchAgent with `SMAppService`, expose status/approval to the user, and launch the Python worker or (preferably) an XPC/native worker from inside the signed bundle. Do not assume `KeepAlive` means “healthy”; preserve the existing health probes and ledger checks.

### 6. Local-network privacy and network security

* Local-network privacy applies to macOS 15+ and is controlled per user in **Privacy & Security → Local Network**. Outgoing TCP/UDP connections to local addresses require the privilege; incoming TCP listening does not. A process that is a launchd **daemon** is automatically allowed, but that exception does not apply to a launchd **agent** ([TN3179: Understanding local network privacy](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy?changes=_9%2C_9)).
* An app using local-network access should declare `NSLocalNetworkUsageDescription`; a short-lived process can fail before the alert is shown, so retry/waiting behavior matters ([TN3179](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy?changes=_9%2C_9)).
* For Swift/URLSession clients, App Transport Security's `NSAllowsLocalNetworking` key controls unqualified names, `.local`, and IP-address connections; newer macOS releases otherwise restrict IP-address loads ([NSAllowsLocalNetworking](https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity/nsallowslocalnetworking)).

**Repository evidence and inference:** `webhook/server.py` binds Flask to `0.0.0.0:5678`, so it listens on every interface. Its `POST /upload` and `POST /ingest` handlers currently perform no authentication, while `/deliver` checks `PENNY_WEBHOOK_SECRET`; therefore an on-path or LAN client can submit arbitrary audio/text and trigger transcription, local Notes/Reminders writes, and ledger growth. This is a **present security gap**, not merely a future hardening suggestion. Restrict the webhook to loopback or a deliberately firewalled interface immediately in the deployment design, add an authenticated ingress (or a Unix-domain socket) before exposing it beyond localhost, require authentication/TLS for any non-loopback route, and test Maya's local-network egress from the actual per-user agent. A Swift rewrite must add the usage string/ATS policy; Python's `requests` is not itself an ATS client, but network exposure still exists.

### 7. App Intents, Apple Intelligence, Siri, and Foundation Models

* `AppIntent` makes an app's actions discoverable by Apple Intelligence, Siri, Shortcuts, and other system experiences ([AppIntent protocol](https://developer.apple.com/documentation/AppIntents/AppIntent); [App Intents framework](https://developer.apple.com/documentation/appintents)).
* macOS 27's App Intents update adds system-defined schemas and contextual cues; entities/actions can be indexed for Spotlight/Siri and tested through system pathways ([what's new in macOS 27](https://developer.apple.com/macos/whats-new/); [contextual cues](https://developer.apple.com/documentation/appintents/providing-contextual-cues-to-apple-intelligence-and-siri)).
* The `.notes` domain defines `createNote`/`updateNote` schemas for apps that implement note-taking, and the `.reminders` domain defines common list/reminder actions ([Notes schemas](https://developer.apple.com/documentation/appintents/app-schema-domain-notes); [Reminders schemas](https://developer.apple.com/documentation/appintents/app-schema-domain-reminders)). Individual schema pages are marked **Beta Software** and say the information is subject to change ([createNote](https://developer.apple.com/documentation/appintents/appschema/notesintent/createnote)).
* The Foundation Models framework is a native Swift API for on-device and Private Cloud Compute language models, structured generation, multimodal prompts, and tool calling. Users must enable Apple Intelligence to use Apple's Foundation Models ([Foundation Models](https://developer.apple.com/documentation/FoundationModels)). Apple warns that the on-device model changes with OS updates, so prompts must be retested on macOS 27 ([Foundation Models updates](https://developer.apple.com/documentation/Updates/FoundationModels)).
* Apple's WWDC26 announcement says Siri AI can use personal context, take actions in apps including Reminders, and access broad world knowledge; developer testing began in the macOS 27 beta, with user availability later and regional/language restrictions ([WWDC26 announcement](https://www.apple.com/newsroom/2026/06/apple-unveils-next-generation-of-apple-intelligence-siri-ai-and-more/)).

**Inference for Penny:** App Intents are a way to expose Penny's own actions (for example, “ingest this memo,” “route this text,” “show pending items”), not a permission bypass into Apple's Notes database. Build intents around the same idempotent core used by the webhook, and keep Apple-side delivery behind explicit EventKit/Automation checks. Foundation Models can be an optional local classifier, but require golden transcript fixtures, schema validation, and a model-version/evaluation record before replacing the current deterministic quality and routing gates.

### 8. Audio transcription APIs

* Apple's Speech framework supports prerecorded or live audio. `SpeechAnalyzer` coordinates asynchronous modules; `SpeechTranscriber` is the general conversation module; `AssetInventory` downloads and manages system speech assets shared across apps ([Speech framework](https://developer.apple.com/documentation/speech/); [SpeechAnalyzer](https://developer.apple.com/documentation/Speech/SpeechAnalyzer); [SpeechTranscriber](https://developer.apple.com/documentation/speech/speechtranscriber?changes=_1); [AssetInventory](https://developer.apple.com/documentation/speech/assetinventory?changes=_7)).
* The newer analyzer/transcriber path does not send the user's voice audio to Apple's servers; the older `SFSpeechRecognizer` path does and requires `NSSpeechRecognitionUsageDescription` and user authorization ([Speech authorization](https://developer.apple.com/documentation/speech/asking-permission-to-use-speech-recognition?changes=_1)).

**Inference for Penny:** add a Swift Speech backend behind the existing `TranscriptionResult` contract and measure accuracy, startup/asset download, offline behavior, locale support, and CPU/memory against MLX Whisper. Keep MLX as the production fallback until the native backend passes a traced-recording soak test.

### 9. Notes, Reminders, and task handoff

* EventKit is Apple's supported framework for creating, retrieving, and editing reminders. Apps must request access and must never directly modify the calendar/reminder database ([EventKit](https://developer.apple.com/documentation/eventkit); [accessing the event store](https://developer.apple.com/documentation/eventkit/accessing-the-event-store?changes=__3%2C__3); [creating reminders](https://developer.apple.com/documentation/eventkit/creating-events-and-reminders?changes=l_6)).
* EventKit's reminder access is user-authorized and the app should request only the level it needs. A native macOS client must include the applicable privacy usage description and, for a sandboxed app, the calendars entitlement ([accessing the event store](https://developer.apple.com/documentation/eventkit/accessing-the-event-store?changes=__3%2C__3)).
* App Intents' `.notes` and `.reminders` schemas make an app's own note/reminder actions understandable to Siri/Apple Intelligence; they do not turn a third-party process into a direct Notes database client ([Notes](https://developer.apple.com/documentation/appintents/app-schema-domain-notes); [Reminders](https://developer.apple.com/documentation/appintents/app-schema-domain-reminders)).

**Inference for Penny:** prefer EventKit for Reminders in a future native bridge because it has a documented data model and authorization path. Keep AppleScript Notes delivery as a compatibility adapter until Apple exposes a supported Notes data framework or the app itself owns the note store. Preserve `core.py`'s routing semantics and make every delivery return a durable success/failure receipt before marking the transcript routed.

### 10. OpenAI and ChatGPT integration (optional, never implicit)

* OpenAI's Apple Intelligence/Siri FAQ says ChatGPT is integrated into iOS, iPadOS, and macOS experiences when the user allows it ([Apple Intelligence - Siri FAQ](https://help.openai.com/en/articles/10263570)).
* OpenAI's setup guide says users can enable ChatGPT without an account or connect an account, and that Siri continues to ask permission before sending files ([Setting up ChatGPT with Apple Intelligence](https://help.openai.com/en/articles/10269382-setting-up-chatgpt-with-apple-intelligence)).
* OpenAI's partnership announcement describes the Apple integration's privacy behavior: requests are not stored by OpenAI and IP addresses are obscured for the no-account integration; connecting a ChatGPT account applies that account's data preferences ([OpenAI and Apple announce partnership](https://openai.com/index/openai-and-apple-announce-partnership/)).
* If Penny ever sends audio directly to OpenAI, the Audio API accepts common audio files through `POST /audio/transcriptions`, with model, language, response-format, chunking, and optional confidence/logprob controls ([Create transcription](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create)). OpenAI's data-controls guide documents endpoint-specific storage/processing defaults and regional requirements ([OpenAI API data controls](https://developers.openai.com/api/docs/guides/your-data#default-usage-policies-by-endpoint)).
* ChatGPT Computer Use on macOS is designed for scoped GUI work and requires separate Screen Recording/Accessibility permissions. OpenAI documents that it cannot authenticate as an administrator or approve macOS privacy prompts ([Computer Use](https://learn.chatgpt.com/docs/computer-use)). Record & Replay can turn a demonstrated macOS workflow into a reusable skill ([Record & Replay](https://learn.chatgpt.com/docs/extend/record-and-replay)).

**Inference for Penny:** macOS's user-facing Apple Intelligence/ChatGPT integration is not an API that Penny can silently invoke with the user's private memo. Keep any direct OpenAI transcription/classification as an explicit, opt-in backend with redaction, retention, cost, and network policy recorded in config and in the ledger. The default path should remain on-device/local (MLX or Speech) and the existing Maya/OpenRouter policy. Computer Use/Record & Replay can make permission recovery or release testing easier for an operator, but cannot grant FDA/Automation or replace Penny's unattended ledger/outbox service.

## Beta/release caveats

1. **macOS 27 is beta:** Apple's release notes and App Intents schema pages explicitly describe preliminary or changing information. Run tests against each beta and again against the final SDK/OS; do not ship a beta-only entitlement or schema as a hard dependency.
2. **Siri AI timing and reach are conditional:** Apple says “later this year,” starts in English, and varies by hardware, language, region, and law. Siri AI is not a reliable ingest trigger for the primary Watch Voice Memos path yet.
3. **Foundation Models are model-versioned by OS:** update tests whenever the OS/model changes; pin expected structured output and keep a fallback classifier.
4. **Speech assets are managed by the system:** first-use download, locale availability, storage reservations, and asset eviction are runtime states. A background agent must expose “assets unavailable/downloading” as a retryable state, not a permanent failure.
5. **Voice Memos internals are undocumented:** a successful query today is not a compatibility guarantee for macOS 27. Never write to Apple's DB, depend on undocumented column names without an adapter/version probe, or treat an open SQLite connection as proof that iCloud sync is complete.
6. **Permission state is executable-identity-specific:** changing the Python/venv path can require regranting FDA/Automation. A signed, stable native responsible code identity is a future reliability improvement, not a reason to remove today's operational permission checks.

## Future-proof plan

### Phase 0 — establish a safe beta lane

* Keep the production Mac on its current known-good macOS and Python runtime.
* Use a spare/secondary Apple Silicon Mac for macOS 27 Beta 4+; snapshot the Penny ledger and keep Voice Memos originals untouched.
* Record OS build, Xcode/SDK build, Python executable identity, TCC approvals, launchd labels, and a small fixture set of non-sensitive test recordings.

### Phase 1 — harden the current Python edge

* Isolate Voice Memos DB discovery/SQL in a single adapter with schema/version checks, WAL-safe read-only connections, and explicit “permission denied / schema changed / audio missing” health states.
* Keep all Apple-private paths and raw filenames out of user-facing logs; report counts, hashes, watermarks, and error classes.
* Keep the local SQLite ledger and idempotent replay behavior unchanged while adding a supported manual/share-upload fallback for recordings.
* Treat the unauthenticated all-interface `POST /upload` and `POST /ingest` surface as a release blocker: bind the webhook to loopback or put an authenticated proxy in front, then retain bearer/signature checks and add a readiness probe that proves routing, not just process presence.

### Phase 2 — introduce a signed native host/helper

* Create a small Swift macOS host (it may initially be a status/permission shell) with a stable bundle identifier and Developer ID signing.
* Move Penny-owned state to an app-data or app-group container only after migration/rollback is tested; do not expect that move to unlock Voice Memos' private container.
* Register a bundled LaunchAgent through `SMAppService`, surface `requiresApproval`/disabled states, and keep the existing Python worker as a child/helper only while the bridge is validated.
* Use XPC or a local Unix-domain socket between the host and worker instead of a publicly bound HTTP port where feasible.

### Phase 3 — add native transcription as a measured backend

* Implement `SpeechAnalyzer` + `SpeechTranscriber` in the native host, install/check `AssetInventory` assets, and map results into Penny's existing `TranscriptionResult`/quality gate.
* Compare native Speech, MLX Whisper, and (only if explicitly enabled) OpenAI transcription on a fixed fixture set: WER/quality, latency, offline behavior, locale, energy, and failure recovery.
* Keep one backend selected at a time per deployment and persist backend/model/version in the transcript ledger for auditability.

### Phase 4 — replace delivery edges deliberately

* Add EventKit Reminders delivery with the least privilege that supports Penny's needs, explicit authorization UI, list-name validation, and a durable delivery receipt.
* Keep `reminders.py` AppleScript for Notes and as a compatibility fallback. Add Automation usage text and test the signed responsible identity after every OS/binary change.
* Add App Intents only for Penny-owned, idempotent actions. If an intent invokes a Notes/Reminders delivery, it must call the same core routing function and return a clear result; it must not mutate databases directly.

### Phase 5 — optional intelligence layer

* Prototype Foundation Models classification/summarization behind a feature flag, with constrained structured output and an evaluation report per OS/model build.
* Keep deterministic routing and quality checks as the authority; an LLM may propose a route, but it cannot bypass deduplication, privacy, or delivery receipts.
* Treat Apple Intelligence/ChatGPT as a user-facing convenience and optional escalation. Require explicit user consent before sending a memo/file to ChatGPT or a direct OpenAI API endpoint, and record the chosen backend without storing secrets.

### Phase 6 — final-release gate

Before promoting macOS 27 to the production Mac, require all of the following:

* one physical Watch → Voice Memos → Penny → transcript → Maya/Penny → Notes/Reminders trace;
* a restart, logout/login, Voice Memos relaunch, network outage, TCC denial, and partial-audio-file test;
* no loss or duplicate rows across DB-schema probes and Python/native backend switches;
* launchd status plus functional health evidence (watermark advance, ledger row, and Apple-side delivery), not just a PID;
* explicit rollback to the last known-good macOS/Python/MLX path;
* written approval for any new OpenAI/cloud route and its retention/region policy.

## Source gaps and open questions

* Apple has no public Voice Memos developer API in the sources reviewed, and the official Voice Memos guide does not document `CloudRecordings.db`, its SQLite schema, or a requirement that Voice Memos remain open for sync. Those are current-repo observations, not supported Apple contracts.
* Apple does not document a public Notes database framework comparable to EventKit in the sources reviewed. Notes App Intents schemas describe app actions, not direct access to Apple's Notes store.
* macOS 27 final build, final release notes, and final Siri AI rollout were not available on the research date; re-check the release-notes index and availability pages at the release candidate.
* Foundation Models, App Intents schemas, and newer Speech input/provider classes may change during beta. The report intentionally treats them as candidate backends with fallbacks, not mandatory dependencies.
* OpenAI's Apple integration and direct API have different privacy/retention behavior. They must not be conflated: “Siri asked before sending” is not equivalent to “Penny's direct API call is not stored.”
