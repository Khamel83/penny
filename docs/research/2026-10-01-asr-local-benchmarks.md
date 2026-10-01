# Apple Speech and Phonon 2: local M4 results — October 1, 2026

## Decision supported by this experiment

A faster backend is worth pursuing. Modern Apple SpeechTranscriber is the first
candidate: it processed a real 93-minute memo in about one minute and two
simultaneous synthetic hour files in 53 seconds. Phonon 2 is also credible,
including its CPU path, which avoids competing with Whisper for GPU execution.
Neither candidate has passed a representative, human-referenced quality gate.
No production transcription backend was changed.

The owner clarified that sharing Penny and Atlas was solely a RAM workaround.
It is not a requirement for the next architecture. Separate Apple sessions are
a valid candidate; separate Phonon workers require measured combined peak RAM
and contention tests. Compare those with a fast serial worker before adding
more orchestration. A 20-second hour is attractive, but the practical outcome
is bounded queues, responsive Penny captures, and complete, accurate transcripts.

## Setup and evidence boundary

- Source worktree started at fetched default branch `origin/main`,
  `c1b0b1d13af7bbda8e5859d7d1c47dc542fe7248`. Dirty production checkout preserved.
- Local machine: M4 Mac mini, ten CPU cores (four performance/six efficiency),
  16 GB RAM; macOS 27.0 build 26A428; Swift 6.4.
- Isolated public downloads and environment live at
  `/Volumes/2TB_SSD/penny-asr-research-20261001`. Production Python was not modified.
- `fermion-research==0.2.7`, Python 3.12.13, MLX 0.32.3, mlx-audio 0.5.7,
  mlx-lm 0.32.0. Full freeze is `requirements-frozen.txt` in that directory.
  Phonon public source inspection checkout: `ba0339cb01d6103a4c632cfc8c7744c23c1587cb`.
- Model download/unpack used the package's pinned SHA-256 verification. Both
  MLX optimizations (`tdt16,dense16`) were installed, with no lever error.
  Package description still says "2-bit planes"; the installed dense16 lever
  is the evidence for the actual encoder execution path.
- Apple probe used installed SDK APIs, not the supplied legacy recognizer.
  Availability was true; AssetInventory initially returned `supported`, then
  `--install-assets` completed and returned `installed`. Installed en-US
  locales alone had not established module readiness. Legacy authorization
  remained `notDetermined`; modern file transcription succeeded.
  A verification build under a second executable filename returned `supported`
  again despite the locale list; its AssetInventory installation request then
  completed immediately and returned `installed`. Recheck readiness under the
  exact installed executable identity; do not infer readiness from locale lists.
- Public model/language assets were downloaded. Audio was processed locally;
  Phonon inference ran with `HF_HUB_OFFLINE=1`. No audio/transcript upload,
  canonical transcript write, routing, or downstream delivery was performed.

## Generated audio throughput

Samantha TTS read a 218-word reference at 150 words/minute, producing 84.45575
seconds of 16 kHz mono PCM. The hour file repeats those bytes and stops at
exactly 3,600 seconds, partway through the final repetition. This tests long
input processing and output coverage, not ordinary human speech quality.

| Engine / run | Input | Measured elapsed | Audio seconds / wall second | Memory evidence |
| --- | --- | ---: | ---: | --- |
| Apple SpeechTranscriber, first file | 84.46 s | 1.57 s in probe; 1.69 s process wall | 53.6× in probe | CLI maximum RSS 20.9 MB; excludes system model |
| Apple SpeechTranscriber | 1 hour | 45.52 s in probe; 46.13 s monitored wall | 78.0× including monitor | System speech process RSS sampled; total model RAM unproven |
| Apple, two separate processes | 2 × 1 hour | 52.63 s batch wall | 136.8× aggregate | Both exit 0; early XPC footprint about 25 MB each |
| Apple, four separate processes | 4 × 84.46 s | 2.09 s batch wall | 161.8× aggregate | All exit 0; short run only |
| Phonon MLX, default | 1 hour | 80.19 s | 44.9× | 6.5 GiB retained/peak physical footprint |
| Phonon MLX, clear cache between files | 1 hour | 46.71 s | 77.1× | 6.4 GiB peak; 1.8 GiB after cache release |
| Phonon CPU, four threads | 1 hour | 77.73 s | 46.3× | 2.9 GiB peak; 2.1 GiB retained |

