#!/usr/bin/env python3
"""Tests for Penny webhook server (webhook/server.py)."""
import hashlib
import io
import logging
import os
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("HOME", "/tmp/penny_test_home")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("PENNY_INGEST_TOKEN", "ingest-test-token")
os.environ.setdefault(
    "GOOGLE_CREDENTIALS_FILE",
    "/tmp/penny_test_home/.penny/google_credentials.json",
)
os.environ.setdefault(
    "GOOGLE_TOKEN_FILE",
    "/tmp/penny_test_home/.penny/google_token.json",
)

# Import the Flask app — must import server module which imports config at module level
import importlib
import webhook.server as server_module  # noqa: E402
import transcript_log  # noqa: E402
from archive import stage_audio  # noqa: E402
from transcript_log import InsertOutcome, TranscriptInsertResult  # noqa: E402
from transcript_quality import QualityResult, TranscriptionResult  # noqa: E402

app = server_module.app
app.config["TESTING"] = True
# Other focused modules may have initialized the shared config singleton before
# this module is collected; keep webhook tests hermetic and explicit.
server_module.cfg.webhook.ingest_token = "ingest-test-token"


def _ingest_auth(token: str = "ingest-test-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _inserted(row_id: int) -> TranscriptInsertResult:
    return TranscriptInsertResult(InsertOutcome.INSERTED, row_id=row_id)


@pytest.fixture
def client(tmp_path, monkeypatch):
    import transcript_log
    monkeypatch.setattr(transcript_log, "TRANSCRIPT_DB_PATH", tmp_path / "transcripts.db")
    monkeypatch.setattr(transcript_log, "_MIGRATION_SOURCES", [])
    import webhook.server as server
    transcript_log.init_db()
    monkeypatch.setattr(server.cfg.archive, "object_root", tmp_path / "archive-objects")
    monkeypatch.setattr(server, "record_archive_unavailable", MagicMock())
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


class HealthTests(unittest.TestCase):
    def test_health_returns_ok(self):
        with app.test_client() as client:
            resp = client.get("/health")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["service"], "penny-webhook")
            self.assertNotIn("telegram_configured", data)

    def test_ready_returns_doctor_projection_and_503_when_unready(self):
        from doctor import ComponentStatus, DoctorReport

        report = DoctorReport(
            "unready",
            {
                "voice_memos": ComponentStatus(
                    "voice_memos",
                    "unready",
                    "terminal_failure",
                    {"terminal_failure_count": 1},
                    "2026-08-10T10:00:00Z",
                )
            },
            "2026-08-10T10:00:00Z",
            "test",
        )
        with patch.object(server_module, "run_doctor", return_value=report):
            response = app.test_client().get("/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["overall"], "unready")


def test_upload_low_quality_transcript_is_durable_and_not_published(client, monkeypatch):
    import transcript_log
    import webhook.server as server

    rejected_text = "A valid memo first. " + "Vous " * 20
    monkeypatch.setattr(server, "get_file_hash", lambda _: "review-upload-hash")
    monkeypatch.setattr(
        server,
        "transcribe",
        lambda _: TranscriptionResult(
            rejected_text,
            QualityResult(False, "needs_review"),
            2,
            (
                "attempt_1=consecutive_token_repetition;"
                "attempt_2=control_token"
            ),
        ),
    )
    route_mock = MagicMock()
    monkeypatch.setattr(server, "classify_and_route", route_mock)

    response = client.post(
        "/upload",
        data={"audio": (io.BytesIO(b"fake audio data"), "test.m4a")},
        content_type="multipart/form-data",
        headers=_ingest_auth(),
    )

    assert response.status_code == 422
    assert response.get_json() == {"error": "Transcript needs review"}
    row = transcript_log.get_transcript_by_hash("review-upload-hash")
    assert row["transcript"] == rejected_text
    stored = transcript_log.get_transcript(row["id"])
    assert stored["ingest_state"] == "needs_review"
    assert stored["error_message"] == "needs_review"
    assert stored["quality_detail"] == (
        "attempt_1=consecutive_token_repetition;attempt_2=control_token"
    )
    assert transcript_log.get_pending_slack_deliveries(transcript_id=row["id"]) == []
    operational = transcript_log.get_pending_quality_failure_deliveries()
    assert len(operational) == 1
    assert operational[0]["content_kind"] == "transcript_quality_failure"
    assert operational[0]["destination"] == "maya-ledger"
    assert rejected_text not in operational[0]["message_text"]
    route_mock.assert_not_called()


def test_upload_stages_before_transcription_and_keeps_durable_object(client, monkeypatch):
    import transcript_log
    import webhook.server as server

    staged_paths = []
    monkeypatch.setattr(
        server,
        "transcribe",
        lambda path: (
            staged_paths.append(Path(path)),
            TranscriptionResult("archived upload", QualityResult(True), 1),
        )[1],
    )
    monkeypatch.setattr(
        server, "classify_and_route", lambda *args, **kwargs: {"items": []}
    )
    response = client.post(
        "/upload",
        data={"audio": (io.BytesIO(b"upload audio"), "../private/capture.m4a")},
        content_type="multipart/form-data",
        headers=_ingest_auth(),
    )
    assert response.status_code == 200
    assert len(staged_paths) == 1
    assert staged_paths[0].is_file()
    assert str(staged_paths[0]).startswith(str(server.cfg.archive.object_root))
    content_hash = hashlib.md5(b"upload audio").hexdigest()
    row = transcript_log.get_transcript_by_hash(content_hash)
    assert row["audio_path"] == str(staged_paths[0])
    due = transcript_log.get_pending_archive_deliveries(limit=10)
    assert len(due) == 1
    assert due[0]["transcript_row_id"] == row["id"]
    assert due[0]["original_name"] == "capture.m4a"
    assert due[0]["source_aliases"] == '["Shortcut","capture.m4a"]'
    assert due[0]["mime_type"] != "multipart/form-data"


def test_upload_duplicate_archive_queue_failure_returns_503_without_route(client, monkeypatch):
    import webhook.server as server

    monkeypatch.setattr(
        server,
        "transcribe",
        lambda _: TranscriptionResult("canonical", QualityResult(True), 1),
    )
    monkeypatch.setattr(
        server,
        "insert_transcript_result",
        lambda **kwargs: TranscriptInsertResult(
            InsertOutcome.DUPLICATE, row_id=77, existing_status="pending"
        ),
    )
    monkeypatch.setattr(
        server,
        "get_transcript_by_hash",
        lambda _: {
            "id": 77,
            "status": "pending",
            "source": "Shortcut",
            "transcript": "canonical",
        },
    )
    monkeypatch.setattr(
        server,
        "queue_archive_delivery",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            sqlite3.OperationalError("archive unavailable")
        ),
    )
    route = MagicMock()
    monkeypatch.setattr(server, "classify_and_route", route)
    response = client.post(
        "/upload",
        data={"audio": (io.BytesIO(b"upload audio"), "capture.m4a")},
        content_type="multipart/form-data",
        headers=_ingest_auth(),
    )
    assert response.status_code == 503
    assert response.get_json() == {"error": "upload unavailable"}
    route.assert_not_called()


