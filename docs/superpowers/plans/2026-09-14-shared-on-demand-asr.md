# Shared On-Demand ASR for Penny and MinusPod Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Penny and MinusPod, the podcast product inside Atlas, to one
Penny-owned on-demand MLX Whisper service on the Mac mini. Keep the model out
of the long-lived watcher and webhook processes, allow only one MLX worker,
give Penny priority, and make a preempted MinusPod chunk retryable from
durable audio.

**Architecture:** Penny contains the service source. A small Flask/Werkzeug
listener accepts the existing OpenAI-compatible transcription request and
owns a priority supervisor. The supervisor starts one `spawn`ed MLX child for
serial requests while work is active, accepts only complete results, and
terminates the child after a short bounded idle grace or when preemption or
model-off requires it. The listener does not import `mlx_whisper`. Penny and
MinusPod use bearer tokens that map to high and normal priority. The existing
`10311` port remains the final port; `10312` is the canary port.

The modules are deliberately split at the resource and trust boundaries:
`worker.py` is the only MLX import boundary, `supervisor.py` owns admission and
preemption, `server.py` owns HTTP/authentication, `protocol.py` validates the
compatibility contract, and `client.py` is the reusable caller. Do not merge
these boundaries into the listener as a simplification; doing so would make it
easy for long-lived HTTP code to retain MLX state or publish an incomplete
result.

**Tech Stack:** Python 3.14, Flask/Werkzeug, `requests`, `multiprocessing`
with the macOS `spawn` context, `mlx-whisper==0.4.3`, ffmpeg, launchd,
systemd/Docker configuration for MinusPod, and pytest.

## Global Constraints

- Penny is the only source owner for the shared Mac ASR service. Do not create
  a new repository.
- The only approved model is
  `mlx-community/whisper-large-v3-turbo@a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb`
  at Penny's verified local path. The service validates the existing model
  receipt before it starts a worker.
- The watcher, webhook, `transcript_quality.py`, MinusPod client, and Atlas
  helper must not import or execute MLX after cutover. The worker is the only
  runtime MLX boundary.
- At most one MLX child and one inference request may exist on the Mac at a
  time. Reuse that child for sequential requests while the queue is active or
  during the short configured idle grace; terminate it after the grace, on
  preemption, on worker failure, or on model-off. Do not use a request thread
  pool in the shared service.
- The service must preserve `POST /v1/audio/transcriptions`, multipart file
  upload, FLAC decoding, `response_format=verbose_json`, segment timestamps,
  word timestamps, and complete-response-only success.
- All upload, ffmpeg, and worker temporary files must use the 2TB SSD temp
  directory. The service must fail closed if that directory is absent or not
  writable; it must not silently fall back to the small internal disk. Every
  request removes its temporary files on success, retryable failure, worker
  crash, disconnect, or preemption.
- A Penny request is high priority. A MinusPod request is normal priority. A
  preempted MinusPod request is HTTP 503 with a retryable error, or a transport
  failure that the client treats as retryable. It must never become a partial
  successful transcript.
- The service must defensively cap MinusPod admission at one request total
  (active or queued), even if the caller's settings are stale. Excess normal
  requests receive HTTP 429 or 503 with `Retry-After`; this guard prevents a
  misconfigured client from accumulating uploads in the Mac service.
- MinusPod must be configured and persisted at one episode, one chunk worker,
  one admitted request, and one pool slot. `transcribe_concurrent_chunks=1`
  alone is insufficient because its current Whisper pool is disabled.
- `com.wyoming.whisper` on `10300`/`10301` remains a separate Home Assistant
  service using the `tiny` model. It is explicitly excluded from the shared
  large-model service and must never be pointed at the large model.
- Keep the existing `com.atlas.minuspod-whisper` plist, Atlas helper, queue,
  and systemd units as disabled rollback artifacts. Do not delete them.
- Audit and retire every legacy Atlas path that can invoke or feed the old Mac
  transcription queue, including the `atlas-whisper-pull`,
  `atlas-whisper-push`, `atlas-whisper-sync`, `atlas-whisper-download`,
  `atlas-whisper-import`/`import-fast`, and `atlas-whisper-cleanup` units and
  the `com.atlas.whisperx` LaunchAgent. Preserve their files as disabled
  rollback artifacts; do not disable the unrelated `com.wyoming.whisper`
  tiny-model service.
