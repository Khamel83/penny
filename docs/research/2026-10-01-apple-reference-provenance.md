# Apple reference comparison: source provenance

Verified against public first-party pages on October 1, 2026. This document
records reference suitability and API boundaries, not benchmark results.
No private recording, live pilot, or canonical transcript was changed.

## Three public episode/reference pairs

| Episode | Official episode and reference | Audio linked by the publisher | Provenance |
| --- | --- | --- | --- |
| Lex #49, Elon Musk, November 12, 2019 | [Episode](https://lexfridman.com/elon-musk-2/); [PDF transcript](https://lexfridman.com/wordpress/wp-content/uploads/2019/11/elon_musk_lex_fridman_2_transcript.pdf) | [MP3](https://media.blubrry.com/takeituneasy/content.blubrry.com/takeituneasy/lex_ai_elon_musk_2.mp3) | The episode directly links the PDF. PDF credits Rev.com and reports its November 12, 2019 export/completion. Speaker names and turn timestamps are present. Only this Rev-credited Lex PDF was verified in this bounded search. Rev credit alone does not establish a certified verbatim transcription. |
| Lex #26, Sean Carroll, July 10, 2019 | [Episode](https://lexfridman.com/sean-carroll/); [HTML transcript](https://lexfridman.com/sean-carroll-transcript/) | [MP3](https://media.blubrry.com/takeituneasy/content.blubrry.com/takeituneasy/mit_ai_sean_carroll.mp3) | Publisher describes the transcript as human generated and warns of errors. Transcript points back to this episode and to timestamped video. It was published much later than the audio; do not claim 2019 Rev provenance. The introduction explains a recorder failure during the original conversation: the benchmark must use the published recording, not treat the unrecorded conversation as omitted ASR text. |
| Lex #14, Kyle Vogt, February 7, 2019 | [Episode](https://lexfridman.com/kyle-vogt/); [HTML transcript](https://lexfridman.com/kyle-vogt-transcript/) | [MP3](https://media.blubrry.com/takeituneasy/content.blubrry.com/takeituneasy/mit_ai_kyle_vogt.mp3) | Publisher describes a human-generated transcript with possible errors. Transcript links identify the episode/video. HTML includes false starts and interruptions. The transcript was published later than the audio; no Rev credit was verified. |

## What the references can establish

First-party means the publisher supplies or endorses the text. It does not make
every word ground truth. A comparison against these sources measures agreement
with the reference until disagreements are checked against the matching audio.
The PDF also has page headers, footers, speaker labels, timestamps, and text
extraction artifacts. These must be removed without deleting spoken words.

Use the same audio interval for Apple and the installed Whisper model. Choose
intervals before viewing either engine's score. Verify start/end alignment by
audio: HTML timestamps address the video, and an MP3 may contain different
introductions or ads. Turn timestamps identify starts, not exact word boundaries.
Use complete turns or trim partial turns from both reference and hypotheses.

Report normalized word error (substitutions, deletions, insertions), plus the
actual important disagreements. Ignore punctuation/case for the primary score;
apply exactly the same number/contraction normalization to both engines.
Keep omissions, invented speech, names, and meaning changes visible. Inspect
large differences against audio before attributing them to either engine.
A few clean interviews support a bounded English-podcast decision; they do not
establish superiority across languages, noisy memos, or overlapping speech.

## Speech, speakers, and compute are separate capabilities

Apple's [SpeechTranscriber result contract](https://developer.apple.com/documentation/speech/speechtranscriber/result)
documents text, alternatives, audio ranges, and finalization state. Its
[result attribute options](https://developer.apple.com/documentation/speech/speechtranscriber/resultattributeoption)
provide time ranges and confidence. Neither contract documents speaker IDs or
names. Therefore a backend switch provides timestamped speech-to-text, but
does not establish who spoke each passage. Speaker diarization (separating
speaker turns) and identifying a speaker by name need separate components and
evidence. This is a conclusion from the documented API surface, not a claim
that no Apple product can label speakers.

If “do speech” means speak text aloud, Apple's
[AVSpeechSynthesizer](https://developer.apple.com/documentation/AVFAudio/AVSpeechSynthesizer)
already provides that separate text-to-speech operation. It is not enabled
by replacing the ASR backend.

Apple's [WWDC25 explanation](https://developer.apple.com/videos/play/wwdc2025/277/)
states that the transcription model executes on device outside the app's memory
space. A small CLI RSS consequently cannot prove small total system RAM or
energy use. Compare elapsed time and whole-system resource deltas under matched
conditions. The [SpeechAnalyzer concurrency contract](https://developer.apple.com/documentation/speech/speechanalyzer)
also describes hardware-dependent resource limits; it does not guarantee four
to eight simultaneous sessions on every Mac mini.