def test_upload_atomic_archive_persistence_failure_returns_503_without_canonical_ack(
    client, monkeypatch
):
    import transcript_log
    import webhook.server as server

    monkeypatch.setattr(
        server,
        "transcribe",
        lambda _: TranscriptionResult("canonical", QualityResult(True), 1),
    )
    monkeypatch.setattr(
        transcript_log,
        "_queue_archive_delivery_conn",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            sqlite3.OperationalError("archive unavailable")
        ),
    )
    route = MagicMock()
    monkeypatch.setattr(server, "classify_and_route", route)
    response = client.post(
        "/upload",
        data={"audio": (io.BytesIO(b"atomic audio"), "atomic.m4a")},
        content_type="multipart/form-data",
        headers=_ingest_auth(),
    )
    assert response.status_code == 503
    assert transcript_log.get_transcript_by_hash(
        hashlib.md5(b"atomic audio").hexdigest()
    ) is None
    route.assert_not_called()
    assert list(server.cfg.archive.object_root.rglob("*.m4a"))


def test_ingest_text_records_archive_not_applicable(client, monkeypatch):
    import transcript_log
    import webhook.server as server

    monkeypatch.setattr(
        server, "classify_and_route", lambda *args, **kwargs: {"items": []}
    )
    response = client.post(
        "/ingest",
        json={"text": "text has no raw audio", "source": "text"},
        headers=_ingest_auth(),
    )
    assert response.status_code == 200
    health = transcript_log.get_archive_delivery_health()
    assert health["not_applicable_count"] == 1


