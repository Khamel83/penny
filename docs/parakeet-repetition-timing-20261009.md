# Parakeet repetition timing — October 9, 2026

Issue [#111](https://github.com/Khamel83/penny/issues/111). The tolerant
(Parakeet) quality path called every run of eight identical tokens a
`consecutive_token_repetition` failure. For an upload longer than 660 seconds the
shared service cannot retry Whisper, so it returns
`quality_review_requires_bounded_excerpt` and the whole episode is held.

Observed hold, 2026-10-09 23:50 UTC: Atlas client, Waveform (MKBHD) "2026
smartphone awards", about two hours, audio sha `9c9d84d7…`, retry receipt
`~/.penny/asr-retries/9d9ba2c2-be55-4646-8db6-6a96e689bfd2/`. The flagged run is
real speech from a Kayak ad read:

> kayak thinks you won't remember that so kayak asked me to say kayak as many
> times as possible kayak kayak kayak kayak kayak kayak kayak kayak search and
> compare travel

The other 1,986 segments are fine. The resulting hold keeps Atlas `/readiness`
at 503.

## Change

Parakeet word pieces carry acoustic word starts, so a genuinely repeated word
occupies real speaking time. `evaluate_transcript` now accepts the result
segments/words and, on the tolerant path only, treats an identical-token run as
a repetition failure only when the aligned word starts show a decoder loop:

- the run is 20 or more repeats, or
- any two consecutive repeats share a start (gap `<= 0 s`), or
- the median start-to-start gap of the run is under 0.12 s.

`shared_whisper/server.py` passes `result.segments`; `transcribe_with_quality`
passes the response segments when the wire type carries them. Segment text and
word timings are matched at each transcript boundary; a mismatched segment
cannot lend timing evidence to a later repeated run. A segment without words
leaves only its own tokens untimed; an untimed run keeps the previous structural
failure. The Whisper path, the low-diversity suffix signal, the bounded-excerpt
rule for long uploads and stored records without word timings are unchanged.

## Candidate pull request description

The source PR must carry the following description (including the archive instruction):

```markdown
Refs #111.

## Summary

Stop holding real spoken-word repeats on the Parakeet path so a two-hour episode
is transcribed instead of held.

## Change

`evaluate_transcript(..., tolerant_restarts=True, segments=...)` now requires
word-timing evidence of a decoder loop before it fails an identical-token run:
the run has 20 or more repeats, any two repeats share a start, or the median
start-to-start gap is under 0.12 s. Segment text and word timings are matched
at each transcript boundary, so mismatched timings cannot weaken a later run.
The Whisper path and records without word timings are unchanged.

## Evidence

- Kayak text, 8 repeats at 0.4 s spacing passes; the same text without timings
  still fails.
- 8 repeats at 0.0 s and 0.01 s spacing still return
  `consecutive_token_repetition`.
- 25 repeats at 0.4 s spacing still fail (a real loop).
- A 7200 s Atlas upload with timed Parakeet repeats returns HTTP 200 with no
  retry receipt.

## Operator step after deploy

Archive the held Waveform (MKBHD) episode in
`/Volumes/2TB_SSD/atlas-whisper/audio/` (audio sha `9c9d84d7…`; retry receipt
`~/.penny/asr-retries/9d9ba2c2-be55-4646-8db6-6a96e689bfd2/`), then confirm Atlas
`/readiness` no longer reports the hold. Do not replay the recording or erase its
receipt.

## Merge danger

Two-way door. The Whisper path and stored records without word timings are
unchanged.

## Remaining gates

Source only. Deployment to the shared ASR service, the Atlas re-run of the held
episode, that archive step and downstream delivery are not done here.
```

## Verification

Local suite on this branch: 781 passed, 2 skipped, 60 subtests
(`python3 -m pytest -q --ignore=tests/test_apple_pilot.py`, minus one
pre-existing environment failure noted below). New tests:
- `tests/test_transcript_quality.py::test_spoken_word_repeats_with_word_timings_pass`
  — the Kayak text with eight repeats at 0.4 s spacing passes; the same text
  without word timings still fails.
- `tests/test_transcript_quality.py::test_repeats_without_speaking_time_still_fail`
  — eight repeats at 0.0 s and 0.01 s spacing still report
  `consecutive_token_repetition`.
- `tests/test_transcript_quality.py::test_long_loop_at_speaking_rate_still_fails`
  — 25 repeats at 0.4 s spacing still fail.
- `tests/test_transcript_quality.py::test_word_timings_that_do_not_match_the_text_are_ignored`
  — unaligned timings do not weaken the rule.
- `tests/test_transcript_quality.py::test_spoken_repeats_pass_when_an_unrelated_segment_has_no_words`
  — a wordless segment leaves only its own tokens untimed; the timed Kayak run
  still passes.
- `tests/test_transcript_quality.py::test_mismatched_segment_cannot_lend_timing_to_a_later_repeat`
  — a later matching repeat cannot borrow timings after a segment-boundary
  mismatch.
- `tests/test_parakeet_adapter.py::test_long_unbounded_parakeet_repeats_with_word_timing_are_not_held`
  — a 7200 s Atlas upload whose Parakeet result holds the Kayak run returns HTTP
  200 with no retry receipt; the existing no-word-timings test still returns
  `quality_review_requires_bounded_excerpt`.

Local verification limits for this sandbox (both pre-existing, unrelated to this
change): `tests/test_apple_pilot.py` cannot be collected because a
site-packages `tests` package shadows the repository `tests/` directory, and
`test_checked_maya_schema_uses_full_json_schema_and_format_validation` fails
because the `jsonschema[format]` extras (`rfc3339-validator` and peers) are not
installed here.

Source tests prove source behavior only. They do not prove deployment, an Atlas
retry of the held episode, or any downstream delivery.

## Operator step after deploy

After the reviewed change is deployed to the shared ASR service, archive the held
Waveform episode instead of leaving it on the Atlas hold list:

```bash
ls -l /Volumes/2TB_SSD/atlas-whisper/audio/
# move the held Waveform episode (audio sha 9c9d84d7…) into that directory,
# then confirm Atlas /readiness no longer reports the hold
curl -fsS http://127.0.0.1:10311/health
```

Retry receipt for the hold: `~/.penny/asr-retries/9d9ba2c2-be55-4646-8db6-6a96e689bfd2/`.
Do not replay held recordings or erase the receipt; retry retention remains open
in [#112](https://github.com/Khamel83/penny/issues/112).
