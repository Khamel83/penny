#!/usr/bin/env python3
"""Durable Slack delivery for Penny voice memo transcripts."""

from __future__ import annotations

import json
import logging
import os
import urllib.request

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
    get_pending_slack_deliveries,
    mark_slack_delivery_failed,
    mark_slack_delivery_sent,
)

log = logging.getLogger(__name__)

SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"


def _slack_bot_token() -> str:
    return os.environ.get("PENNY_SLACK_BOT_TOKEN") or os.environ.get(
        "SLACK_BOT_TOKEN", ""
    )


def _post_to_slack(channel_id: str, message_text: str) -> None:
    token = _slack_bot_token()
    if not token:
        raise RuntimeError("PENNY_SLACK_BOT_TOKEN/SLACK_BOT_TOKEN is not configured")

    resp = requests.post(
        SLACK_POST_MESSAGE_URL,
        json={
            "channel": channel_id,
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
        raise RuntimeError(str(data.get("error") or f"HTTP {resp.status_code}"))


def process_pending_slack_deliveries(limit: int = 20) -> int:
    delivered = 0
    for row in get_pending_slack_deliveries(limit=limit):
        delivery_id = int(row["id"])
        try:
            _post_to_slack(str(row["channel_id"]), str(row["message_text"]))
            mark_slack_delivery_sent(delivery_id)
            delivered += 1
        except Exception as exc:
            mark_slack_delivery_failed(delivery_id, str(exc))
            log.warning("Slack delivery failed id=%s: %s", delivery_id, exc)
    return delivered
