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
