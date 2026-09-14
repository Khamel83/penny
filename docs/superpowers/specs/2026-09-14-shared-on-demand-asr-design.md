# Shared on-demand ASR for Penny and Atlas

**Date:** 2026-09-14  
**Status:** Approved direction; implementation plan pending review  
**Owner:** Penny  
**Related systems:** Penny Voice Memos, Atlas's MinusPod podcast product

## Decision in one paragraph

Penny will own one Mac mini speech-to-text service. There will be no new
repository. The service will run a small control/listener process and at most
one MLX Whisper worker process. The listener may stay available so Penny can
meet its latency target, but the large model worker will start only for actual
transcription work and will terminate after the queue is idle. Penny and
MinusPod will submit requests to this service; neither application will load
MLX Whisper directly. Penny requests have priority and may preempt MinusPod
work.

The existing `com.atlas.minuspod-whisper` service is useful evidence and a
temporary compatibility reference, but it is not the final ownership boundary.
The live host also has an old Atlas SSH transcription path and Penny's direct
MLX path. Both must be retired after parity is proven.

## 1. Why this change is needed

The Mac mini has 16 GiB of unified CPU/GPU memory. The current live system has
three independent MLX owners:

1. `com.penny.watcher` loads Penny's pinned `whisper-large-v3-turbo` model and
   keeps the allocation in its long-lived process.
2. `com.atlas.minuspod-whisper` serves MinusPod, the podcast product inside
   Atlas, on port `10311` and owns an independent MLX worker.
3. The active legacy `atlas-whisper-pull` timer in the Atlas repository SSHes
   to the Mac and starts `.atlas_macwhisper_transcribe.py`, another independent
   MLX process. This is not a separate Atlas product requirement; it is an old
   competing MinusPod/Atlas podcast path that must be retired.

The current evidence showed approximately 2.6 GiB, 4.3 GiB plus 0.6 GiB, and
1.8 GiB of physical footprints respectively. The exact footprint changes with
the audio and backend, but the ownership problem does not.

The same model files on disk do not create one shared model in RAM. Each
process owns its own MLX arrays and Metal buffers. The existing agent-cli
service does unload its worker after its TTL; that does not help when other
processes hold separate allocations or when MinusPod is continuously active.

## 2. Goals

- Keep Penny's Voice Memos flow on the Mac mini.
- Meet a one-minute target from Penny detecting and durably staging a new
  recording to the transcript being persisted, for representative short memos.
  iCloud or Voice Memos sync time before Penny detects the file is reported
  separately and is not included in this local SLA.
- Keep MinusPod, the podcast product inside Atlas, available as an application
  and client.
- Load only one approved MLX Whisper model at a time.
- Keep the model unloaded when there is no inference work.
- Give Penny priority over MinusPod.
- Allow Penny to preempt MinusPod safely when the one-minute target requires
  it.
- Allow MinusPod work to resume after preemption without losing or duplicating a
  podcast chunk.
- Provide explicit status, model-off, service-off, and service-on operations.
- Preserve Penny's existing transcript quality, SQLite, archive, routing, and
  downstream receipt behavior.
- Preserve Atlas's existing durable episode state and retry behavior.

## 3. Non-goals

- Do not change the approved MLX model revision during this work.
- Do not move Penny's audio or transcription off the Mac mini.
- Do not add a cloud transcription fallback automatically.
- Do not rewrite Voice Memos capture, Penny routing, Maya, or MinusPod's feed
  behavior.
- Do not delete the old helper, plists, queues, or transcript evidence during
  rollout. Retain disabled rollback artifacts until the observation window is
  complete.
- Do not promise that continuous MinusPod backfill is free. If MinusPod has a
  real backlog, one model will remain loaded while that backlog is processed. The
  design prevents duplicate model allocations and gives Penny priority; it
  cannot make a large model consume zero memory while it is actively working.

## 4. Ownership and repository placement

Penny is the source owner for the shared Mac service because:

- Penny owns the Mac-local Voice Memo transcription contract.
- Penny already pins and verifies the approved local model.
- Penny needs the strictest latency guarantee.
- Penny can preserve a recording and retry if the service is off.

