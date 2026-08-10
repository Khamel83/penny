#!/usr/bin/env python3
"""Durably deliver persisted Penny transcripts to Maya's v2 intake."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from typing import Any

import requests

from config import get_config
from transcript_log import (
    build_maya_v2_envelope,
    claim_maya_delivery,
    get_pending_maya_deliveries,
    mark_maya_delivery_failed,
    mark_maya_delivery_retryable,
    mark_maya_delivery_sent,
    release_maya_delivery_claim,
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
    claim: dict[str, str],
) -> None:
    try:
        mark_maya_delivery_retryable(
            row_id,
            error_message,
            retry_after_seconds=_retry_delay_seconds(delivery),
            max_attempts=getattr(cfg.maya, "max_attempts", 20),
            max_age_days=getattr(cfg.maya, "max_age_days", 7),
            claim_token=claim["maya_claim_token"],
            claim_owner=claim["maya_claim_owner"],
        )
    except Exception as exc:
        log.error(
            "Maya retry state could not be persisted for transcript=%s: %s",
            row_id,
            type(exc).__name__,
        )


def _record_invalid_receipt(
    row_id: int,
    error_message: str,
    claim: dict[str, str],
) -> None:
    try:
        mark_maya_delivery_failed(
            row_id,
            error_message,
            claim_token=claim["maya_claim_token"],
            claim_owner=claim["maya_claim_owner"],
        )
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


def _mark_permanent_failure(
    row_id: int,
    error_code: str,
    claim: dict[str, str],
) -> None:
    try:
        mark_maya_delivery_failed(
            row_id,
            error_code,
            claim_token=claim["maya_claim_token"],
            claim_owner=claim["maya_claim_owner"],
        )
    except Exception as exc:
        log.error(
            "Maya failure state could not be persisted for transcript=%s: %s",
            row_id,
            type(exc).__name__,
        )


def _process_one_maya_delivery(
    delivery: dict[str, Any],
    *,
    maya_url: str,
    maya_token: str,
    claim: dict[str, str],
) -> bool:
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
        _mark_permanent_failure(row_id, "delivery_error", claim)
        return False

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
        _schedule_retry(row_id, delivery, "delivery_error", claim)
        return False

    if _is_transient_status(response.status_code):
        log.warning(
            "Maya delivery remains pending for transcript=%s after HTTP %s",
            row_id,
            response.status_code,
        )
        _schedule_retry(row_id, delivery, "provider_error:TransientHTTP", claim)
        return False
    if response.status_code != 200:
        _mark_permanent_failure(row_id, "provider_error:HTTPError", claim)
        return False

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
            claim,
        )
        return False

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
            claim,
        )
        return False
    except InvalidReceiptError as exc:
        log.error(
            "Maya receipt rejected for transcript=%s: %s",
            row_id,
            type(exc).__name__,
        )
        _record_invalid_receipt(
            row_id,
            "acknowledgement_error:InvalidReceipt",
            claim,
        )
        return False

    try:
        mark_maya_delivery_sent(
            row_id,
            drop_id,
            claim_token=claim["maya_claim_token"],
            claim_owner=claim["maya_claim_owner"],
        )
    except Exception as exc:
        release_maya_delivery_claim(
            row_id,
            claim["maya_claim_token"],
            claim["maya_claim_owner"],
        )
        log.error(
            "Maya receipt persistence failed for transcript=%s: %s",
            row_id,
            type(exc).__name__,
        )
        return False

    return True


def process_pending_maya_deliveries(limit: int = 20) -> int:
    """Send bounded persisted envelopes and record validated durable receipts."""
    maya_url = cfg.maya.transcript_url.strip()
    maya_token = cfg.maya.ingest_token.strip()
    if not maya_url or not maya_token:
        return 0

    delivered = 0
    max_attempts = getattr(cfg.maya, "max_attempts", 20)
    max_age_days = getattr(cfg.maya, "max_age_days", 7)
    worker_owner = f"penny-maya-worker:{os.getpid()}:{threading.get_ident()}"
    for delivery in get_pending_maya_deliveries(
        limit=limit,
        max_attempts=max_attempts,
        max_age_days=max_age_days,
    ):
        try:
            row_id = int(delivery["id"])
            claim = claim_maya_delivery(row_id, worker_owner)
        except Exception as exc:
            log.error(
                "Maya delivery claim failed for transcript=%s: %s",
                delivery.get("id", "unknown"),
                type(exc).__name__,
            )
            continue
        if claim is None:
            continue
        try:
            if _process_one_maya_delivery(
                delivery,
                maya_url=maya_url,
                maya_token=maya_token,
                claim=claim,
            ):
                delivered += 1
        except Exception as exc:
            # One malformed/corrupt row must not starve later captures.
            row_id = delivery.get("id", "unknown")
            log.error(
                "Maya delivery row failed for transcript=%s: %s",
                row_id,
                type(exc).__name__,
            )
    return delivered
