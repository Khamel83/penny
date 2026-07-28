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
    mark_maya_delivery_retryable,
    mark_maya_delivery_sent,
)

log = logging.getLogger(__name__)
cfg = get_config()

MAYA_RETRY_BASE_SECONDS = 30
MAYA_RETRY_MAX_SECONDS = 1800
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


class InvalidReceiptError(ValueError):
    """Maya returned a response that is not a valid v2 receipt."""


class ReceiptConflictError(ValueError):
    """Maya's receipt conflicts with the submitted persisted identity."""


def _is_transient_status(status_code: int) -> bool:
    return status_code in _TRANSIENT_HTTP_STATUSES or status_code >= 500


def _retry_delay_seconds(delivery: dict[str, Any]) -> int:
    attempt = max(1, int(delivery.get("maya_delivery_attempt_count") or 0) + 1)
    exponent = min(attempt - 1, 6)
    return min(MAYA_RETRY_BASE_SECONDS * (2**exponent), MAYA_RETRY_MAX_SECONDS)


def _schedule_retry(
    row_id: int,
    delivery: dict[str, Any],
    error_message: str,
) -> None:
    try:
        mark_maya_delivery_retryable(
            row_id,
            error_message,
            retry_after_seconds=_retry_delay_seconds(delivery),
        )
    except Exception as exc:
        log.error(
            "Maya retry state could not be persisted for transcript=%s: %s",
            row_id,
            type(exc).__name__,
        )


def _record_invalid_receipt(row_id: int, error_message: str) -> None:
    try:
        mark_maya_delivery_failed(row_id, error_message)
    except Exception as exc:
        log.error(
            "Maya invalid-receipt state could not be persisted for transcript=%s: %s",
            row_id,
            type(exc).__name__,
        )


def _validated_drop_id(
    receipt: Any,
    envelope: dict[str, object],
) -> str:
    if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_FIELDS:
        raise InvalidReceiptError("Maya receipt has an invalid shape")
    if receipt["schema_version"] != "penny-maya.v2":
        raise InvalidReceiptError("Maya receipt has an invalid schema version")
    if receipt["transcript_id"] != envelope["transcript_id"]:
        raise ReceiptConflictError(
            "Maya receipt transcript ID conflicts with the request"
        )
    if receipt["transcript_sha256"] != envelope["transcript_sha256"]:
        raise ReceiptConflictError(
            "Maya receipt transcript hash conflicts with the request"
        )
    if type(receipt["duplicate"]) is not bool:
        raise InvalidReceiptError("Maya receipt duplicate marker is invalid")

    drop_id = receipt["drop_id"]
    if not isinstance(drop_id, str) or not drop_id.strip():
        raise InvalidReceiptError("Maya receipt Drop ID is invalid")

    acknowledged_at = receipt["durable_acknowledged_at"]
    if not isinstance(acknowledged_at, str):
        raise InvalidReceiptError("Maya receipt acknowledgement time is invalid")
    try:
        parsed_acknowledgement = datetime.fromisoformat(
            acknowledged_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise InvalidReceiptError(
            "Maya receipt acknowledgement time is invalid"
        ) from exc
    if parsed_acknowledgement.tzinfo is None:
        raise InvalidReceiptError(
            "Maya receipt acknowledgement time must include a timezone"
        )

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
                timeout=cfg.maya.delivery_timeout_seconds,
            )
        except requests.RequestException as exc:
            log.warning(
                "Maya delivery remains pending for transcript=%s after %s",
                row_id,
                type(exc).__name__,
            )
            _schedule_retry(row_id, delivery, "delivery_error")
            continue

        if _is_transient_status(response.status_code):
            log.warning(
                "Maya delivery remains pending for transcript=%s after HTTP %s",
                row_id,
                response.status_code,
            )
            _schedule_retry(row_id, delivery, "provider_error:TransientHTTP")
            continue
        if response.status_code != 200:
            mark_maya_delivery_failed(row_id, "provider_error:HTTPError")
            continue

        try:
            receipt = response.json()
        except Exception as exc:
            log.error(
                "Maya receipt JSON rejected for transcript=%s: %s",
                row_id,
                type(exc).__name__,
            )
            _record_invalid_receipt(
                row_id,
                "acknowledgement_error:InvalidReceipt",
            )
            continue

        try:
            drop_id = _validated_drop_id(receipt, envelope)
        except ReceiptConflictError as exc:
            log.error(
                "Maya receipt conflicts for transcript=%s: %s",
                row_id,
                type(exc).__name__,
            )
            _record_invalid_receipt(
                row_id,
                "acknowledgement_error:ReceiptConflict",
            )
            continue
        except InvalidReceiptError as exc:
            log.error(
                "Maya receipt rejected for transcript=%s: %s",
                row_id,
                type(exc).__name__,
            )
            _record_invalid_receipt(
                row_id,
                "acknowledgement_error:InvalidReceipt",
            )
            continue

        try:
            mark_maya_delivery_sent(row_id, drop_id)
        except Exception as exc:
            log.error(
                "Maya receipt persistence failed for transcript=%s: %s",
                row_id,
                type(exc).__name__,
            )
            continue

        delivered += 1
    return delivered
