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
accepted; eight consecutive repeated
tokens or the existing low-diversity suffix signal trigger review. Existing
Whisper quality-held records/policy are unchanged. A malformed output or severe
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
