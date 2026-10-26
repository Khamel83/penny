# iCloud Markdown transcript view

Issue https://github.com/Khamel83/penny/issues/136 remains open through natural
input acceptance. The existing watcher invokes `transcript_view.py` after its
archive outbox pass. It has a 30-second subprocess deadline; File Provider
cannot indefinitely hold capture processing. No new scheduler or outbox replay
is introduced. Failures log bounded reason codes without paths or content.

The canonical ledger supplies only nonempty `quality_status=passed` text for
new files or updates. Canonical IDs identify files; existing snapshot paths are
retained and new rows use `transcript__p<ID>__.md`. Frontmatter records canonical
ID, capture time, source, quality and transcription identity. There are no audio,
JSON, database, or temporary files in the shared view. Writes stage privately on
the same filesystem, rename atomically, read back bytes and update `INDEX.md`
last. An interrupted pass retries idempotently under a private file lock. An
unchanged file is not rewritten. No existing file is deleted. Unknown files,
unknown IDs, duplicate IDs or symlinks fail closed before publication.

The initial metadata-only inventory on October 25 found 346 Markdown files:
345 distinct filename IDs plus the index. Of those IDs, 202 currently have
passed ledger quality, 110 are pending and 33 need review. Existing nonpassed
snapshot files remain untouched and are marked `retained history` in the new
index. They are not reclassified as accepted. Resolving their quality is outside
this task; no historical recovery or delivery replay is authorized.

The destination is `iCloud Drive/Sync/Penny Transcripts`. Private staging and
lock live at `~/Library/Caches/Penny/transcript-view` on the same filesystem.
No runtime credentials, SSD objects, backup behavior or other delivery stream
change. A blocked File Provider read was observed during read-only inventory;
file content and titles were not printed. This is not reconciliation evidence.

Run source checks with `venv/bin/python -m pytest -q` and
`venv/bin/python scripts/trust_check.py`. Use the existing controlled deployment
procedure in [the deployment runbook](macmini-deployment.md), from a clean,
reviewed, merged main runtime checkout. After deployment, record the bounded
`transcript_view.py` result, source revision and `/ready` independently. Wait for
an ordinary new passed transcript, then verify its Markdown bytes and index
entry privately. Never fabricate a recording or close #136 on source merge.

Rollback source through the documented deployment procedure. Existing exported
Markdown remains preserved. Local file readback proves this Mac's projection;
it does not prove another device's synchronization or cloud quota changes.
