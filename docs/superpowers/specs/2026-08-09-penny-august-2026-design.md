# Penny August 2026 design specification

**Status:** approved design, 2026-08-09
**Scope:** Penny Phase A hardening and the staged path through macOS 27 qualification

This specification separates the target architecture from the behavior audited on 2026-08-09. The four research reports are the evidence base: [iCloud archive inputs](../../research/2026-08-09-penny-icloud-archive-design-inputs.md), [macOS 27 future-proofing](../../research/2026-08-09-penny-macos-27-future-proofing.md), [native ingest options](../../research/2026-08-09-penny-native-ingest-macos27-options.md), and [Watch capture options](../../research/2026-08-09-watch-ultra-penny-capture-options.md).

## 1. Outcomes and non-goals

The target system provides a durable, local-first capture path from Apple Watch or an approved upload through local transcription, Maya reasoning, Hermes execution, and observable provider receipts. A capture is never lost merely because a downstream service, Apple application, network, or beta operating system is unavailable. Every externally visible effect is attributable, bounded by policy, and safe to retry.

This design does not make Voice Memos' private database a supported API, make iCloud Drive a database or disaster-recovery system, or turn a voice transcription into authority for sensitive actions. It does not require a wholesale Swift rewrite, automatic OpenAI/ChatGPT use, or automatic sending, sharing, purchasing, legal filing, deployment, credential changes, or permanent deletion.

## 2. Current evidence and problems

### Current behavior (audited, not the target contract)

- The production host is a macOS 26.6 Apple Silicon Mac mini. Penny's Python/MLX/ffmpeg runtime is arm64.
- `watcher.py` reads the undocumented Voice Memos `CloudRecordings.db`/`ZCLOUDRECORDING` path, waits for matching audio, writes `~/.penny/transcripts.db`, transcribes with MLX Whisper, routes locally first, and then processes independent Slack and Maya v2 outboxes.
- A Flask service accepts alternate audio/text uploads and a Maya delivery callback. The current service binds to `0.0.0.0`; `/upload` and `/ingest` are unauthenticated.
- Notes and Reminders are currently written through `osascript` AppleScript. No provider read-after-write receipt is persisted.
- The live audit found 479 transcript rows, healthy SQLite checks, 22 sent Slack rows, 16 sent Maya v2 rows, a fresh 479-row export, and a passing repository suite (197 passed, 2 skipped). One historical Voice Memos row remains failed even though the source watermark advanced.

### Problems to correct

1. An all-interface unauthenticated ingress can spend resources and trigger routing from any reachable client.
2. Advancing the Voice Memos discovery watermark while marking a processing failure can create an unrecoverable gap; failed rows are not eligible for the normal retry query.
3. `insert_transcript()` conflates duplicate and database failure, allowing an upstream poller to acknowledge work that was not stored.
4. The health bit does not prove Voice Memos responsiveness, source failures, local-route backlog, provider receipts, or backup freshness.
5. AppleScript side effects can duplicate after an ambiguous timeout or a progress-write failure.
6. Maya retries can run for 128–187 attempts without a terminal cap or clear quarantine.
7. Export logging does not make backup failure unhealthy, and no scratch restore is part of readiness.
8. Current operator documents and configuration still describe stale legacy paths.
9. Direct Penny classification calls use configured OpenRouter behavior for the remaining small interpretation path; those calls must not be removed until Maya's replacement is deployed and proven.

## 3. Target architecture and ownership

The target flow is:

`capture source → Penny local staging → canonical SQLite row → local transcription → Maya reasoning/policy → Hermes execution → provider receipt`

Penny owns capture adapters, local staging, source identity, canonical SQLite persistence, raw-audio archive publication, local transcription orchestration, Notes/Reminders adapters, receipts, retries, health, and backup production. Maya owns interpretation, policy, action envelopes, approval state, and the mediated reasoning boundary. Hermes owns execution of approved capability calls and returns execution evidence. Slack is the confirmation and notification channel, not the canonical ledger.