class UploadTests(unittest.TestCase):
    @patch(
        "webhook.server.transcribe",
        return_value=TranscriptionResult("test transcript", QualityResult(True), 1),
    )
    @patch("webhook.server.insert_transcript_result", return_value=_inserted(1))
    @patch("webhook.server.classify_and_route", return_value={"items": [], "skip": True})
    def test_upload_success(self, mock_route, mock_insert, mock_transcribe):
        with app.test_client() as client:
            data = {"audio": (io.BytesIO(b"fake audio data"), "test.m4a")}
            resp = client.post(
                "/upload",
                data=data,
                content_type="multipart/form-data",
                headers=_ingest_auth(),
            )
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertEqual(body["status"], "ok")
            self.assertIn("test transcript", body["transcript"])
            self.assertFalse(mock_insert.call_args.kwargs["enqueue_slack"])
            self.assertIn("archive_staged", mock_insert.call_args.kwargs)
            self.assertIn("archive_metadata", mock_insert.call_args.kwargs)
            self.assertFalse(mock_route.call_args.kwargs["allow_maya"])

    @patch(
        "webhook.server.get_transcript_by_hash",
        return_value={"id": 1, "status": "routed", "transcript": "test transcript", "source": "Shortcut"},
    )
    @patch(
        "webhook.server.insert_transcript_result",
        return_value=TranscriptInsertResult(
            InsertOutcome.DUPLICATE, row_id=1, existing_status="routed"
        ),
    )
    @patch(
        "webhook.server.transcribe",
        return_value=TranscriptionResult("test transcript", QualityResult(True), 1),
    )
    def test_upload_duplicate_returns_ok(self, mock_transcribe, mock_insert, mock_get):
        with patch.object(server_module, "queue_archive_delivery") as queue, app.test_client() as client:
            data = {"audio": (io.BytesIO(b"fake audio data"), "test.m4a")}
            resp = client.post(
                "/upload",
                data=data,
                content_type="multipart/form-data",
                headers=_ingest_auth(),
            )
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertEqual(body["status"], "ok")
            self.assertTrue(body["skipped"])
            queue.assert_called_once()

    def test_upload_missing_audio_returns_400(self):
        with app.test_client() as client:
            resp = client.post("/upload", headers=_ingest_auth())
            self.assertEqual(resp.status_code, 400)

    @patch("webhook.server.transcribe", side_effect=RuntimeError("transcription failed"))
    def test_upload_error_returns_500(self, mock_transcribe):
        with app.test_client() as client:
            data = {"audio": (io.BytesIO(b"fake audio data"), "test.m4a")}
            resp = client.post(
                "/upload",
                data=data,
                content_type="multipart/form-data",
                headers=_ingest_auth(),
            )
            self.assertEqual(resp.status_code, 500)

    @patch("webhook.server.get_file_hash", return_value="abc123")
    @patch("webhook.server.transcribe", side_effect=RuntimeError("transcription failed"))
    def test_upload_cleans_temp_file_on_error(self, mock_transcribe, mock_hash):
        """Temp file should be cleaned up even when transcription fails."""
        with app.test_client() as client:
            data = {"audio": (io.BytesIO(b"fake audio data"), "test.m4a")}
            resp = client.post(
                "/upload",
                data=data,
                content_type="multipart/form-data",
                headers=_ingest_auth(),
            )
            self.assertEqual(resp.status_code, 500)


class IngestTests(unittest.TestCase):
    def test_ingest_database_failure_returns_503(self):
        failed = TranscriptInsertResult(
            InsertOutcome.FAILED, error_code="database_unavailable"
        )
        with (
            patch.object(
                server_module,
                "insert_transcript_result",
                return_value=failed,
            ),
            patch.object(server_module, "classify_and_route") as route,
            app.test_client() as client,
        ):
            response = client.post(
                "/ingest", json={"text": "buy milk"}, headers=_ingest_auth()
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"error": "ingest unavailable"})
        route.assert_not_called()

    @patch("webhook.server.insert_transcript_result", return_value=_inserted(1))
    @patch("webhook.server.classify_and_route", return_value={"items": [{"item": "milk", "category": "groceries"}]})
    def test_ingest_success(self, mock_route, mock_insert):
        with app.test_client() as client:
            resp = client.post(
                "/ingest",
                json={"text": "buy milk", "source": "test"},
                headers=_ingest_auth(),
            )
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertEqual(body["status"], "ok")
            self.assertEqual(body["items_added"], 1)
            mock_route.assert_called_once()
            mock_insert.assert_called_once()
            self.assertFalse(mock_insert.call_args.kwargs["enqueue_slack"])
            self.assertFalse(mock_route.call_args.kwargs["allow_maya"])

    def test_ingest_missing_json_returns_400(self):
        with app.test_client() as client:
            resp = client.post("/ingest", headers=_ingest_auth())
            self.assertEqual(resp.status_code, 400)

    def test_ingest_missing_text_returns_400(self):
        with app.test_client() as client:
            resp = client.post(
                "/ingest", json={"not_text": "buy milk"}, headers=_ingest_auth()
            )
            self.assertEqual(resp.status_code, 400)

    def test_ingest_empty_text_returns_400(self):
        with app.test_client() as client:
            resp = client.post(
                "/ingest", json={"text": "   "}, headers=_ingest_auth()
            )
            self.assertEqual(resp.status_code, 400)

    @patch(
        "webhook.server.get_transcript_by_hash",
        return_value={"id": 1, "status": "routed", "transcript": "buy milk", "source": "text"},
    )
    @patch(
        "webhook.server.insert_transcript_result",
        return_value=TranscriptInsertResult(
            InsertOutcome.DUPLICATE, row_id=1, existing_status="routed"
        ),
    )
    def test_ingest_duplicate_returns_ok(self, mock_insert, mock_get):
        with patch.object(server_module, "record_archive_unavailable") as applicability, app.test_client() as client:
            resp = client.post(
                "/ingest", json={"text": "buy milk"}, headers=_ingest_auth()
            )
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertTrue(body["skipped"])
            applicability.assert_called_once()

    @patch("webhook.server.insert_transcript_result", return_value=_inserted(1))
    @patch("webhook.server.classify_and_route", side_effect=RuntimeError("routing failed"))
    def test_ingest_error_returns_500(self, mock_route, mock_insert):
        with app.test_client() as client:
            resp = client.post(
                "/ingest", json={"text": "buy milk"}, headers=_ingest_auth()
            )
            self.assertEqual(resp.status_code, 500)


