# Parakeet corpus: five Dwarkesh references

Historical validation before the Parakeet cutover. Current deployment and
recovery evidence are in [HANDOFF.md](../../HANDOFF.md).

Prepared October 1, 2026 before inspecting campaign ASR outputs. All five
sources are the publisher's own full interview pages and embedded audio,
not third-party transcript mirrors. Corpus preparation does not establish ASR
accuracy, speaker attribution, deployment, or downstream delivery.

| Official source | Audio duration | Reference words | Speech turns | Turn timing |
| --- | ---: | ---: | ---: | --- |
| [Dario Amodei, 2023](https://www.dwarkesh.com/p/dario-amodei) | 7,123.32 s | 19,853 | 172 | Explicit start/end ranges |
| [Richard Sutton](https://www.dwarkesh.com/p/richard-sutton) | 3,981.48 s | 9,367 | 131 | Start times; next turn supplies end where available |
| [Noam Brown](https://www.dwarkesh.com/p/noam-brown) | 4,809.77 s | 13,300 | 78 | Speaker headers without turn timestamps |
| [Andrej Karpathy](https://www.dwarkesh.com/p/andrej-karpathy) | 8,719.25 s | 26,022 | 228 | 226 timestamped turns; remaining times null |
| [Satya Nadella](https://www.dwarkesh.com/p/satya-nadella) | 4,569.83 s | 11,571 | 97 | Speaker headers without turn timestamps |

Total downloaded audio is 29,203.65 seconds (8.112 hours); references contain
80,113 words. Every MP3 passes `ffprobe` duration extraction. Downloads were
limited to two concurrent requests, 256 MiB per audio file and 180 seconds per
download. Dario's previously downloaded full audio was copied locally.

The local `dw-manifest.json` under
`/Volumes/2TB_SSD/penny-parakeet-corpus-20261001` binds each episode's official
source URL, embedded audio URL, audio/reference paths, measured duration and
SHA-256 hashes for audio, reference and source HTML. Full publisher text and
generated speech-turn references remain local. The five `dw-*-reference.json`
files contain `turns` with `text`, `speaker`, `start`, and `end` fields.

Extraction begins at the publisher's Transcript heading and groups every
following direct body paragraph under its speaker header. All inline text and
all continuation paragraphs are retained. Chapter headings, timestamp menus,
and non-speech page sections are excluded. Empty repeated speaker-header markup
is omitted. A separate validation compared the extracted paragraphs against
every eligible source paragraph in order: exact matches for all five sources
(341, 182, 189, 397, and 241 paragraphs respectively). Untimed turns retain null
times rather than fabricated precision. This validation establishes extraction
completeness relative to the publisher text, not fidelity to the audio.

The references are publisher supplied and may be edited or contain mistakes;
no certified verbatim or independent human-transcription claim is made. Dario's
reference starts at 49 seconds while the MP3 includes its introduction. Other
intros, sponsorships, or version differences must be checked before scoring.
Reference word error measures agreement with the supplied text; consequential
disagreements need audio adjudication. Full audio files should be retained even
when a clearly unmatched introduction is excluded from the score.

The suggested `/p/john-carmack` URL returned 404. Gwern's actual
`/p/gwern-branwen` page exists, but the guest's published voice is a voice-over;
it was excluded in favor of recorded guest voices. Five distinct guests span
reinforcement learning, model scaling, agents, engineering and quantum
computing. This selection supplies the Dwarkesh half of the parent's ten-show
campaign; it does not claim the other five references have been validated.

Next verification belongs to the campaign owner: run each candidate on the
same full audio bytes, establish reference/audio coverage, inspect major errors
and names, and record whole-system resource measurements separately from CLI
memory. No recognition, model installation, or live pilot activation was run
by this corpus-preparation task.