The shared service source, protocol, launchd template, operator command, and
service tests belong in the Penny repository. Atlas remains the source owner
for MinusPod's podcast selection, episode state, and downstream import. The
MinusPod client remains the source owner for podcast processing. There is no
separate Atlas transcription client. Neither the Atlas/MinusPod client nor
Penny may import `mlx_whisper` or start a Mac-side model process after cutover.

The existing port `10311` should be retained to minimize the client change.
The final launchd label should describe Penny ownership, such as
`com.penny.asr`. The current Atlas-labelled service remains the rollback
artifact until the new service has passed live parity.

## 5. Target flow

```text
Voice Memos
    |
    v
Penny watcher -> Penny SQLite/staging -> high-priority ASR request --+
                                                                      |
MinusPod (inside Atlas) -> durable episode/chunk -> normal ASR request --+--> Penny ASR supervisor
                                                                            |
                                                                            +--> one MLX worker
                                                                            |
                                                                            +--> transcript response
```

The service is split into two deliberately different pieces:

### Listener and supervisor

This is a small Python process. It accepts authenticated local and Tailscale
requests, places them in a priority queue, reports status, starts or stops the
worker, and records request outcomes. It must not load the model at import or
startup.

The local Penny client uses loopback. Homelab uses the Mac's private Tailscale
address. The service must not expose unauthenticated private audio on a broad
network bind. The final deployment must use an authentication token plus a
network restriction or an equivalent private-interface policy.

### MLX worker

This is a separate spawned process. It loads the pinned local model only when
the supervisor admits a request. There is exactly one worker slot. When the
worker exits, macOS can reclaim the MLX and Metal allocations completely.

The worker receives bounded audio units and returns a complete response. A
partial response is never published as a successful transcript.

## 6. Priority and preemption policy

Penny is the high-priority client. MinusPod is the normal-priority client.

- If the worker is idle, the highest-priority request starts immediately.
- If MinusPod is waiting and Penny arrives, Penny runs first.
- If MinusPod is actively transcribing, the supervisor first asks it to finish
  the current bounded unit.
- If finishing that unit would miss Penny's one-minute target, the supervisor
  terminates only the MinusPod worker process, marks the in-flight unit
  retryable, and starts Penny. MinusPod retains the audio and retries the unit
  later.
- If the current unit is inside a bounded protected completion window and is
  projected to finish within the SLA, the supervisor lets it finish. The
  protected window is finite and visible in status; Penny must never wait
  indefinitely for a MinusPod job.
- MinusPod commits a result only after the complete unit succeeds. A terminated
  unit therefore cannot create a false success or a partial duplicate.

The first implementation must make the current job, queue, estimated remaining
time, cancellation state, and retry identity visible in logs and status. If
the underlying MLX call cannot provide reliable progress, the implementation
must use bounded units and a conservative time limit rather than pretending to
know that a job is 99% complete.

## 7. Memory and operating modes

The normal idle state is:

- Penny watcher: small process, no MLX model.
- Penny ASR listener: small process, no MLX model.
- MLX worker: absent.
- MinusPod podcast processing: available on Homelab, but no Mac model memory is
  used until a request is admitted.

The normal active state is:

- one MLX worker only;
- one request being executed;
- later requests waiting in priority order;
- the worker terminated after an idle grace period, defaulting to a short
  configurable interval rather than the current five-minute assumption;
- explicit unload available immediately after the queue drains.

The operator interface must expose these separate controls:

- `status`: show listener state, worker PID, model loaded state, queue counts,
  current client, and physical memory evidence;
- `on`: bootstrap the listener;
- `model-off`: reject or drain new work, finish or safely cancel active work,
  terminate the MLX worker, and leave the listener available;
- `off`: stop the listener after callers have been told to retain and retry
  their durable work;
- `minuspod-off` / `minuspod-on`: pause or resume MinusPod's normal-priority
  producer;
- `penny-off` / `penny-on`: pause or resume Penny processing without deleting
  staged recordings.

The listener may remain on for the one-minute Penny target. If the operator
wants zero ASR footprint, `off` removes even that small process. The large
model is the memory-sensitive part and must not remain resident merely because
the listener is available.

## 8. Required code changes

### Penny

- Add the shared ASR protocol and client.
- Replace the direct MLX calls in the watcher and webhook with the client.
- Keep staging, hashing, SQLite persistence, quality checks, archive writes,
  and downstream routing in Penny.