The canonical operational record is Penny's local `~/.penny/transcripts.db`. iCloud Drive is a rebuildable, human-readable mirror. A versioned homelab backup is the independent disaster-recovery source. Apple Notes is a user-facing projection only.

## 4. Capture sources

### Just Press Record (Phase B primary)

Use JPR on Apple Watch as the pilot source. JPR records locally on the Watch, transfers to the paired iPhone, and can sync to an iCloud Drive `Just Press Record` folder. Cellular service is not required for recording or delayed transfer. Configure the supported iCloud Drive location and treat it as a JPR-owned inbox.

The Penny adapter must not rename, move, edit, or add sidecars inside that inbox. It waits for full materialization, copies the original bytes to non-iCloud local staging, computes SHA-256, and then ingests. JPR's embedded transcript is not Penny authority; Penny's selected local backend produces the canonical transcript. JPR's optional cloud transcription is disabled or ignored.

Promotion to primary requires the capture matrix in Section 10. Until then, JPR is a pilot and Voice Memos remains the fallback.

### Voice Memos (fallback)

The existing private SQLite reader is retained only as a read-only compatibility adapter. It must report container denial, schema/file errors, and “no new memo” distinctly; quarantine malformed or incomplete input; deduplicate by source/content identity; and never write Apple's database. A supported manual Share/Finder export path must remain available when the private reader is unavailable. Voice Memos is not an API or durable storage contract.

### Uploads and other inputs

Alternate audio/text uploads remain supported only through the same persisted envelope/outbox pipeline. Ingress is authenticated, bounded by request size and content type, and defaults to loopback or a protected Unix socket. No upload may bypass persistence, provenance, policy, approval, or receipts.

## 5. Durable archive, iCloud mirror, and backup

For each canonical row, Penny publishes an immutable, paired archive object under `iCloud Drive/Penny Archive/YYYY/YYYY-MM/YYYY-MM-DD/`:

```text
<utc-time>__p<row-id>__<source>__<audio-sha12>.<original-extension>
<utc-time>__p<row-id>__<source>__<audio-sha12>.md
<utc-time>__p<row-id>__<source>__<audio-sha12>.json
```

The audio preserves its original bytes and extension. The Markdown file contains UTF-8 Penny transcript content with compact provenance front matter. The JSON manifest contains schema version, canonical row ID, every observed source alias, original filename, recorded/ingested times, duration, MIME type, byte length, full audio and transcript SHA-256, and transcription engine/model identity. Files are written to temporary siblings and atomically renamed; the manifest is published last. Consumers accept an object only after all three files exist and every hash matches. Publication status is independent of ingest, transcription, Notes, Reminders, Maya, Slack, and backup status.

The homelab backup contains a transactionally consistent whole-database snapshot (including outboxes and receipts), all fully materialized archive bytes, and a catalog of path, size, hash, creation time, and backup-set ID. Retained sets do not inherit iCloud deletions. A periodic transcript JSON export is a readable aid, not a restorable operational backup.

Restore is staging-only first: verify catalog, archive hashes, SQLite integrity/schema/row count/max ID; stop writers; restore the whole database before external effects can replay; reconcile archive objects by canonical ID and full hashes; quarantine hash-valid extras; rebuild the iCloud mirror only after SQLite is healthy; resume only after read-only ledger, archive, and backup health checks pass.

## 6. Transcription and reasoning backends

- **Phase A/production:** retain MLX Whisper with a locally pinned model and networking disabled for the transcription path. Persist backend/model identity and quality outcome.
- **Shadow challenger:** evaluate Apple `SpeechAnalyzer`/`SpeechTranscriber` on finished audio files with pre-provisioned `AssetInventory` assets. Shadow results do not replace canonical transcripts or trigger effects.
- **Later challenger:** MacWhisper Pro CLI may implement the same challenger interface after MLX and Apple Speech have measured results.
- **Reasoning:** Maya is the target reasoning and policy owner. Penny's direct OpenRouter content-type/reminder calls are removed only after the Maya replacement is deployed, authenticated, idempotent, and verified on representative captures. Until that gate, keep the existing fallback behavior so degraded Maya does not silently misroute work.

