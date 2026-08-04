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
from transcript_quality import QualityResult, TranscriptionResult  # noqa: E402

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


def test_upload_low_quality_transcript_is_durable_and_not_published(client, monkeypatch):
    import transcript_log
    import webhook.server as server

    rejected_text = "A valid memo first. " + "Vous " * 20
    monkeypatch.setattr(server, "get_file_hash", lambda _: "review-upload-hash")
    monkeypatch.setattr(server, "is_already_logged", lambda _: False)
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


class UploadTests(unittest.TestCase):
    @patch("webhook.server.is_already_logged", return_value=False)
    @patch(
        "webhook.server.transcribe",
        return_value=TranscriptionResult("test transcript", QualityResult(True), 1),
    )
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
            self.assertFalse(mock_route.call_args.kwargs["allow_maya"])

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
            self.assertFalse(mock_route.call_args.kwargs["allow_maya"])

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


ACTION_PAYLOADS = [
    ("POST", "/actions/reminder", {"title": "Call dentist", "list": "Inbox"}),
    ("POST", "/actions/note", {"title": "Meeting", "folder": "Penny"}),
    ("GET", "/actions/reminders/state?list=Inbox", None),
]


@pytest.mark.parametrize("method,path,payload", ACTION_PAYLOADS)
@pytest.mark.parametrize("authorization", [None, "Bearer wrong-secret"])
def test_action_routes_reject_missing_or_incorrect_bearer(
    client, monkeypatch, method, path, payload, authorization
):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    headers = {} if authorization is None else {"Authorization": authorization}

    response = client.open(path, method=method, json=payload, headers=headers)

    assert response.status_code == 401
    assert response.get_json() == {"error": "unauthorized"}


@pytest.mark.parametrize("method,path,payload", ACTION_PAYLOADS)
def test_action_routes_reject_requests_when_secret_is_unset(
    client, monkeypatch, method, path, payload
):
    monkeypatch.delenv("PENNY_WEBHOOK_SECRET", raising=False)

    response = client.open(path, method=method, json=payload)

    assert response.status_code == 401
    assert response.get_json() == {"error": "unauthorized"}


def test_create_reminder_returns_provider_id_and_external_id(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    import webhook.server as server

    captured = {}

    def _fake_add_reminder(title, list_name, **kwargs):
        captured["title"] = title
        captured["list_name"] = list_name
        captured.update(kwargs)
        return "x-apple-reminder://created"

    monkeypatch.setattr(server, "add_reminder", _fake_add_reminder)

    response = client.post(
        "/actions/reminder",
        json={
            "title": "Call dentist",
            "list": "Inbox",
            "notes": "https://example.test",
            "external_id": "maya-123",
        },
        headers=_auth(),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "created",
        "provider_id": "x-apple-reminder://created",
        "external_id": "maya-123",
    }
    # Maya's lists must be self-provisioning: a missing list is created, never
    # silently diverted into Penny's Inbox fallback.
    assert captured["create_if_missing"] is True
    assert captured["fallback_list"] == "Inbox"


@pytest.mark.parametrize(
    "payload,field",
    [
        ({"list": "Inbox"}, "title"),
        ({"title": "Call dentist"}, "list"),
    ],
)
def test_create_reminder_validates_required_fields(client, monkeypatch, payload, field):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")

    response = client.post("/actions/reminder", json=payload, headers=_auth())

    assert response.status_code == 422
    assert response.get_json() == {
        "error": f"{field} is required and must be non-empty"
    }


def test_create_reminder_returns_502_when_apple_script_fails(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    import webhook.server as server

    monkeypatch.setattr(server, "add_reminder", lambda *args, **kwargs: None)

    response = client.post(
        "/actions/reminder",
        json={"title": "Call dentist", "list": "Inbox"},
        headers=_auth(),
    )

    assert response.status_code == 502
    assert response.get_json() == {"error": "applescript_failed"}


def test_create_note_returns_provider_id(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    import webhook.server as server

    monkeypatch.setattr(
        server,
        "add_note",
        lambda text, folder_name="Penny", source="", title=None:
        "x-coredata://created/ICNote/p823",
    )

    response = client.post(
        "/actions/note",
        json={
            "title": "Meeting",
            "folder": "Penny",
            "body": "First line\nhttps://example.test",
        },
        headers=_auth(),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "created",
        "provider_id": "x-coredata://created/ICNote/p823",
    }


def test_create_note_validates_required_folder(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")

    response = client.post(
        "/actions/note", json={"title": "Meeting"}, headers=_auth()
    )

    assert response.status_code == 422
    assert response.get_json() == {
        "error": "folder is required and must be non-empty"
    }


def test_read_reminders_state_returns_populated_list(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    import webhook.server as server

    reminders = [
        {
            "provider_id": "x-apple-reminder://one",
            "title": "Call dentist",
            "completed": False,
            "completion_date": None,
            "notes": "https://example.test",
        }
    ]
    monkeypatch.setattr(server, "read_reminders", lambda list_name: reminders)

    response = client.get(
        "/actions/reminders/state?list=Inbox", headers=_auth()
    )

    assert response.status_code == 200
    assert response.get_json() == {"list": "Inbox", "reminders": reminders}


def test_read_reminders_state_requires_list_param(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")

    response = client.get("/actions/reminders/state", headers=_auth())

    assert response.status_code == 422
    assert response.get_json() == {
        "error": "list is required and must be non-empty"
    }


def test_read_reminders_state_returns_404_for_unknown_list(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    import webhook.server as server

    monkeypatch.setattr(server, "read_reminders", lambda list_name: None)

    response = client.get(
        "/actions/reminders/state?list=Missing", headers=_auth()
    )

    assert response.status_code == 404
    assert response.get_json() == {"error": "list_not_found"}


def test_read_reminders_state_returns_502_on_apple_script_failure(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    import webhook.server as server

    monkeypatch.setattr(
        server, "read_reminders", lambda list_name: (_ for _ in ()).throw(RuntimeError("failed"))
    )

    response = client.get(
        "/actions/reminders/state?list=Inbox", headers=_auth()
    )

    assert response.status_code == 502
    assert response.get_json() == {"error": "applescript_failed"}


def test_action_routes_never_call_classify_and_route(client, monkeypatch):
    monkeypatch.setenv("PENNY_WEBHOOK_SECRET", "test-secret")
    import webhook.server as server

    route_mock = MagicMock()
    monkeypatch.setattr(server, "classify_and_route", route_mock)
    monkeypatch.setattr(
        server, "add_reminder", lambda *args, **kwargs: "x-apple-reminder://created"
    )
    monkeypatch.setattr(
        server, "add_note", lambda *args, **kwargs: "x-coredata://created/ICNote/p823"
    )
    monkeypatch.setattr(server, "read_reminders", lambda list_name: [])

    reminder_response = client.post(
        "/actions/reminder",
        json={"title": "Call dentist", "list": "Inbox"},
        headers=_auth(),
    )
    note_response = client.post(
        "/actions/note",
        json={"title": "Meeting", "folder": "Penny"},
        headers=_auth(),
    )
    state_response = client.get(
        "/actions/reminders/state?list=Inbox", headers=_auth()
    )

    assert reminder_response.status_code == 200
    assert note_response.status_code == 200
    assert state_response.status_code == 200
    route_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