- Preserve the dirty Atlas worktree. Stage only intended ASR files; do not use
  `git add -A`.
- Never place a token value in tracked files, logs, test output, or a rollout
  receipt. Use environment-variable names and redacted configuration state.
- No runtime or external configuration change is part of writing this plan.

---

## 1. Define configuration and the compatibility contract

### 1.1 Write failing tests first

- [ ] Add `tests/test_asr_config.py` covering default values, bounded numeric
  values, the `10311` final port, the `10312` canary override, required model
  identity, allowed source CIDRs, the SSD temp directory, the one-request
  normal-admission bound, and missing-token failure without printing a token.
- [ ] Add `tests/test_asr_protocol.py` covering:
  - accepted request fields and `timestamp_granularities[]` parsing;
  - rejection of the wrong model or unsupported response format;
  - complete `verbose_json` parsing with segment and word timestamps;
  - rejection of a missing, malformed, or partial result;
  - the machine-readable `asr_preempted` retryable error;
  - safe bounded error messages with no audio path, transcript text, or key.

### 1.2 Implement the configuration and protocol

- [ ] Add an `[asr]` section to `config.toml` with these non-secret defaults:
  `host=0.0.0.0`, `port=10311`, `canary_port=10312`,
  `base_url=http://127.0.0.1:10311/v1`, `model_name=large-v3-turbo`,
  `max_upload_bytes=52428800`, `max_queue=8`, `max_normal_admitted=1`,
  `temp_dir=/Volumes/2TB_SSD/atlas-whisper/tmp`,
  `idle_grace_seconds=30`, `preemption_grace_seconds=5`,
  `worker_start_timeout_seconds=15`, `worker_terminate_timeout_seconds=2`,
  and `worker_join_timeout_seconds=3`.
  Keep the existing Voice Memos model path and pinned revision as the model
  source of truth.
- [ ] Add `AsrConfig` to `config.py`. Read endpoint and timing overrides from
  `PENNY_ASR_HOST`, `PENNY_ASR_PORT`, `PENNY_ASR_BASE_URL`,
  `PENNY_ASR_MAX_QUEUE`, `PENNY_ASR_MAX_NORMAL_ADMITTED`,
  `PENNY_ASR_TEMP_DIR`, `PENNY_ASR_IDLE_GRACE_SECONDS`,
  `PENNY_ASR_PREEMPTION_GRACE_SECONDS`,
  `PENNY_ASR_WORKER_START_TIMEOUT_SECONDS`,
  `PENNY_ASR_WORKER_TERMINATE_TIMEOUT_SECONDS`,
  `PENNY_ASR_WORKER_JOIN_TIMEOUT_SECONDS`, and
  `PENNY_ASR_ALLOWED_CIDRS`. Read secrets only from
  `PENNY_ASR_TOKEN`, `MINUSPOD_ASR_TOKEN`, and
  `PENNY_ASR_ADMIN_TOKEN`.
- [ ] Keep the normal Penny client default at
  `http://127.0.0.1:10311/v1`. Allow `PENNY_ASR_BASE_URL` to point the
  canary client at `http://127.0.0.1:10312/v1` or the Homelab canary at the
  Mac's Tailscale address without editing tracked source.
- [ ] Add `asr/__init__.py` and `asr/protocol.py`. Define the request, response,
  segment, word, status, and error dataclasses. Require these response fields:
  `language`, `duration`, `text`, and `segments`; require each segment's
  `start`, `end`, and `text`, and each word's `word`, `start`, and `end`.
- [ ] Define the API error mapping. Use HTTP 400 for invalid form data or
  model/format selection, HTTP 401 for a missing or wrong bearer token, HTTP
  413 for an oversized upload, HTTP 429/503 for bounded admission or service
  pressure with a bounded `Retry-After`, and HTTP 503 with code
  `asr_preempted` for Penny preemption.
- [ ] Keep `verbose_json` as the required success format. The worker always
  asks MLX for `word_timestamps=True`, even when a client requests only
  segment granularity, so the internal response remains useful for both
  consumers.

Run:

```bash
venv/bin/python -m pytest tests/test_asr_config.py tests/test_asr_protocol.py
```

Commit: `test: define shared ASR configuration and contract`.