## 7. Action authority and approvals

Automatic execution is limited to reversible or private work: archive, Notes, Reminders, private tasks, drafts, research, read-only work, and isolated code changes. A Slack step-up confirmation is required before sending or sharing, inviting others, merging/deploying, recoverable deletion, purchases, or access changes. The approval is one-time, durable, expires, is bound to the exact action/target/content, and is accepted only from the configured Slack user allowlist. Financial transfers, legal filings/signatures, credentials, and permanent destruction require a stronger separate manual/provider confirmation. A Watch recording never bypasses these tiers.

## 8. Failure state model and idempotency

Each capture has independently durable states for `observed`, `staged`, `persisted`, `transcribed`, `interpreted`, `approval_required`, `approved`, `executing`, `succeeded`, `failed_retryable`, `quarantined`, and `dead_letter`. Source discovery and completion watermarks are separate. A typed persistence result distinguishes `inserted`, `duplicate`, and `failed`; external work is acknowledged only for the first two.

Every effect has a deterministic idempotency key derived from canonical row ID, effect type, target, and content hash. Notes/Reminders store keys plus provider identifiers and read-back receipts. Maya and Hermes envelopes carry stable capture IDs, hashes, client references, schema versions, and durable acknowledgements. Retryable failures use bounded exponential backoff, attempt-age alerts, and a circuit breaker; terminal failures enter visible quarantine/dead-letter state. An uncertain external timeout is reconciled before retrying.

## 9. Phase A: independently deployable hardening

Phase A must ship without JPR, macOS 27, or a Swift rewrite and must preserve the current Voice Memos path while making the local contract truthful:

1. Authenticate and limit `/upload` and `/ingest` with a dedicated ingest credential; retain and verify the separate `/deliver` callback credential; default to loopback/Unix socket, enforce content type and size before expensive work, and redact credentials/content from logs.
2. Add typed persistence outcomes; separate source discovery from completion; repair the Voice Memos watermark/retry behavior; retry eligible failures with bounded backoff and quarantine terminal failures.
3. Make Penny own raw-audio staging and archive publication with SHA-256, complete-copy verification, atomic renames, and manifest-last completion.
4. Add idempotent Notes/Reminders effect keys, provider identifiers, read-back receipts, and explicit permission failures to the guarded AppleScript adapters. EventKit replaces the Reminders adapter only in a later native phase after its compatibility contract is proven.
5. Replace process-only health with a truthful Penny Doctor/readiness contract covering SQLite, source responsiveness/watermarks, staging/archive, transcription, Maya, Slack, Notes/Reminders, backup age, and dead-letter/quarantine counts.
6. Add bounded Maya retries, circuit-breaker/age alerts, durable dead-letter state, and reconciliation for uncertain delivery.
7. Produce versioned full backups and run a scratch restore verification; backup failure must affect readiness.
8. Pin the MLX model locally and prove transcription with networking disabled.
9. Converge `HANDOFF.md`, `LLM-OVERVIEW.md`, README, troubleshooting, launchd templates, and runtime configuration on the local-first + independent Slack/Maya v2 architecture.

Phase A acceptance: existing fixtures and live-safe checks pass; authenticated ingress is enforced; duplicate and database-failure paths are distinguishable; a raw capture can be restored with its hashes; Apple effects have receipts; `penny doctor` fails when any required contract is unhealthy; a scratch restore proves the backup; and MLX succeeds offline with the pinned model.

## 10. Rollout phases and macOS 27 gates

### Phase B — capture and reasoning cutover

Pilot JPR with Penny's folder adapter. Run at least 20 synthetic captures covering phone present/absent, offline recording and delayed reconnection, Watch/phone reboot, iCloud delay, duplicate files, partial files, and p95 latency. Promote JPR to primary only after zero loss/duplicates, five physical Watch Action-button canaries, and complete source-to-receipt traces. Route reasoning through Maya, then remove Penny's direct OpenRouter dependency only after the replacement gate in Section 6.

