# Conversations with Tyler: full-episode corpus provenance

Prepared October 1, 2026 for the owner's authorized ten-podcast Parakeet
campaign. This half contains five distinct public publisher transcript/audio
pairs, **16,706 seconds (4.64 hours)**. Preparation downloaded files and
extracted references; it did not run ASR or change a production service.

| ID | First-party transcript | RSS duration | Reference words / turns |
|---|---|---:|---:|
| cwt-paul-graham | [Paul Graham](https://conversationswithtyler.com/episodes/paul-graham/) | 55:11 | 10,113 / 328 |
| cwt-ada-palmer | [Ada Palmer](https://conversationswithtyler.com/episodes/ada-palmer/) | 1:04:46 | 10,973 / 94 |
| cwt-luis-garicano | [Luis Garicano](https://conversationswithtyler.com/episodes/luis-garicano/) | 50:51 | 8,343 / 102 |
| cwt-daron-acemoglu | [Daron Acemoglu](https://conversationswithtyler.com/episodes/daron-acemoglu/) | 55:19 | 9,470 / 115 |
| cwt-jared-diamond | [Jared Diamond](https://conversationswithtyler.com/episodes/jared-diamond/) | 52:19 | 8,129 / 104 |

Audio was matched by exact episode title in the publisher-linked
[official RSS](https://cowenconvos.libsyn.com/rss), using its enclosure URL.
Episode numbers embedded in filenames are not reliable match identifiers.
Exact stable URLs, SHA-256 hashes, paths, byte counts and duration metadata are
in the local `cwt-manifest.json`, under
`/Volumes/2TB_SSD/penny-parakeet-corpus-20261001`. Full transcripts, HTML and
audio remain local; none are included in this document. Files have mode 600.

The extraction begins at the first uppercase speaker label in each official
transcript text block. It includes all speech paragraphs, joins continuation
paragraphs into their speaker's turn, preserves inline linked text, and removes
speaker labels and explicit laughter/applause/crosstalk stage annotations.
Headings and pullquote/blockquote/aside duplicates are excluded. Each
`cwt-<guest>-reference.json` retains full clean turn text and speaker labels.
No ASR output was used to select or amend reference wording.

These references do not have turn timestamps. They may omit audio introductions,
advertisements, repetitions and other editorial material. First-party publication
is not certification of human transcription or verbatim accuracy: no such
production certification was established for these pages. Whole-file output
versus published text therefore measures reference agreement, with separate
inspection needed for editorial insertions or consequential word errors. Audio
duration metadata is not a verified transcript alignment.

Patrick Collison was preferred, but its official transcript page returned HTTP
403 under ordinary requests. Several other candidates also returned 403; Gita
Gopinath was initially readable but returned 403 during preparation. They were
excluded rather than substituted with third-party transcripts. The five selected
official pages were readable and complete through their closing speaker turns.
Some small candidate HTML files outside the manifest remain local; they are not
campaign inputs. Parent owns execution, memory measurements and final acceptance.
