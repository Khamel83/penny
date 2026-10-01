# Apple Speech pilot

The owner approved an Apple pilot on October 1, 2026 following the M4 research
in draft PR #66. Sharing Penny and Atlas was a RAM workaround, not a required
future architecture. Pilot approval does not imply that an unverified candidate
may replace or deliver a held transcript.

## Workflow and acceptance contract

The opt-in shadow hook captures authorized real requests from Penny, Atlas and
historical backfill at the existing shared ASR boundary. The canonical response
remains pinned MLX Whisper. Apple receives a private immutable audio snapshot
and runs independently through the modern on-device SpeechTranscriber API.
Live admission is best effort: at most two daemon admission threads retain open
upload descriptors. Copying, hashing and fsync run outside the response thread;
stalled storage fills these slots and later admissions are refused immediately.
An uncommitted admission can be lost on service restart. Only a committed queue
row proves durable admission. Capture failure must not alter the primary HTTP response or service startup.
Existing clients and Atlas's retry, ad-cutting and publication behavior are
unchanged. There is no cloud fallback.

The pilot has its own SQLite queue, private text/segment results and metadata
receipts. It never writes Penny's canonical database, archives, quality status,
Drop, Slack, Maya, Atlas queues or publication state. Candidate quality checks
use the existing Penny rule set; `quality_passed` means those heuristics passed,
not that the transcript has human-verified word accuracy.

Two sessions run at most. Live Penny requests precede Atlas requests, followed
by the historical corpus. Jobs are keyed by client plus original-audio SHA-256;
repeated requests do not create repeated jobs. Audio is hash-checked before
execution. The default campaign cap is 200 unique jobs and 8 GiB of retained
original audio; one input is capped at 512 MiB. Admission at capacity is refused
without changing the primary response. Results are retained for comparison;
capacity does not imply permission to delete source audio.

FFmpeg converts only a scratch copy to 16 kHz mono WAV. Conversion has a
120-second deadline; Apple execution has a 300-second deadline. Timeout kills
the process group. Worker shutdown cancels its subprocess groups. One process
lock prevents duplicate queue runners. Restarted in-flight jobs can be claimed
at most three times, then become visibly failed. Ordinary failed jobs are not
automatically replayed. Host pressure below 12% free prevents starting new jobs.

The pilot checks the external volume's deployed UUID at startup and its mount
and device identity before database operations. Audio and receipts stay on the
Mac; private root directories are mode 0700, payload files mode 0600. Apple model
assets must be installed and checked using the exact deployed executable.
Apple owns model updates; record OS build and CLI hash rather than inventing a
fixed Apple model revision.

## Initial workload

The October 1 inventory found 32 quality-held Penny recordings, all with local
audio, and no ordinary waiting Penny transcription queue. These are a useful
quality-recovery test set, not permission to clear the holds. Atlas's actual
auto-process queue had two pending and two processing episodes; its 57,888
discovered episodes were not queued transcription work. There were also 264
retained local legacy Atlas audio files, distinct from its live MinusPod queue.

`scripts/seed_apple_pilot.py` reads Penny in SQLite read-only mode. Its initial
cohort is all 32 available held recordings plus eight recently modified local
Atlas MP3 files. It stores existing Penny text only as a private baseline.
There is no automatic promotion. New live ASR requests then keep testing Apple
on the ongoing workflow. Source row durations are inconsistent with some
transcript metadata; use actual audio duration from the native result for
throughput totals. Do not present a corpus count as a drained production queue.

## Deployment and recheck

Run from clean, reviewed, pushed main:

```bash
venv/bin/python scripts/deploy_apple_pilot.py --apply
venv/bin/python scripts/deploy_apple_pilot.py
venv/bin/python -m apple_pilot --root /Volumes/2TB_SSD/penny-apple-pilot --status
```

Deployment compiles a revision-named Swift binary, records its source/binary
hash, installs/checks Apple assets, verifies the existing backup, installs
`com.penny.apple-pilot`, and enables `PENNY_APPLE_PILOT_DIR` plus the volume UUID
in the existing shared owner's private plist. It uses Penny's existing deploy
command for trust, verified backup and five-label activation. That command
refuses to restart active ASR. Repeat deployment at the same source only after
resolving a reported failure; binary identity must match its receipt.

Seed the cohort after deployment using the deployed UUID from the pilot plist
as the process's `PENNY_APPLE_PILOT_VOLUME_UUID` (load in Python, never print the
whole plist):

```bash
venv/bin/python scripts/seed_apple_pilot.py --root /Volumes/2TB_SSD/penny-apple-pilot
venv/bin/python scripts/seed_apple_pilot.py --root /Volumes/2TB_SSD/penny-apple-pilot --apply
```

The metadata-only `health.json` contains source revision, observation time,
active-job count, queue/client counts and processed-audio total. Freshness and
completion receipts must be checked; a loaded launchd label is insufficient.
The standalone status command reports queue state without printing text,
paths, source IDs or private errors. Inspect comparison text only locally in
the private results/queue; never paste it into GitHub or operational logs.

## Gate to primary Apple ownership

Required before a production switch: real Penny and Atlas receipts; clean
timeout/error isolation; sustained two-session memory/latency; representative
local audio review for names, amounts, negation, omissions and repetition;
timestamp/segment compatibility with Atlas's ad-cutting pipeline; truthful
backend provenance and Doctor readiness; and one integrated capture/archive
receipt with normal delivery boundaries. Compare separate sessions with a
fast serial worker rather than preserving the shared model solely by habit.
Whisper output is a baseline, not ground truth. Fewer words or fewer quality
alarms alone does not establish better transcription.

Rollback: stop `com.penny.apple-pilot` using launchctl; preserve the queue and
all receipts. Restore the backed-up shared plist from the private deployment
directory and reload the shared service through the normal idle-only deployment
procedure. Canonical backend remains Whisper throughout the pilot. Do not
delete recordings, reset application queues, or replay delivery to roll back.