### Phase C — macOS 27 qualification

Boot the exact Golden Gate beta/final build from a separate APFS volume (a VM may preflight APIs). Use a separate test user and synthetic recordings. Validate public Voice Memos surfaces, manual Share, file/folder security-scoped grants, private-reader denial behavior, Shortcuts triggers, offline Apple Speech assets, EventKit receipts, Notes Automation failure, `SMAppService` approval/disabled states, quarantine handling for launch artifacts, logout/login, reboot, and a physical Watch trace. Do not call a route supported or unattended without evidence across reboot and permission denial.

### Phase D — upgrade and soak

Take verified snapshots, upgrade the main volume only after all gates pass, run physical Watch canaries, and monitor for 48 hours with rollback available. Keep Apple Speech in shadow initially. MacWhisper may join later as a measured challenger. Voice Memos private-database failure does not block the upgrade once JPR is proven primary.

## 11. Security and privacy

Raw audio never leaves the approved Apple/Penny storage and backup boundary, and transcription always runs locally. The canonical transcript is stored locally; transcript text may pass through authenticated Maya/Hermes reasoning and their explicitly configured model providers under the approved action policy. Penny has no direct OpenRouter dependency after the Maya cutover. Do not print raw content in operational logs or metadata-only alerts. The existing verbatim `#penny` mirror remains an explicitly approved content destination. iCloud is a synchronized mirror, not backup, and deletion propagates across devices. Homelab backup sets are versioned and deletion-resistant. Secrets remain runtime-only and dedicated by service. Use stable signed identities for future native helpers and user-approved TCC/Automation/File Provider grants; never read or edit the TCC database or Apple's Voice Memos database. Cloud transcription is never implicit and requires separate explicit approval.

## 12. Testing and service objectives

Test unit, integration, offline, reboot, logout/login, permission-denial, duplicate, partial-file, timeout, migration, backup, and restore paths. The required end-to-end targets are: 20 synthetic JPR captures with zero losses/duplicates; five physical Watch canaries; online Watch capture reaches Penny within five minutes p95; once audio reaches the Mac, transcript plus durable Maya receipt completes within two minutes p95; MLX works with networking disabled; every Apple/provider effect has a read-back receipt; and a scratch restore succeeds. Health claims require durable state and downstream evidence, not PID or process freshness alone.

## 13. Migration and rollback

Migrations are additive and versioned. Preserve existing SQLite IDs, hashes, outbox rows, and receipts; introduce new state/receipt fields before changing writers. Archive existing rows by copying and hashing; never mutate source folders. Run dual-read/shadow comparison before promoting a new transcription or capture adapter. On any failed gate, disable the new adapter, preserve staged/archive evidence, restore the prior database/config from the verified snapshot if needed, and resume the known-good Voice Memos + MLX path. Do not delete old data until a verified restore and retention window have completed.

## 14. Operational readiness

`penny doctor` is the operator entry point and reports each component separately: source receipt, durable copy, canonical SQLite, transcription, interpretation, approval, each delivery target, archive mirror, homelab backup, retry age, and dead-letter/quarantine. Launch agents must expose registration/approval/disabled state; quarantined plist artifacts are detected and handled only for verified Penny files. Alerts identify the capture ID, state, attempt age, and remediation class without exposing transcript content. The runbook distinguishes provider receipt, durable storage, routing, downstream effect, failure, and current state.

## 15. Explicit manual gates

The following remain human decisions or actions: install/configure JPR; grant macOS/iCloud/File Provider/Automation/EventKit permissions; approve Slack step-up actions and stronger provider confirmations; approve any cloud provider or OpenAI route; create/choose a separate APFS beta volume and test Apple Account; approve the production macOS upgrade after gate evidence; and authorize any permanent deletion, financial transfer, legal filing/signature, credential change, merge, deploy, send, or share. No implementation step treats a beta observation, generated document, process PID, or provider request as proof of a completed external effect.
