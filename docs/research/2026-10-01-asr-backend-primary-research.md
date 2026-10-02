# Primary-source ASR comparison — October 1, 2026

This is the historical research checkpoint before the later Parakeet cutover.
Current deployment and recovery evidence are in [HANDOFF.md](../../HANDOFF.md).

This is research for a local challenger benchmark. It does not authorize a
production cutover or establish throughput on Penny's Mac. This source review
did not execute models. The accompanying local benchmark report separately
records downloaded public assets and local-only execution; production is unchanged.

## Recommendation

Test modern Apple `SpeechAnalyzer` with `SpeechTranscriber` first, and test
Phonon-2 as a separate English challenger. Do not implement the supplied legacy
`SFSpeechURLRecognitionRequest` wrapper as the proposed long-form replacement.
Keep the current Whisper runtime unchanged during research. The owner clarified
that the shared Penny/Atlas service was a RAM workaround, not the desired
architecture. If a replacement solves the measured total RAM problem, separate
engines or workers are valid candidates. Compare their simpler ownership and
isolation against a shared fast serial engine before choosing an architecture.
These are conclusions from the sources below, not local performance measurements.

## Apple: the proposed script chooses the older engine

Apple distinguishes the Siri/dictation-era `SFSpeechRecognizer` from the newer
`SpeechAnalyzer` / `SpeechTranscriber` model introduced in OS 26. The latter was
designed for long recordings, distant microphones, meetings and conversations.
It performs transcription on-device, exposes asynchronous results and timing
attributes, and manages language assets with `AssetInventory`. Apple's model
runs outside the caller's process; a small CLI footprint therefore does not
prove small total system memory consumption. Assets update automatically, which
also limits exact model-version reproducibility. Supported locales and hardware
must be checked on the actual device. These properties make the modern API the
appropriate Apple candidate for Penny's long-form work.
[Apple WWDC25 session](https://developer.apple.com/videos/play/wwdc2025/277/)

The legacy recognizer documentation still tells developers to plan for a
one-minute audio-duration limit, in discussion associated with network service
limits. Do not infer that all local requests stop at exactly one minute, or
that setting `requiresOnDeviceRecognition` guarantees unlimited files. The
relevant long-duration behavior needs a local probe.
[Legacy API](https://developer.apple.com/documentation/speech/sfspeechrecognizer)

The supplied script correctly checks `supportsOnDeviceRecognition` before
setting `requiresOnDeviceRecognition`. Apple says this combination prevents
audio network transmission; the setting alone is insufficient when unsupported.
[Local request requirement](https://developer.apple.com/documentation/speech/sfspeechrecognitionrequest/requiresondevicerecognition)

It omits legacy authorization handling and a usage-description plist. Apple
requires `requestAuthorization` before other recognition tasks and a valid
`NSSpeechRecognitionUsageDescription`; absence can cause a crash. It also needs
a bounded timeout, cancellation, and protection against multiple callback
resumes before it is a reliable worker. Those last requirements are code-review
inferences from the supplied callback/continuation structure.
[Authorization method](https://developer.apple.com/documentation/speech/sfspeechrecognizer/requestauthorization(_:))

Apple's current permission guide explicitly confines its speech-recognition
authorization process to `SFSpeechRecognizer`, and states that SpeechAnalyzer
transcriber modules do not send voice data to Apple's servers. A modern file
transcription test should therefore not be designed around the old permission
flow. Microphone capture has a separate permission boundary. For a blank
JavaScript-rendered documentation page, the canonical JSON below contains the
same article and was inspected directly.
[Permission guide](https://developer.apple.com/documentation/speech/asking-permission-to-use-speech-recognition),
[Apple article JSON](https://developer.apple.com/tutorials/data/documentation/speech/asking-permission-to-use-speech-recognition.json)

No source establishes that enabling Keyboard Dictation downloads the modern
SpeechTranscriber assets. Use its supported/installed locale queries and
`AssetInventory`, rather than assuming old Dictation setup proves readiness.
[SpeechTranscriber API](https://developer.apple.com/documentation/speech/speechtranscriber)

## Concurrency: measure aggregate throughput and contention

Apple documents a conservative, hardware-dependent limit on simultaneous
analyses. Exceeding it can produce `insufficientResources`. Current documentation
offers `ignoresResourceLimits`, while warning that actual capacity can still be
exceeded and fail unpredictably. This is not a guarantee of four to eight
workers. Check API availability against the installed SDK before using newer
options. Test ordinary limits first.
[SpeechAnalyzer resource limits](https://developer.apple.com/documentation/speech/speechanalyzer)

Several similarly configured transcribers may share backing engines and models.
Sharing is a reason to test sessions in one native service as well as separate
CLI processes; it is not proof of linear scaling.
[SpeechTranscriber engine sharing](https://developer.apple.com/documentation/speech/speechtranscriber)

The user-provided claim of negligible memory and four to eight concurrent
instances is unverified. Measure system speech processes and memory pressure,
not just the executable's RSS. Record both single-file latency and total audio
seconds completed per wall second. Four jobs at once can improve throughput
while increasing each job's completion time.

## Phonon-2: promising speed, with important qualifications

Fermion reports 174× realtime on an **M5 MacBook Air**, using MLX GPU inference.
Its hour-in-about-20-seconds claim is consistent with 3600 / 174 = 20.7 seconds.
The comparison uses 20 dictations totaling 797 seconds, one stream at a time,
with model loading excluded. Its whisper.cpp large-v3-turbo result is 17×.
That comparison does not measure Penny's MLX Whisper service or an uninterrupted
hour-long recording. The 164 MB artifact expands to a dense FP16 encoder on
Apple silicon, so download size is not resident-memory size. CUDA batching
results apply to A100/H100 GPUs, not Mac concurrency. Fermion reports mean
English benchmark WER of 5.21% versus 6.58% for the published Whisper turbo row;
these are developer-reported results, not our reproduced measurements.
[Fermion research and methodology](https://www.fermionresearch.com/research/phonon-2/)

The official file-transcription docs specify:

- CLI engine load can take 10–40 seconds; a persistent engine matters for short
  jobs and warm throughput.
- Input is resampled to 16 kHz mono. WAV/FLAC/OGG/AIFF are supported; MP3 and M4A
  require conversion before this path.
- Files above 35 seconds use pause-cut 25–35 second windows. JSON includes
  segment/word timing, wall/decode timing and a `truncated` flag.
- The HTTP server accepts an API key, but request bodies are capped at 32 MB.

These facts need adapter work for long Penny/Atlas input. A one-hour mono
16-bit 16 kHz WAV is about 115 MB before headers (arithmetic), above that
default HTTP cap. Avoid treating the endpoint as a ready drop-in replacement.
[Official speech docs](https://www.fermionresearch.com/docs/speech/)

Phonon-2 derives from NVIDIA Parakeet TDT 0.6B v3 and is English-only. Its
weights are CC-BY-4.0; code is Apache 2.0. Retain attribution and modification
notices if deploying/distributing. The model card and public runtime repository
make a local trial possible; publication alone does not prove maintainability,
crash isolation, or the authenticity of a pinned installed artifact.
[Model card](https://huggingface.co/FermionResearch/Phonon-2),
[Runtime repository](https://github.com/fermionresearch/phonon)

## Existing Apple CLIs and Marco context

There is already an open-source native CLI, `yap`, targeting macOS 26 with
text/subtitle/JSON output and optional word timestamps. Argmax also publishes a
SpeechAnalyzer CLI example with language-asset setup. Evaluate existing source
before writing a new wrapper; installation or model download is separate work.
[yap](https://github.com/finnvoor/yap),
[Argmax CLI example](https://github.com/argmaxinc/apple-speechanalyzer-cli-example)

Marco Arment's ATP episode 683, dated March 19, 2026, is the primary discussion
of Overcast transcription at scale; its official notes link Mac hosting,
launchd and XPC. The page does not publish a transcript or numeric benchmark.
I have not verified the reported 200× aggregate throughput directly from its
audio. Do not attribute the supplied SFSpeechRecognizer code or four-to-eight
worker recommendation to Marco on the basis of that page.
[Official ATP episode](https://atp.fm/683)

## Acceptance experiment

1. Record macOS build, chip/RAM, SDK, locale/asset readiness, model revision,
   dependencies, defaults and exact adapter version. Keep existing live service
   unchanged. Run generated fixtures first; keep private audio/transcripts local.
2. Time decode plus preprocessing, loading and final-result collection
   separately. Compare cold CLI and warm persistent service at 1, 2, 4 sessions;
   try 8 only after measured stability. Measure memory pressure and full process
   footprint, including Apple's system engine.
3. Use short read speech, uninterrupted natural 30/60/90-minute speech,
   multi-speaker/noisy audio, silence, interrupted and invalid containers.
   Synthetic repetitions do not establish conversational accuracy.
4. With local reference text, score omissions, insertions and substitutions.
   Check proper names, numerals, repeated speech, long gaps, timestamp ordering,
   segment coverage and end-of-file completion. Existing Whisper quality checks
   may need backend-specific interpretation; keep the no-routing review gate.
5. Exercise timeout, cancellation, crash recovery, bounded resource use,
   priority/preemption where still required, restart/launchd operation and strict
   local inference. Compare separate Penny/Atlas engines or workers against a
   shared fast serial engine using measured total system RAM, throughput,
   isolation and operational complexity. Preserve immutable ledger/archive
   boundaries. A shared endpoint is an option, not an acceptance requirement;
   any retained network endpoint still needs authentication.

Decision rule: choose the backend that passes quality and operational gates with
the best measured latency/aggregate throughput on this hardware. A faster warm
microbenchmark alone does not justify retiring Whisper.
