#!/usr/bin/env python3
"""Durably deliver persisted Penny transcripts to Maya's v2 intake."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import requests

from config import get_config
from transcript_log import (
    build_maya_v2_envelope,
    get_pending_maya_deliveries,
    mark_maya_delivery_failed,
    mark_maya_delivery_sent,
)

log = logging.getLogger(__name__)
cfg = get_config()

MAYA_DELIVERY_TIMEOUT_SECONDS = 10
_TRANSIENT_HTTP_STATUSES = frozenset({408, 425, 429})
_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "transcript_id",
        "transcript_sha256",
        "drop_id",
        "durable_acknowledged_at",
        "duplicate",
    }
)


def _is_transient_status(status_code: int) -> bool:
    return status_code in _TRANSIENT_HTTP_STATUSES or status_code >= 500


def _validated_drop_id(
    receipt: Any,
    envelope: dict[str, object],
) -> str:
    if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_FIELDS:
        raise ValueError("Maya receipt has an invalid shape")
    if receipt["schema_version"] != "penny-maya.v2":
        raise ValueError("Maya receipt has an invalid schema version")
    if receipt["transcript_id"] != envelope["transcript_id"]:
        raise ValueError("Maya receipt transcript ID conflicts with the request")
    if receipt["transcript_sha256"] != envelope["transcript_sha256"]:
        raise ValueError("Maya receipt transcript hash conflicts with the request")
    if type(receipt["duplicate"]) is not bool:
        raise ValueError("Maya receipt duplicate marker is invalid")

    drop_id = receipt["drop_id"]
    if not isinstance(drop_id, str) or not drop_id.strip():
        raise ValueError("Maya receipt Drop ID is invalid")

    acknowledged_at = receipt["durable_acknowledged_at"]
    if not isinstance(acknowledged_at, str):
        raise ValueError("Maya receipt acknowledgement time is invalid")
    try:
        parsed_acknowledgement = datetime.fromisoformat(
            acknowledged_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("Maya receipt acknowledgement time is invalid") from exc
    if parsed_acknowledgement.tzinfo is None:
        raise ValueError("Maya receipt acknowledgement time must include a timezone")

    return drop_id


def process_pending_maya_deliveries(limit: int = 20) -> int:
    """Send eligible persisted envelopes and record validated durable receipts."""
    maya_url = cfg.maya.transcript_url.strip()
    maya_token = cfg.maya.ingest_token.strip()
    if not maya_url or not maya_token:
        return 0

    delivered = 0
    for delivery in get_pending_maya_deliveries(limit=limit):
        row_id = int(delivery["id"])
        try:
            envelope = build_maya_v2_envelope(row_id)
            request_body = json.dumps(
                envelope,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except Exception as exc:
            log.error(
                "Maya envelope validation failed for transcript=%s: %s",
                row_id,
                type(exc).__name__,
            )
            mark_maya_delivery_failed(row_id, "delivery_error")
            continue

        try:
            response = requests.post(
                maya_url,
                data=request_body,
                headers={
                    "Authorization": f"Bearer {maya_token}",
                    "Content-Type": "application/json",
                },
                timeout=MAYA_DELIVERY_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            log.warning(
                "Maya delivery remains pending for transcript=%s after %s",
                row_id,
                type(exc).__name__,
            )
            continue

        if _is_transient_status(response.status_code):
            log.warning(
                "Maya delivery remains pending for transcript=%s after HTTP %s",
                row_id,
                response.status_code,
            )
            continue
        if response.status_code != 200:
            mark_maya_delivery_failed(row_id, "provider_error:HTTPError")
            continue

        try:
            receipt = response.json()
            drop_id = _validated_drop_id(receipt, envelope)
            mark_maya_delivery_sent(row_id, drop_id)
        except Exception as exc:
            log.error(
                "Maya receipt rejected for transcript=%s: %s",
                row_id,
                type(exc).__name__,
            )
            mark_maya_delivery_failed(
                row_id,
                "acknowledgement_error:ReceiptConflict",
            )
            continue

        delivered += 1
    return delivered
