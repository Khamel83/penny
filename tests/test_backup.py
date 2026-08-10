from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from archive import sha256_file
from backup import (
    BackupError,
    create_backup_set,
    plan_retention,
    verify_backup_set,
)
import backup_penny
import export_transcripts


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "transcripts.db"
        self.archive = self.root / "archive" / "objects"
        self.backup = self.root / "backup"
        self.now = datetime(2026, 8, 10, 12, 30, tzinfo=timezone.utc)
        self.addCleanup(self.tmp.cleanup)
        self._init_db()

    def _init_db(self) -> None:
        self.db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE transcripts (id INTEGER PRIMARY KEY, transcript TEXT NOT NULL)"
            )
            conn.execute("INSERT INTO transcripts(id, transcript) VALUES (1, 'one')")
            conn.commit()
        finally:
            conn.close()

    def _add_object(self, data: bytes = b"audio", extension: str = ".m4a") -> Path:
        digest = hashlib.sha256(data).hexdigest()
        destination = self.archive / "sha256" / digest[:2] / f"{digest}{extension}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return destination

    def test_backup_uses_sqlite_backup_and_hash_catalog(self) -> None:
        self._add_object()
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        self.assertEqual(receipt.status, "created")
        catalog = json.loads(receipt.catalog_path.read_text(encoding="utf-8"))
        self.assertEqual(catalog["database"]["sha256"], sha256_file(receipt.database_path))
        self.assertEqual(catalog["database"]["integrity"], "ok")
        self.assertEqual(catalog["database"]["foreign_key_violations"], 0)
        self.assertEqual(catalog["database"]["row_count"], 1)
        self.assertEqual(catalog["database"]["max_transcript_id"], 1)
        self.assertTrue(any(item["path"].startswith("objects/") for item in catalog["files"]))
        self.assertEqual(receipt.catalog_path.parent.name, "20260810T123000Z")

    def test_wal_snapshot_is_consistent_and_live_database_is_untouched(self) -> None:
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO transcripts(id, transcript) VALUES (2, 'two')")
        before = self.db.read_bytes()
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        conn.rollback()
        conn.close()
        self.assertEqual(self.db.read_bytes(), before)
        snapshot = sqlite3.connect(f"file:{receipt.database_path}?mode=ro", uri=True)
        try:
            self.assertEqual(snapshot.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0], 1)
        finally:
            snapshot.close()

    def test_verifier_is_valid_and_does_not_touch_live_database(self) -> None:
        self._add_object()
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        before = self.db.read_bytes()
        scratch = self.root / "scratch"
        result = verify_backup_set(receipt.set_path, scratch)
        self.assertTrue(result.valid, result.errors)
        self.assertEqual(self.db.read_bytes(), before)
        self.assertFalse((scratch / "transcripts.db").exists())

    def test_verifier_rejects_missing_or_wrong_hash(self) -> None:
        source = self._add_object()
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        source_backup = receipt.backup_root / "objects" / "sha256" / source.parent.name / source.name
        source_backup.unlink()
        self.assertFalse(verify_backup_set(receipt.set_path, self.root / "scratch").valid)

        receipt = create_backup_set(self.db, self.archive, self.backup, self.now + timedelta(seconds=1))
        source_backup = receipt.backup_root / "objects" / "sha256" / source.parent.name / source.name
        source_backup.chmod(0o600)
        source_backup.write_bytes(b"wrong")
        self.assertFalse(verify_backup_set(receipt.set_path, self.root / "scratch2").valid)

    def test_archive_symlink_is_rejected_and_destination_conflict_is_rejected(self) -> None:
        source = self._add_object()
        link = self.archive / "sha256" / "link"
        link.symlink_to(source)
        with self.assertRaises(BackupError):
            create_backup_set(self.db, self.archive, self.backup, self.now)

        link.unlink()
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        destination = receipt.backup_root / "objects" / "sha256" / source.parent.name / source.name
        destination.chmod(0o600)
        destination.write_bytes(b"conflict")
        with self.assertRaises(BackupError):
            create_backup_set(self.db, self.archive, self.backup, self.now + timedelta(seconds=1))

    def test_interrupted_catalog_does_not_publish_set(self) -> None:
        self._add_object()
        with patch("backup._atomic_write_json", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                create_backup_set(self.db, self.archive, self.backup, self.now)
        self.assertEqual(list((self.backup / "sets").glob("20260810T123000Z")), [])
        self.assertEqual(list((self.backup / "sets").glob("*.partial")), [])

    def test_verifier_preserves_unrelated_scratch_and_warns_on_extra_object(self) -> None:
        self._add_object()
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        scratch = self.root / "scratch"
        scratch.mkdir()
        marker = scratch / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        extra_data = b"extra shared object"
        extra_hash = hashlib.sha256(extra_data).hexdigest()
        extra = receipt.backup_root / "objects" / "sha256" / extra_hash[:2] / (extra_hash + ".m4a")
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_bytes(extra_data)
        extra.chmod(0o400)
        result = verify_backup_set(receipt.set_path, scratch)
        self.assertTrue(result.valid, result.errors)
        self.assertTrue(any("extra_object" in warning for warning in result.warnings))
        self.assertTrue(marker.exists())
        self.assertTrue(extra.exists())

    def test_valid_shared_object_omitted_from_both_catalogs_is_warning_only(self) -> None:
        source = self._add_object()
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        object_relative = f"objects/sha256/{source.parent.name}/{source.name}"
        catalog = json.loads(receipt.catalog_path.read_text(encoding="utf-8"))
        catalog["objects"] = [
            item for item in catalog["objects"] if item["path"] != object_relative
        ]
        catalog["files"] = [
            item for item in catalog["files"] if item["path"] != object_relative
        ]
        receipt.catalog_path.chmod(0o600)
        receipt.catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        receipt.catalog_path.chmod(0o400)
        result = verify_backup_set(receipt.set_path, self.root / "scratch-shared")
        self.assertTrue(result.valid, result.errors)
        self.assertIn("extra_object", result.warnings)

    def test_verifier_rejects_nested_or_symlink_scratch(self) -> None:
        self._add_object()
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        with self.assertRaises(BackupError):
            verify_backup_set(receipt.set_path, receipt.set_path / "scratch")
        real = self.root / "real-scratch"
        real.mkdir()
        link = self.root / "scratch-link"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(BackupError):
            verify_backup_set(receipt.set_path, link)

    def test_retention_plan_is_deterministic_and_never_deletes_objects(self) -> None:
        self._add_object()
        old = create_backup_set(self.db, self.archive, self.backup, self.now - timedelta(days=91))
        new = create_backup_set(self.db, self.archive, self.backup, self.now)
        plan = plan_retention(self.backup, self.now)
        self.assertEqual(plan.expired_set_ids, (old.set_path.name,))
        self.assertEqual(plan.retained_set_ids, (new.set_path.name,))
        self.assertTrue((self.backup / "objects").exists())
        self.assertFalse(plan.deletes_objects)

    def test_retention_keeps_newest_valid_set_when_all_are_expired(self) -> None:
        self._add_object()
        first = create_backup_set(self.db, self.archive, self.backup, self.now - timedelta(days=180))
        second = create_backup_set(self.db, self.archive, self.backup, self.now - timedelta(days=91))
        plan = plan_retention(self.backup, self.now)
        self.assertEqual(plan.expired_set_ids, (first.set_path.name,))
        self.assertEqual(plan.retained_set_ids, (second.set_path.name,))

    def test_verifier_rejects_catalog_object_inventory_drift(self) -> None:
        self._add_object()
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        catalog = json.loads(receipt.catalog_path.read_text(encoding="utf-8"))
        catalog["objects"] = []
        receipt.catalog_path.chmod(0o600)
        receipt.catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        self.assertFalse(verify_backup_set(receipt.set_path, self.root / "scratch").valid)

    def test_remote_catalog_hash_mismatch_is_fatal(self) -> None:
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        calls: list[list[str]] = []

        def runner(command: list[str], **_: object) -> object:
            calls.append(command)
            if command[0] == "ssh":
                return SimpleNamespace(returncode=0, stdout="0" * 64 + "  catalog.json\n")
            return SimpleNamespace(returncode=0, stdout="")

        with self.assertRaises(backup_penny.SyncError):
            backup_penny.sync_backup_set(receipt, runner=runner)
        self.assertEqual([call[0] for call in calls], ["rsync", "rsync", "ssh"])

    def test_remote_rsync_failure_is_fatal(self) -> None:
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)

        def runner(command: list[str], **_: object) -> object:
            if command[0] == "rsync":
                return SimpleNamespace(returncode=23, stdout="")
            return SimpleNamespace(returncode=0, stdout="")

        with self.assertRaises(backup_penny.SyncError):
            backup_penny.sync_backup_set(receipt, runner=runner)

    def test_export_json_is_atomic_and_export_main_fails_on_sync(self) -> None:
        destination = self.root / "export" / "history.json"
        export_transcripts.export_json([{"id": 1, "transcript": "body"}], destination)
        self.assertEqual(json.loads(destination.read_text(encoding="utf-8"))[0]["id"], 1)
        self.assertEqual(list(destination.parent.glob("*.partial")), [])
        with patch.object(export_transcripts, "dump_transcripts", return_value=[]), patch.object(
            export_transcripts, "export_json"
        ), patch.object(export_transcripts, "rsync_to_homelab", return_value=False):
            self.assertEqual(export_transcripts.main(), 1)

    def test_verifier_cli_returns_zero_and_only_safe_summary(self) -> None:
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        command = [
            sys.executable,
            str(SCRIPTS / "verify_penny_backup.py"),
            str(receipt.set_path),
            str(self.root / "scratch"),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "verified")
        self.assertTrue(summary["valid"])
        self.assertEqual(summary["row_count"], 1)
        self.assertNotIn(str(self.root), result.stdout)

    def test_verification_receipt_is_atomic_bounded_and_mode_restricted(self) -> None:
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        verification = verify_backup_set(receipt.set_path, self.root / "scratch-receipt")
        destination = self.backup / "last_verification.json"
        written = backup_penny.write_verification_receipt(
            destination,
            receipt=receipt,
            verification=verification,
            remote_catalog_verified=True,
            verified_at=self.now,
        )
        self.assertEqual(written, destination)
        payload = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "verified")
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["backup_set_id"], receipt.backup_set_id)
        self.assertTrue(payload["remote_catalog_verified"])
        self.assertNotIn(str(self.root), destination.read_text(encoding="utf-8"))
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        self.assertEqual(list(destination.parent.glob("*.partial")), [])

    def test_failed_verification_cannot_advance_existing_receipt(self) -> None:
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        destination = self.backup / "last_verification.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text('{"status":"verified","backup_set_id":"old"}\n', encoding="utf-8")
        invalid = verify_backup_set(receipt.set_path, self.root / "scratch-invalid")
        receipt.catalog_path.chmod(0o600)
        receipt.catalog_path.write_text("{}", encoding="utf-8")
        invalid = verify_backup_set(receipt.set_path, self.root / "scratch-invalid-2")
        self.assertFalse(invalid.valid)
        with self.assertRaises(backup_penny.SyncError):
            backup_penny.write_verification_receipt(
                destination,
                receipt=receipt,
                verification=invalid,
                remote_catalog_verified=True,
            )
        self.assertEqual(json.loads(destination.read_text(encoding="utf-8"))["backup_set_id"], "old")

    def test_verifier_cli_returns_one_for_invalid_set_and_two_for_safety(self) -> None:
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        receipt.catalog_path.chmod(0o600)
        receipt.catalog_path.write_text("{}", encoding="utf-8")
        invalid = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "verify_penny_backup.py"),
                str(receipt.set_path),
                str(self.root / "scratch"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(invalid.returncode, 1)
        self.assertNotIn(str(self.root), invalid.stdout + invalid.stderr)
        unsafe = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "verify_penny_backup.py"),
                "relative-set",
                str(self.root / "scratch"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(unsafe.returncode, 2)

    def test_verifier_cli_requires_both_explicit_paths(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "verify_penny_backup.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)

    def test_backup_rejects_destination_prefix_symlink_without_outside_write(self) -> None:
        source = self._add_object()
        outside = self.root / "outside-destination"
        outside.mkdir()
        prefix_root = self.backup / "objects" / "sha256"
        prefix_root.mkdir(parents=True)
        (prefix_root / source.parent.name).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(BackupError):
            create_backup_set(self.db, self.archive, self.backup, self.now)
        self.assertEqual(list(outside.iterdir()), [])

    def test_backup_rejects_intermediate_archive_symlink(self) -> None:
        source = self._add_object()
        real_archive = self.root / "real-archive"
        real_archive.mkdir()
        (real_archive / "sha256").mkdir()
        target = real_archive / "sha256" / source.parent.name
        target.mkdir()
        target.joinpath(source.name).write_bytes(source.read_bytes())
        linked_parent = self.root / "linked-archive"
        linked_parent.symlink_to(real_archive, target_is_directory=True)
        with self.assertRaises(BackupError):
            create_backup_set(self.db, linked_parent, self.backup, self.now)

    def test_verifier_rejects_omitted_object_file_inventory(self) -> None:
        self._add_object()
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        catalog = json.loads(receipt.catalog_path.read_text(encoding="utf-8"))
        catalog["files"] = [
            item for item in catalog["files"] if not item["path"].startswith("objects/")
        ]
        receipt.catalog_path.chmod(0o600)
        receipt.catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        result = verify_backup_set(receipt.set_path, self.root / "scratch")
        self.assertFalse(result.valid)

    def test_verifier_rejects_malformed_catalog_object_types_and_cli_is_invalid(self) -> None:
        self._add_object()
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        catalog = json.loads(receipt.catalog_path.read_text(encoding="utf-8"))
        catalog["objects"] = [None]
        receipt.catalog_path.chmod(0o600)
        receipt.catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        result = verify_backup_set(receipt.set_path, self.root / "scratch")
        self.assertFalse(result.valid)
        cli = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "verify_penny_backup.py"),
                str(receipt.set_path),
                str(self.root / "scratch-cli"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(cli.returncode, 1)

    def test_verifier_rejects_malformed_catalog_numeric_fields(self) -> None:
        self._add_object()
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        catalog = json.loads(receipt.catalog_path.read_text(encoding="utf-8"))
        catalog["files"][0]["size"] = None
        receipt.catalog_path.chmod(0o600)
        receipt.catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        result = verify_backup_set(receipt.set_path, self.root / "scratch")
        self.assertFalse(result.valid)

    def test_verifier_rejects_set_extra_and_permissive_or_hardlinked_files(self) -> None:
        source = self._add_object()
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        (receipt.set_path / "unexpected.txt").write_text("extra", encoding="utf-8")
        result = verify_backup_set(receipt.set_path, self.root / "scratch")
        self.assertFalse(result.valid)

        (receipt.set_path / "unexpected.txt").unlink()
        object_path = receipt.backup_root / "objects" / "sha256" / source.parent.name / source.name
        object_path.chmod(0o644)
        result = verify_backup_set(receipt.set_path, self.root / "scratch-mode")
        self.assertFalse(result.valid)

        object_path.chmod(0o400)
        hardlink = self.root / "hardlink-object"
        os.link(object_path, hardlink)
        result = verify_backup_set(receipt.set_path, self.root / "scratch-hardlink")
        self.assertFalse(result.valid)

    def test_verifier_rejects_invalid_extra_objects(self) -> None:
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        extra_data = b"bad extra object"
        extra_hash = hashlib.sha256(extra_data).hexdigest()
        extra = receipt.backup_root / "objects" / "sha256" / extra_hash[:2] / (extra_hash + ".m4a")
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_bytes(b"wrong bytes")
        extra.chmod(0o400)
        self.assertFalse(verify_backup_set(receipt.set_path, self.root / "scratch-extra-hash").valid)

        extra.chmod(0o600)
        extra.write_bytes(extra_data)
        extra.chmod(0o644)
        self.assertFalse(verify_backup_set(receipt.set_path, self.root / "scratch-extra-mode").valid)

        extra.chmod(0o400)
        hardlink = self.root / "extra-hardlink"
        os.link(extra, hardlink)
        self.assertFalse(verify_backup_set(receipt.set_path, self.root / "scratch-extra-link").valid)

    def test_verifier_binds_database_path_to_snapshot_filename(self) -> None:
        receipt = create_backup_set(self.db, self.archive, self.backup, self.now)
        catalog = json.loads(receipt.catalog_path.read_text(encoding="utf-8"))
        catalog["database"]["path"] = "renamed.db"
        receipt.catalog_path.chmod(0o600)
        receipt.catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        self.assertFalse(verify_backup_set(receipt.set_path, self.root / "scratch-db-path").valid)

    def test_retention_preserves_newest_verified_set_not_corrupt_newest_timestamp(self) -> None:
        old = create_backup_set(self.db, self.archive, self.backup, self.now - timedelta(days=180))
        corrupt = create_backup_set(self.db, self.archive, self.backup, self.now - timedelta(days=91))
        corrupt.catalog_path.chmod(0o600)
        corrupt.catalog_path.write_text("{}", encoding="utf-8")
        plan = plan_retention(self.backup, self.now)
        self.assertEqual(plan.expired_set_ids, ())
        self.assertEqual(plan.retained_set_ids, (old.set_path.name,))
        self.assertTrue(any("invalid_set_verification" in warning for warning in plan.warnings))


if __name__ == "__main__":
    unittest.main()