## 2. Isolate MLX and implement one-worker priority supervision

### 2.1 Write failing tests first

- [ ] Add `tests/test_asr_worker.py` covering the worker's pinned-model
  validation, `word_timestamps=True`, language/task options, complete result
  serialization, worker exception serialization, and import isolation. The
  parent-side modules must be importable when a test blocks `mlx_whisper`.
- [ ] Add `tests/test_asr_supervisor.py` covering:
  - FIFO order within Penny and within MinusPod;
  - Penny ahead of queued MinusPod work;
  - exactly one active worker and one active request;
  - reuse of one worker PID for sequential requests while work or the idle
    grace is active, followed by termination after the grace;
  - a normal request preempted after the five-second bounded grace;
  - a normal request allowed to finish when it completes inside that grace;
  - no result publication after worker termination;
  - model-off rejection and retryable release of queued work;
  - worker crash, timeout, bounded process-group termination, queue full, and
    idle child termination;
  - status fields for queue counts, current client, request ID, worker PID,
    loaded state, and counters.

### 2.2 Implement the isolated worker

- [ ] Add `asr/worker.py`. Import `mlx_whisper` only inside the spawned worker
  entrypoint. Validate `PENNY_WHISPER_MODEL_PATH` with the existing pinned
  model receipt functions before calling MLX.
- [ ] Use `multiprocessing.get_context("spawn")`, a private pipe or bounded
  queue, and one persistent child for the current active burst. The child
  loads MLX once and processes requests serially while work is active or the
  30-second idle grace is running; it never accepts a second simultaneous
  request. Pass only the staged audio path and validated transcription options
  to the child.
- [ ] Start the child in its own process group and report its process-group ID
  to the parent. Any ffmpeg descendants created during decoding must remain in
  that group so preemption can clean up the whole worker tree.
- [ ] Call MLX with the approved local model path, `language` when supplied,
  `task="transcribe"`, `condition_on_previous_text=False`, and
  `word_timestamps=True`. Normalize the result into `asr.protocol` objects.
- [ ] Treat an absent or malformed result as a worker failure. The parent must
  accept a result only after the child reports completion and the protocol
  validator succeeds. Do not return whatever partial data exists when the
  child exits unexpectedly.
- [ ] Keep the child for the configured idle grace after the last completed
  request so sequential MinusPod chunks and Penny quality retries can reuse
  the loaded model. After the grace, or immediately on preemption,
  model-off, worker timeout, or worker crash, terminate the entire process
  group and join the child within the configured bounds. This is the
  memory-release mechanism: no MLX arrays or Metal buffers remain in the
  listener after the child exits.

### 2.3 Implement the supervisor

- [ ] Add `asr/supervisor.py` with a `PriorityQueue`, a monotonic sequence
  number, one dispatcher, one active job, and a bounded queue. Give Penny
  priority `0` and MinusPod priority `10`; preserve FIFO order for equal
  priorities.
- [ ] Track per-client admission separately from the global queue. Allow at
  most one admitted MinusPod request total (active or queued); reject further
  normal submissions with a bounded retryable error. Keep Penny's own bound
  finite so duplicate captures cannot grow memory without limit.
- [ ] On a Penny submission while a MinusPod child is active, allow the active
  child to finish only during the configured five-second grace. If it does not
  finish, send `SIGTERM` to the supervisor-owned worker process group, wait
  only `worker_terminate_timeout_seconds`, and escalate to `SIGKILL` for that
  same group if it is still alive. Bound `Process.join()` by
  `worker_join_timeout_seconds`, verify the child PID has been joined before
  starting Penny, and never signal a PID obtained from an unrelated process
  listing. Resolve the MinusPod future as `asr_preempted` only after the
  worker tree is dead, and publish no result from that child.
- [ ] When the normal child finishes inside the grace, publish its complete
  response and then start Penny. Record the wait in status so the one-minute
  Penny measurement is explainable.
- [ ] Keep the staged upload file owned by the HTTP request until the future
  resolves. Delete it only after the complete response has been returned or a
  retryable failure has been recorded. MinusPod's durable source remains at
  the caller.
- [ ] Implement `model_off()` to stop admitting requests, preempt a normal
  child safely, resolve all queued futures retryably, and terminate the child
  while leaving the listener alive. Implement `resume_model()` for the
  operator command.
