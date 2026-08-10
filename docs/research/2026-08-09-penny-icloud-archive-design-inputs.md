# Penny iCloud archive design inputs

**Research date:** 2026-08-09
**Scope:** Primary-source constraints for a human-readable iCloud archive of paired audio and Penny transcripts. This is design input only; it does not authorize or implement storage changes.

## Executive conclusion

Use **iCloud Drive as a synchronized, human-readable mirror**, not as Penny's database and not as the independent backup.

Keep three explicit layers:

1. **Canonical operational record:** Penny's local `~/.penny/transcripts.db`. It remains authoritative for transcript identity, deduplication, quality, routing, and delivery state.
2. **iCloud mirror:** a Penny-owned `Penny Archive` folder containing an immutable audio file, UTF-8 transcript, and hash manifest for each canonical row. It is convenient for browsing and device access, but it is a rebuildable projection.
3. **Independent homelab backup:** versioned, non-delete-propagating backup sets containing a transactionally consistent SQLite snapshot and the fully materialized archive bytes. This is the disaster-recovery source.

Apple Notes should remain a **user-facing output** for reading/searching selected results. It should not be the binary/transcript repository.

## What iCloud Drive actually guarantees

### Sync and local availability

iCloud Drive is a synchronization surface: files and changes are kept current across devices. Finder may show an item as **In iCloud**, **Waiting to Upload**, **Downloaded**, **Keep Downloaded**, or transferring. An **In iCloud** item is not locally usable until downloaded; **Waiting to Upload** means it is not yet stored in iCloud; **Downloaded** means the Mac's copy is current; and **Keep Downloaded** asks macOS to retain a local copy ([Apple: check iCloud Drive status](https://support.apple.com/en-ae/guide/mac-help/mchlc994344b/mac), [Apple: work with iCloud Drive files](https://support.apple.com/en-gb/guide/mac-help/mchl1a02d711/mac)).

Apple's File Provider model explains the underlying hazard for unattended readers: a file can be a **dataless** local item containing metadata but no content, later materialized on access, and materialized content can be evicted again to save space ([Apple: synchronizing a File Provider extension](https://developer.apple.com/documentation/FileProvider/synchronizing-the-file-provider-extension), [Apple WWDC21: File Provider on macOS](https://developer.apple.com/videos/play/wwdc2021/10182/)). A read can trigger and block on download; merely seeing a directory entry, size, timestamp, or filesystem event is therefore not proof that Penny has durable bytes.

**Design consequence:** mark `Penny Archive` **Keep Downloaded** on the Mac mini, but still make the adapter open and copy the entire source into local staging, compute a SHA-256 over the completed copy, and only then publish it. The homelab job must back up bytes it has read and hash-verified, never placeholder metadata.

### Atomicity and conflicts

