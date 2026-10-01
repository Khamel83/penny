# Apple versus deployed Whisper: official-reference check

## Decision

The owner authorized a few public first-party transcript comparisons after the
large shadow cohort, with conditional primary adoption if Apple is at least as
accurate and materially reduces resources. The large cohort remains paused.
This bounded check does not support a blanket switch: Apple was approximately
five times faster but disagreed more with all three references. It did not meet
the requested accuracy gate. No primary backend, ledger, archive or delivery
ownership changed.

## Same audio, independent published references

The source pairs and provenance are documented in
[the provenance report](2026-10-01-apple-reference-provenance.md). Musk's
[official episode](https://lexfridman.com/elon-musk-2/) links a Rev.com-credited
[PDF](https://lexfridman.com/wordpress/wp-content/uploads/2019/11/elon_musk_lex_fridman_2_transcript.pdf).
The [Carroll](https://lexfridman.com/sean-carroll-transcript/) and
[Vogt](https://lexfridman.com/kyle-vogt-transcript/) references are described by
the publisher as human generated with possible errors. These are references,
not certified word-perfect ground truth. They were chosen before recognition.

| Reference / video interval | Scored words after normalization | Apple agreement error | Whisper agreement error | Apple seconds | Whisper seconds |
|---|---:|---:|---:|---:|---:|
| Musk #49, 10:13–15:28 | 895 | 13.30% | 8.60% | 6.83 | 32.86 |
| Carroll #26, 05:03–10:18 | 967 | 6.93% | 4.14% | 5.27 | 31.56 |
| Vogt #14, 05:23–10:06 | 1,017 | 5.01% | 4.23% | 6.32 | 31.34 |
| Weighted total | 2,879 | **8.23%** | **5.56%** | **18.41** | **95.77** |

Each input included 30 seconds of extra audio at either boundary, producing
18.22 minutes of identical 16 kHz mono WAV across the three cases. The scored
reference turns span 15.22 minutes. The same audio hash was used for both
engines. Published turn times are for video; the scorer aligns the complete
reference within the padded MP3 clip, ignoring only outer hypothesis words.
Missing reference words remain deletion errors. Both engines matched the
same content window; boundary sensitivity remains an evaluation limitation,
not a claimed independently listened timestamp alignment.

The exact deployed Apple binary was
`~/.penny/bin/apple-transcribe-ec0f51a4b86c4649ab063a83377891c4ef513686`,
using modern on-device SpeechTranscriber on macOS 27 build 26A428. Whisper was
the actual shared HTTP service with `mlx-community/whisper-large-v3-turbo` at
`a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb`, using English transcription,
`condition_on_previous_text=false` and word timestamps. Requests used backfill
priority and waited for idle rather than starting a second MLX owner. Existing
natural workloads continued. No cloud ASR or provider request was made.

## What counts as an error here

The score is exact Levenshtein substitutions + deletions + insertions divided
by normalized reference tokens. Case and punctuation are ignored. Contractions,
cardinal/ordinal number presentation, Apple II notation, and the compound
spacing variants spacetime / BattleBots are normalized equally for all texts.
The latter cosmetic normalizations were added after inspecting mismatches;
raw initial scores are retained in the execution history and the ranking did
not reverse. None of the normalizations corrects a mistaken technical term or
name. Outer clip padding is not scored. Seven regression tests verify edits,
missing speech, padding and formatting behavior.

A secondary score also removes simple hesitation tokens and repeated adjacent
identical words equally from reference and hypotheses. Apple versus Whisper:
Musk 12.75% / 8.05%; Carroll 6.24% / 3.74%; Vogt 4.24% / 3.46%. The same ranking
persists. This is an explicit sensitivity analysis, not an alternative claim
of true word accuracy.

Some apparent errors are editorial/reference artifacts: the Rev text omits
some fillers and has questionable wording; both engines can agree on a spoken
alternative that differs from the reference. More verbatim fillers can score
worse against edited text. Therefore do not call 8.23% an adjudicated Apple
WER, or the difference a universal accuracy gap. We did not independently
listen to every disagreement. Nonetheless, higher disagreement on all three
clips plus visible technical/name substitutions does not establish non-inferiority.
For example, in the Carroll sample Apple used cubits in place of qubits and
Boston in place of Bostrom; Whisper matched those reference terms. These
are distinct from commas or number rendering. The source references support
those terms; the private alignment files contain the exact local comparisons.

## Resource evidence and speaker capabilities

Elapsed processing was 5.20 times shorter in aggregate, median paired ratio
4.96. Apple uses a fresh CLI per clip; Whisper is the installed persistent
service and was already resident at request admission. These are serial,
operational timings under normal host load, not isolated accelerator benchmarks.
Apple CLI user CPU was approximately 0.22–0.24 seconds and system CPU
0.04–0.06 seconds. Its maximum RSS was 20.1–21.0 MiB. This excludes Apple-owned
model/inference services and accelerator allocations, so it cannot establish
small total model memory or energy. Noninteractive powermetrics was unavailable
without additional privileges; no privilege change or owner prompt was made.
Total energy and system-model memory remain unmeasured. Speed is demonstrated;
a broad claim of lower total compute is not.

The [Apple result contract](https://developer.apple.com/documentation/speech/speechtranscriber/result)
provides text and timing but no documented speaker ID/name output. A backend
switch does not add diarization (separating speakers) or identification (mapping
a speaker to a name). If speech means reading text aloud,
[AVSpeechSynthesizer](https://developer.apple.com/documentation/AVFAudio/AVSpeechSynthesizer)
is a separate text-to-speech facility; it is not activated by replacing ASR.

## Receipts, reproducibility and next boundary

Public downloaded media/references, exact clips, both outputs, edit alignments,
scopes and hash manifest remain local under
`/Volumes/2TB_SSD/penny-asr-reference-20261001`. Full source/audio/transcript
bodies are not committed. The repository utility is
`scripts/benchmark_apple_references.py`; recognition was completed once for
three clips per engine. Later passes only rescored existing text. Published
references are human edited, speakers are clean English interview voices,
and this is one excerpt per episode. Do not generalize to all recordings.

The direct research utility ran successfully on the target Mac; it is not a
new launchd worker or deployed primary adapter. Apple background label remains
unloaded and shared health remains `apple_pilot_enabled=false`. The current
conditional adoption/evaluation owner remains GitHub #70. Useful next work is
adjudication of consequential existing disagreements or a separately approved
vocabulary/domain experiment, not more bulk recognition. A switch still needs
representative accuracy, timestamp compatibility, resource evidence and reviewed
integration with a normal capture/archive receipt.
