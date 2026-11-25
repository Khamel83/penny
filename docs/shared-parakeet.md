# Shared Parakeet primary with bounded Whisper retries

Owner approved implementation and controlled cutover October 1, 2026. Penny
owns the existing authenticated service on 10311. Atlas and MinusPod remain
HTTP clients. Existing module/label/header names stay compatible; health and
responses report the actual pinned model identity.

The checked-in `[shared_whisper] backend = "parakeet"` configuration selects
Parakeet for ordinary CLI/Doctor callers as well as launch agents.
`PENNY_SHARED_ASR_BACKEND=whisper` explicitly selects rollback.
`PENNY_SHARED_ASR_BACKEND=parakeet` selects Parakeet v3 BF16 at
`ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15`; the default configuration can be overridden with `whisper`.
`PENNY_PARAKEET_MODEL_PATH` and `PENNY_PARAKEET_PYTHON` bind a separately staged
external-SSD model and Python 3.12 runtime. Model/config/tokenizer SHA-256 values
are verified in the child before any model load. No hub lookup is permitted.
The root Python environment and existing Whisper weights remain unchanged.

Parakeet uses native 30-second chunks with 2-second overlap and reconstructs
words from timed wordpieces. No diarization or speaker naming is implied.
Sentence boundaries can overlap by well under a second: a word start no more
than 1.0 s behind the previous word start is clamped to that start instead of
failing the whole transcript, and the shared protocol validator applies the
same 1.0 s tolerance. A larger backward jump still fails as
`backwards_parakeet_token_time`. For new Parakeet output, brief restarts are
accepted. Eight consecutive repeated tokens still trigger review unless the
Parakeet output has matching, acoustically aligned word starts at speaking rate:
the run must have fewer than 20 tokens, strictly increasing starts and a median
start-to-start gap of at least 0.12 seconds. Shared, negative, nonfinite,
unrepresentably large, missing or mismatched timing cannot relax that hold.
Timing alignment is segment-local, so an unrelated segment without word timing
does not invalidate a fully timed run elsewhere. The existing low-diversity
suffix check and Whisper quality-held records/policy are unchanged. A malformed output or severe
repetition-quality failure triggers at most one
Whisper retry of a bounded upload (maximum 660 seconds including context).
Longer flagged uploads return a review error, requiring an excerpt rather than
silently retranscribing a whole podcast. Fluent missing words/negations cannot
reliably be detected by these checks. A different model is not ground truth.

One supervisor serializes both engines: it terminates and verifies exit of the
old child before loading the other, checks host ownership/memory pressure, and
retains existing Penny priority and 300-second idle unloading. Tiny Wyoming
on 10300/10301 is unchanged. Actual backend identity is preserved in responses
and Penny metadata/checkpoints; model-policy-specific checkpoints do not reuse
old Whisper text as new Parakeet output. Mixed chunk results identify both.

Jobs have a deadline of `max(900 seconds, 2 × audio duration)` when duration is
available, otherwise 900 seconds. An unresponsive worker is terminated through
the supervisor stop path and the request fails with
`WhisperUnavailable("worker_deadline_exceeded")`; the next request creates a
fresh worker. A warning records the client, elapsed time and deadline, not audio
or transcript content. Health/status expose `active_job_started_at` as Unix
epoch seconds and `active_job_age_seconds` measured with the monotonic clock;
both are null when idle. The keeper treats age above 1800 seconds as unhealthy,
even with HTTP 200, and requests service recovery after two consecutive strikes.
This backstop also applies to legitimately long jobs; the fixed keeper bound
can interrupt one after 30 minutes plus the strike interval.

