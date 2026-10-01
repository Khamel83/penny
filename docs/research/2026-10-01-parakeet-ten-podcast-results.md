# Ten full podcasts: Parakeet v3 validation

October 1, 2026. **Parakeet is the leading practical candidate for the owner’s speed/RAM goal.** All ten full episodes completed; inspected passages preserved broad gist. Occasional meaningful errors remain, so neither universal superiority nor semantic equivalence to Whisper is established. No further broad evaluation batch is needed for this decision. Production adoption is a separate adapter/deployment step.

## Measured run

Apple M4 Mac mini, 16 GB. Five Conversations with Tyler and five Dwarkesh full episodes: **12.75 hours**, recognized sequentially in **12.30 minutes** (62.2× realtime). Recognition time includes each wrapper request but excludes downloads, ffmpeg preparation, output serialization and post-request observation. The memory-monitor session spans 13.30 minutes; model load was 2.67 seconds.

**Whole-process physical lifetime peak: 4.3 GiB**, not 1.21 GiB. Post-request footprint ranged 1.5–2.2 GiB with no rising plateau. MLX active allocations were exactly 1,295,868,280 bytes (1.21 GiB) after all ten requests; cache reported zero. Physical samples were collected approximately once per second plus vmmap overhead; vmmap’s lifetime peak captures peaks between samples. A sampled 5 GiB abort is a guard, not a guaranteed hard allocation limit. This is one 13-minute session, not multi-day stability or concurrency proof. Normal shared Whisper activity was left available on the host.