- [ ] Apply the same targeted termination sequence to `model_off()` and
  `pause_client("minuspod")`: for Penny preemption, allow the configured grace
  only while a Penny request is waiting; for an explicit model-off or
  MinusPod-pause command, stop the active normal child through its owned
  process-group handle, escalate only after the bounded termination wait,
  join it, and resolve the request retryably. A Penny child is never preempted
  by a MinusPod pause or normal admission change.
- [ ] Implement `pause_client("minuspod")` and `resume_client("minuspod")`.
  Pausing rejects new normal requests and resolves queued normal requests
  retryably; it never stops a Penny request. Resuming only changes admission
  state and does not create a worker until a request arrives.
- [ ] Implement `shutdown()` so the listener can stop only after pending work
  has been resolved retryably. Never use queue deletion as shutdown or
  rollback.

Run:

```bash
venv/bin/python -m pytest tests/test_asr_worker.py tests/test_asr_supervisor.py
```

Commit: `feat: add isolated on-demand ASR worker and supervisor`.

## 3. Add the HTTP service and Penny client

### 3.1 Write failing tests first

- [ ] Add `tests/test_asr_server.py` using an injected fake supervisor. Cover
  bearer role selection, source-CIDR rejection, multipart FLAC upload,
  ffmpeg-path availability, form-field compatibility, health, model-off,
  queue-full, per-client admission rejection with `Retry-After`, preemption,
  client disconnect while queued, and cleanup of temporary files on success,
  retryable failure, crash, and preemption.
- [ ] Add `tests/test_asr_client.py` with mocked HTTP responses. Assert the
  exact multipart request, bearer header, `model=large-v3-turbo`,
  `response_format=verbose_json`, both timestamp granularities, and bounded
  error classification. Assert that 503/preemption is raised as retryable and
  that a partial 200 is rejected.

### 3.2 Implement the service

- [ ] Add `asr/server.py` with an app factory, `create_app(config, supervisor)`,
  and a `main()` entrypoint. Use Werkzeug's threaded WSGI server only for
  concurrent request handling; the supervisor remains the sole inference
  admission point.
- [ ] Implement `POST /v1/audio/transcriptions`. Require the `file` multipart
  field, enforce the upload cap before saving, preserve the safe basename and
  suffix, parse `model`, `language`, `response_format`, `vad_filter`, and
  `timestamp_granularities[]`, then submit one request to the supervisor.
  Return bounded retryable errors with `Retry-After` for normal-admission
  rejection, worker pressure, and preemption.
- [ ] Keep ffmpeg on the launchd `PATH` and verify both ffmpeg and the SSD temp
  directory at service startup. The service must accept MinusPod's
  ffmpeg-produced FLAC files and retain its current decode behavior. A
  client-side FLAC conversion failure remains a retryable caller error; it
  must not produce a false transcript. Refuse startup if the temp directory is
  unavailable or not writable.
- [ ] Implement `GET /health` as metadata-only liveness plus supervisor state:
  service name, approved model identity, listener state, accepting state,
  worker PID, loaded/idle state, current client, queue counts, active request
  count, and load/unload/request counters. Do not include paths, tokens,
  transcripts, or audio details. Permit unauthenticated health only from
  loopback; require either client bearer token from the allowed Tailscale
  path.
- [ ] Implement loopback-only admin routes
  `POST /control/model-off`, `POST /control/model-on`, and
  `POST /control/shutdown`, plus
  `POST /control/client/minuspod-off` and
  `POST /control/client/minuspod-on`. Require
  `PENNY_ASR_ADMIN_TOKEN` and compare it with a constant-time check. Return
  only bounded status metadata.
- [ ] Use the default source allowlist `127.0.0.0/8`, `::1/128`, and the
  Homelab Tailscale peer `100.112.130.100/32`; permit an explicit operator
  override for a changed private Tailscale address. Require a separate bearer
  token for every transcription request.

### 3.3 Implement the client

- [ ] Add `asr/client.py` with `SharedAsrClient.transcribe_file()` and
  `health()`. Upload the caller's file as multipart `file`; send a list of
  form tuples so both `timestamp_granularities[]=segment` and
  `timestamp_granularities[]=word` are preserved.
