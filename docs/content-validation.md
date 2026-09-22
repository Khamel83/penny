# Local capture content validation

Penny validates a discovered capture from its bytes before it crosses the
immutable staging boundary. The order is:

```text
completed and readable source -> Magika content detection -> immutable staging
                               -> canonical SQLite -> local MLX Whisper
```

The detector is local. It is initialized once with the watcher, not once per
capture. The pinned MLX Whisper model is also a local, offline dependency and
must be verified during startup/readiness before transcription work is allowed.
A detector or model initialization failure is an operational dependency failure;
it is not permission to send the capture to a provider or to bypass validation.

## Classification policy

Filename extensions and multipart MIME values are hints only. Penny accepts a
capture only when Magika's content label and the suffix agree with this explicit
allowlist:

| Magika label | Accepted suffixes | Canonical media |
| --- | --- | --- |
| `aac` | `.aac` | `audio/aac` |
| `amr` | `.amr` | `audio/amr` |
| `caf` | `.caf` | `audio/caf` |
| `m4a` | `.m4a` | `audio/m4a` |
| `mp3` | `.mp3` | `audio/mpeg` |
| `mp4` | `.mp4` | `audio/mp4` |
| `ogg` | `.oga`, `.ogg` | `audio/ogg` |
| `wav` | `.wav` | `audio/wav` |

This is a policy for Penny's current MLX/ffmpeg path, not a claim that every
format recognized by Magika is supported. For example, `flac`, `opus`, and
`aiff` remain unsupported until they are deliberately added and tested.

A supported label with a different suffix is a content/extension mismatch. A
non-audio label (including generic binary data) is rejected. An unsupported
audio label is rejected. An unknown or low-confidence result is retained as a
review outcome rather than being passed to Whisper. The result records bounded
label, MIME/type, status, and reason fields; it never records raw audio or
provider output.

## Failure and retry semantics

Validation happens after the source is complete and readable, but before
`stage_audio`, archive publication, canonical transcript insertion for the
normal path, or MLX Whisper. Therefore a mismatch, unsupported label, or
unknown result cannot create an immutable staged object or trigger
transcription. The source is retained and its existing durable review/failure
record is updated with the bounded validation detail.

An input that disappears, cannot be read, or is still incomplete is retryable,
not terminally rejected. The watcher keeps its existing `awaiting_file` /
retryable behavior and must classify again after the source becomes stable. A
successful validation is only local admission evidence; it does not prove that
staging, transcription, routing, Apple effects, Slack, Maya, Hermes, or any
other downstream delivery occurred.

## Local smoke check

Use synthetic fixtures only. The check initializes an isolated SQLite ledger,
exercises valid WAV bytes, a `.m4a` file containing non-audio bytes, an
unsupported FLAC signature, incomplete WAV input, and an unreadable/missing
input. It writes metadata-only local outcome rows and never invokes providers,
network, Apple automation, staging, or MLX:

```bash
python3 scripts/smoke_content_validation.py --json
```

On a host with the pinned Magika dependency installed, the same fixture matrix
can exercise the model adapter instead:

```bash
python3 scripts/smoke_content_validation.py --real-magika --json
```

The default command remains the dependency-free contract check used in local
CI; neither mode contacts a provider or downstream service.

Expected evidence is a passing local check with five distinct ledger row IDs,
accepted/rejected/retryable outcomes, and `downstream_delivery` set to
`not_attempted`. This receipt proves only the local validation-and-ledger
boundary. It is not a launchd, model-readiness, archive, provider, or delivery
receipt.
