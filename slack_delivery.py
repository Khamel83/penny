#!/usr/bin/env python3
"""Durable Slack delivery for Penny voice memo transcripts."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import uuid

try:
    import requests
except ImportError:

    class _UrllibResponse:
        def __init__(self, status_code: int, body: bytes) -> None:
            self.status_code = status_code
            self._body = body

        def json(self) -> dict:
            return json.loads(self._body.decode("utf-8"))

    class _RequestsCompat:
        @staticmethod
        def post(
            url: str,
            *,
            json: dict,
            headers: dict,
            timeout: int,
        ) -> _UrllibResponse:
            body = json_module.dumps(json).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _UrllibResponse(resp.status, resp.read())

    json_module = json
    requests = _RequestsCompat()

from transcript_log import (
    SLACK_API_ERROR_CODES,
    get_pending_slack_deliveries,
    mark_slack_delivery_failed,
    mark_slack_delivery_sent,
)

log = logging.getLogger(__name__)

SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
SLACK_DELIVERY_NAMESPACE = uuid.UUID("bc6feeb4-d1e8-4e84-8483-699c02146a2f")


class SlackAPIError(RuntimeError):
    """A controlled error code returned by Slack."""


class SlackConfigurationError(RuntimeError):
    """A local Slack delivery configuration error."""


def _slack_bot_token() -> str:
    return os.environ.get("PENNY_SLACK_BOT_TOKEN") or os.environ.get(
        "SLACK_BOT_TOKEN", ""
    )


def _delivery_client_msg_id(delivery_id: int) -> str:
    return str(
        uuid.uuid5(
            SLACK_DELIVERY_NAMESPACE,
            f"penny:slack-delivery:{delivery_id}",
        )
    )


def _safe_exception_class(exc: Exception) -> str:
    class_name = type(exc).__name__
    if (
        class_name
        and len(class_name) <= 48
        and class_name[0].isalpha()
        and all(character.isalnum() or character == "_" for character in class_name)
    ):
        return class_name
    return "Exception"


def _classified_error(category: str, exc: Exception) -> str:
    return f"{category}:{_safe_exception_class(exc)}"


def _safe_slack_error_code(value: object) -> str:
    if isinstance(value, str) and value in SLACK_API_ERROR_CODES:
        return value
    return "slack_api_error"


def _post_to_slack(
    channel_id: str,
    message_text: str,
    client_msg_id: str,
) -> None:
    token = _slack_bot_token()
    if not token:
        raise SlackConfigurationError

    resp = requests.post(
        SLACK_POST_MESSAGE_URL,
        json={
            "channel": channel_id,
            "client_msg_id": client_msg_id,
            "text": message_text,
            "unfurl_links": False,
            "unfurl_media": False,
        },
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        timeout=10,
    )
    data = resp.json()
    if not data.get("ok"):
        raise SlackAPIError(_safe_slack_error_code(data.get("error")))


def _record_delivery_failure(delivery_id: int, safe_error: str) -> None:
    try:
        mark_slack_delivery_failed(delivery_id, safe_error)
    except Exception as ack_exc:
        log.error(
            "Failed to record Slack delivery failure id=%s: %s",
            delivery_id,
            _classified_error("acknowledgement_error", ack_exc),
        )
    log.warning("Slack delivery failed id=%s: %s", delivery_id, safe_error)


def process_pending_slack_deliveries(limit: int = 20) -> int:
    delivered = 0
    for row in get_pending_slack_deliveries(limit=limit):
        delivery_id = int(row["id"])
        try:
            _post_to_slack(
                str(row["channel_id"]),
                str(row["message_text"]),
                _delivery_client_msg_id(delivery_id),
            )
        except SlackAPIError as exc:
            _record_delivery_failure(delivery_id, str(exc))
            continue
        except SlackConfigurationError:
            _record_delivery_failure(delivery_id, "configuration_error")
            continue
        except Exception as exc:
            _record_delivery_failure(
                delivery_id,
                _classified_error("provider_error", exc),
            )
            continue

        try:
            mark_slack_delivery_sent(delivery_id)
        except Exception as exc:
            _record_delivery_failure(
                delivery_id,
                _classified_error("acknowledgement_error", exc),
            )
            continue

        delivered += 1
    return delivered