- [ ] Map HTTP 503/429, connection errors, timeout, and `asr_preempted` to a
  bounded `RetryableAsrError` carrying only a safe code and optional retry
  delay. Parse and honor a bounded `Retry-After` value. Do not automatically
  replay a preempted request inside the HTTP client; the caller must retry the
  same durable audio unit.
- [ ] Validate the returned model identity and response schema before exposing
  text or segments to Penny. Return `AsrResponse` with the full segment/word
  structure so MinusPod's existing parser remains unchanged.

Run:

```bash
venv/bin/python -m pytest tests/test_asr_server.py tests/test_asr_client.py
```

Commit: `feat: expose the shared OpenAI-compatible ASR service`.

## 4. Move Penny's watcher, webhook, and readiness boundary

### 4.1 Write failing integration tests first

- [ ] Update `tests/test_transcript_quality.py` to mock
  `SharedAsrClient`, preserving the existing two-attempt quality policy and
  `TranscriptionResult` shape. Add a test that a retryable ASR error exits
  before a second quality attempt.
- [ ] Update `tests/test_watcher.py` to assert that processing stages the audio
  before the shared client call, marks a retryable ASR failure as retryable,
  and leaves the staged object intact. Add a static import-boundary assertion
  that watcher and quality modules do not import `mlx_whisper`.
- [ ] Update `tests/test_webhook.py` to cover shared-client transcription,
  retryable 503 behavior, and durable staged audio on service failure.
- [ ] Update `tests/test_doctor.py` to cover healthy listener with unloaded
  model, service unavailable, model identity mismatch, and malformed health.

### 4.2 Change the Penny runtime

- [ ] Refactor `transcript_quality.py` so `transcribe_with_quality()` calls
  `SharedAsrClient` twice when quality requires the existing fallback. Keep
  `evaluate_transcript()`, model receipt verification, quality codes, and
  `TranscriptionResult`; remove its runtime MLX import. A retryable service
  failure must propagate as a typed retryable error.
- [ ] In `watcher.py`, remove the direct `mlx_whisper` dependency check and
  direct model argument at the call site. Probe the shared `/health` contract
  instead. Add a bounded `asr_service_ok` health field and a specific
  `transcription_service_unavailable` retry reason before the generic
  `processing_error` path.
- [ ] In `webhook/server.py`, keep the existing ffmpeg normalization and
  upload/persistence flow, but call the shared client without a model path.
  Return HTTP 503 for retryable ASR failure and do not publish a transcript.
- [ ] Preserve existing transcript/archive columns without a schema migration.
  Set transcription backend metadata to `penny-shared-asr` and retain the
  existing full pinned `WHISPER_MODEL_ID` in both watcher and webhook archive
  metadata.
- [ ] In `doctor.py`, replace the direct local-inference readiness test with
  a local pinned-model receipt check plus authenticated/loopback shared-service
  health check. A healthy listener with `loaded=false` is ready; an absent
  listener is unready with `asr_service_unavailable`; a wrong revision is
  unready with `model_identity_mismatch`.
- [ ] Change `voice_memos.poll_interval_seconds` in `config.toml` from `60` to
  `10` so detection latency is measurable against the one-minute target. Keep
  the target measured from local detection/staging, not from iCloud sync.
- [ ] Keep the watcher and webhook launchd templates free of model-loading
  behavior. The service template, not those templates, owns the model path and
  `HF_HUB_OFFLINE=1`.

Run:

```bash
venv/bin/python -m pytest tests/test_transcript_quality.py tests/test_watcher.py tests/test_webhook.py tests/test_doctor.py
venv/bin/python -m pytest
```

Commit: `feat: route Penny transcription through shared ASR`.

## 5. Add controls, launchd ownership, and operator documentation

- [ ] Add `scripts/penny_asr.py` with these commands:
  - `status`: print service health, worker PID/state, queue/current client,
    `vmmap` physical footprint when a worker exists, swap summary, and the
    redacted `10301` Wyoming health;
  - `on`: bootstrap `com.penny.asr`;
  - `off`: boot it out after it has resolved pending requests retryably;
  - `model-off` and `model-on`: call the loopback admin routes;
  - `minuspod-off` and `minuspod-on`: toggle normal-priority admission;
  - `penny-off` and `penny-on`: stop/start `com.penny.watcher` without
    deleting staged captures.
