from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from archive import (
    ArchivePublishError,
    SourceChangedError,
    publish_archive,
    sha256_file,
    stage_audio,
    validate_archive,
)


class ArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_stage_audio_hashes_complete_bytes_and_deduplicates(self) -> None:
        source = self.root / "Memo.M4A"
        source.write_bytes(b"complete-audio")

        first = stage_audio(source, self.root / "objects")
        second = stage_audio(source, self.root / "objects")

        self.assertEqual(
            first.audio_sha256, hashlib.sha256(b"complete-audio").hexdigest()
        )
        self.assertEqual(first.path, second.path)
        self.assertEqual(first.path.read_bytes(), b"complete-audio")
        self.assertEqual(first.extension, ".m4a")
        self.assertEqual(stat.S_IMODE(first.path.stat().st_mode), 0o400)

    def test_stage_audio_rejects_source_change_and_removes_partial(self) -> None:
        source = self.root / "changing.m4a"
        source.write_bytes(b"audio")
        signatures = [(5, 1), (6, 2)]

        with patch("archive._source_signature", side_effect=signatures):
            with self.assertRaises(SourceChangedError):
                stage_audio(source, self.root / "objects")

        self.assertEqual(list((self.root / "objects").rglob("*.partial")), [])

    def test_stage_audio_same_hash_keeps_alias_extension_and_single_bytes(self) -> None:
        first_source = self.root / "first.m4a"
        second_source = self.root / "renamed.wav"
        first_source.write_bytes(b"same")
        second_source.write_bytes(b"same")

        first = stage_audio(first_source, self.root / "objects")
        second = stage_audio(second_source, self.root / "objects")

        self.assertEqual(first.audio_sha256, second.audio_sha256)
        self.assertNotEqual(first.path, second.path)
        self.assertEqual(first.path.read_bytes(), second.path.read_bytes())

    def test_publish_manifest_is_last_and_all_hashes_are_distinctly_verified(self) -> None:
        source = self.root / "memo.m4a"
        source.write_bytes(b"complete-audio")
        staged = stage_audio(source, self.root / "objects")
        replacements: list[str] = []

        receipt = publish_archive(
            staged=staged,
            transcript_id=478,
            transcript="buy milk",
            source="voice-memos",
            source_aliases=["voice-memos", "iCloud"],
            original_name="memo.m4a",
            captured_at="2026-08-09T19:27:31Z",
            ingested_at="2026-08-09T19:28:00Z",
            duration_seconds=3.2,
            mime_type="audio/mp4",
            backend="mlx-whisper",
            model="whisper-large-v3-turbo",
            quality_status="passed",
            mirror_root=self.root / "Penny Archive",
            on_replace=lambda path: replacements.append(path.suffix),
        )

        self.assertEqual(receipt.status, "published")
        self.assertEqual(replacements[-1], ".json")
        self.assertEqual(receipt.audio_path.stem, receipt.markdown_path.stem)
        self.assertEqual(receipt.audio_path.stem, receipt.manifest_path.stem)
        self.assertEqual(
            receipt.audio_path.parent,
            self.root / "Penny Archive" / "2026" / "2026-08" / "2026-08-09",
        )
        manifest = json.loads(receipt.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["audio_sha256"], sha256_file(receipt.audio_path))
        self.assertEqual(
            manifest["transcript_sha256"],
            hashlib.sha256(b"buy milk").hexdigest(),
        )
        self.assertEqual(
            manifest["markdown_sha256"], sha256_file(receipt.markdown_path)
        )
        self.assertNotEqual(
            manifest["transcript_sha256"], manifest["markdown_sha256"]
        )
        self.assertEqual(manifest["source_aliases"], ["iCloud", "voice-memos"])
        markdown = receipt.markdown_path.read_text(encoding="utf-8")
        self.assertIn(f"audio_sha256: {staged.audio_sha256}", markdown)
        self.assertIn(f"transcript_sha256: {manifest['transcript_sha256']}", markdown)
        self.assertIn('quality_status: "passed"', markdown)
        self.assertTrue(validate_archive(receipt.manifest_path))

    def test_stage_rejects_unhydrated_or_unsafe_source(self) -> None:
        empty = self.root / "empty.m4a"
        empty.write_bytes(b"")
        with self.assertRaises(SourceChangedError):
            stage_audio(empty, self.root / "objects")
        unsafe = self.root / "audio.bad-extension-too-long"
        unsafe.write_bytes(b"audio")
        with self.assertRaises(ValueError):
            stage_audio(unsafe, self.root / "objects")

    def test_manifest_rename_failure_is_retryable_without_acceptance(self) -> None:
        source = self.root / "memo.m4a"
        source.write_bytes(b"durable")
        staged = stage_audio(source, self.root / "objects")

        def fail_manifest(path: Path) -> None:
            if path.suffix == ".json":
                raise OSError("simulated rename failure")

        with self.assertRaises(ArchivePublishError):
            publish_archive(
                staged=staged,
                transcript_id=8,
                transcript="text",
                source="voice-memos",
                captured_at="2026-08-09T19:27:31Z",
                mirror_root=self.root / "mirror",
                on_replace=fail_manifest,
            )

        self.assertTrue(staged.path.exists())
        self.assertEqual(list((self.root / "mirror").rglob("*.json")), [])
        self.assertEqual(list((self.root / "mirror").rglob("*.partial")), [])

        receipt = publish_archive(
            staged=staged,
            transcript_id=8,
            transcript="text",
            source="voice-memos",
            captured_at="2026-08-09T19:27:31Z",
            mirror_root=self.root / "mirror",
        )
        self.assertTrue(validate_archive(receipt.manifest_path))

    def test_validate_rejects_missing_or_mismatched_consumer_hashes(self) -> None:
        source = self.root / "memo.wav"
        source.write_bytes(b"durable")
        staged = stage_audio(source, self.root / "objects")
        receipt = publish_archive(
            staged=staged,
            transcript_id=9,
            transcript="text",
            source="JPR",
            captured_at="2026-08-09T19:27:31Z",
            mirror_root=self.root / "mirror",
        )
        os.chmod(receipt.markdown_path, 0o600)
        receipt.markdown_path.write_text("tampered", encoding="utf-8")
        self.assertFalse(validate_archive(receipt.manifest_path))


if __name__ == "__main__":
    unittest.main()