These are observations under a changing real host workload, not controlled
hardware comparisons. Atlas was actively using the shared GPU Whisper worker
through much of the experiment. It briefly went idle and resumed. The second
Phonon long run therefore is not a completely idle-host result, nor does its
speed difference establish that cache clearing made inference faster.

Short Phonon MLX calls took 1.96/2.02 seconds initially, 0.90 seconds after Atlas
went idle, and 1.82 seconds after the next long run while Atlas was active again.
This is evidence that contention matters; it is not an M4/M5 speed ratio.
Phonon CPU's short call took 1.46 seconds. Cached model loading still took about
8.6–10.4 seconds for MLX and 14.5 seconds for the CPU wrapper. First CLI use,
including initial shader compilation but excluding downloads, took 26.63
seconds on a 2.085-second public LibriSpeech sample.

Both hour engines produced nonempty output with final timestamps at 3,600
seconds; Phonon reported no token-budget truncation. This does not prove that
every spoken word was recognized. Literal token edit distance on the short
reference was distorted by Apple's conversion of number words to numerals;
it is not presented as comparative WER. Both preserved the final sentence.
A single public LibriSpeech sample was recognized correctly by Phonon, which
is too little evidence to validate its published accuracy table.

## Real long memo: private shadow only

The exact previously recovered, quality-held memo linked to row 769 was
converted locally to 16 kHz mono PCM. Its duration is 5,589.35 seconds. New
candidate texts and raw receipts are under the mode-0700 `private/` scratch
directory; files are mode 0600. No transcript text is included in this report.

| Candidate | Elapsed | Throughput | Output end | Repetition-rule failures in ~300 s groups |
| --- | ---: | ---: | ---: | ---: |
| Apple SpeechTranscriber | 60.67 s | 92.1× | 5,588.04 s | 11 / 19 |
| Phonon MLX, 100 MiB free cache limit + cache release | 92.95 s | 60.1× | 5,589.35 s | 10 / 19 |
| Previously recovered Whisper transcript | Not timed here | Unknown | Historical receipt | 15 / 19 historical chunks |

Phonon used both optimizations, reported no truncation, and reached a 3.9 GiB
physical peak. Its post-request footprint was 2.0 GiB and post-release footprint
1.9 GiB. This capped-cache real-input result differs from the uncapped synthetic
hour's 6.4–6.5 GiB peaks; the differing inputs prevent attributing the entire
peak difference to the limit.

Whole outputs from both candidates still failed Penny's existing
`consecutive_token_repetition` rule. Candidate group assignments use segment
start times at five-minute boundaries, rather than retranscribing exact
300-second slices; historical failure counts are context, not an apples-to-
apples accuracy test. Word counts differed substantially: existing Whisper
8,639, Apple 7,043, Phonon 6,552. Repetition, numeral formatting, omissions, and
actual speech disfluencies may contribute. Fewer words/fewer rejected groups
does not prove a better transcript. Human-reviewed audio/reference excerpts
are needed to distinguish omissions from hallucinations and false rule alarms.

The canonical target's transcript hash, quality status, routing suppression,
and Maya delivery status matched before/after. Row 769 remains `needs_review`.
No candidate text replaced it or entered delivery.

## RAM and architecture interpretation

Phonon's packed download is not its loaded RAM. On this machine MLX reported
about 1.30 GB active allocations; cache grew to 3.59 GB after an uncapped hour.
`mx.clear_cache()` dropped reported free cache to zero. These allocator counters
are distinct from vmmap's physical footprint including driver allocations.
The same cache discipline recently added to Whisper is relevant to Phonon.