| Episode | Audio minutes | Recognition seconds | × realtime | Sampled case peak GiB | Post-request GiB | Reference lexical recall |
|---|---:|---:|---:|---:|---:|---:|
| [Paul Graham on Ambition, Art, and Evaluating Talent](https://conversationswithtyler.com/episodes/paul-graham/) | 55.18 | 36.74 | 90.1 | 2.4 | 1.9 | 93.71% |
| [Ada Palmer on Viking Metaphysics, Contingent Moments, and Censorship](https://conversationswithtyler.com/episodes/ada-palmer/) | 64.76 | 42.20 | 92.1 | 3.2 | 1.5 | 97.81% |
| [Luis Garicano on Spain, Europe, and the Future of Work](https://conversationswithtyler.com/episodes/luis-garicano/) | 50.83 | 33.79 | 90.3 | 2.4 | 1.9 | 96.76% |
| [Daron Acemoglu on the Struggle Between State and Society](https://conversationswithtyler.com/episodes/daron-acemoglu/) | 55.31 | 37.20 | 89.2 | 2.5 | 1.5 | 95.14% |
| [Jared Diamond on Leaders, Luck, and Irreplaceability](https://conversationswithtyler.com/episodes/jared-diamond/) | 52.31 | 33.85 | 92.7 | 2.7 | 2.1 | 95.81% |
| [Dario Amodei (Anthropic CEO) - $10 Billion Models, OpenAI, Scaling, & AGI in 2 years](https://www.dwarkesh.com/p/dario-amodei) | 118.72 | 116.26 | 61.3 | 3.5 | 1.7 | 95.90% |
| [Richard Sutton – Father of RL thinks LLMs are a dead end](https://www.dwarkesh.com/p/richard-sutton) | 66.36 | 71.53 | 55.7 | 2.8 | 2.2 | 97.62% |
| [Noam Brown – Agent swarms, alignment, & recursive self-improvement](https://www.dwarkesh.com/p/noam-brown) | 80.16 | 89.66 | 53.6 | 2.9 | 1.7 | 94.38% |
| [Andrej Karpathy — AGI is still a decade away](https://www.dwarkesh.com/p/andrej-karpathy) | 145.32 | 168.22 | 51.8 | 3.9 | 1.8 | 95.62% |
| [Satya Nadella — Microsoft’s AGI plan & quantum breakthrough](https://www.dwarkesh.com/p/satya-nadella) | 76.16 | 108.36 | 42.2 | 2.9 | 2.1 | 96.86% |

## What the quality checks mean

Thirty fixed windows—350 normalized reference tokens each at 5%, 50% and 90% of each reference—were frozen before recognition. The full audio was recognized; manual content inspection covers 10,500 reference tokens, not every word of 12.75 hours. Publisher references were extracted with continuation paragraphs and speaker boundaries preserved. They are first-party publications, not certified verbatim ground truth. See the [Tyler provenance](2026-10-01-parakeet-cwt-provenance.md) and [Dwarkesh provenance](2026-10-01-parakeet-dwarkesh-provenance.md).

The table is **lexical reference recall, not percent accurate, semantic fidelity or WER**. Alignment consumes every reference token and permits extra hypothesis words at zero cost, matching the owner’s tolerance for fillers/restarts and avoiding penalties for sponsor segments missing from edited references. It can overlook a harmful extra assertion or match a word across unrelated extras. Manual contextual inspection remains necessary. Case/punctuation, basic contractions, numbers, a small filler list and adjacent identical repeats are normalized; comma-formatted numbers and accented names have known cosmetic tokenization artifacts.

Initial unit-cost insertion scores wrongly shortened some matching spans across advertisements/boundaries. Those scores remain preserved locally; reference windows and recognition output were not changed. Final scores use zero insertion cost. No reference words were silently discarded to improve the result.

All 30 inspected passages retained a usable broad discussion; this is not 20% gibberish. Localized errors matter for exact retrieval: names/acronyms/technical terms, a 99%→98% threshold, and one missing negative qualification. See [Tyler content review](2026-10-01-parakeet-cwt-content-check.md) and [Dwarkesh content review](2026-10-01-parakeet-dw-content-check.md).

A single three-minute Daron spot was cross-checked through the existing shared Whisper service (22.29 seconds). Whisper recovered the reference’s missing negative qualification. A separate native Parakeet 30-second/2-second-overlap test took 2.22 seconds, peaked at 2.2 GiB, and recovered the missing interviewer question but still omitted the qualification. Thus overlap is not demonstrated to solve this content error. This is reference/Whisper corroboration, not an independent human listening verdict. Two other reference omissions remain unresolved against audio. There is no reason to rerun ten whole episodes just to increase the check count.

Every output reported no decoder truncation; all word timestamps were bounded and nondecreasing. These validate structural timing only, not semantic completeness, speaker diarization or speech synthesis.

## Comparison and decision

The earlier **7.7× speedup over Whisper applies to three matched Lex excerpts**, not to all ten episodes here; no ten-episode Whisper or Phonon campaign was run. Parakeet’s earlier advantage over Phonon was meaningful for specific terms in a small sample, not established across podcasts. On the full prior short episode Phonon was slightly faster, while Parakeet had a lower measured process peak. See [prior matched comparison](https://github.com/Khamel83/penny/pull/73). Phonon’s smaller download expands into dense model allocations, so it did not demonstrate a comparable reduction in live model RAM.

For the owner’s stated tolerance, **recommend Parakeet v3 for the next production adapter**, retaining one model owner and current cache/idle unloading discipline. Do not split Penny and Atlas simply to keep two engines resident. Whisper remains a useful fallback for selected difficult content; this run does not establish Parakeet as uniformly more accurate. The owner-reported old 11 GB spike was not reproduced; this measured campaign stayed below 4.3 GiB peak, with lower settled use. Peak is still higher than the 1.7–2.3 GiB idle target.

## Reproduction and evidence boundaries

Model: mlx-community/parakeet-tdt-0.6b-v3 at ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15, unquantized BF16. Python 3.12.13; mlx 0.32.3; mlx-audio 0.5.7; fermion-research 0.2.7. Parakeet encoder/decoder are wrapped in Fermion’s pause-aligned 25–35-second segmentation/timing adapter; the compressed Phonon weights are not used. Native overlap follow-up is separate evidence. The current utility adds fail-safe receipt-writing and WAV reuse guards after the observed campaign; these guard-only changes did not trigger recognition reruns.

Artifacts remain owner-only under `/Volumes/2TB_SSD/penny-parakeet-corpus-20261001`: corpus/public-source manifests, frozen windows, MP3/WAV/reference/output hashes, per-episode receipts, model identity, memory samples, scores, content-summary, native spot and Whisper spot. `artifact-hashes.json` binds local evidence; full audio and transcripts are not committed. The isolated environment/model stays on the external SSD.

```bash
/Volumes/2TB_SSD/penny-phonon-benchmark-20261001/venv/bin/python scripts/benchmark_parakeet_corpus.py \
  --root /Volumes/2TB_SSD/penny-parakeet-corpus-20261001 \
  --model /Volumes/2TB_SSD/penny-phonon-benchmark-20261001/hf/hub/models--mlx-community--parakeet-tdt-0.6b-v3/snapshots/ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15 --resume
```

This verifies completed inputs/model/output/WAV receipts without loading the model or recognizing again. For a fresh run, prepare the ten-item manifest and frozen references in a new owner-only directory; existing unverified WAVs are refused. Re-score without recognition with `scripts/score_parakeet_corpus.py --root <root>`.

Source is an isolated research branch from fetched e997211. Live health still reports one penny-shared-whisper worker, pinned Whisper revision a4aaeec, and apple_pilot_enabled=false. No capture ledger, private archive, canonical transcript, provider call, downstream delivery, primary adapter or launchd deployment was changed. Next specific step is shared-adapter integration with timestamp/model identity compatibility and rollback, then authenticated Penny/Atlas canaries; this report does not claim those effects.
