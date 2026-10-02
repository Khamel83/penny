# Phonon-2 and Parakeet: bounded local podcast comparison

Historical research checkpoint before the Parakeet cutover. Current deployment
and recovery evidence are in [HANDOFF.md](../../HANDOFF.md).

## Decision

The owner authorized a few first-party podcast references, speed and RAM checks,
not a large replay campaign. Four existing/new excerpt pairs and one complete
Lex episode were used. Both new models are fast and completed long input
without growth toward the owner's reported historical 11 GB spikes. No primary
switch is justified yet. Unquantized Parakeet v3 BF16 is the stronger new
candidate: it recovers technical terms Phonon-2 misses, at nearly the same
retained MLX model memory. Edited reference scores do not establish true WER.

Production remains shared MLX Whisper at e997211; Apple sidecar is disabled.
No canonical ledger, archive, provider or downstream delivery was changed.

## Identical Lex excerpts

The three audio/reference pairs, complete-turn boundaries and normalization are
those already documented in research PR [#72](https://github.com/Khamel83/penny/pull/72).
Prior media, clip, reference, scope and engine-output hashes were verified against
the observed-run manifest. Whisper and Apple were not rerun on these excerpts.

| Reference disagreement (punctuation/case ignored) | Whisper | Apple | Phonon-2 | Parakeet v3 BF16 |
|---|---:|---:|---:|---:|
| Musk | 8.60% | 13.30% | 22.79% | 19.11% |
| Carroll | 4.14% | 6.93% | 7.03% | 5.69% |
| Vogt | 4.23% | 5.01% | 9.44% | 7.87% |
| Weighted, 2,879 normalized reference tokens | 5.56% | 8.23% | 12.78% | 10.63% |

First-party publication is not word-perfect certification. Lex's published
transcripts are edited and may contain errors. Much of the higher new-model
score is additional words rather than replacement words: Musk Parakeet has
145 insertions, six deletions and 20 substitutions, versus Whisper 58/6/13.
Phonon has 143/40/21. Removing simple hesitation/repetition tokens leaves the
same ordering but does not remove every editorial difference. These are
reference-agreement results, not a universal accuracy ranking.

A bounded consequential-term check on the existing Carroll outputs supports
preferring Parakeet over Phonon: Parakeet and Whisper both render qubits and
Bostrom as published; Phonon renders cubits instead of qubits, while Apple
also substitutes Boston for Bostrom. This spot check was chosen after looking
at disagreements, not a preregistered term benchmark or independently listened
adjudication of every word.

Loaded Parakeet processed all three identical clips (18.22 minutes) in 12.44s;
the previously measured warm shared Whisper took 95.77s, approximately 7.7x
longer. Apple took 18.41s across fresh CLI calls. Phonon warm Carroll/Vogt took
3.86/3.48s, versus Whisper 31.56/31.34s. Its first cold Musk CLI took 21.26s
including fetch/load, with 6.17s reported decode time; do not pool that
cold wall time with warm decode-only results. Normal host activity continued;
these are operational measurements, not isolated accelerator benchmarks.

## Full episode and memory

The complete downloaded Musk MP3 was decoded to 16 kHz mono WAV: 2,185.56s
(36.43 minutes), not merely the scored five-minute excerpt. Each new model
recognized it once. The same pause-aligned 25–35s window adapter was used for
both models; they process the whole file through bounded windows rather than
one enormous attention input.

| Measure | Phonon-2 | Parakeet v3 BF16 |
|---|---:|---:|
| Complete episode processing, loaded model | 22.10s | 23.60s |
| MLX active allocations after each short/full request | 1.21 GiB | 1.21 GiB |
| MLX allocator peak over load and requests | 1.59 GiB | 1.68 GiB |
| Process physical lifetime peak, including Metal | 3.5 GiB | 2.8 GiB |
| Loaded-session model loading | 7.57s | 2.78s |

No segment reported token-budget truncation. This is completion/resource
proof, not proof that every spoken word was retained. The full episode was not
rerun through Whisper/Apple. A full-reference Phonon alignment remains local,
but edited-reference and boundary limitations prevent calling it true WER.

Memory was sampled with vmmap, including the kernel-reported lifetime physical
peak; MLX active/cache/peak counters were recorded separately. Free allocator
cache was limited to 100 MiB and cleared after each request, like the production
cleanup principle. A sampled 5 GiB process-footprint abort was installed for
these isolated benchmark processes; it is not an instantaneous hard ceiling.
Retained *MLX allocations* are not the entire process footprint. Physical
samples near the end were around 3.0 GiB for Phonon and 2.3 GiB for Parakeet;
those were active/end-of-inference samples, not a separately measured idle plateau.
No sustained multi-day claim follows from a 36-minute input decoded in seconds.

The live Whisper worker's already accumulated physical peak was 4.3 GiB during
this visit; it is not a reset peak for these clips. Its subsequent Dwarkesh
request sampled at up to 2.6 GiB. The old 11 GB spikes are owner-reported;
this comparison does not re-create them. Prior cleanup evidence remains
2.3 -> 1.7 GiB post-request, not a peak-memory comparison.

## Dwarkesh cross-check: edited reference, not gibberish

The [official Dario Amodei episode](https://www.dwarkesh.com/p/dario-amodei)
provided 11 complete turns, 05:16–10:24, plus 30s audio padding on each side
(368s input). All four engines recognized this clip once. The reference was
extracted from all 18 speech paragraphs; inline text is preserved and audited
against the downloaded HTML. No dropped nodes or obvious gross alignment
failure were found.

| Reference disagreement | Whisper | Apple | Phonon-2 | Parakeet |
|---|---:|---:|---:|---:|
| Strict | 25.03% | 30.32% | 32.40% | 32.09% |
| Simple hesitation/repetition removed | 24.74% | 29.21% | 29.83% | 29.63% |

Insertions account for 87–90% of edits for every engine. All four agree on
many extra restarts, fillers and a phrase absent from the published text.
That strongly suggests editorial differences, without independently listening
to every discrepancy. Keep this separate from pooled accuracy claims; 25–32%
disagreement does not mean that proportion of text is gibberish. Do not amend
the reference to match an engine. Published human/AI production provenance
is not explicit.

Loaded processing: Phonon 3.98s, Parakeet 4.26s, Apple fresh CLI 5.79s.
Whisper's recorded 53.71s includes the memory-monitor thread teardown and is
an upper bound for the request elapsed time. New-model and baseline requests
may overlap normal host work; do not use this case for a precise isolated speed
ratio. New-model word timestamps were present, nondecreasing and within clip
bounds. This does not establish word alignment accuracy or Atlas integration.

## Exact implementation and receipts

Isolated Python 3.12 environment/artifacts:
`/Volumes/2TB_SSD/penny-phonon-benchmark-20261001` (owner-only root).
Package versions: fermion-research 0.2.7, mlx-audio 0.5.7, mlx 0.32.3;
complete dependency lock, audio/references, output/alignment JSON, memory samples
and observed artifact hashes remain local. No audio/full transcript is committed.

Phonon used verified model.fermion and default tdt16,dense16 levers. Its
[164 MB download expands to a dense 16-bit encoder](https://www.fermionresearch.com/research/phonon-2/)
in this GPU path. The experiment confirms that small download does not imply
164 MB runtime RAM. The reference Parakeet checkpoint was
[mlx-community/parakeet-tdt-0.6b-v3](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v3)
at ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15, loaded lazily and cast to BF16:
unquantized BF16, not a claim to reproduce the publisher's FP32 leaderboard row.
Both use the same pause-window/timing adapter. The initial Parakeet receipt's
inherited generic runtime caption refers to five-value planes; its profile,
backend and actual loader identify the unquantized parent. The source caption
is corrected for future runs; raw observed receipts are preserved.

The explicit utility is scripts/benchmark_phonon_references.py. It refuses
completed/partial result reuse and samples physical memory. Research execution
on the target Mac is proven; no new launchd or production adapter is deployed.
Ruff and diff checks pass. Four focused resource-observation regressions pass.
A review found that monitor errors could silently remove the sampled abort; the
utility now stops visibly on failed/missing measurements, requires an initial
valid sample before model loading, and does not report missing peaks as zero.
This correction followed the observed runs; their nonzero resource receipts are
preserved and no additional recognition was run. This is a small live benchmark,
not a new unit-test campaign. Verified Tyler/Dwarkesh corpus candidates are recorded in the adjacent
public-asr-corpus-expansion note.

Next useful step: adjudicate a few consequential existing Parakeet/Whisper
word differences against audio, then consider a bounded quantized-Whisper or
Core ML Parakeet comparison if it can improve memory/latency. Keep the reusable
small reference set; no bulk private replay or primary switch on these scores.