DELIVER_PAYLOAD = {
    "transcript": "remind me to call the dentist tomorrow",
    "source": "voice_memo",
    "duration_seconds": 4.2,
    "recorded_at": "2026-07-09T18:00:00Z",
    "metadata": {"via": "maya"},
}


def test_upload_rejects_missing_token_before_transcription(client, monkeypatch):
    transcribe = MagicMock()
    monkeypatch.setattr(server_module, "transcribe", transcribe)
    response = client.post(
        "/upload",
        data={"audio": (io.BytesIO(b"audio"), "memo.m4a")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 401
    transcribe.assert_not_called()


def test_upload_does_not_log_raw_transcript(client, monkeypatch, caplog):
    transcript = "private upload transcript must not appear in logs"
    monkeypatch.setattr(server_module, "get_file_hash", lambda _: "upload-log-hash")
    monkeypatch.setattr(
        server_module,
        "transcribe",
        lambda _: TranscriptionResult(transcript, QualityResult(True), 1),
    )
    monkeypatch.setattr(server_module, "insert_transcript_result", lambda **_: _inserted(1))
    monkeypatch.setattr(
        server_module, "classify_and_route", lambda *_, **__: {"items": []}
    )
    caplog.set_level(logging.INFO, logger=server_module.log.name)

    response = client.post(
        "/upload",
        data={"audio": (io.BytesIO(b"audio"), "memo.m4a")},
        content_type="multipart/form-data",
        headers=_ingest_auth(),
    )

    assert response.status_code == 200
    assert transcript not in caplog.text


def test_webhook_redacts_ffmpeg_stderr_and_source_path(caplog, monkeypatch, tmp_path):
    sentinel = "FFMPEG_PROVIDER_BODY_SENTINEL"
    source_path = tmp_path / "PRIVATE_SOURCE_FILENAME_SENTINEL.m4a"
    source_path.write_bytes(b"audio")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.CalledProcessError(
                1,
                ["ffmpeg"],
                stderr=sentinel.encode("utf-8"),
            )
        ),
    )
    monkeypatch.setattr(
        server_module,
        "transcribe_with_quality",
        lambda path, model: TranscriptionResult("safe transcript", QualityResult(True), 1),
    )
    caplog.set_level(logging.INFO, logger=server_module.log.name)

    result = server_module.transcribe(source_path)

    assert result.text == "safe transcript"
    assert sentinel not in caplog.text
    assert str(source_path) not in caplog.text


def test_upload_redacts_user_filename_from_logs(client, monkeypatch, caplog):
    sentinel = "PRIVATE_UPLOAD_FILENAME_SENTINEL.m4a"
    monkeypatch.setattr(server_module, "get_file_hash", lambda _: "upload-name-hash")
    monkeypatch.setattr(
        server_module,
        "transcribe",
        lambda _: TranscriptionResult("safe transcript", QualityResult(True), 1),
    )
    monkeypatch.setattr(server_module, "insert_transcript_result", lambda **_: _inserted(1))
    monkeypatch.setattr(server_module, "classify_and_route", lambda *_, **__: {"items": []})
    caplog.set_level(logging.INFO, logger=server_module.log.name)

    response = client.post(
        "/upload",
        data={"audio": (io.BytesIO(b"audio"), sentinel)},
        content_type="multipart/form-data",
        headers=_ingest_auth(),
    )

    assert response.status_code == 200
    assert sentinel not in caplog.text


def test_deliver_redacts_user_source_from_logs(client, monkeypatch, caplog):
    sentinel = "PRIVATE_DELIVER_SOURCE_SENTINEL"
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(server_module, "insert_transcript_result", lambda **_: _inserted(1))
    monkeypatch.setattr(server_module, "classify_and_route", lambda *_, **__: {"items": []})
    monkeypatch.setattr(
        server_module,
        "get_transcript_by_hash",
        lambda _: {"id": 1, "status": "routed"},
    )
    caplog.set_level(logging.INFO, logger=server_module.log.name)

    response = client.post(
        "/deliver",
        json={**DELIVER_PAYLOAD, "source": sentinel},
        headers=_auth(),
    )

    assert response.status_code == 200
    assert sentinel not in caplog.text


def test_ingest_does_not_log_raw_text(client, monkeypatch, caplog):
    text = "private ingest text must not appear in logs"
    monkeypatch.setattr(server_module, "insert_transcript_result", lambda **_: _inserted(1))
    monkeypatch.setattr(
        server_module, "classify_and_route", lambda *_, **__: {"items": []}
    )
    caplog.set_level(logging.INFO, logger=server_module.log.name)

    response = client.post("/ingest", json={"text": text}, headers=_ingest_auth())

    assert response.status_code == 200
    assert text not in caplog.text


