# Shared Markdown transcript view

This is the contract for the shared, text-only transcript view in iCloud
Drive. It is a rebuildable projection of the canonical SQLite ledger, not a
backup, not a database, and not a delivery target for audio.

## Purpose and boundaries

The owner asked for shared iCloud storage that stays tailored and text-only.
On October 21, 2026 a one-time snapshot was created by hand: 345 Markdown
transcripts copied from the SSD mirror plus an `INDEX.md`, with a SHA-256
readback for every copied file. That snapshot is a starting point, not the
maintenance mechanism.

Penny now maintains the same view incrementally from the ledger:

- one Markdown file per accepted transcript, plus one index file;
- stable filenames derived from the canonical transcript row;
- a changed accepted text updates that one file instead of adding a copy;
- the existing one-time snapshot reconciles into the same naming without
  duplicates.

The view never contains audio, raw JSON envelopes, databases, models,
backups, or hidden conflict generations. Source raw recordings stay on the
local SSD and are never written here. The local object store and the local
archive mirror must stay outside the view directory; `config.py` rejects a
configuration that nests them.

Personal transcripts in this folder are shared storage, not work-approved
content. Exporting a personal transcript does not turn it into a Trojan
Pack, and it does not authorize any other downstream use.

## Layout

```text
Penny Transcripts/
├── INDEX.md
├── p00000772__2026-10-02T18-05-11Z__iCloud.md
└── p00000773__2026-10-02T19-14-02Z__iCloud.md
```

Each transcript file is named
`p<canonical transcript id>__<captured UTC timestamp>__<source>.md`. The
canonical transcript id is the stable identity; the timestamp and source are
readable context and may change only when the ledger corrects them.

The file body is the accepted transcript text, byte for byte. Its front
matter carries compact provenance:

```text
---
schema_version: 1
canonical_transcript_id: 772
source: "iCloud"
captured_at: "2026-10-02T18:05:11Z"
ingested_at: "2026-10-02T18:06:00Z"
transcript_sha256: "<sha256 of the transcript text>"
audio_sha256: "<sha256 of the local audio object>"
transcription_backend: "parakeet"
transcription_model: "<model identity>"
quality_status: "passed"
---
```

Recording titles are not exported. The provenance above identifies the
canonical row without copying a personal file name.

`INDEX.md` lists the published entries with capture time, canonical id,
source, transcript digest and a relative link. It is rewritten from the
ledger and changes only when an entry is added, removed or renamed.

## Reconciliation

Publishing one transcript resolves its existing copies before writing:

1. A file that declares the same canonical transcript id, or whose body
   hashes to the same transcript digest, or whose body matches the
   transcript after whitespace is collapsed, is that transcript's copy.
2. One copy is renamed into the canonical file name; any further copy of the
   same transcript is removed, so the view holds one file per transcript.
3. The canonical file is rewritten only when its bytes differ from the
   ledger's current accepted text.

Files that cannot be positively identified as a ledger transcript are left
untouched. Penny does not delete unknown personal files from the shared
folder.

## Ledger integration

`transcript_log.py` owns one additive table, `transcript_view_publications`,
with one row per transcript. The view mirrors the accepted, archived capture
set: a transcript becomes eligible when its local-mirror trio is published,
which is the same population the one-time snapshot was copied from.

- a published local-mirror trio queues the view publication for an accepted
  transcript, inside the archive publication transaction;
- a transcript that only reaches `needs_review` is never queued;
- migrated placeholders are never queued;
- a transcript without a published trio stays out of the shared folder;
- `queue_transcript_view_backlog` queues accepted, already-archived rows that
  predate the view, which is how the existing snapshot is reconciled;
- `mark_transcript_view_published` records the written path and digest.

`watcher.py` drains this outbox inside the existing ingest pass. There is no
new scheduler and no new control plane. The drain never retranscribes,
replays, or invents text. A failed publication stays pending, is recorded
with a bounded error class, and is re-queued by the backlog on a later pass,
so a temporarily unavailable iCloud Drive does not strand a transcript.

## Configuration

```toml
[transcript_view]
root = "~/Library/Mobile Documents/com~apple~CloudDocs/Sync/Penny Transcripts"
enabled = true
batch_limit = 25
```

Environment overrides: `PENNY_TRANSCRIPT_VIEW_ROOT`,
`PENNY_TRANSCRIPT_VIEW_ENABLED`, `PENNY_TRANSCRIPT_VIEW_BATCH_LIMIT`.

The root must be absolute. A relative root, or a root that contains the
archive object store or the local archive mirror, is rejected when the
configuration loads, and the watcher refuses a non-absolute root. The parsed
values are the ones the watcher uses: `Config` requires the `transcript_view`
field, so a missing configuration fails loudly instead of falling back to a
default path.

The publisher refuses to create the view directory when its parent container
is missing, so an unmounted iCloud Drive never becomes a silent local
directory that looks synced but is not.

## Operator checks

Source, deployment, and the actual downstream file are separate facts. After
a reviewed merge and a controlled deployment on the Mac mini:

```sh
# The view exists and holds Markdown only.
ls -1 "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Sync/Penny Transcripts" | head
find "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Sync/Penny Transcripts" \
  -type f ! -name '*.md' -print

# A newly accepted transcript appears as Markdown and in the index.
grep -l "canonical_transcript_id: <id>" \
  "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Sync/Penny Transcripts"/*.md
grep "<id>" \
  "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Sync/Penny Transcripts/INDEX.md"
```

A watcher log line with `Transcript view publication failed` means the
publication was recorded as failed in the ledger and retried; it is not a
delivery receipt.

## Limits

- The view is rebuildable from the ledger; it is not disaster recovery.
- iCloud eviction, cross-device appearance, and cloud quota are iCloud
  behaviors. A local file write is not proof that another device received
  the file.
- The retired legacy cloud archive tree is not resurrected, hydrated,
  exported, or recovered by this feature.