- [ ] Add `launchd/com.penny.asr.plist.template`. Run
  `/Users/macmini/penny/venv/bin/python -m asr.server` with label
  `com.penny.asr`, final port `10311`, `PENNY_SOURCE_REVISION`,
  `PENNY_WHISPER_MODEL_PATH`, `PENNY_ASR_TOKEN`,
  `MINUSPOD_ASR_TOKEN`, `PENNY_ASR_ADMIN_TOKEN`, `HF_HUB_OFFLINE=1`, and a
  `PATH` containing `/opt/homebrew/bin` for ffmpeg. Set both `TMPDIR` and
  `PENNY_ASR_TEMP_DIR` to `/Volumes/2TB_SSD/atlas-whisper/tmp/`; deployment
  must create that directory with service-only permissions and verify it is
  writable before bootstrap. Do not add a fallback to the internal disk.
  Write logs under `~/.penny/logs`, not to the SSD log path that causes launchd
  failure.
- [ ] Add `PENNY_ASR_BASE_URL=http://127.0.0.1:10311/v1` and the
  `PENNY_ASR_TOKEN` placeholder to both
  `launchd/com.penny.watcher.plist.template` and
  `launchd/com.penny.webhook.plist.template`. Do not put the admin or
  MinusPod token in either client plist.
- [ ] Update `docs/macmini-deployment.md`, `docs/reliability.md`, and
  `docs/troubleshooting.md` to distinguish listener liveness, worker/model
  residency, durable transcription, and downstream receipts. Document that
  `model-off` keeps the listener but stops all inference, while `off` removes
  the listener too.
- [ ] Document the memory states: idle listener with no MLX child; one worker
  reused for serial work and immediate quality retries; child exit after the
  short idle grace; and separate tiny Wyoming service at `10301`. State that
  Homelab's MinusPod container still uses its own RAM, but it no longer creates
  a second Mac model allocation.
- [ ] Add a static boundary check to `scripts/trust_check.py` or the focused
  test suite: runtime references to `mlx_whisper` are allowed only in
  `asr/worker.py` and the existing model-provisioning code, not in watcher,
  webhook, quality, or client modules.

Run:

```bash
venv/bin/python -m compileall asr scripts/penny_asr.py
venv/bin/python scripts/trust_check.py
git diff --check
```

Commit: `docs: add shared ASR controls and deployment boundary`.

## 6. Prepare the Atlas/MinusPod client and retire competing ownership

Work in `/Volumes/2TB_SSD/GitHub/atlas` only for the files named here. Preserve
the existing modifications to `1shot/DEBUG.md`, `CONTEXT.md`, and `TODO.md`.

- [ ] Update `deploy/minuspod/.env.example` so the documented endpoint remains
  `http://100.113.216.27:10311/v1`, the model remains `large-v3-turbo`, and
  `WHISPER_API_KEY` is described as the Homelab-held `MINUSPOD_ASR_TOKEN`
  rather than `not-needed`. Do not put the real token in the example.
- [ ] Update `deploy/minuspod/README.md` to identify Penny's shared service as
  the final Mac owner, state that the model is unloaded after work, document
  the `10312` canary endpoint, and list the rollback `com.atlas` plist.
- [ ] Add the serialized MinusPod settings to the deployment runbook. Use the
  authenticated `PUT /api/settings/ad-detection` surface with:
  `transcribeConcurrentChunks=1`, `whisperPoolEnabled=true`,
  `whisperPoolMaxRequests=1`, and `whisperPoolMaxEpisodes=1`. Verify with
  `GET /api/settings`; do not rely on the current source defaults of `4` and
  disabled pool. If authenticated settings access is unavailable, stop at
  that gate and do not claim the cutover is safe.
- [ ] Verify the live long-episode log reports `workers=1` and that no more
  than one `Sending audio to whisper API` interval overlaps another. The
  existing remote API integration already sends multipart FLAC,
  `verbose_json`, segment/word timestamp granularity, and a configured model;
  retain that contract during the endpoint change.
- [ ] Verify the deployed MinusPod client treats HTTP 503 with
  `asr_preempted` and bounded `Retry-After` as a retryable chunk result, and
  that a transport disconnect during preemption also retains the durable audio
  for retry. If either behavior marks the episode terminal, stop at this gate
  and repair the client behavior before the endpoint cutover.
