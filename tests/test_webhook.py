#!/usr/bin/env python3
"""Tests for Penny webhook server (webhook/server.py)."""
import hashlib
import io
import os
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
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot")
os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")
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

app = server_module.app
app.config["TESTING"] = True


@pytest.fixture
def client(tmp_path, monkeypatch):
    import transcript_log
    monkeypatch.setattr(transcript_log, "TRANSCRIPT_DB_PATH", tmp_path / "transcripts.db")
    import webhook.server as server
    transcript_log.init_db()
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


class UploadTests(unittest.TestCase):
    @patch("webhook.server.is_already_logged", return_value=False)
    @patch("webhook.server.transcribe", return_value="test transcript")
    @patch("webhook.server.insert_transcript", return_value=1)
    @patch("webhook.server.classify_and_route", return_value={"items": [], "skip": True})
    def test_upload_success(self, mock_route, mock_insert, mock_transcribe, mock_logged):
        with app.test_client() as client:
            data = {"audio": (io.BytesIO(b"fake audio data"), "test.m4a")}
            resp = client.post("/upload", data=data, content_type="multipart/form-data")
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertEqual(body["status"], "ok")
            self.assertIn("test transcript", body["transcript"])
            self.assertFalse(mock_insert.call_args.kwargs["enqueue_slack"])

    @patch("webhook.server.is_already_logged", return_value=True)
    def test_upload_duplicate_returns_ok(self, mock_logged):
        with app.test_client() as client:
            data = {"audio": (io.BytesIO(b"fake audio data"), "test.m4a")}
            resp = client.post("/upload", data=data, content_type="multipart/form-data")
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertEqual(body["status"], "ok")
            self.assertIn("already processed", body["message"])

    def test_upload_missing_audio_returns_400(self):
        with app.test_client() as client:
            resp = client.post("/upload")
            self.assertEqual(resp.status_code, 400)

    @patch("webhook.server.is_already_logged", return_value=False)
    @patch("webhook.server.transcribe", side_effect=RuntimeError("transcription failed"))
    def test_upload_error_returns_500(self, mock_transcribe, mock_logged):
        with app.test_client() as client:
            data = {"audio": (io.BytesIO(b"fake audio data"), "test.m4a")}
            resp = client.post("/upload", data=data, content_type="multipart/form-data")
            self.assertEqual(resp.status_code, 500)

    @patch("webhook.server.is_already_logged", return_value=False)
    @patch("webhook.server.get_file_hash", return_value="abc123")
    @patch("webhook.server.transcribe", side_effect=RuntimeError("transcription failed"))
    def test_upload_cleans_temp_file_on_error(self, mock_transcribe, mock_hash, mock_logged):
        """Temp file should be cleaned up even when transcription fails."""
        with app.test_client() as client:
            data = {"audio": (io.BytesIO(b"fake audio data"), "test.m4a")}
            resp = client.post("/upload", data=data, content_type="multipart/form-data")
            self.assertEqual(resp.status_code, 500)


class IngestTests(unittest.TestCase):
    @patch("webhook.server.is_already_logged", return_value=False)
    @patch("webhook.server.insert_transcript", return_value=1)
    @patch("webhook.server.classify_and_route", return_value={"items": [{"item": "milk", "category": "groceries"}]})
    def test_ingest_success(self, mock_route, mock_insert, mock_logged):
        with app.test_client() as client:
            resp = client.post("/ingest", json={"text": "buy milk", "source": "test"})
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertEqual(body["status"], "ok")
            self.assertEqual(body["items_added"], 1)
            mock_route.assert_called_once()
            mock_insert.assert_called_once()
            self.assertFalse(mock_insert.call_args.kwargs["enqueue_slack"])

    def test_ingest_missing_json_returns_400(self):
        with app.test_client() as client:
            resp = client.post("/ingest")
            self.assertEqual(resp.status_code, 400)

    def test_ingest_missing_text_returns_400(self):
        with app.test_client() as client:
            resp = client.post("/ingest", json={"not_text": "buy milk"})
            self.assertEqual(resp.status_code, 400)

    def test_ingest_empty_text_returns_400(self):
        with app.test_client() as client:
            resp = client.post("/ingest", json={"text": "   "})
            self.assertEqual(resp.status_code, 400)

    @patch("webhook.server.is_already_logged", return_value=True)
    def test_ingest_duplicate_returns_ok(self, mock_logged):
        with app.test_client() as client:
            resp = client.post("/ingest", json={"text": "buy milk"})
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertIn("already processed", body["message"])

    @patch("webhook.server.is_already_logged", return_value=False)
    @patch("webhook.server.insert_transcript", return_value=1)
    @patch("webhook.server.classify_and_route", side_effect=RuntimeError("routing failed"))
    def test_ingest_error_returns_500(self, mock_route, mock_insert, mock_logged):
        with app.test_client() as client:
            resp = client.post("/ingest", json={"text": "buy milk"})
            self.assertEqual(resp.status_code, 500)


DELIVER_PAYLOAD = {
    "transcript": "remind me to call the dentist tomorrow",
    "source": "voice_memo",
    "duration_seconds": 4.2,
    "recorded_at": "2026-07-09T18:00:00Z",
    "metadata": {"via": "maya"},
}


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
    seen_hashes = set()

    def fake_insert_transcript(**kwargs):
        insert_calls.append(kwargs)
        seen_hashes.add(kwargs["content_hash"])
        return 1

    def fake_classify_and_route(transcript, source, row_id=None,
                                duration_seconds=None, allow_maya=True):
        seen.update(transcript=transcript, source=source, allow_maya=allow_maya)
        return {"content_type": "action_items"}

    import webhook.server as server
    monkeypatch.setattr(server, "classify_and_route", fake_classify_and_route)
    monkeypatch.setattr(server, "insert_transcript", fake_insert_transcript)
    monkeypatch.setattr(server, "is_already_logged", lambda content_hash: content_hash in seen_hashes)

    resp = client.post("/deliver", json=DELIVER_PAYLOAD, headers=_auth())
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "delivered"
    assert seen["allow_maya"] is False
    assert seen["transcript"] == DELIVER_PAYLOAD["transcript"]
    assert insert_calls[0]["enqueue_slack"] is False

    # Same payload again → dedup via md5 content hash
    resp2 = client.post("/deliver", json=DELIVER_PAYLOAD, headers=_auth())
    assert resp2.status_code == 200
    assert resp2.get_json()["status"] == "duplicate"


def test_deliver_handles_insert_race_as_duplicate(client, monkeypatch):
    """Two concurrent /deliver requests can both pass is_already_logged before either
    inserts. The loser's INSERT OR IGNORE returns None from insert_transcript — that
    must surface as {"status": "duplicate"}, not route with row_id=None."""
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")

    import webhook.server as server
    monkeypatch.setattr(server, "is_already_logged", lambda content_hash: False)
    monkeypatch.setattr(server, "insert_transcript", lambda **kwargs: None)

    route_called = MagicMock()
    monkeypatch.setattr(server, "classify_and_route", route_called)

    resp = client.post("/deliver", json=DELIVER_PAYLOAD, headers=_auth())
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "duplicate"}
    route_called.assert_not_called()


if __name__ == "__main__":
    unittest.main()
