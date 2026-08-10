from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import apple_effects
import reminders
import transcript_log


class AppleEffectOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_dir = tempfile.mkdtemp()
        self.db_path = Path(self.db_dir) / "transcripts.db"
        self.db_patch = patch.object(transcript_log, "TRANSCRIPT_DB_PATH", self.db_path)
        self.db_patch.start()
        transcript_log.init_db()
        self.row_id = int(
            transcript_log.insert_transcript(
                content_hash="apple-effects-test", source="iCloud", transcript="body"
            )
        )
        self.addCleanup(self.db_patch.stop)

    def test_first_create_requires_marker_readback_and_replay_does_not_create(self) -> None:
        with (
            patch.object(transcript_log, "mark_apple_effect_succeeded", wraps=transcript_log.mark_apple_effect_succeeded),
            patch.object(apple_effects.reminders, "find_note_by_marker", side_effect=[[], ["note-1"]]) as find,
            patch.object(apple_effects.reminders, "create_note_with_marker", return_value="note-1") as create,
        ):
            first = apple_effects.ensure_note(self.row_id, "body", folder="Penny")
            second = apple_effects.ensure_note(self.row_id, "body", folder="Penny")
        self.assertEqual(first.state, "succeeded")
        self.assertEqual(first.provider_id, "note-1")
        self.assertFalse(first.reconciled)
        self.assertEqual(second.provider_id, "note-1")
        create.assert_called_once()
        self.assertEqual(find.call_count, 2)

    def test_timeout_becomes_uncertain_then_marker_reconciliation(self) -> None:
        timeout = reminders.AppleScriptError("timeout_uncertain", ambiguous=True)
        with (
            patch.object(apple_effects.reminders, "find_note_by_marker", side_effect=[timeout, ["note-2"]]) as find,
            patch.object(apple_effects.reminders, "create_note_with_marker") as create,
        ):
            with self.assertRaisesRegex(apple_effects.AppleEffectError, "timeout_uncertain"):
                apple_effects.ensure_note(self.row_id, "timeout body")
            retry = apple_effects.ensure_note(self.row_id, "timeout body")
        self.assertTrue(retry.reconciled)
        self.assertEqual(retry.provider_id, "note-2")
        create.assert_not_called()
        self.assertEqual(find.call_count, 2)

    def test_receipt_write_failure_after_create_retries_by_marker_without_duplicate(self) -> None:
        real_mark = transcript_log.mark_apple_effect_succeeded
        mark_attempts = 0

        def flaky_mark(*args, **kwargs):
            nonlocal mark_attempts
            mark_attempts += 1
            if mark_attempts == 1:
                return False
            return real_mark(*args, **kwargs)

        with (
            patch.object(apple_effects.reminders, "find_note_by_marker", side_effect=[[], ["note-3"], ["note-3"]]),
            patch.object(apple_effects.reminders, "create_note_with_marker", return_value="note-3") as create,
            patch.object(transcript_log, "mark_apple_effect_succeeded", side_effect=flaky_mark),
        ):
            with self.assertRaisesRegex(apple_effects.AppleEffectError, "database_unavailable"):
                apple_effects.ensure_note(self.row_id, "receipt crash")
            retry = apple_effects.ensure_note(self.row_id, "receipt crash")
        self.assertEqual(retry.provider_id, "note-3")
        create.assert_called_once()

    def test_active_claim_does_not_create_and_stale_claim_can_reconcile(self) -> None:
        payload_hash = apple_effects.normalized_payload_sha256("active")
        key = apple_effects.effect_key_for(self.row_id, "note", "Penny", "", payload_hash)
        claim = transcript_log.claim_apple_effect(
            effect_key=key,
            transcript_id=self.row_id,
            effect_type="note",
            requested_target="Penny",
            payload_sha256=payload_hash,
        )
        with patch.object(apple_effects.reminders, "find_note_by_marker") as find, patch.object(
            apple_effects.reminders, "create_note_with_marker"
        ) as create:
            active = apple_effects.ensure_note(self.row_id, "active")
        self.assertEqual(active.state, "in_flight")
        find.assert_not_called()
        create.assert_not_called()

        conn = transcript_log._get_conn()
        try:
            conn.execute(
                "UPDATE apple_effects SET lease_expires_at='2020-01-01T00:00:00Z' WHERE effect_key=?",
                (key,),
            )
            conn.commit()
        finally:
            conn.close()
        with (
            patch.object(apple_effects.reminders, "find_note_by_marker", side_effect=[[], ["note-4"]]),
            patch.object(apple_effects.reminders, "create_note_with_marker", return_value="note-4") as create,
        ):
            stale = apple_effects.ensure_note(self.row_id, "active")
        self.assertEqual(stale.provider_id, "note-4")
        create.assert_called_once()

    def test_multiple_markers_quarantine_without_create(self) -> None:
        with (
            patch.object(apple_effects.reminders, "find_note_by_marker", return_value=["a", "b"]),
            patch.object(apple_effects.reminders, "create_note_with_marker") as create,
        ):
            with self.assertRaisesRegex(apple_effects.AppleEffectError, "marker_conflict"):
                apple_effects.ensure_note(self.row_id, "duplicate marker")
        create.assert_not_called()
        key = apple_effects.effect_key_for(
            self.row_id, "note", "Penny", "", apple_effects.normalized_payload_sha256("duplicate marker")
        )
        self.assertEqual(transcript_log.get_apple_effect(key)["state"], "quarantined")

    def test_reminder_fallback_identity_is_stable_and_searches_both_targets(self) -> None:
        with (
            patch.object(
                apple_effects.reminders,
                "find_reminders_by_marker",
                side_effect=[[], [reminders.ProviderReceipt("rem-1", "Inbox")], [reminders.ProviderReceipt("rem-1", "Inbox")]],
            ) as find,
            patch.object(
                apple_effects.reminders,
                "create_reminder_with_marker",
                return_value=reminders.ProviderReceipt("rem-1", "Inbox"),
            ) as create,
        ):
            first = apple_effects.ensure_reminder(self.row_id, "buy milk", "Later", "Inbox")
            # Force a replay path to model the requested list appearing later.
            conn = transcript_log._get_conn()
            try:
                conn.execute(
                    "UPDATE apple_effects SET state='uncertain', provider_id=NULL WHERE effect_key=?",
                    (first.effect_key,),
                )
                conn.commit()
            finally:
                conn.close()
            second = apple_effects.ensure_reminder(self.row_id, "buy milk", "Later", "Inbox")
        self.assertEqual(first.effect_key, second.effect_key)
        self.assertEqual(second.actual_target, "Inbox")
        create.assert_called_once()
        self.assertEqual(find.call_count, 3)

    def test_error_does_not_log_item_or_provider_stderr(self) -> None:
        with (
            patch.object(apple_effects.reminders, "find_note_by_marker", side_effect=reminders.AppleScriptError("provider_error")),
            patch.object(apple_effects.log, "error") as error,
        ):
            with self.assertRaisesRegex(apple_effects.AppleEffectError, "provider_error") as raised:
                apple_effects.ensure_note(self.row_id, "secret transcript body")
        self.assertNotIn("secret transcript body", str(raised.exception))
        self.assertNotIn("secret transcript body", " ".join(str(call) for call in error.call_args_list))

    def test_non_ambiguous_permission_error_is_quarantined_not_uncertain(self) -> None:
        with (
            patch.object(apple_effects.reminders, "find_note_by_marker", return_value=[]),
            patch.object(
                apple_effects.reminders,
                "create_note_with_marker",
                side_effect=reminders.AppleScriptError("permission_denied"),
            ) as create,
        ):
            with self.assertRaisesRegex(apple_effects.AppleEffectError, "permission_denied"):
                apple_effects.ensure_note(self.row_id, "permission")
        key = apple_effects.effect_key_for(
            self.row_id, "note", "Penny", "", apple_effects.normalized_payload_sha256("permission")
        )
        stored = transcript_log.get_apple_effect(key)
        self.assertEqual(stored["state"], "quarantined")
        self.assertEqual(stored["last_error_code"], "permission_denied")
        create.assert_called_once()

    def test_unsafe_provider_code_is_bounded_and_not_persisted(self) -> None:
        sentinel = "provider stderr secret transcript body"
        with patch.object(
            apple_effects.reminders,
            "find_note_by_marker",
            side_effect=reminders.AppleScriptError(sentinel),
        ):
            with self.assertRaisesRegex(apple_effects.AppleEffectError, "provider_error") as raised:
                apple_effects.ensure_note(self.row_id, "redacted")
        self.assertNotIn(sentinel, str(raised.exception))
        key = apple_effects.effect_key_for(
            self.row_id, "note", "Penny", "", apple_effects.normalized_payload_sha256("redacted")
        )
        stored = transcript_log.get_apple_effect(key)
        self.assertEqual(stored["last_error_code"], "provider_error")
        self.assertNotIn(sentinel, str(stored))

    def test_effect_key_requires_exact_lowercase_payload_hash(self) -> None:
        with self.assertRaisesRegex(apple_effects.AppleEffectError, "invalid_effect"):
            apple_effects.effect_key_for(
                self.row_id, "note", "Penny", "", "z" * 64
            )
        with self.assertRaisesRegex(apple_effects.AppleEffectError, "invalid_effect"):
            apple_effects.effect_key_for(
                self.row_id, "note", "Penny", "", "A" * 64
            )


if __name__ == "__main__":
    unittest.main()
