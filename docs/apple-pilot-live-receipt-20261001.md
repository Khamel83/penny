# Apple pilot receipt — October 1, 2026

## Source and installed runtime

PR #68 implemented the modern on-device SpeechTranscriber shadow pilot. Both
Standards and Spec source reviews passed exact head d947a9f. Full tests passed
(698 tests, two skipped, 53 subtests); Python 3.11/3.12 hosted checks passed.
First activation found launchd PATH excluded diskutil; PR #69 fixes its absolute
path, with both reviews and 19 focused tests passing. Corrected activation at
`ec0f51a4b86c4649ab063a83377891c4ef513686` verified all six labels, exact-binary
installed assets, fresh health and enabled natural Atlas capture. Private
activation receipt: `~/.penny/deployments/20261001T200031Z-apple-pilot/receipt.json`.

## Real corpus and what the checks mean

All 32 quality-held Penny recordings completed: 43.2 actual audio hours. All
eight historical Atlas files were admitted; seven completed before the owner
stopped further transcription. Ten natural Atlas inputs completed. At pause,
the separate ledger had 49 completed jobs, one historical job marked failed
while active shutdown occurred, and one pending live input. No automatic replay
was requested. All 32 canonical Penny text and review-status pairs remain equal
to the seeded baselines. No candidate was promoted or delivered.

The initial binary quality pass counts were misleading as a comparison of
accuracy. The existing heuristic flags three consecutive identical normalized
words (with a narrow exemption), empty text, control tokens and low-diversity
suffixes. It does not measure word error rate, omissions, meaning or punctuation
accuracy. Correctly transcribed spoken repetition can trigger it. There was no
first-party transcript or independently verified audio reference for this run;
existing Whisper text was only a comparator. The held Penny cohort is deliberately
biased toward previously flagged recordings.

Local severity analysis of the existing outputs, without further recognition:

| Corpus / output | Repeated-run tokens as share of all tokens | Longest run | Runs of 10+ words |
|---|---:|---:|---:|
| Penny Apple, 32 jobs | 0.285% | 30 | 7 |
| Penny Whisper, same 32 baselines | 0.725% | 223 | 28 |
| Live Atlas Apple, 10 jobs | 0.208% | 4 | 0 |
| Live Atlas Whisper, 9 available baselines | 0.134% | 3 | 0 |
| Historical Atlas Apple, 7 jobs | 0.084% | 5 | 0 |

These percentages count all tokens in flagged repeated-word runs, not incorrect
words. Median Penny Apple job share was 0.211%. Two very short recordings
(approximately 3.6 and 10.8 seconds) exceeded 20%; among hour-scale examples the
observed shares were 1.09%, 1.50%, and 2.36%. Do not call this a 0.285% WER or
infer that the rest of the words are correct. Apple reduced severe repeated-word
loops relative to this Whisper comparator, despite similar binary pass counts.

Seven early paired live jobs had median Apple processing time 12.38 seconds
versus 49.47 seconds for the Whisper response, median paired ratio 3.97.
Apple timing includes hashing, scratch conversion and recognition, but excludes
background queue/admission waiting; Whisper response timing may include model
startup and service overhead. This is a workload observation, not a clean
encoder-only benchmark. Two Apple sessions ran alongside normal Whisper work;
sampled system free memory remained at least 45%, with health age at most 1.1
seconds over the observed window. This does not isolate Apple's model RAM or
establish multi-day stability. Atlas completed queue count advanced from 22 to
23 while its existing production path continued; that is separate from pilot
candidate recognition and does not prove publication of each tested candidate.

## Owner-directed pause and next evaluation

The owner explicitly stopped further transcription after the Penny cohort.
`com.penny.apple-pilot` was booted out; its plist is retained as
`~/Library/LaunchAgents/com.penny.apple-pilot.plist.paused`, preventing automatic
login activation. Pilot environment settings were removed from the shared plist
with a private backup; normal deployment reloaded the five primary labels at
ec0f51a and `/health` reports `apple_pilot_enabled=false`. Audio, SQLite and all
results remain private at `/Volumes/2TB_SSD/penny-apple-pilot`.

Metadata-only severity and pause receipts are `repetition-severity.json` and
`paused-acceptance.json` under that root. Do not print private result bodies.
Next work is evaluation of existing outputs against available official podcast
transcripts or a small audio-grounded reference sample, and inspection of the
flagged locations in context. Do not resume corpus recognition to accumulate
more binary alarms. Actual word accuracy and Atlas word/phrase timing compatibility
remain unmeasured. Conditional adoption is tracked in GitHub issue #70.

Recheck pause without starting a worker:

```bash
venv/bin/python scripts/deploy_apple_pilot.py
venv/bin/python -m apple_pilot --root /Volumes/2TB_SSD/penny-apple-pilot --status
curl --max-time 5 http://127.0.0.1:10311/health
```

Do not run `deploy_apple_pilot.py --apply` until a new instruction authorizes
resuming transcription. Source support remains installed; the pilot is paused.