- [ ] Add an opt-in retirement guard to
  `scripts/macwhisper_pipeline.sh`: after argument validation and before any
  SSH or MLX work, exit safely unless
  `ATLAS_LEGACY_WHISPER_ROLLBACK=1` is explicitly set. Document that the
  variable is for bounded rollback only. Keep the helper and queue intact.
- [ ] Add the same opt-in rollback guard to
  `scripts/whisper_push_pipeline.sh`, which directly invokes WhisperX on the
  Mac. Do not let the old push job create a second model owner during or after
  cutover.
- [ ] Mark the old queue path as retired in `docs/MAC_MINI_WHISPER.md`,
  `docs/TRANSCRIPT_SYSTEMS.md`, and `docs/WHISPER_PIPELINE.md`. Audit the
  deployed state of `atlas-whisper-pull`, `atlas-whisper-push`,
  `atlas-whisper-sync`, `atlas-whisper-download`,
  `atlas-whisper-import`/`import-fast`, and `atlas-whisper-cleanup`, plus the
  Mac `com.atlas.whisperx` LaunchAgent and cron/LaunchAgent watchers. Disable
  any unit that can invoke, feed, or consume the old Mac transcription queue
  before final ownership. Keep the unit files, plist, helper, and queue as
  disabled rollback artifacts; do not delete them or disable the separate
  `com.wyoming.whisper` service.
- [ ] Run the Atlas shell and focused checks without touching unrelated dirty
  files:

```bash
bash -n scripts/macwhisper_pipeline.sh
git diff --check
```

Commit the intended Atlas changes separately as:
`docs: route MinusPod transcription through Penny shared ASR`.

## 7. Controlled canary and final cutover

All steps in this section are live operations. Execute them only after the
code commits above pass their focused and full tests. Capture a redacted,
durable receipt under `~/.penny/asr/receipts/` with the Penny and Atlas source
SHAs, service label, endpoint, health metadata, MinusPod settings, timer state,
worker PID/state, and memory evidence. Never include token values or audio.

### 7.1 Preflight evidence

- [ ] Record the current `com.atlas.minuspod-whisper` launchd state, `:10311`
  health, current active request count, `com.wyoming.whisper`/`:10301`
  health, every legacy Atlas Whisper timer/LaunchAgent state, current Atlas
  service PID, and current `vmmap`/swap and internal/SSD free-space evidence.
- [ ] Confirm the pinned Penny model receipt exists and matches the approved
  revision. Confirm ffmpeg is available from the launchd `PATH`, and confirm
  the SSD temp directory exists, is writable by the service, and has adequate
  free space.
- [ ] Confirm the current Atlas timer job is either idle or has a durable queue
  position that can be retried. Do not kill a live job without preserving its
  source and retry state.

### 7.2 Canary on `10312`

- [ ] Start the new Penny service on `10312` with the canary launchd
  environment while leaving the current `10311` service untouched. Verify
  `GET http://127.0.0.1:10312/health` reports the approved identity,
  `worker_count=0`, and `loaded=false` after idle.
- [ ] Send a synthetic multipart FLAC to `10312` and verify authentication,
  complete `verbose_json`, segment and word timestamps, one child PID reused
  for two sequential requests, process-group cleanup on termination, and no
  worker after the idle-grace check.
- [ ] Persist MinusPod's four serialized settings and verify them from the
  authenticated settings API before changing its endpoint.
- [ ] Point a controlled Penny client at `10312` and run one real short Voice
  Memo canary. Verify the existing SQLite row, archive manifest/hashes,
  quality result, routing, and downstream receipts. Measure detection/staging
  to durable transcript; require less than one minute for the representative
  short memo.
- [ ] Before any long canary, stop the active legacy Atlas service safely and
  pause/disable its timer for the bounded test window. Preserve its queue and
  rollback receipt. This prevents the old direct SSH/MLX path from allocating
  a second Mac model during the new-service test.
- [ ] Point MinusPod at `http://100.113.216.27:10312/v1` and run one
  representative long episode. Confirm one chunk upload at a time, one
  service worker, complete response, and durable downstream episode state.
