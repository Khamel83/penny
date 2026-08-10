from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core
import reminders
import transcript_log


class AppleEffectSQLiteIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "transcripts.db"
        patch.object(transcript_log, "TRANSCRIPT_DB_PATH", self.db_path).start()
        patch.object(transcript_log, "_MIGRATION_SOURCES", []).start()
        self.addCleanup(patch.stopall)
        transcript_log.init_db()

    def test_core_replay_uses_real_ledger_and_creates_one_note(self) -> None:
        row_id = transcript_log.insert_transcript(
            content_hash="core-real-apple-ledger",
            source="iCloud",
            transcript="canonical note body",
            enqueue_slack=False,
        )
        with (
            patch.object(core, "detect_content_type", return_value="long_note"),
            patch.object(core, "mark_routed", transcript_log.mark_routed),
            patch.object(core, "mark_failed", transcript_log.mark_failed),
            patch.object(
                reminders,
                "find_note_by_marker",
                side_effect=[[], ["note-provider-1"]],
            ) as find,
            patch.object(
                reminders,
                "create_note_with_marker",
                return_value=reminders.ProviderReceipt("note-provider-1", "Penny"),
            ) as create,
        ):
            first = core.classify_and_route(
                "canonical note body", "iCloud", row_id=int(row_id), allow_maya=False
            )
            second = core.classify_and_route(
                "canonical note body", "iCloud", row_id=int(row_id), allow_maya=False
            )

        self.assertTrue(first["skip"])
        self.assertTrue(second["skip"])
        create.assert_called_once()
        self.assertEqual(find.call_count, 2)
        canonical = transcript_log.get_transcript(int(row_id))
        self.assertEqual(canonical["status"], "routed")
        conn = transcript_log._get_conn()
        try:
            effect = dict(conn.execute(
                "SELECT state, provider_id, actual_target, reconciled "
                "FROM apple_effects WHERE transcript_id = ?",
                (row_id,),
            ).fetchone())
        finally:
            conn.close()
        self.assertEqual(
            effect,
            {
                "state": "succeeded",
                "provider_id": "note-provider-1",
                "actual_target": "Penny",
                "reconciled": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