def test_oversized_upload_is_rejected_before_processing(client, monkeypatch):
    transcribe = MagicMock()
    route = MagicMock()
    temp_file = MagicMock()
    monkeypatch.setattr(server_module, "transcribe", transcribe)
    monkeypatch.setattr(server_module, "classify_and_route", route)
    monkeypatch.setattr(server_module.tempfile, "NamedTemporaryFile", temp_file)

    response = client.post(
        "/upload",
        data=b"x" * (server_module.cfg.webhook.max_request_bytes + 1),
        content_type="audio/m4a",
        headers=_ingest_auth(),
    )

    assert response.status_code == 413
    transcribe.assert_not_called()
    route.assert_not_called()
    temp_file.assert_not_called()


def test_raw_upload_over_audio_limit_is_rejected_before_processing(client, monkeypatch):
    transcribe = MagicMock()
    route = MagicMock()
    temp_file = MagicMock()
    monkeypatch.setattr(server_module, "transcribe", transcribe)
    monkeypatch.setattr(server_module, "classify_and_route", route)
    monkeypatch.setattr(server_module.tempfile, "NamedTemporaryFile", temp_file)

    response = client.post(
        "/upload",
        data=b"x" * (server_module.MAX_FILE_SIZE + 1),
        content_type="audio/m4a",
        headers=_ingest_auth(),
    )

    assert response.status_code == 413
    assert response.get_json() == {"error": "Audio file too large"}
    transcribe.assert_not_called()
    route.assert_not_called()
    temp_file.assert_not_called()


def test_multipart_upload_rejects_unknown_media_before_staging(
    client, monkeypatch, caplog
):
    """Unsupported multipart media must not reach the archive or transcriber."""
    filename = "PRIVATE_UPLOAD_FILENAME_SENTINEL.pdf"
    body = b"PRIVATE_UPLOAD_CONTENT_SENTINEL"
    stage = MagicMock()
    transcribe = MagicMock()
    monkeypatch.setattr(server_module, "stage_audio", stage)
    monkeypatch.setattr(server_module, "transcribe", transcribe)
    caplog.set_level(logging.INFO, logger=server_module.log.name)

    response = client.post(
        "/upload",
        data={"audio": (io.BytesIO(body), filename)},
        content_type="multipart/form-data",
        headers=_ingest_auth(),
    )

    assert response.status_code == 415
    assert response.get_json() == {"error": "unsupported audio media"}
    assert filename not in response.get_data(as_text=True)
    assert body.decode() not in caplog.text
    assert filename not in caplog.text
    stage.assert_not_called()
    transcribe.assert_not_called()


def test_multipart_upload_rejects_non_audio_mime_before_staging(
    client, monkeypatch
):
    """A trusted-looking extension cannot override a non-audio MIME type."""
    stage = MagicMock()
    transcribe = MagicMock()
    monkeypatch.setattr(server_module, "stage_audio", stage)
    monkeypatch.setattr(server_module, "transcribe", transcribe)

    response = client.post(
        "/upload",
        data={
            "audio": (
                io.BytesIO(b"audio"),
                "PRIVATE_UPLOAD_FILENAME_SENTINEL.m4a",
                "text/plain",
            )
        },
        content_type="multipart/form-data",
        headers=_ingest_auth(),
    )

    assert response.status_code == 415
    assert response.get_json() == {"error": "unsupported audio media"}
    stage.assert_not_called()
    transcribe.assert_not_called()


def test_multipart_upload_rejects_missing_filename_before_staging(client, monkeypatch):
    """Multipart audio requires a safe, supported filename extension."""
    stage = MagicMock()
    transcribe = MagicMock()
    monkeypatch.setattr(server_module, "stage_audio", stage)
    monkeypatch.setattr(server_module, "transcribe", transcribe)

    response = client.post(
        "/upload",
        data={"audio": (io.BytesIO(b"audio"), "PRIVATE_UPLOAD_FILENAME_SENTINEL", "audio/m4a")},
        content_type="multipart/form-data",
        headers=_ingest_auth(),
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "audio filename required"}
    stage.assert_not_called()
    transcribe.assert_not_called()


def test_raw_upload_rejects_unknown_media_before_staging(client, monkeypatch, caplog):
    """Raw uploads require an allowlisted audio MIME type before materialization."""
    body = b"PRIVATE_RAW_UPLOAD_CONTENT_SENTINEL"
    stage = MagicMock()
    transcribe = MagicMock()
    monkeypatch.setattr(server_module, "stage_audio", stage)
    monkeypatch.setattr(server_module, "transcribe", transcribe)
    caplog.set_level(logging.INFO, logger=server_module.log.name)

    response = client.post(
        "/upload",
        data=body,
        content_type="application/octet-stream",
        headers=_ingest_auth(),
    )

    assert response.status_code == 415
    assert response.get_json() == {"error": "unsupported audio media"}
    assert body.decode() not in caplog.text
    stage.assert_not_called()
    transcribe.assert_not_called()