- [ ] Start a normal MinusPod chunk, submit a Penny memo during that chunk,
  and verify the normal request receives `asr_preempted`/503 or a retryable
  disconnect, Penny completes within the SLA, the durable MinusPod chunk is
  still present, and the retry later completes exactly once.

### 7.3 Final port and ownership switch

- [ ] Verify the canary has no direct Atlas helper process, no duplicate MLX
  worker, no unexpected `10301` large-model allocation, and no active or
  enabled legacy Atlas unit that can invoke or feed the old Mac transcription
  queue.
- [ ] Disable the deployed legacy timer with `systemctl disable --now
  atlas-whisper-pull.timer`; stop any remaining
  `atlas-whisper-pull.service` only after its durable queue state is recorded.
  Verify the retirement guard prevents accidental direct SSH/MLX execution.
- [ ] Confirm the old owner is in the current user's GUI domain, then unload
  it with `launchctl bootout gui/$(id -u)/com.atlas.minuspod-whisper`; verify
  its label is no longer loaded and `10311` is free. Keep its plist and the
  old systemd units disabled as rollback artifacts. If `bootout` reports that
  the label is already absent, verify the port and continue; do not delete the
  plist.
- [ ] Stop the canary service, start `com.penny.asr` on `10311`, and point
  MinusPod back to `http://100.113.216.27:10311/v1`. Do not change the model or
  API contract during this port move.
- [ ] Verify final source revision, launchd label, health, authentication,
  worker count, model unloaded state, `10301` tiny/unloaded state, memory
  footprint, and swap behavior.
- [ ] Run one final Penny memo, one MinusPod chunk, and one simultaneous
  preemption canary. Verify durable results, no partial 200, no duplicate
  success, and one-minute Penny timing.
- [ ] Observe idle, Penny-only, MinusPod-only, simultaneous, and reboot/long
  idle states. The steady-state idle receipt must show a small listener, no
  MLX child, `loaded=false`, and no direct Atlas worker.

### 7.4 Rollback

- [ ] If the new service fails a canary, stop new requests and retain all
  durable source media and staged captures.
- [ ] Point MinusPod back to the old `10311` service only if its health and
  contract probe pass. Restore the old launchd plist and set
  `ATLAS_LEGACY_WHISPER_ROLLBACK=1` only for an explicitly bounded rollback;
  never restore the old timer silently.
- [ ] If Penny's client must be rolled back, restore its prior direct-client
  code only through a reviewed commit and record that this reintroduces the
  memory problem. Prefer leaving captures retryable until the shared service
  is repaired.
- [ ] Record the rollback source/runtime/effect receipt. Do not delete queues,
  transcripts, model files, or logs to make health appear green.

## 8. Final verification and completion gate

- [ ] Run Penny's full tests, trust check, bytecode compile, and `git diff
  --check` on the exact deployed SHA.
- [ ] Run the Atlas shell/focused tests and verify the exact Atlas deployment
  SHA separately from the Penny SHA.
- [ ] Verify with `rg` that watcher, webhook, `transcript_quality.py`, and the
  MinusPod client no longer contain runtime MLX imports or direct Mac SSH
  transcription calls.
- [ ] Verify `com.atlas.minuspod-whisper` is not loaded, the
  legacy Atlas Whisper timers are inactive/disabled, `com.atlas.whisperx` is
  not loaded, and no legacy helper or WhisperX PID is live. Verify that the
  pure shared-service client and downstream receipt paths remain enabled.
- [ ] Verify `com.wyoming.whisper` still serves only the separate tiny model
  on `10300`/`10301` and reports unloaded at idle.
- [ ] Verify the final ASR health response identifies the approved model
  revision, current client, queue, worker PID, and loaded/unloaded state.
- [ ] Verify the worker process group and every request temp directory are
  gone after success, preemption, crash, disconnect, and idle expiry; verify
  the internal disk was not used for ASR temporary files.
- [ ] Verify no Penny or MinusPod transcript is marked successful from a
  partial response, and every preempted MinusPod unit has a retry and eventual
  exactly-once durable completion receipt.
- [ ] Verify the final memory evidence shows one active model allocation at
  most, no model allocation while idle, and no return of the old three-path
  MLX ownership pattern.

The implementation is complete only when the code, deployment identity,
health, memory state, durable transcript receipts, and downstream effects all
have independent evidence. A healthy process or HTTP response alone is not
completion evidence.
