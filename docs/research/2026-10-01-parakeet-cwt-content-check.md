# Parakeet CWT content assessment

October 1, 2026. Read-only comparison of the five existing public outputs
against their first-party references. No recognition, reference amendment or
audio listening occurred. The owner accepts immaterial differences; fillers,
restarts, spelling variants and editorial cleanup do not by themselves fail
this assessment.

Read all fifteen preselected 350-token reference windows (5%, 50%, 90% positions)
from local `reference-windows.json`, and their aligned hypothesis spans using
`normalize(text, True)` and saved global hypothesis indices. Also read context
outside flagged boundaries. This covers 5,250 reference tokens, not every word
of the episodes. Published edited references are not certified verbatim truth.

| Episode | Assessment within inspected windows | Consequential details |
|---|---|---|
| [Paul Graham](https://conversationswithtyler.com/episodes/paul-graham/) | **Adequate for gist** | Founder judgment, housing constraints, soundproofing and fame arguments remain intelligible. Most discrepancies are interruptions, colloquial contractions and formatting. |
| [Ada Palmer](https://conversationswithtyler.com/episodes/ada-palmer/) | **Adequate for gist; terminology needs care** | Historical claims and causal explanations are preserved. Yersinia becomes Yurcinia; Poetic Edda becomes Poeticetta/edit; de Sade has phonetic variants. These matter for exact retrieval, not evidence of general gibberish. |
| [Luis Garicano](https://conversationswithtyler.com/episodes/luis-garicano/) | **Uncertain for precise details; gist usable** | Housing, startup finance and second-mover arguments remain clear. Bargaining power becomes organic power; the recovery fund's name is distorted. Those are substantive term errors, unlike the additional fillers. |
| [Daron Acemoglu](https://conversationswithtyler.com/episodes/daron-acemoglu/) | **Uncertain: material omission candidate** | Institutional-development argument survives. A question and a negative qualification are absent in the middle span; exact names also have errors. This needs targeted audio inspection before claiming detailed fidelity. |
| [Jared Diamond](https://conversationswithtyler.com/episodes/jared-diamond/) | **Uncertain for names and titles; gist usable** | Geography, communication and family influences remain coherent. Angela Merkel becomes Anglo marital; the book-title and Bach-cantata references are garbled. These hinder named-entity retrieval without making the entire discussion unusable. |

## Long deletions need context

Paul's beginning-window ten-word deletion is a **scoring boundary artifact**.
The full hypothesis immediately after the selected endpoint retains his plan
to investigate over the summer and return to YC. Do not report that as lost
speech. The thirteen-word omission near the end is permission/interruption
about whether to give multiple answers. The ensuing substantive soundproofing
principles remain intact; that omission is immaterial under the owner's criterion.

Daron's middle-window omissions are different. They remove an interviewer
question about printing/literacy and a qualification that the roots are not in
Christianity. The subsequent explanation about its mixture with bottom-up
institutions remains. This is a material missing qualification relative to the
reference, though its cause (ASR, overlap, or reference/audio differences) has
not been adjudicated. It cannot be dismissed as merely a comma.

## What the assessment supports

No inspected case shows wholesale gibberish or a collapsed discussion. Most
observed differences are harmless under the owner's criterion. There are also
specific wrong names/terms and one material omission candidate, so the evidence
does not justify a claim of word-perfect or detailed claim-preserving transcription.
It supports usable gist with bounded limitations, not automatic rejection from
strict disagreement percentages and not universal acceptance for exact quoting.

Some score differences are normalization artifacts: comma-separated numbers
can split into number-plus-zero tokens, while accented names split under the
ASCII tokenizer. These should not count as changed quantities or identities
without checking the original word forms. References and scores were preserved.
Parent owns any targeted audio adjudication and the overall adoption decision.

## Parent’s bounded follow-up

After this text review, the parent checked the three-minute Daron passage through the existing local Whisper service. Whisper recovered the negative qualification missing from Parakeet, corroborating the publisher reference. Native Parakeet 30-second chunks with 2-second overlap recovered the interviewer question but still omitted that qualification. No independent human audio listening was performed; this is stronger comparative corroboration, not certified ground truth. Final zero-insertion-cost scores keep all frozen reference words and correct the Paul beginning boundary artifact. Neither recognition output nor references were amended.