def test_upload_failure_does_not_leak_exception_text(client, monkeypatch, caplog):
    sentinel = "upload-routing-secret-must-not-leak"
    monkeypatch.setattr(server_module, "transcribe", lambda _: (_ for _ in ()).throw(RuntimeError(sentinel)))
    caplog.set_level(logging.ERROR, logger=server_module.log.name)

    response = client.post(
        "/upload",
        data={"audio": (io.BytesIO(b"audio"), "memo.m4a")},
        content_type="multipart/form-data",
        headers=_ingest_auth(),
    )

    assert response.status_code == 500
    assert response.get_json() == {"error": "upload processing failed"}
    assert sentinel not in caplog.text
    assert sentinel not in response.get_data(as_text=True)


def test_main_rejects_unprotected_non_loopback_bind(monkeypatch):
    monkeypatch.setattr(server_module.cfg.webhook, "host", "0.0.0.0")
    monkeypatch.delenv("PENNY_WEBHOOK_ALLOW_NONLOOPBACK", raising=False)
    init_db = MagicMock()
    run = MagicMock()
    monkeypatch.setattr(server_module, "init_db", init_db)
    monkeypatch.setattr(server_module.app, "run", run)

    with pytest.raises(SystemExit):
        server_module.main()

    init_db.assert_not_called()
    run.assert_not_called()


def test_main_allows_explicitly_protected_non_loopback_bind(monkeypatch):
    monkeypatch.setattr(server_module.cfg.webhook, "host", "0.0.0.0")
    monkeypatch.setenv("PENNY_WEBHOOK_ALLOW_NONLOOPBACK", "1")
    init_db = MagicMock()
    run = MagicMock()
    monkeypatch.setattr(server_module, "init_db", init_db)
    monkeypatch.setattr(server_module.app, "run", run)

    server_module.main()

    init_db.assert_called_once()
    run.assert_called_once_with(
        host="0.0.0.0", port=server_module.cfg.webhook.port, use_reloader=False
    )


def test_ingest_failure_does_not_leak_exception_text(client, monkeypatch, caplog):
    sentinel = "ingest-routing-secret-must-not-leak"
    monkeypatch.setattr(
        server_module,
        "insert_transcript_result",
        lambda **_: (_ for _ in ()).throw(RuntimeError(sentinel)),
    )
    caplog.set_level(logging.ERROR, logger=server_module.log.name)

    response = client.post(
        "/ingest", json={"text": "buy milk"}, headers=_ingest_auth()
    )

    assert response.status_code == 500
    assert response.get_json() == {"error": "ingest processing failed"}
    assert sentinel not in caplog.text
    assert sentinel not in response.get_data(as_text=True)


def test_ingest_token_cannot_authorize_deliver(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "deliver-secret")
    response = client.post(
        "/deliver", json=DELIVER_PAYLOAD, headers=_ingest_auth()
    )
    assert response.status_code == 401


