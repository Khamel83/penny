# ASR alternatives and the remaining RAM question

Research checked October 1, 2026. No models were installed, recognition run,
or services changed for this note. The shared Whisper service remains primary;
the Apple bulk pilot remains paused.

## What the cache change establishes

The [September 30 live receipt](2026-09-30-shared-whisper-live-memory-receipt.md)
measured shared Whisper's retained physical footprint, including Metal, falling
from 2.3 to 1.7 GiB after requests. Identical short inputs retained identical
transcript hashes. Four alternating longer generated inputs also ended at
1.7 GiB. This reduces retained allocator memory; it does not eliminate resident
FP16 model weights, prove active peak memory is capped, or prove multi-day
stability. The receipt explicitly leaves natural completion and sustained-load
acceptance open. A cache limit is not a hard cap on all process memory.

Keeping one model owner for Penny and Atlas still avoids duplicated model
residency. Splitting Apple for Penny and Whisper for Atlas retains Whisper's
floor and may add Apple system-model memory. It can improve scheduling
independence, but no combined RAM reduction has been measured.

## Candidates worth distinguishing

| Candidate | Evidence | Remaining local question |
|---|---|---|
| Current shared FP16 MLX Whisper | Retained 1.7 GiB in bounded local probes; best reference agreement in the three existing public comparisons | Sustained natural workload and active peak |
| Phonon-2 MLX | Promising vendor accuracy/speed; compact download | Actual expanded-model footprint, reference agreement and timestamps on this Mac |
| Quantized Whisper | Upstream supports integer quantization to reduce memory/disk | Quality and peak/retained memory versus current MLX service; a different runtime is not a drop-in configuration change |
| Parakeet via FluidAudio/Core ML | Native local Swift/ANE path exists | Local memory, quality, integration and timestamp behavior |
| Apple SpeechTranscriber | Existing local check was about 5x faster | More reference disagreement on all three; total system-model memory remains unknown |

[Fermion's Phonon-2 report](https://www.fermionresearch.com/research/phonon-2/)
reports a 164 MB download, but its MLX encoder expands into dense 16-bit weights
at load. Download size is therefore not resident RAM. The publisher reports
174x realtime on an M5 MacBook Air, excluding model load, and average benchmark
WER of 5.21% versus the published Whisper large-v3-turbo row's 6.58%. These are
vendor dataset results, not this machine or our clips. M4 throughput cannot be
assumed equal. Its CPU path uses an int8 encoder and offers another surface to
measure. The documented CLI provides word timestamps with JSON; their usefulness
for Atlas still needs a local check.

[whisper.cpp's upstream documentation](https://github.com/ggml-org/whisper.cpp#quantization)
supports quantized models with reduced memory and disk, and provides Metal and
Core ML paths. Quantizing keeps the Whisper family but may change word output;
neither its quality nor its resource savings here have been measured.

[FluidAudio's upstream README](https://github.com/FluidInference/FluidAudio)
documents fully local Swift/Core ML inference through the ANE and Parakeet v3
and Redux models. It also offers separate diarization components. This is an
alternative Apple hardware runtime, not Apple's SpeechTranscriber. Published
speed or memory claims do not establish a local replacement advantage.

## Bounded next decision

Whisper is the best verified baseline here, not a proven best possible backend.
Phonon-2 is the most useful next challenger because its English benchmark
results and runtime speed could improve both quality and throughput. Test only
the same three already prepared public clips, with no bulk replay. Reuse the
reference normalization and artifact identities; measure cold load, warm wall
time, active peak and retained physical memory including Metal; check word
timestamps and consequential disagreements. Record whether the expanded MLX
model really lowers RAM before considering concurrency. If it does not, a
quantized Whisper or Phonon CPU test can target memory directly. Keep the
current shared runtime until local accuracy and resource evidence support a
change. This note recommends that experiment; it does not claim it ran.
