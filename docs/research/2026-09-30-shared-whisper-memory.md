# Local transcription RAM research — 2026-09-30

Research only; no model execution, assets downloaded, or production edits. Primary documentation and upstream maintainer comments.

## Most direct explanation and lowest quality risk

MLX Whisper maintainer awni attributes repeated word-timestamp memory growth to expected allocator cache growth, aggravated by varying cross-attention score shapes. He recommends limiting the cache (suggestion: approximately 100 MB) or clearing it every few chunks. The original reporter confirmed that setting the limit resolved their case without observable slowdown. This is evidence of a relevant mechanism, not proof of this machine's diagnosis.

Source: https://github.com/ml-explore/mlx-examples/issues/1254#issuecomment-2643500174
Reporter: https://github.com/ml-explore/mlx-examples/issues/1254#issuecomment-2645877203

Current `mx.set_cache_limit` governs FREE cached buffers, and defaults to the memory limit. Setting zero disables cache. This does not unload live weights or bound Python/audio arrays. `mx.set_memory_limit` is a graph-evaluation guideline, not a strict process-memory ceiling; default is 1.5 times Metal's recommended working set.

Sources: https://ml-explore.github.io/mlx/build/html/python/_autosummary/mlx.core.set_cache_limit.html
https://ml-explore.github.io/mlx/build/html/python/_autosummary/mlx.core.set_memory_limit.html

The upstream transcriber retains its model in a process-global ModelHolder and computes the input log-mel spectrogram before windowed decoding. Long-file preprocessing and cache retention must therefore be distinguished from model weight memory.

Source: https://github.com/ml-explore/mlx-examples/blob/main/whisper/mlx_whisper/transcribe.py

## Same Whisper turbo model, lower precision

The upstream MLX converter supports weight quantization with selectable `--q-bits` and group size (default 64). Default quantization is four bits. MLX quantizes eligible Linear and Embedding layers. Eight bits is available through the same conversion path. Relative to FP16, eight-bit eligible weights theoretically take about half and four-bit about one quarter, plus quantization metadata and unquantized layers. These are arithmetic expectations for weights, NOT promises about total RAM. Activations, preprocessing, cache, and Python overhead remain.

Sources: https://github.com/ml-explore/mlx-examples/blob/main/whisper/convert.py
https://github.com/ml-explore/mlx/blob/main/python/mlx/nn/layers/quantized.py

Recommendation (inference): fix allocator retention first to retain precisely the same model and precision. Then benchmark eight-bit same turbo as the conservative precision experiment; four-bit requires stronger accuracy checks. No verified primary M4 16 GB peak-memory/accuracy benchmark was found for these variants during this research.

## Alternative engine, same model

whisper.cpp supports large-v3-turbo, Apple Silicon Metal, and integer quantization (example Q5_0). Its README states quantization reduces memory and disk requirements. Its memory table lists generic large at approximately 3.9 GB, but does NOT give a separately measured turbo figure; do not cite that as an M4 turbo guarantee. Engine and decoding differences can change text even with the same underlying model. Quantized turbo Q8 or Q5 is a candidate if MLX bounds still fail.

Source: https://github.com/ggml-org/whisper.cpp

Core ML encoder offload to ANE exists; upstream calls for Xcode and command-line tools during conversion. Do not claim deleting all developer toolchains is compatible with that route without checking build needs. Metal route is separate.

## Apple native speech engine

SpeechAnalyzer/SpeechTranscriber was introduced with the macOS 26 generation; it is not a macOS 27-only feature. Apple describes long-form, conversational, and live transcription, on-device processing after model asset download, and audio timing attributes on text runs. The model runs outside the application's address space. This does NOT imply zero machine RAM consumption; measure the system service too. Apple provides no numerical RAM ceiling or comparative Whisper accuracy guarantee in these sources.

Source: https://developer.apple.com/videos/play/wwdc2025/277/

Runtime support must be checked using `SpeechTranscriber.isAvailable`, `supportedLocales`, `installedLocales`, and normalized `supportedLocale(equivalentTo:)`. Similar transcribers can share backing engines/models. Assets are system managed, with limited per-app language allocation. Do not hardcode an inferred locale list or assume all Whisper languages are supported.

Source: https://developer.apple.com/documentation/speech/speechtranscriber
https://developer.apple.com/documentation/speech/speechtranscriber/supportedlocales

## Proposed acceptance experiment

Preserve current service behavior. Use existing local audio, not user uploads/cloud providers: quiet Penny dictation, noisy/distant dictation, proper nouns and numbers; Atlas podcast clean speech, overlap/music, 30-60 minute recording, and the longest representative file. Establish a human-checked reference subset; current Whisper is a baseline, not ground truth.

Run serially: FP16 current turbo with capped cache, eight-bit turbo, then Apple SpeechTranscriber if support is confirmed. Add whisper.cpp only if needed. Keep identical languages/output schema, and record engine/precision/decoding settings. Measure total process footprint including Metal, active/cache/peak MLX bytes, system memory pressure/swap delta, elapsed time, timestamp sanity, and memory after release. Repeated different clips plus one long file exposes shape-dependent cache growth. Avoid parallel model loading on this 16 GB machine.

Compare word error rate on reference snippets and inspect errors that matter (names, amounts, negation, omissions, hallucinations); compare timestamp behavior and downstream ingestion. Require stable memory across many jobs and sufficient host headroom under ordinary development load before replacing production. Quality threshold should be agreed from actual baseline error distribution, not an unsupported universal 'no impact' claim.

## Installed-source findings and first implementation

The installed Penny service is `com.penny.shared-whisper`, with its only model child running `shared_whisper/worker.py`. Atlas is a caller. MLX 0.32.0 and mlx-whisper 0.4.3 are installed. The pinned model cache occupies approximately 1.5 GiB; vmmap measured a 7.3 GiB child footprint including approximately 7.0 GiB graphics allocations. A September 30 pre-reboot Jetsam report recorded Python 3.14 at 11.45 GiB; the report alone does not prove its service identity.

The worker had no cache limit or explicit cache reclamation. The supervisor's pressure guard executes only when creating a child, and its five-minute idle expiry cannot unload a continuously busy child. Word timestamps are already off by default; the upstream issue's exact trigger is therefore not established here.

First implementation retains model identity, precision, options, authentication and priority semantics. Set the free cache limit to 100 MiB once in the model child; synchronize and clear free cached buffers after successful and failed transcription. This limits retained buffers, not live model/activation memory. Unit regression exercises three requests through the real child loop, including a failure, and verifies identical options/output with cleanup each time. Real repeated-request footprint and natural Atlas completion remain deployment acceptance gates.

Simulator cleanup: the external 8.9 GiB dyld cache was removed. Internal iOS/tvOS/watchOS assets total approximately 14.8 GiB. Administrator-authorized deletion returned Operation not permitted because files carry restricted flags; no internal space reclamation is claimed. Developer Command Line Tools remain installed.