Apple's local speech XPC processes were small in early vmmap samples, but that
is not the system-wide model footprint. `aned` and `aneuserd` could not be
examined by unprivileged vmmap. No claim of negligible total RAM is established.
System memory-pressure snapshots stayed above Penny's 12% free threshold during
bounded tests, but unrelated workloads and pre-existing swap prevent attributing
swap changes to one engine. Two full-length sessions and four short sessions
succeeded with ordinary API limits. Sustained four/eight-worker capacity remains
unproven; resource-limit bypass was not used.

The current Whisper service remains the pinned MLX model, not whisper.cpp.
Metadata snapshots kept one shared worker and `preemption_count=0`. Correctly
authenticated backfill-priority baseline attempts returned `503 busy` while
Atlas held the service (including an idle-snapshot race). An initial request
without the revision suffix correctly returned `400 model_mismatch` before
inference. No production job was interrupted and no new comparable Whisper
timing was obtained. The September 30 receipt's 1.7 GiB retained footprint and
7.7-second canary timings are dated, different-input evidence, not a speedup
factor for this benchmark.

## Reproduce and next acceptance gate

Runnable probes are in `scripts/research/`; they are not installed services.
The Apple batch probe bounds execution, saves full output only at the chosen
local destination, and samples speech process metadata. Its vmmap sampling adds
small monitoring overhead. Phonon output includes private-capable text; use a
private output directory for real recordings and never commit its JSON.

```bash
xcrun swiftc -parse-as-library -O -framework Speech -framework AVFoundation \
  scripts/research/apple_speech_probe.swift -o /path/to/private/apple-speech-probe
/path/to/private/apple-speech-probe
/path/to/private/apple-speech-probe --install-assets
python3 scripts/research/apple_batch_probe.py /path/to/private/apple-speech-probe \
  /path/to/audio.wav /path/to/private/results --jobs 2 --timeout 180

FERMION_CACHE_DIR=/path/to/private/models HF_HUB_OFFLINE=1 \
  /path/to/research/venv/bin/python scripts/research/phonon_probe.py \
  --clear-cache --cache-limit-mib 100 --output /path/to/private/phonon.json \
  /path/to/audio.wav
# CPU alternative: add --engine cpu; cache controls then do not apply.
```

Raw receipts, frozen packages, public-artifact hashes, and public source copy
remain on the external SSD. Research scripts compiled/executed; Swift compile,
Python syntax, and Ruff checks are separate from runtime/backend acceptance.

Next: use a fixed local human-reference set covering ordinary memos, noisy and
distant speech, names, amounts, negation, podcast speakers/music/overlap, and
any required non-English input. Compare candidate error types and omissions
against Whisper using identical audio and options appropriate to each engine.
Then test sustained independent Penny/Atlas sessions, cancellation/timeout,
total system peak memory, idle release, and backlog drain. Select separate or
shared ownership from those measurements. Only then adapt model identity,
segments/timestamp semantics, failure/quality handling, client contracts,
Doctor, provenance, deployment, and rollback. A passing standalone CLI is not
an integrated ledger/archive/downstream receipt.

## Primary sources

Source details and uncertainty are in
[the primary-source review](2026-10-01-asr-backend-primary-research.md).
Fermion's 174×/20-second result is warm **M5 Air** inference, excludes loading,
and does not establish this M4's one-hour result. Its English accuracy figures
are promising but were not reproduced here.
[Fermion research](https://www.fermionresearch.com/research/phonon-2/),
[runtime docs](https://www.fermionresearch.com/docs/speech/),
[runtime source](https://github.com/fermionresearch/phonon),
[Apple long-form API](https://developer.apple.com/videos/play/wwdc2025/277/),
[Apple resource limits](https://developer.apple.com/documentation/speech/speechanalyzer).
