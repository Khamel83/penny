# Dwarkesh Parakeet content check

This is a text-only check of the three fixed 350-token reference windows per
interview in local `reference-windows.json`. Windows were selected before ASR
results. The corresponding normalized hypothesis coordinates come from each
episode's score file. Where a window suggests omitted content, the full local
hypothesis was inspected around that passage. No audio was heard or adjudicated.
Scores measure reference agreement, not independently established accuracy.

## Completed windows

| Publisher reference | Beginning | Middle | End | Content judgement |
| --- | --- | --- | --- | --- |
| [Dario Amodei](https://www.dwarkesh.com/p/dario-amodei) | Scaling limits, architecture and loss-function arguments preserved. An architecture acronym is wrong: LSTM becomes LSDM. Extra hesitations and restarts dominate remaining differences. | Empirical alignment-testing argument preserved, including the link between frontier models and interpretability. Differences are mostly conversational additions. | Economic integration, valuation uncertainty, and investor-governance question preserved. The question's explicit public-benefit corporate status is absent from the full hypothesis. The trust acronym survives but its spelled-out expansion does not. | Adequate broad gist across all three. One substantive reference omission and an acronym error prevent a claim of exact technical equivalence. Whether missing corporate wording was spoken in this audio version remains unresolved. |
| [Richard Sutton](https://www.dwarkesh.com/p/richard-sutton) | Critique of LLM feedback/goals and distinction from reinforcement-learning reward preserved. Added acknowledgements and restarts are immaterial. | Value function, state representation, transition model and reward distinction preserved. Named researcher and games survive. A model name is only split into two words. | Caution about kinds of change and species' control of the future preserved. The Russian ruler term is mistranscribed; one statement about humanity's track record becomes grammatically tangled. Adjacent context still indicates dissatisfaction with the status quo. | Adequate broad gist across all three. One historical term error and a locally unclear sentence; no clear argument reversal established. |
| [Andrej Karpathy](https://www.dwarkesh.com/p/andrej-karpathy) | Contrast between evolved animals and engineered model training preserved. A researcher name is misheard locally, though correctly recognized shortly afterward; a neural-network phrase becomes nonsensical. | Job bottlenecks, human oversight and wage argument preserved. One near-complete automation threshold changes from 99 percent to 98 percent. A driver/company phrase is mangled, though the surrounding autonomous-car example remains clear. | Human flourishing, culture and individual influence arguments preserved. Restarts and extra conversational wording dominate differences. | Adequate broad gist across all three; a numerical threshold and local technical/name wording need correction. No clear argument reversal established. |
| [Noam Brown](https://www.dwarkesh.com/p/noam-brown) | Agent-count, cost and speed tradeoffs preserved. The technical property parallelizability is repeatedly rendered as paralysis-related wording. A reference interjection about a weekend experiment/data point is not found anywhere in the full hypothesis. | Alignment-risk claim and institutional-control analogy preserved overall. The model-company target is misnamed, as are two historical labels. Initial window agreement was distorted by an advertisement insertion and has since been corrected; see below. | Sandboxing, air gaps, side channels and limitations of safeguards preserved. A repeated phrase about safeguards buying time becomes malformed; a phrase about training pressure uses the wrong term. | Gist remains usable, but technical terms and proper names need correction. Some suspected missing speech is an alignment artifact; the weekend interjection remains an unresolved reference/audio-version difference or ASR omission. |
| [Satya Nadella](https://www.dwarkesh.com/p/satya-nadella) | Browser/search business-model lesson and compute-infrastructure value argument preserved. Differences are mostly hesitations and phrasing. | Quantum/AI simulation combination and long-horizon research-budget argument preserved. A sponsor message is additional output between interview passages, not lost interview speech. | Company-refounding and underserved-domain arguments preserved. A named entrepreneur is mistranscribed as a different first name; an idiomatic description of CEOs is also malformed. | Adequate gist across all three. A proper name needs correction; no consequential numeric or proposition change established in these windows. |

## Noam's initial low recall was partly an alignment artifact

The original middle window started inside a sponsor message. The apparently
missing predictions about one-year progress, 50-percent acceleration and a
possible tenfold acceleration are present immediately before that advertisement
in the full output. Expanded coordinates now include them; the original low
score is not current evidence of lost speech.

The reference's weekend-experiment interjection is absent from the full output;
its cause remains unresolved without audio. Technical terms and names also
change materially. Thus the advertisement explains some numerical disagreement,
not all content differences.

Extra hesitations, acknowledgements, restarted phrases, punctuation, and edited
wording are not counted here as content failures. Conversely, a lower numerical
reference-agreement score cannot establish a meaning failure without context,
and a high score cannot excuse a changed name, quantity or negation.

## Scope and outcome

All fifteen fixed Dwarkesh windows are checked. Broad gist is adequate in these
samples, with localized acronym, proper-name, technical-term and numeric errors.
The examples do not justify a clear whole-interview meaning-failure verdict, but
also do not establish complete accuracy or equivalence to Whisper. The Dario
corporate-status omission and Noam interjection remain unresolved reference
versus audio differences. This note does not claim Parakeet is not worse than
Whisper. A comparative claim requires matched Whisper evidence;
an ASR-attributed omission requires an audio or source-version check.