A worker that never starts is caught sooner (penny#192). Both workers send a
ready message once the model process is up. If none arrives within
`PENNY_SHARED_WHISPER_START_TIMEOUT_SECONDS` (default 180, bounded 30–1800),
the request fails with `worker_start_timeout` and the child is stopped. A
stop never raises: a child that survives kill is kept on an abandoned list, so
no second model loads while it lives (penny#186).

`/health` returns 503 (with the same JSON plus `healthy: false` and
`unhealthy_reason`) when the service cannot finish work: three failures in a
row that a restart can fix (`consecutive_failures`), an abandoned child still
alive (`worker_did_not_exit`), a job 120 seconds past its deadline or start
limit (`job_past_deadline`, `worker_start_timeout`), or a supervisor lock that
does not answer within 3 seconds (`supervisor_unresponsive`). One success
clears the count. Memory-pressure refusals and errors returned by a running
model do not count. The keeper's `curl -sf` treats the 503 as a strike, so
launchd restarts the service after two strikes; Doctor and Uptime Kuma show it
down meanwhile. `consecutive_failures`, `last_failure_reason` and
`last_success_at` are in the payload. While `/health` is 503 the deploy
scripts refuse to proceed until the keeper has recovered the service.

Two 503 reasons come from the process-list check that runs before a model
loads. While idle, `/health` runs that check itself, so both show at once after
a restart and clear on their own; requests are refused meanwhile and do not add
to `consecutive_failures`.

- `large_owner_present`: the check found another process holding a Whisper or
  Parakeet model. The usual cause is a child that survived kill: the restart
  for `worker_did_not_exit` drops the abandoned list, and the new service
  process then finds the child. A restart cannot clear it, so the keeper
  leaves this reason alone instead of restarting every four minutes, while
  Doctor and Uptime Kuma keep showing it down.
- `owner_check_failed`: `ps` failed or timed out, so nobody knows whether
  another owner is there. Loading stays refused, but this is not proof of an
  owner, so the keeper counts it as a normal strike and restarts after two
  checks. If it keeps coming back, find out why `ps` fails on the Mac. Do not
  end any process for it.

To clear `large_owner_present`, identify the owner before ending anything. In
the runtime checkout:

1. `curl -s http://127.0.0.1:10311/health` must show `unhealthy_reason`
   `large_owner_present`. For any other reason, end nothing.
2. List exactly the processes the check matched (each line is a PID and its
   command; an error means `ps` could not be read, so end nothing):

   ```sh
   venv/bin/python -c 'from shared_whisper.worker import MacMemoryGuard; print(*MacMemoryGuard().large_owner_lines(), sep="\n")'
   ```

3. For each PID, run `ps -o ppid=,etime=,command= -p <pid>`. A worker left by
   an earlier service process has parent PID 1, because its parent is gone. A
   parent equal to the `pid` that
   `launchctl print gui/$(id -u)/com.penny.shared-whisper` shows means it is
   the running service's own worker: leave it. A command starting
   `agent-cli-` is another service, not a stuck worker: stop it through its
   own launchd job, not with `kill`.
4. `kill <pid>`. If `ps -p <pid>` still shows it ten seconds later, use
   `kill -9 <pid>`. One that survives `kill -9` is stuck in the kernel and
   needs a Mac restart. `/health` clears once the process is gone.

Retry receipts keep the copied upload and both model results owner-only. They
are written under `/Volumes/2TB_SSD/penny-asr-runtime/asr-retries` while that
volume is mounted; `PENNY_ASR_RETRY_DIR` must be an absolute physical path
(no symlink aliases or `..`) and overrides the default. If the volume is unavailable and no explicit absolute override is
set, retry receipt creation fails closed rather than copying bulk audio to the
internal disk. Retention is bounded: once a receipt reaches a terminal state
(`retry_completed` or `retry_failed`), its `audio.*` copy is deleted and only
`receipt.json` stays. Only terminal receipt directories with receipts older
than 14 days are pruned. Pending, review, unknown and unreadable receipts keep
their audio and are never age-pruned. A fresh receipt in an old directory stays;
symlink roots, receipt directories, receipts and audio are not followed for
retention. Explicit overrides beneath the SSD also fail closed when its mount
is unavailable.

For an explicitly questioned passage, use the installed credential environment:

```bash
venv/bin/python scripts/retry_asr_excerpt.py /path/to/original.mp3 \
  --start 3600 --end 3900 --output /private/path/whisper-second-opinion.json
```

This clips only those five minutes plus five seconds of context on either side,
requests pinned Whisper, and adds the offset back to segment/word timestamps.
The second opinion is a new owner-only local artifact, never an automatic
canonical rewrite or delivery replay. Retain source and both versions; verify
consequential disagreements against audio before adopting a correction.

Cutover order: stage and test source/runtime first; pause Penny transcription
producers and Atlas/MinusPod admission; drain or preserve active work; back up
installed configs; activate reviewed source/clients; run authenticated generated
or public-audio canaries including Parakeet→Whisper→Parakeet and timestamp
contracts; restore admission/producers; verify health and the next normal
capture/archive and MinusPod completion separately. Retain a rollback restoring
both client selection and service env/plists/image. Do not release held private
rows or replay old deliveries. Source success alone is not deployment proof.