Apple's File Provider stack integrates with APFS safe-save behavior and uses compare-and-swap/file coordination to avoid losing local changes during remote updates, but that does not make a group of separate files one cross-device transaction ([Apple WWDC21: File Provider on macOS](https://developer.apple.com/videos/play/wwdc2021/10182/)). Apple also documents that offline edits from multiple devices can create conflicting document versions; users may keep multiple numbered copies, and versions they reject are deleted across iCloud Drive devices ([Apple: iCloud Drive document conflicts](https://support.apple.com/en-mide/guide/mac-help/mh40780/mac)). Apple's developer guidance requires coordinated access and explicit conflict handling for iCloud documents rather than assuming a single uncontested file ([Apple: handling iCloud version conflicts](https://developer.apple.com/library/archive/technotes/tn2336/_index.html), [Apple: `NSFileVersion`](https://developer.apple.com/documentation/foundation/nsfileversion)).

**Design consequence:** use one writer for the Penny archive. Treat Just Press Record's folder as an input, never edit its source file in place, and make archive objects immutable. Write each destination file to a temporary sibling and rename it into place. Because the audio, text, and manifest can still arrive on another device in different orders, a consumer must accept a capture only when all three exist and their hashes match the manifest. Filename appearance or a final filesystem event is insufficient.

### Deletion, recovery, and versioning

Deleting an iCloud Drive item on one device deletes it on every device signed into the same Apple Account. Deleted files are normally recoverable from Recently Deleted for 30 days; after 30 days, or after explicit permanent deletion, they are not recoverable through that facility ([Apple: delete and recover Files items](https://support.apple.com/en-ca/104953), [Apple: permanently remove deleted iCloud files](https://support.apple.com/guide/icloud/permanently-remove-deleted-files-mm9cf51c51f4/icloud)).

Conflict copies are not an archive history. Apple documents version browsing for particular document apps, such as Pages, but that is an app-specific feature and restoration replaces the shared current version ([Apple: Pages for iCloud version history](https://support.apple.com/guide/pages-icloud/restore-earlier-versions-gilc269af9ca/icloud)). The general iCloud Drive guidance reviewed here documents conflict resolution and 30-day deleted-file recovery, not immutable retention for arbitrary M4A/TXT/JSON files.

**Design consequence:** never rely on iCloud conflict versions or Recently Deleted as Penny's retention policy. The homelab backup must keep historical backup sets and must not mirror iCloud deletions into all retained versions.

### Why iCloud sync is not the backup

Apple distinguishes syncing from backup. Data already synchronized through iCloud Drive is stored in iCloud **instead of** being included in the device's iCloud Backup; Apple specifically says local Files content using iCloud Drive is not included in iCloud Backup ([Apple: what iCloud backs up](https://support.apple.com/en-ie/108770), [Apple: missing data after an iCloud Backup restore](https://support.apple.com/en-us/102325)). Combined with deletion propagation, one mistaken delete or bad edit can affect every synchronized copy.

Therefore, the phrase “live repository and backup” needs a precise split: `Penny Archive` is the live **mirror**; the homelab's versioned copy is the independent **backup**.

## Just Press Record's folder is an inbox, not the archive

When configured for iCloud Drive, Just Press Record (JPR) stores recordings in a visible `Just Press Record` iCloud Drive folder. Watch recordings first transfer automatically to the paired iPhone over Bluetooth and then sync through iCloud Drive ([JPR: device synchronization](https://openplanet.zendesk.com/hc/en-gb/articles/115004471393-How-are-recordings-synced-between-devices), [JPR: missing iCloud Drive folder](https://openplanet.zendesk.com/hc/en-gb/articles/115004500014-I-ve-made-recordings-on-my-iPhone-but-I-can-t-see-a-Just-Press-Record-folder-in-iCloud-Drive)). JPR's current storage choices are iCloud Drive, Files-visible `On My iPhone`, and a hidden legacy in-app container; changing the selected location does not move existing recordings ([JPR: storage locations](https://openplanet.zendesk.com/hc/en-gb/articles/360006542398-What-are-the-three-storage-locations), [JPR: changing storage location](https://openplanet.zendesk.com/hc/en-gb/articles/115004500114-Do-recordings-move-when-changing-storage-location)).

JPR organizes folders by date by default and permits external renaming in Finder/Files ([JPR: renaming recordings and folders](https://openplanet.zendesk.com/hc/en-gb/articles/115004471933-Can-recordings-and-folders-be-renamed)). More importantly, JPR stores its transcript as metadata **inside the audio file**; producing a separate text file is a Share operation ([JPR: transcript storage](https://openplanet.zendesk.com/hc/en-gb/articles/115004471593-Where-are-my-transcripts-stored), [JPR: sharing transcripts](https://openplanet.zendesk.com/hc/en-gb/articles/115004500414-How-can-I-share-my-transcription)). JPR also states that it has no server-side copy from which it can restore lost recordings or transcripts ([JPR: recording recovery](https://openplanet.zendesk.com/hc/en-gb/articles/360005683134-Can-you-restore-my-recordings-if-I-loose-them)).

Accordingly:

- configure JPR for iCloud Drive for the pilot, not the hidden legacy location;
- treat `iCloud Drive/Just Press Record` as a capture inbox owned by JPR;
- do not rename, move, normalize, or add Penny sidecars inside that folder;
- after full materialization, copy the original bytes into Penny staging, hash them, ingest them into canonical SQLite, and publish Penny's own plain-text transcript and manifest into `Penny Archive`; and
- retain the original extension (`.m4a`, `.wav`, or `.aif`) instead of transcoding the “raw” archive copy.

This also keeps Penny's local transcript authoritative instead of silently substituting JPR's embedded transcript.

## Apple Notes: projection only

Notes can synchronize notes across devices, hold audio attachments, and show audio transcripts. Apple also documents that deleting a Notes audio recording deletes its transcript ([Apple: Notes iCloud synchronization](https://support.apple.com/en-mide/guide/icloud/mm2d069f7097/icloud), [Apple: record and transcribe audio in Notes](https://support.apple.com/en-au/guide/iphone/iphbe11247b5/ios), [Apple: Notes attachments on iCloud.com](https://support.apple.com/en-mide/guide/icloud/view-or-download-attachments-mm198698c442/1.0/icloud/1.0)). Deleted notes have the same kind of 30-day Recently Deleted window and then disappear permanently ([Apple: delete and recover iCloud Notes](https://support.apple.com/guide/icloud/delete-and-recover-notes-mm2f42f05cb9/1.0)).

Notes is nevertheless a poor repository contract for Penny. Apple DTS confirms there is no Notes CRUD API; AppleScript is macOS-only and described as less than ideal for this role ([Apple DTS: Notes API](https://developer.apple.com/forums/thread/813810)). Notes does not expose Penny's required stable filesystem pair, SHA-256 identity, manifest, atomic publish check, or operational routing state.

Use Notes for a readable title, transcript, summary, and optional link back to the iCloud mirror. Do not treat a successful Notes write as proof that raw audio, the canonical SQLite row, iCloud mirror, or homelab backup exists.

## Recommended human-readable archive layout

Use date directories and one shared basename per capture:

```text
iCloud Drive/
└── Penny Archive/
    └── 2026/
        └── 2026-08/
            └── 2026-08-09/
                ├── 2026-08-09T19-27-31Z__p00000478__jpr__6f2a90b1b4e3.m4a
                ├── 2026-08-09T19-27-31Z__p00000478__jpr__6f2a90b1b4e3.txt
                └── 2026-08-09T19-27-31Z__p00000478__jpr__6f2a90b1b4e3.json
```

The components are:

- recording time in UTC, without filename-hostile colons;
- canonical Penny transcript row ID, zero-padded for scanning;
- short source label (`jpr`, `voice-memos`, `upload`, and so on); and
- first 12 hexadecimal characters of the **audio SHA-256**, which disambiguates duplicates without making filenames unwieldy.

The `.txt` file is UTF-8 Penny transcript text. The `.json` manifest is the completion contract and should include at least `schema_version`, canonical row ID, source, original filename, recorded/ingested timestamps, duration, MIME type, byte length, full audio SHA-256, full transcript SHA-256, and transcription engine/model identity. Human titles belong in the manifest, not the stable basename.

## Publish and restoration contract

### Publish

1. Fully materialize the source and copy it to non-iCloud local staging.
2. Hash the staged audio; insert or reconcile the canonical SQLite row first.
3. Write audio and transcript to temporary sibling names in `Penny Archive`, then rename each into place.
4. Write and rename the manifest last. A reader still verifies both payload hashes; manifest presence alone is not enough because remote sync ordering is not transactional.
5. Record mirror success/failure separately from ingest, transcription, Notes, Maya, Slack, and backup success.

### Independent backup

Each homelab backup set should contain:

- a transactionally consistent snapshot of the **whole** `transcripts.db`, including delivery/outbox state;
- every fully materialized archive audio/text/manifest object;
- a backup-set catalog with path, size, SHA-256, creation time, and backup-set ID; and
- retention that preserves prior sets when a source file is changed or deleted.

The current periodic transcript JSON export can remain a readable recovery aid, but it cannot by itself restore SQLite IDs, schema, routing/outbox receipts, or exactly-once delivery state. A raw live copy of a WAL-mode SQLite file is also not the required snapshot contract.

### Restore

1. Restore a chosen homelab backup set into staging, never directly over the live database or iCloud folder.
2. Verify the backup catalog, every archive hash/pair, SQLite integrity, schema version, row count, and maximum canonical row ID.
3. Stop Penny writers and preserve the old live database. Restore the verified whole-database snapshot first, including its delivery tables, so already-sent external effects are not replayed.
4. Reconcile staged archive objects to SQLite by canonical row ID plus full hashes. Canonical SQLite wins for transcript and operational state. Hash-valid archive extras are quarantined for explicit import; they do not silently create rows.
5. Rebuild the iCloud mirror from the verified staged archive only after the canonical database is healthy. Let iCloud resynchronize, then independently verify materialization and hashes on the Mac mini.
6. Resume Penny and prove one read-only ledger lookup plus archive and backup health before accepting new work.

If only the iCloud archive survives, Penny can recover audio and transcript **content**, but not trustworthy historical routing/delivery state. That is a degraded, explicitly reviewed reconstruction—not a full operational restore.

## Decision

Adopt the three-layer model: **SQLite authority → iCloud human mirror → versioned homelab backup**. Use JPR's iCloud folder only as a source inbox, and Notes only as a user-facing projection. The iCloud mirror becomes useful and pleasant to browse without being asked to provide database transactions, immutable history, or disaster recovery that Apple does not promise it will provide.