- Treat a service-off, timeout, preemption, or unavailable response as a
  retryable transcription state. Do not mark a capture terminal and do not
  delete its staged audio.
- Change readiness checks so they verify the shared service contract instead
  of importing MLX or requiring a model to be loaded in the watcher process.
- Add the supervisor, worker, launchd template, configuration, status command,
  and unit/integration tests.
- Keep the approved model identity and local receipt in the service health
  response and in Penny's existing transcript metadata.
- Reduce the discovery interval enough to make the local one-minute target
  measurable. Report sync-to-detection separately from detection-to-transcript.

### Atlas and MinusPod

- Point the MinusPod OpenAI-compatible transcription client at the Penny-owned
  endpoint and use the shared authentication contract. This is the only
  Atlas-side transcription client in the target design.
- Remove the direct SSH invocation of
  `.atlas_macwhisper_transcribe.py` from the canonical Atlas path.
- Retire `atlas-whisper-pull.timer` only after MinusPod/shared-service parity
  and a live transcript canary are proven.
- Keep the old timer, helper, and queue as disabled rollback evidence during
  the observation window.
- Set MinusPod requests to normal priority and ensure an interrupted bounded
  unit is retried from durable source media.
- Reconcile or archive stale Atlas configuration that advertises multiple Mac
  transcription owners or concurrent podcast jobs.

### Deployment and security

- Install the service from the Penny checkout at a recorded source revision.
- Do not copy credentials into tracked files or logs.
- Use a dedicated service token for Homelab-to-Mac requests and a local client
  configuration for Penny.
- Verify the endpoint is reachable only from loopback and the intended private
  Tailscale path.
- Preserve the current model directory and verify its receipt before cutover.

## 9. Rollout and rollback

1. Build and test the Penny supervisor on an unused local port while the
   current service remains untouched.
2. Run a local synthetic request and verify one worker, one model allocation,
   complete response, explicit worker termination, and no model in the idle
   state.
3. Switch Penny to the new client and run one real Voice Memo canary. Verify
   the existing SQLite/archive/routing receipts.
4. Switch MinusPod to the new endpoint and run one representative podcast
   chunk. Verify the downstream episode result.
5. Drain or safely stop the active old Atlas job, disable the old timer, and
   verify that no direct Atlas MLX process returns.
6. Move the new service to port `10311`, install its final launchd label, and
   verify source revision, health, worker count, model state, and memory.
7. Exercise Penny preemption of a MinusPod canary, then verify MinusPod retry
   and eventual completion.
8. Observe idle, Penny-only, MinusPod-only, and simultaneous-request states.

Rollback is a controlled client/service cutback: stop new requests, preserve
durable source media, restore the prior launchd service and client endpoint,
and verify the old path before resuming work. Do not use blind `kill -9`, delete
queue files, or delete transcript evidence as a rollback mechanism.

## 10. Acceptance evidence

The change is not complete until all of the following are demonstrated:

- After an idle period, the service listener is small and no MLX worker exists.
- One request creates one worker; a second request queues and does not create
  a second worker or model allocation.
- A Penny recording detected on the Mac reaches durable transcript state within
  the one-minute target for representative short memos.
- A Penny request preempts or safely waits behind a MinusPod unit according to
  the finite protected-completion rule.
- MinusPod resumes a preempted unit without data loss or duplicate success.
- `model-off` removes the worker and the physical footprint falls accordingly.
- `off` preserves both Penny and MinusPod work for later retry.
- No Penny watcher, webhook, Atlas helper, or MinusPod client loads MLX
  directly after cutover.
- `atlas-whisper-pull.timer` is inactive and no direct SSH MLX worker is live.
- The service health response identifies the approved model revision, current
  queue, current client, worker PID, and loaded/unloaded state.
- A reboot and a long idle period return to the no-worker state.

## 11. Known tradeoff

Sharing one model means MinusPod and Penny share one physical inference
resource.
They can both be available, but they do not perform heavy inference at the
same instant. Penny's short, user-facing request wins. MinusPod may take
longer when Penny interrupts it, but the machine avoids holding multiple
models and the user-facing path remains responsive.