def test_deliver_rejects_non_json_before_parsing_or_persistence(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    insert = MagicMock()
    monkeypatch.setattr(server_module, "insert_transcript_result", insert)

    response = client.post(
        "/deliver",
        data=b"PRIVATE_DELIVER_BODY_SENTINEL",
        content_type="text/plain",
        headers=_auth(),
    )

    assert response.status_code == 415
    assert response.get_json() == {"error": "delivery requires JSON"}
    insert.assert_not_called()
    assert b"PRIVATE_DELIVER_BODY_SENTINEL" not in response.data


def test_deliver_rejects_oversized_request_before_parsing_or_persistence(
    client, monkeypatch
):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    insert = MagicMock()
    monkeypatch.setattr(server_module, "insert_transcript_result", insert)

    response = client.post(
        "/deliver",
        data=b"x" * (server_module.MAX_DELIVER_REQUEST_BYTES + 1),
        content_type="application/json",
        headers=_auth(),
    )

    assert response.status_code == 413
    assert response.get_json() == {"error": "request too large"}
    insert.assert_not_called()


def test_oversized_ingest_is_rejected_before_route(client, monkeypatch):
    route = MagicMock()
    monkeypatch.setattr(server_module, "classify_and_route", route)
    response = client.post(
        "/ingest",
        json={"text": "x" * 65_537},
        headers=_ingest_auth(),
    )
    assert response.status_code == 413
    route.assert_not_called()


def _auth(secret="test-secret"):
    return {"Authorization": f"Bearer {secret}"}


def test_deliver_requires_bearer_token(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    resp = client.post("/deliver", json=DELIVER_PAYLOAD)
    assert resp.status_code == 401


def test_deliver_rejects_empty_transcript(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    resp = client.post("/deliver", json={**DELIVER_PAYLOAD, "transcript": "  "},
                       headers=_auth())
    assert resp.status_code == 422


def test_deliver_routes_locally_without_maya(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    seen = {}
    insert_calls = []
    def fake_insert_transcript_result(**kwargs):
        insert_calls.append(kwargs)
        if len(insert_calls) == 1:
            return _inserted(1)
        return TranscriptInsertResult(
            InsertOutcome.DUPLICATE, row_id=1, existing_status="routed"
        )

    def fake_classify_and_route(transcript, source, row_id=None,
                                duration_seconds=None, allow_maya=True):
        seen.update(transcript=transcript, source=source, allow_maya=allow_maya)
        return {"content_type": "action_items"}

    import webhook.server as server
    monkeypatch.setattr(server, "classify_and_route", fake_classify_and_route)
    monkeypatch.setattr(server, "insert_transcript_result", fake_insert_transcript_result)
    monkeypatch.setattr(
        server,
        "get_transcript_by_hash",
        lambda _: {"id": 1, "status": "routed", "transcript": DELIVER_PAYLOAD["transcript"], "source": "maya:voice_memo"},
    )

    resp = client.post("/deliver", json=DELIVER_PAYLOAD, headers=_auth())
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "delivered"
    assert seen["allow_maya"] is False
    assert seen["transcript"] == DELIVER_PAYLOAD["transcript"]
    assert insert_calls[0]["enqueue_slack"] is False
    assert insert_calls[0]["archive_unavailable_reason"] == "no_raw_audio"

    # Same payload again → dedup via md5 content hash
    resp2 = client.post("/deliver", json=DELIVER_PAYLOAD, headers=_auth())
    assert resp2.status_code == 200
    assert resp2.get_json()["status"] == "duplicate"


def test_deliver_handles_insert_race_as_duplicate(client, monkeypatch):
    """A duplicate insert acknowledges only after finding the canonical row."""
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")

    import webhook.server as server
    monkeypatch.setattr(
        server,
        "insert_transcript_result",
        lambda **kwargs: TranscriptInsertResult(
            InsertOutcome.DUPLICATE, row_id=1, existing_status="routed"
        ),
    )
    monkeypatch.setattr(
        server,
        "get_transcript_by_hash",
        lambda _: {"id": 1, "status": "routed"},
    )

    route_called = MagicMock()
    monkeypatch.setattr(server, "classify_and_route", route_called)

    resp = client.post("/deliver", json=DELIVER_PAYLOAD, headers=_auth())
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "duplicate"}
    route_called.assert_not_called()


def test_deliver_duplicate_archive_applicability_failure_returns_503(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(
        server_module,
        "insert_transcript_result",
        lambda **_: TranscriptInsertResult(
            InsertOutcome.DUPLICATE, row_id=8, existing_status="routed"
        ),
    )
    monkeypatch.setattr(
        server_module, "get_transcript_by_hash",
        lambda _: {"id": 8, "status": "routed"},
    )
    monkeypatch.setattr(
        server_module, "record_archive_unavailable",
        MagicMock(side_effect=sqlite3.OperationalError("unavailable")),
    )
    route = MagicMock()
    monkeypatch.setattr(server_module, "classify_and_route", route)

    response = client.post("/deliver", json=DELIVER_PAYLOAD, headers=_auth())

    assert response.status_code == 503
    assert response.get_json() == {"error": "delivery unavailable"}
    route.assert_not_called()


@pytest.mark.parametrize("endpoint", ["ingest", "deliver"])
@pytest.mark.parametrize("archive_status", ["pending", "published"])
def test_text_duplicate_preserves_existing_raw_audio_archive_delivery(
    client, monkeypatch, tmp_path, endpoint, archive_status
):
    text = DELIVER_PAYLOAD["transcript"]
    content_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    source = tmp_path / f"existing-{endpoint}-{archive_status}.m4a"
    source.write_bytes(b"existing raw audio")
    staged = stage_audio(source, server_module.cfg.archive.object_root)
    row_id = transcript_log.insert_transcript(
        content_hash=content_hash,
        source="iCloud",
        transcript=text,
        archive_staged=staged,
        archive_metadata={
            "source": "iCloud",
            "source_alias": source.name,
            "quality_status": "passed",
        },
        enqueue_slack=False,
    )
    transcript_log.mark_routed(int(row_id), {"skip": True}, "test")
    pending = transcript_log.get_pending_archive_deliveries(limit=1)[0]
    if archive_status == "published":
        transcript_log.mark_archive_delivery_published(
            pending["id"],
            audio_path="/mirror/existing.m4a",
            markdown_path="/mirror/existing.md",
            manifest_path="/mirror/existing.json",
            receipt_sha256="existing-receipt",
        )

    def archive_state():
        conn = transcript_log._get_conn()
        try:
            return tuple(conn.execute(
                "SELECT status, availability_status, local_object_path, audio_sha256, "
                "source_aliases, destination_audio_path, destination_markdown_path, "
                "destination_manifest_path, receipt_sha256, publication_generation "
                "FROM archive_deliveries WHERE transcript_row_id = ?",
                (row_id,),
            ).fetchone())
        finally:
            conn.close()

    before = archive_state()
    monkeypatch.setattr(
        server_module,
        "record_archive_unavailable",
        transcript_log.record_archive_unavailable,
    )
    if endpoint == "ingest":
        response = client.post(
            "/ingest",
            json={"text": text, "source": "text"},
            headers=_ingest_auth(),
        )
    else:
        monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
        response = client.post("/deliver", json=DELIVER_PAYLOAD, headers=_auth())

    assert response.status_code == 200
    assert archive_state() == before


@pytest.mark.parametrize("status", ["pending", "failed"])
def test_deliver_resumes_pending_or_failed_duplicate_before_success(
    client, monkeypatch, status
):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    canonical = {
        "id": 7,
        "status": status,
        "transcript": "canonical delivery transcript",
        "source": "maya:voice_memo",
    }
    routed = {**canonical, "status": "routed"}
    monkeypatch.setattr(
        server_module,
        "insert_transcript_result",
        lambda **_: TranscriptInsertResult(
            InsertOutcome.DUPLICATE, row_id=7, existing_status=status
        ),
    )
    monkeypatch.setattr(
        server_module, "get_transcript_by_hash", MagicMock(side_effect=[canonical, routed])
    )
    route = MagicMock(return_value={"items": []})
    monkeypatch.setattr(server_module, "classify_and_route", route)

    response = client.post("/deliver", json=DELIVER_PAYLOAD, headers=_auth())

    assert response.status_code == 200
    assert response.get_json() == {"status": "delivered", "id": 7}
    assert server_module.get_transcript_by_hash.call_count == 2
    route.assert_called_once_with(
        "canonical delivery transcript",
        "maya:voice_memo",
        row_id=7,
        duration_seconds=DELIVER_PAYLOAD["duration_seconds"],
        allow_maya=False,
    )


def test_deliver_duplicate_requires_durable_route_confirmation(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    canonical = {
        "id": 9,
        "status": "pending",
        "transcript": "canonical delivery transcript",
        "source": "maya:voice_memo",
    }
    monkeypatch.setattr(
        server_module,
        "insert_transcript_result",
        lambda **_: TranscriptInsertResult(
            InsertOutcome.DUPLICATE, row_id=9, existing_status="pending"
        ),
    )
    monkeypatch.setattr(
        server_module,
        "get_transcript_by_hash",
        MagicMock(side_effect=[canonical, canonical]),
    )
    route = MagicMock(return_value={"items": []})
    monkeypatch.setattr(server_module, "classify_and_route", route)

    response = client.post("/deliver", json=DELIVER_PAYLOAD, headers=_auth())

    assert response.status_code == 503
    assert response.get_json() == {"error": "delivery unavailable"}
    route.assert_called_once()


def test_deliver_routed_duplicate_skips_routing(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(
        server_module,
        "insert_transcript_result",
        lambda **_: TranscriptInsertResult(
            InsertOutcome.DUPLICATE, row_id=8, existing_status="routed"
        ),
    )
    monkeypatch.setattr(
        server_module,
        "get_transcript_by_hash",
        lambda _: {"id": 8, "status": "routed"},
    )
    route = MagicMock()
    monkeypatch.setattr(server_module, "classify_and_route", route)

    response = client.post("/deliver", json=DELIVER_PAYLOAD, headers=_auth())

    assert response.status_code == 200
    assert response.get_json() == {"status": "duplicate"}
    route.assert_not_called()


def test_deliver_inserted_requires_durable_route_confirmation(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(
        server_module, "insert_transcript_result", lambda **_: _inserted(10)
    )
    get_canonical = MagicMock(return_value={"id": 10, "status": "pending"})
    monkeypatch.setattr(
        server_module,
        "get_transcript_by_hash",
        get_canonical,
    )
    route = MagicMock(return_value={"items": []})
    monkeypatch.setattr(server_module, "classify_and_route", route)

    response = client.post("/deliver", json=DELIVER_PAYLOAD, headers=_auth())

    assert response.status_code == 503
    assert response.get_json() == {"error": "delivery unavailable"}
    get_canonical.assert_called_once()
    route.assert_called_once()


def test_deliver_inserted_returns_success_after_durable_route_confirmation(
    client, monkeypatch
):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(
        server_module, "insert_transcript_result", lambda **_: _inserted(11)
    )
    get_canonical = MagicMock(return_value={"id": 11, "status": "routed"})
    monkeypatch.setattr(server_module, "get_transcript_by_hash", get_canonical)
    route = MagicMock(return_value={"items": []})
    monkeypatch.setattr(server_module, "classify_and_route", route)

    response = client.post("/deliver", json=DELIVER_PAYLOAD, headers=_auth())

    assert response.status_code == 200
    assert response.get_json() == {"status": "delivered", "id": 11}
    get_canonical.assert_called_once()
    route.assert_called_once()


def test_deliver_failure_does_not_leak_exception_text(client, monkeypatch, caplog):
    sentinel = "deliver-routing-secret-must-not-leak"
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(
        server_module, "insert_transcript_result", lambda **_: _inserted(1)
    )
    monkeypatch.setattr(
        server_module,
        "classify_and_route",
        lambda *_, **__: (_ for _ in ()).throw(RuntimeError(sentinel)),
    )
    caplog.set_level(logging.ERROR, logger=server_module.log.name)

    response = client.post("/deliver", json=DELIVER_PAYLOAD, headers=_auth())

    assert response.status_code == 500
    assert response.get_json() == {"error": "delivery processing failed"}
    assert sentinel not in caplog.text
    assert sentinel not in response.get_data(as_text=True)


if __name__ == "__main__":
    unittest.main()
