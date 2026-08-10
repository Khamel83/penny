from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["HOME"] = "/tmp/penny_test_home"
os.environ["OPENROUTER_API_KEY"] = "test-key"
os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot"
os.environ["TELEGRAM_CHAT_ID"] = "12345"
os.environ["GOOGLE_CREDENTIALS_FILE"] = (
    "/tmp/penny_test_home/.penny/google_credentials.json"
)
os.environ["GOOGLE_TOKEN_FILE"] = "/tmp/penny_test_home/.penny/google_token.json"
logging.disable(logging.CRITICAL)

import core  # noqa: E402
from apple_effects import AppleEffectReceipt  # noqa: E402
import slack_delivery  # noqa: E402
import transcript_log  # noqa: E402


class _SlackResponse:
    def __init__(
        self,
        payload: dict[str, object],
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self) -> dict[str, object]:
        return self._payload


class _MayaResponse:
    def __init__(
        self,
        payload: dict[str, object],
        *,
        status_code: int = 200,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self) -> dict[str, object]:
        return self._payload


_MAYA_SUBMISSION_SCHEMA_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "maya_penny_transcript_submission.schema.json"
)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _load_checked_maya_submission_artifact(
) -> tuple[dict[str, object], dict[str, str]]:
    artifact = json.loads(_MAYA_SUBMISSION_SCHEMA_PATH.read_text(encoding="utf-8"))
    provenance = artifact.pop("x-generated-from")
    canonical_bytes = _canonical_json_bytes(artifact)
    assert provenance == {
        "generator": (
            "app.integrations.penny.contracts."
            "PennyTranscriptSubmission.model_json_schema"
        ),
        "maya_commit": provenance["maya_commit"],
        "maya_source": "app/integrations/penny/contracts.py",
        "maya_source_sha256": provenance["maya_source_sha256"],
        "schema_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
    }
    assert re.fullmatch(r"[0-9a-f]{40}", provenance["maya_commit"])
    assert re.fullmatch(r"[0-9a-f]{64}", provenance["maya_source_sha256"])
    Draft202012Validator.check_schema(artifact)
    return artifact, provenance


def _validate_against_checked_maya_schema(value: object) -> None:
    schema, _ = _load_checked_maya_submission_artifact()
    Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    ).validate(value)


_MAYA_MODEL_PROBE = """
import json
import sys

from app.integrations.penny.contracts import PennyTranscriptSubmission

request = json.load(sys.stdin)
result = {
    "schema": PennyTranscriptSubmission.model_json_schema(),
}
if "envelope" in request:
    try:
        PennyTranscriptSubmission.model_validate(request["envelope"])
    except Exception as exc:
        result["valid"] = False
        result["validation_error"] = str(exc)
    else:
        result["valid"] = True
print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
"""


def _execute_actual_maya_model(
    maya_repo: Path,
    *,
    envelope: dict[str, object] | None = None,
) -> dict[str, object]:
    maya_python = maya_repo / ".venv" / "bin" / "python"
    if not maya_python.is_file():
        raise AssertionError(f"Maya virtualenv Python not found: {maya_python}")
    request = {} if envelope is None else {"envelope": envelope}
    completed = subprocess.run(
        [str(maya_python), "-c", _MAYA_MODEL_PROBE],
        cwd=maya_repo,
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "Maya model probe failed "
            f"(exit {completed.returncode}): {completed.stderr.strip()}"
        )
    return json.loads(completed.stdout)


def _maya_receipt(
    envelope: dict[str, object],
    *,
    drop_id: str,
    duplicate: bool,
) -> dict[str, object]:
    return {
        "schema_version": "penny-maya.v2",
        "transcript_id": envelope["transcript_id"],
        "transcript_sha256": envelope["transcript_sha256"],
        "drop_id": drop_id,
        "durable_acknowledged_at": "2026-07-28T19:15:00Z",
        "duplicate": duplicate,
    }


def _slack_section_text(payload: dict[str, object]) -> str:
    return "".join(
        block["text"]["text"]
        for block in payload["blocks"]
        if block["type"] == "section"
    )


class TranscriptContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_dir = tempfile.mkdtemp()
        self.db_path = Path(self.db_dir) / "test_transcripts.db"
        patch.object(transcript_log, "TRANSCRIPT_DB_PATH", self.db_path).start()
        transcript_log.init_db()
        self.addCleanup(patch.stopall)

        self.original_channel = os.environ.get("PENNY_SLACK_CHANNEL_ID")
        self.original_bot_token = os.environ.get("PENNY_SLACK_BOT_TOKEN")
        os.environ["PENNY_SLACK_CHANNEL_ID"] = "C0BKS0QT7FU"
        os.environ["PENNY_SLACK_BOT_TOKEN"] = "xoxb-test"
        self.addCleanup(self._restore_slack_env)

        self.original_maya_url = core.cfg.maya.transcript_url
        self.original_maya_token = core.cfg.maya.ingest_token
        core.cfg.maya.transcript_url = "http://maya:8200/ingest/transcript"
        core.cfg.maya.ingest_token = "test-token"
        self.addCleanup(self._restore_maya_config)

    def _restore_slack_env(self) -> None:
        if self.original_channel is None:
            os.environ.pop("PENNY_SLACK_CHANNEL_ID", None)
        else:
            os.environ["PENNY_SLACK_CHANNEL_ID"] = self.original_channel
        if self.original_bot_token is None:
            os.environ.pop("PENNY_SLACK_BOT_TOKEN", None)
        else:
            os.environ["PENNY_SLACK_BOT_TOKEN"] = self.original_bot_token

    def _restore_maya_config(self) -> None:
        core.cfg.maya.transcript_url = self.original_maya_url
        core.cfg.maya.ingest_token = self.original_maya_token

    def _insert_maya_eligible(self, **kwargs: object) -> int | None:
        kwargs.setdefault("ingest_state", "transcribed")
        kwargs.setdefault("recorded_at", "2026-07-28T12:34:56Z")
        kwargs.setdefault("quality_status", "passed")
        kwargs.setdefault("maya_delivery_eligible", True)
        kwargs.setdefault("enqueue_slack", False)
        return transcript_log.insert_transcript(**kwargs)

    def test_checked_maya_schema_uses_full_json_schema_and_format_validation(
        self,
    ) -> None:
        row_id = self._insert_maya_eligible(
            content_hash="json-schema-validation-audio-hash",
            source="iCloud",
            transcript="Validate this envelope with Draft 2020-12.",
            discovered_at="2026-07-28T12:34:56Z",
            quality_status="passed",
            enqueue_slack=False,
        )
        self.assertIsNotNone(row_id)
        envelope = transcript_log.build_maya_v2_envelope(int(row_id))

        _validate_against_checked_maya_schema(envelope)

        malformed_timestamp = deepcopy(envelope)
        malformed_timestamp["captured_at"] = "not-an-rfc3339-timestamp"
        with self.assertRaises(ValidationError):
            _validate_against_checked_maya_schema(malformed_timestamp)

        unexpected_field = deepcopy(envelope)
        unexpected_field["penny_only"] = True
        with self.assertRaises(ValidationError):
            _validate_against_checked_maya_schema(unexpected_field)

        malformed_hash = deepcopy(envelope)
        malformed_hash["transcript_sha256"] = "not-a-sha256"
        with self.assertRaises(ValidationError):
            _validate_against_checked_maya_schema(malformed_hash)

    @unittest.skipUnless(
        os.environ.get("MAYA_REPO_PATH"),
        "set MAYA_REPO_PATH to run the cross-repo Maya contract integration",
    )
    def test_actual_maya_model_schema_matches_fixture_and_accepts_penny_envelope(
        self,
    ) -> None:
        maya_repo = Path(os.environ["MAYA_REPO_PATH"]).resolve()
        schema, provenance = _load_checked_maya_submission_artifact()
        row_id = self._insert_maya_eligible(
            content_hash="actual-maya-model-valid-audio-hash",
            source="iCloud",
            transcript="Maya validates this real Penny envelope.",
            duration_seconds=8.25,
            discovered_at="2026-07-28T12:34:56Z",
            quality_status="passed",
            enqueue_slack=False,
        )
        self.assertIsNotNone(row_id)
        envelope = transcript_log.build_maya_v2_envelope(int(row_id))

        actual = _execute_actual_maya_model(maya_repo, envelope=envelope)

        self.assertEqual(actual["schema"], schema)
        self.assertEqual(
            _canonical_json_bytes(actual["schema"]),
            _canonical_json_bytes(schema),
        )
        self.assertTrue(actual["valid"])
        maya_source = maya_repo / provenance["maya_source"]
        self.assertEqual(
            hashlib.sha256(maya_source.read_bytes()).hexdigest(),
            provenance["maya_source_sha256"],
        )
        generated_source = subprocess.run(
            [
                "git",
                "show",
                f"{provenance['maya_commit']}:{provenance['maya_source']}",
            ],
            cwd=maya_repo,
            capture_output=True,
            check=True,
        ).stdout
        self.assertEqual(
            hashlib.sha256(generated_source).hexdigest(),
            provenance["maya_source_sha256"],
        )

    @unittest.skipUnless(
        os.environ.get("MAYA_REPO_PATH"),
        "set MAYA_REPO_PATH to run the cross-repo Maya contract integration",
    )
    def test_actual_maya_model_rejects_negative_duration(self) -> None:
        maya_repo = Path(os.environ["MAYA_REPO_PATH"]).resolve()
        row_id = self._insert_maya_eligible(
            content_hash="actual-maya-negative-duration-audio-hash",
            source="iCloud",
            transcript="Negative duration must fail Maya model validation.",
            duration_seconds=4.0,
            discovered_at="2026-07-28T12:34:56Z",
            quality_status="passed",
            enqueue_slack=False,
        )
        self.assertIsNotNone(row_id)
        envelope = transcript_log.build_maya_v2_envelope(int(row_id))
        envelope["duration_seconds"] = -0.01

        actual = _execute_actual_maya_model(maya_repo, envelope=envelope)

        self.assertFalse(actual["valid"])
        self.assertIn(
            "duration_seconds must be non-negative",
            actual["validation_error"],
        )

    def test_maya_v2_envelope_is_persisted_and_pending_query_excludes_ineligible_rows(
        self,
    ) -> None:
        transcript = "Persist this exact v2 transcript."
        audio_path = "/tmp/penny-v2-test.m4a"
        row_id = self._insert_maya_eligible(
            content_hash="audio-sha256-for-v2-test",
            source="iCloud",
            transcript=transcript,
            audio_path=audio_path,
            duration_seconds=42.5,
            ingest_state="transcribed",
            discovered_at="2026-07-28T12:34:56Z",
            recorded_at="2026-07-28T12:34:56Z",
            quality_status="passed",
            maya_delivery_eligible=True,
        )
        self.assertIsNotNone(row_id)
        transcript_log.upsert_voice_memo_recording(
            9876,
            label="v2 test recording",
            raw_path="recording.m4a",
            duration_seconds=42.5,
        )
        transcript_log.link_voice_memo_transcript(
            9876,
            transcript_row_id=int(row_id),
            content_hash="audio-sha256-for-v2-test",
            audio_path=audio_path,
        )
        maya_source_row_id = transcript_log.insert_transcript(
            content_hash="maya-origin-row",
            source="maya:reminder",
            transcript="Maya-originated rows never return to Maya.",
            quality_status="passed",
            enqueue_slack=False,
        )
        review_row_id = transcript_log.insert_transcript(
            content_hash="review-row",
            source="iCloud",
            transcript="Human review remains local.",
            ingest_state="needs_review",
            quality_status="needs_review",
            enqueue_slack=False,
        )

        envelope = transcript_log.build_maya_v2_envelope(int(row_id))
        _validate_against_checked_maya_schema(envelope)
        pending_ids = {
            delivery["id"] for delivery in transcript_log.get_pending_maya_deliveries()
        }

        self.assertEqual(
            set(envelope),
            {
                "schema_version",
                "transcript_id",
                "transcript_sha256",
                "transcript",
                "source",
                "captured_at",
                "duration_seconds",
                "audio_provenance",
                "source_spans",
                "client_ref",
            },
        )
        self.assertEqual(envelope["schema_version"], "penny-maya.v2")
        self.assertEqual(envelope["transcript_id"], str(row_id))
        self.assertEqual(
            envelope["transcript_sha256"],
            hashlib.sha256(transcript.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(envelope["transcript"], transcript)
        self.assertEqual(envelope["source"], "icloud")
        self.assertEqual(envelope["captured_at"], "2026-07-28T12:34:56Z")
        self.assertEqual(envelope["duration_seconds"], 42.5)
        self.assertEqual(
            envelope["audio_provenance"],
            {
                "content_hash": "audio-sha256-for-v2-test",
                "audio_path": None,
                "recording_pk": 9876,
            },
        )
        self.assertEqual(envelope["source_spans"], [])
        self.assertEqual(envelope["client_ref"], f"penny:{row_id}")
        self.assertEqual(pending_ids, {row_id})
        self.assertNotIn(maya_source_row_id, pending_ids)
        self.assertNotIn(review_row_id, pending_ids)

    def test_maya_v2_envelope_rejects_maya_origin_and_review_rows(self) -> None:
        maya_origin_row_id = transcript_log.insert_transcript(
            content_hash="maya-origin-envelope-hash",
            source="maya:reminder",
            transcript="This must never be returned to Maya.",
            quality_status="passed",
            enqueue_slack=False,
        )
        review_row_id = transcript_log.insert_transcript(
            content_hash="review-envelope-hash",
            source="iCloud",
            transcript="This must remain under review.",
            ingest_state="needs_review",
            quality_status="needs_review",
            enqueue_slack=False,
        )
        self.assertIsNotNone(maya_origin_row_id)
        self.assertIsNotNone(review_row_id)

        with self.assertRaisesRegex(ValueError, "Maya-originated"):
            transcript_log.build_maya_v2_envelope(int(maya_origin_row_id))
        with self.assertRaisesRegex(ValueError, "Only passed"):
            transcript_log.build_maya_v2_envelope(int(review_row_id))

    def test_maya_v2_envelope_normalizes_persisted_capture_time_to_iso8601_utc(
        self,
    ) -> None:
        row_id = self._insert_maya_eligible(
            content_hash="captured-at-audio-hash",
            source="iCloud",
            transcript="Use the SQLite capture timestamp.",
            recorded_at="2026-07-28T05:34:56-07:00",
            quality_status="passed",
        )
        self.assertIsNotNone(row_id)

        envelope = transcript_log.build_maya_v2_envelope(int(row_id))

        self.assertEqual(
            envelope["captured_at"],
            "2026-07-28T12:34:56Z",
        )

    def test_maya_delivery_worker_posts_authenticated_v2_and_accepts_duplicate_receipt(
        self,
    ) -> None:
        import maya_delivery

        transcript = "Deliver this persisted transcript to Maya exactly once."
        row_id = self._insert_maya_eligible(
            content_hash="maya-worker-contract-hash",
            source="iCloud",
            transcript=transcript,
            duration_seconds=9.5,
            discovered_at="2026-07-28T18:00:00Z",
            quality_status="passed",
        )
        envelope = transcript_log.build_maya_v2_envelope(int(row_id))
        response = _MayaResponse(
            _maya_receipt(
                envelope,
                drop_id="drop-penny-v2-worker",
                duplicate=True,
            )
        )

        with (
            patch.object(
                maya_delivery.cfg.maya,
                "transcript_url",
                "http://maya:8200/ingest/transcript",
            ),
            patch.object(maya_delivery.cfg.maya, "ingest_token", "test-token"),
            patch.object(
                maya_delivery.cfg.maya,
                "delivery_timeout_seconds",
                7.5,
                create=True,
            ),
            patch.object(
                maya_delivery.requests,
                "post",
                return_value=response,
            ) as maya_post,
        ):
            delivered = maya_delivery.process_pending_maya_deliveries()

        self.assertEqual(delivered, 1)
        posted = maya_post.call_args.kwargs
        posted_body = json.loads(posted["data"].decode("utf-8"))
        _validate_against_checked_maya_schema(posted_body)
        self.assertEqual(posted_body, envelope)
        self.assertEqual(
            posted["headers"],
            {
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(posted["timeout"], 7.5)
        stored = transcript_log.get_transcript(int(row_id))
        self.assertEqual(stored["maya_delivery_status"], "sent")
        self.assertEqual(stored["maya_drop_id"], "drop-penny-v2-worker")

    def test_maya_transport_retry_is_identity_stable_and_never_falls_back_to_notes(
        self,
    ) -> None:
        import maya_delivery

        transcript = "Retry these exact UTF-8 bytes: café.\nSecond line."
        row_id = self._insert_maya_eligible(
            content_hash="maya-worker-retry-hash",
            source="Shortcut",
            transcript=transcript,
            discovered_at="2026-07-28T18:01:00Z",
            quality_status="passed",
            enqueue_slack=False,
        )
        envelope = transcript_log.build_maya_v2_envelope(int(row_id))
        accepted = _MayaResponse(
            _maya_receipt(
                envelope,
                drop_id="drop-penny-v2-retry",
                duplicate=False,
            )
        )

        with (
            patch.object(
                maya_delivery.cfg.maya,
                "transcript_url",
                "http://maya:8200/ingest/transcript",
            ),
            patch.object(maya_delivery.cfg.maya, "ingest_token", "test-token"),
            patch.object(
                maya_delivery.requests,
                "post",
                side_effect=[
                    maya_delivery.requests.Timeout("simulated timeout"),
                    accepted,
                ],
            ) as maya_post,
            patch.object(core, "add_note") as add_note,
        ):
            first_delivered = maya_delivery.process_pending_maya_deliveries()
            after_timeout = transcript_log.get_transcript(int(row_id))
            self.assertIsNotNone(after_timeout["maya_next_attempt_at"])
            self.assertEqual(after_timeout["maya_delivery_attempt_count"], 1)
            conn = transcript_log._get_conn()
            try:
                conn.execute(
                    """
                    UPDATE transcripts
                    SET maya_next_attempt_at = datetime('now', '-1 second')
                    WHERE id = ?
                    """,
                    (row_id,),
                )
                conn.commit()
            finally:
                conn.close()
            second_delivered = maya_delivery.process_pending_maya_deliveries()

        self.assertEqual(first_delivered, 0)
        self.assertEqual(after_timeout["maya_delivery_status"], "pending")
        self.assertEqual(second_delivered, 1)
        self.assertEqual(maya_post.call_count, 2)
        first_body = maya_post.call_args_list[0].kwargs["data"]
        second_body = maya_post.call_args_list[1].kwargs["data"]
        self.assertEqual(first_body, second_body)
        self.assertEqual(json.loads(first_body.decode("utf-8")), envelope)
        add_note.assert_not_called()

    def test_local_maya_receipt_write_failure_stays_pending_and_replays(
        self,
    ) -> None:
        import maya_delivery

        row_id = self._insert_maya_eligible(
            content_hash="maya-local-receipt-write-hash",
            source="iCloud",
            transcript="Replay after a local receipt write failure.",
            discovered_at="2026-07-28T18:02:00Z",
            quality_status="passed",
            enqueue_slack=False,
        )
        envelope = transcript_log.build_maya_v2_envelope(int(row_id))
        responses = [
            _MayaResponse(
                _maya_receipt(
                    envelope,
                    drop_id="drop-local-write-replay",
                    duplicate=False,
                )
            ),
            _MayaResponse(
                _maya_receipt(
                    envelope,
                    drop_id="drop-local-write-replay",
                    duplicate=True,
                )
            ),
        ]
        persistence_attempts = 0

        def persist_receipt(transcript_row_id: int, drop_id: str) -> None:
            nonlocal persistence_attempts
            persistence_attempts += 1
            if persistence_attempts == 1:
                raise sqlite3.OperationalError("simulated local write failure")
            transcript_log.mark_maya_delivery_sent(transcript_row_id, drop_id)

        with (
            patch.object(
                maya_delivery.cfg.maya,
                "transcript_url",
                "http://maya:8200/ingest/transcript",
            ),
            patch.object(maya_delivery.cfg.maya, "ingest_token", "test-token"),
            patch.object(
                maya_delivery.requests,
                "post",
                side_effect=responses,
            ),
            patch.object(
                maya_delivery,
                "mark_maya_delivery_sent",
                side_effect=persist_receipt,
            ),
        ):
            first_delivered = maya_delivery.process_pending_maya_deliveries(limit=1)
            after_failure = transcript_log.get_transcript(int(row_id))
            second_delivered = maya_delivery.process_pending_maya_deliveries(limit=1)

        self.assertEqual(first_delivered, 0)
        self.assertEqual(after_failure["maya_delivery_status"], "pending")
        self.assertIsNone(after_failure["maya_delivery_error"])
        self.assertIsNone(after_failure["maya_drop_id"])
        self.assertEqual(second_delivered, 1)
        stored = transcript_log.get_transcript(int(row_id))
        self.assertEqual(stored["maya_delivery_status"], "sent")
        self.assertEqual(stored["maya_drop_id"], "drop-local-write-replay")

    def test_maya_delivery_pass_backs_off_transient_row_and_attempts_later_row(
        self,
    ) -> None:
        import maya_delivery

        first_id = self._insert_maya_eligible(
            content_hash="maya-fair-first-hash",
            source="iCloud",
            transcript="The first delivery times out.",
            quality_status="passed",
            enqueue_slack=False,
        )
        second_id = self._insert_maya_eligible(
            content_hash="maya-fair-second-hash",
            source="iCloud",
            transcript="The second delivery must still be attempted.",
            quality_status="passed",
            enqueue_slack=False,
        )
        second_envelope = transcript_log.build_maya_v2_envelope(int(second_id))

        with (
            patch.object(
                maya_delivery.cfg.maya,
                "transcript_url",
                "http://maya:8200/ingest/transcript",
            ),
            patch.object(maya_delivery.cfg.maya, "ingest_token", "test-token"),
            patch.object(
                maya_delivery.requests,
                "post",
                side_effect=[
                    maya_delivery.requests.Timeout("simulated oldest-row timeout"),
                    _MayaResponse(
                        _maya_receipt(
                            second_envelope,
                            drop_id="drop-fair-second",
                            duplicate=False,
                        )
                    ),
                ],
            ) as maya_post,
        ):
            delivered = maya_delivery.process_pending_maya_deliveries(limit=2)

        self.assertEqual(delivered, 1)
        self.assertEqual(maya_post.call_count, 2)
        attempted_ids = [
            json.loads(call.kwargs["data"].decode("utf-8"))["transcript_id"]
            for call in maya_post.call_args_list
        ]
        self.assertEqual(attempted_ids, [str(first_id), str(second_id)])
        first = transcript_log.get_transcript(int(first_id))
        second = transcript_log.get_transcript(int(second_id))
        self.assertEqual(first["maya_delivery_status"], "pending")
        self.assertEqual(first["maya_delivery_attempt_count"], 1)
        self.assertIsNotNone(first["maya_next_attempt_at"])
        self.assertEqual(second["maya_delivery_status"], "sent")
        self.assertEqual(transcript_log.get_pending_maya_deliveries(), [])

    def test_maya_delivery_worker_fails_closed_on_conflicting_receipt_and_skips_review(
        self,
    ) -> None:
        import maya_delivery

        eligible_id = self._insert_maya_eligible(
            content_hash="maya-worker-conflict-hash",
            source="iCloud",
            transcript="Reject a receipt for a different transcript.",
            quality_status="passed",
        )
        review_id = transcript_log.insert_transcript(
            content_hash="maya-worker-review-hash",
            source="iCloud",
            transcript="Keep this transcript under human review.",
            ingest_state="needs_review",
            quality_status="needs_review",
            enqueue_slack=False,
        )
        envelope = transcript_log.build_maya_v2_envelope(int(eligible_id))
        conflicting = _maya_receipt(
            envelope,
            drop_id="drop-conflicting-receipt",
            duplicate=False,
        )
        conflicting["transcript_id"] = "different-transcript"

        with (
            patch.object(
                maya_delivery.cfg.maya,
                "transcript_url",
                "http://maya:8200/ingest/transcript",
            ),
            patch.object(maya_delivery.cfg.maya, "ingest_token", "test-token"),
            patch.object(
                maya_delivery.requests,
                "post",
                return_value=_MayaResponse(conflicting),
            ) as maya_post,
        ):
            delivered = maya_delivery.process_pending_maya_deliveries()

        self.assertEqual(delivered, 0)
        self.assertEqual(maya_post.call_count, 1)
        eligible = transcript_log.get_transcript(int(eligible_id))
        review = transcript_log.get_transcript(int(review_id))
        self.assertEqual(eligible["maya_delivery_status"], "failed")
        self.assertIsNone(eligible["maya_drop_id"])
        self.assertEqual(review["maya_delivery_status"], "ineligible")

    def test_empty_normalized_transcript_stays_failed_and_not_slack_eligible(
        self,
    ) -> None:
        transcript = "SE<|hr|><|hr|><|hr|>"
        row_id = transcript_log.insert_transcript(
            content_hash="empty-normalized-contract-hash",
            source="iCloud",
            transcript=transcript,
            ingest_state="transcribed",
            quality_status="needs_review",
            quality_detail="empty_after_normalization",
            enqueue_slack=False,
        )

        with (
            patch.object(core, "mark_failed", transcript_log.mark_failed),
            self.assertRaisesRegex(
                core.RoutingError,
                "empty transcript after normalization",
            ),
        ):
            core.classify_and_route(
                transcript,
                source="iCloud",
                row_id=row_id,
            )

        failed_row = transcript_log.get_transcript(row_id)
        self.assertEqual(failed_row["status"], "failed")
        self.assertEqual(failed_row["ingest_state"], "failed")
        self.assertEqual(
            transcript_log.get_pending_slack_deliveries(
                transcript_id=row_id,
            ),
            [],
        )

        with patch.object(slack_delivery.requests, "post") as slack_post:
            delivered = slack_delivery.process_pending_slack_deliveries()

        self.assertEqual(delivered, 0)
        slack_post.assert_not_called()

    def test_local_mark_routed_failure_does_not_suppress_slack(
        self,
    ) -> None:
        transcript = "A long note that should be saved locally."
        row_id = transcript_log.insert_transcript(
            content_hash="local-mark-routed-failure-contract-hash",
            source="iCloud",
            transcript=transcript,
            ingest_state="transcribed",
        )
        core.cfg.maya.transcript_url = ""
        core.cfg.maya.ingest_token = ""

        with (
            patch.object(core, "detect_content_type", return_value="long_note"),
            patch.object(
                core,
                "ensure_note",
                return_value=AppleEffectReceipt(
                    "e" * 64, "note", "note-id", "succeeded",
                    actual_target="Penny", transcript_id=row_id,
                ),
            ) as ensure_note_mock,
            patch.object(core, "mark_routed", return_value=False) as mark_routed_mock,
            patch.object(core, "mark_failed", transcript_log.mark_failed),
            self.assertRaisesRegex(
                core.RoutingError,
                "receipt_persistence_failed",
            ),
        ):
            core.classify_and_route(
                transcript,
                source="iCloud",
                row_id=row_id,
            )

        ensure_note_mock.assert_called_once()
        mark_routed_mock.assert_called_once_with(
            row_id,
            {"type": "long_note"},
            "note in Penny",
        )
        failed_row = transcript_log.get_transcript(row_id)
        self.assertEqual(failed_row["status"], "failed")
        self.assertEqual(failed_row["ingest_state"], "failed")
        self.assertEqual(
            len(
                transcript_log.get_pending_slack_deliveries(
                    transcript_id=row_id,
                )
            ),
            1,
        )

        with patch.object(
            slack_delivery.requests,
            "post",
            return_value=_SlackResponse({"ok": True, "ts": "171717.100"}),
        ) as slack_post:
            delivered = slack_delivery.process_pending_slack_deliveries()

        self.assertEqual(delivered, 1)
        slack_post.assert_called_once()

    def test_unavailable_persisted_body_fails_closed_before_maya_or_local_routing(
        self,
    ) -> None:
        for scenario, persisted_row in (
            ("missing-row", None),
            ("missing-transcript-field", {"routing_progress": None}),
        ):
            with self.subTest(scenario=scenario):
                transcript = f"Fallback body must not be sent for {scenario}."
                row_id = transcript_log.insert_transcript(
                    content_hash=f"persisted-body-{scenario}-contract-hash",
                    source="iCloud",
                    transcript=transcript,
                    ingest_state="transcribed",
                )

                with (
                    patch.object(core, "get_transcript", return_value=persisted_row),
                    patch.object(core, "mark_failed", transcript_log.mark_failed),
                    patch.object(core.requests, "post") as maya_post,
                    patch.object(core, "detect_content_type") as detect_mock,
                    patch.object(core, "add_note") as note_mock,
                    patch.object(core, "add_reminder") as reminder_mock,
                    patch.object(core, "mark_routed") as mark_routed_mock,
                    self.assertRaisesRegex(
                        core.RoutingError,
                        "persisted transcript.*row_id",
                    ),
                ):
                    core.classify_and_route(
                        transcript,
                        source="iCloud",
                        row_id=row_id,
                    )

                maya_post.assert_not_called()
                detect_mock.assert_not_called()
                note_mock.assert_not_called()
                reminder_mock.assert_not_called()
                mark_routed_mock.assert_not_called()

                failed_row = transcript_log.get_transcript(row_id)
                self.assertEqual(failed_row["status"], "failed")
                self.assertEqual(failed_row["ingest_state"], "failed")
                self.assertIsNone(failed_row["routed_to"])
                self.assertIsNone(failed_row["routing_result"])
                self.assertIsNone(failed_row["routing_progress"])
                self.assertEqual(
                    len(
                        transcript_log.get_pending_slack_deliveries(
                            transcript_id=row_id,
                        )
                    ),
                    1,
                )

    def test_icloud_transcript_contract_preserves_exact_body_across_maya_and_slack_retry(
        self,
    ) -> None:
        transcript = (
            "Penny contract   canary line one.\tTabbed tail  \n"
            "    Indented line two keeps punctuation, numbers 12345, and spacing exactly.\n"
            "Line three has  repeated  spaces and a trailing pad.  "
        )

        row_id = transcript_log.insert_transcript(
            content_hash="task5-contract-hash",
            source="iCloud",
            transcript=transcript,
        )

        self.assertIsNotNone(row_id)
        stored_row = transcript_log.get_transcript(row_id)
        self.assertEqual(stored_row["source"], "iCloud")
        self.assertEqual(stored_row["transcript"], transcript)

        maya_response = unittest.mock.Mock()
        maya_response.status_code = 200
        maya_response.json.return_value = {
            "ok": True,
            "routed_to": "clio",
            "routing_detail": "accepted",
        }

        with patch.object(core.requests, "post", return_value=maya_response) as maya_post:
            route_result = core.classify_and_route(
                transcript,
                source="iCloud",
                row_id=row_id,
            )

        self.assertEqual(route_result, {"skip": True, "reason": "routed_to_maya"})
        maya_payload = maya_post.call_args.kwargs["json"]
        self.assertEqual(maya_payload["transcript"], transcript)
        self.assertEqual(maya_payload["source"], "iCloud")
        self.assertEqual(maya_payload["client_ref"], f"penny:{row_id}")

        routed_row = transcript_log.get_transcript(row_id)
        self.assertEqual(routed_row["routed_to"], "maya")
        routing_progress = json.loads(routed_row["routing_progress"])
        self.assertEqual(routing_progress["maya_route"]["state"], "accepted")
        self.assertEqual(routing_progress["maya_route"]["client_ref"], f"penny:{row_id}")

        pending = transcript_log.get_pending_slack_deliveries(transcript_id=row_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["channel_id"], "C0BKS0QT7FU")
        self.assertEqual(pending[0]["message_text"], transcript)

        with patch.object(slack_delivery.requests, "post") as slack_post:
            slack_post.side_effect = [
                _SlackResponse(
                    {"ok": False, "error": "ratelimited"},
                    headers={"Retry-After": "17"},
                ),
                _SlackResponse({"ok": True, "ts": "999.001"}),
            ]

            first_delivered = slack_delivery.process_pending_slack_deliveries()
            self.assertEqual(first_delivered, 0)

            conn = transcript_log._get_conn()
            try:
                first_attempt = conn.execute(
                    "SELECT status, attempt_count, last_error, next_attempt_at, message_text, channel_id "
                    "FROM slack_deliveries WHERE transcript_row_id = ?",
                    (row_id,),
                ).fetchone()
                conn.execute(
                    "UPDATE slack_deliveries "
                    "SET next_attempt_at = datetime('now', '-1 second') "
                    "WHERE transcript_row_id = ?",
                    (row_id,),
                )
                conn.commit()
            finally:
                conn.close()

            second_delivered = slack_delivery.process_pending_slack_deliveries()

        self.assertEqual(second_delivered, 1)
        first_attempt_row = dict(first_attempt)
        self.assertEqual(first_attempt_row["status"], "pending")
        self.assertEqual(first_attempt_row["attempt_count"], 1)
        self.assertEqual(first_attempt_row["last_error"], "ratelimited")
        self.assertIsNotNone(first_attempt_row["next_attempt_at"])
        self.assertEqual(first_attempt_row["message_text"], transcript)
        self.assertEqual(first_attempt_row["channel_id"], "C0BKS0QT7FU")

        self.assertEqual(slack_post.call_count, 2)
        first_payload = slack_post.call_args_list[0].kwargs["json"]
        second_payload = slack_post.call_args_list[1].kwargs["json"]
        self.assertEqual(first_payload["channel"], "C0BKS0QT7FU")
        self.assertEqual(second_payload["channel"], "C0BKS0QT7FU")
        self.assertEqual(first_payload["text"], transcript)
        self.assertEqual(second_payload["text"], transcript)
        self.assertEqual(first_payload["client_msg_id"], second_payload["client_msg_id"])
        self.assertNotIn("thread_ts", first_payload)
        self.assertNotIn("thread_ts", second_payload)
        self.assertEqual(
            first_payload["blocks"][0]["elements"][0]["text"],
            f"Penny transcript {row_id}",
        )
        self.assertEqual(_slack_section_text(first_payload), transcript)
        self.assertEqual(_slack_section_text(second_payload), transcript)
        self.assertEqual(first_payload["blocks"], second_payload["blocks"])

        conn = transcript_log._get_conn()
        try:
            delivery_row = conn.execute(
                "SELECT status, attempt_count, provider_ts, message_text, channel_id "
                "FROM slack_deliveries WHERE transcript_row_id = ?",
                (row_id,),
            ).fetchone()
        finally:
            conn.close()

        final_delivery = dict(delivery_row)
        self.assertEqual(final_delivery["status"], "sent")
        self.assertEqual(final_delivery["attempt_count"], 1)
        self.assertEqual(final_delivery["provider_ts"], "999.001")
        self.assertEqual(final_delivery["message_text"], transcript)
        self.assertEqual(final_delivery["channel_id"], "C0BKS0QT7FU")
        self.assertEqual(transcript_log.get_pending_slack_deliveries(transcript_id=row_id), [])
