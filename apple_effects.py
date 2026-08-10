#!/usr/bin/env python3
"""Idempotent, receipt-backed Apple Notes and Reminders effects."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable

import reminders
import transcript_log

log = logging.getLogger(__name__)

_SAFE_ERROR_CODES = frozenset(
    {
        "active_claim", "canonical_id_required", "database_unavailable",
        "effect_key_conflict", "effect_not_found", "invalid_effect",
        "marker_conflict", "permission_denied", "provider_conflict",
        "provider_error", "timeout_uncertain",
    }
)
_TERMINAL_ERROR_CODES = frozenset(
    {
        "effect_key_conflict", "invalid_effect", "marker_conflict",
        "permission_denied", "provider_conflict",
    }
)


class AppleEffectError(RuntimeError):
    """Safe effect failure; the message is always a machine error code."""

    def __init__(self, code: str):
        candidate = str(code or "").strip().lower()
        self.code = candidate if candidate in _SAFE_ERROR_CODES else "provider_error"
        super().__init__(self.code)


@dataclass(frozen=True)
class AppleEffectReceipt:
    effect_key: str
    effect_type: str
    provider_id: str | None
    state: str
    reconciled: bool = False
    actual_target: str | None = None
    transcript_id: int | None = None
    error_code: str | None = None
    attempt_count: int = 0


def _normalize_text(value: Any) -> str:
    return unicodedata.normalize(
        "NFC", str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    ).strip()


def normalized_payload_sha256(payload: Any) -> str:
    """Hash a stable UTF-8 payload representation, not provider text."""
    if isinstance(payload, dict):
        normalized: Any = {
            str(key): _normalize_text(value)
            for key, value in sorted(payload.items(), key=lambda item: str(item[0]))
        }
    else:
        normalized = _normalize_text(payload)
    if isinstance(normalized, str):
        encoded = normalized.encode("utf-8")
    else:
        encoded = json.dumps(
            normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def effect_key_for(
    transcript_id: int,
    effect_type: str,
    requested_target: str,
    fallback_target: str = "",
    payload_sha256: str | None = None,
    payload: Any | None = None,
) -> str:
    """Derive the complete effect identity from explicit canonical dimensions."""
    if not isinstance(transcript_id, int) or transcript_id <= 0:
        raise AppleEffectError("canonical_id_required")
    if effect_type not in {"note", "reminder"}:
        raise AppleEffectError("invalid_effect")
    requested = _normalize_text(requested_target)
    fallback = _normalize_text(fallback_target)
    if not requested:
        raise AppleEffectError("invalid_effect")
    payload_hash = payload_sha256 or normalized_payload_sha256(payload)
    if not isinstance(payload_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", payload_hash
    ):
        raise AppleEffectError("invalid_effect")
    material = "\0".join(
        [str(transcript_id), effect_type, requested, fallback, payload_hash]
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


compute_effect_key = effect_key_for
make_effect_key = effect_key_for


def _receipt(row: dict[str, Any] | None, *, key: str, effect_type: str) -> AppleEffectReceipt:
    if row is None:
        return AppleEffectReceipt(key, effect_type, None, "failed", error_code="effect_not_found")
    return AppleEffectReceipt(
        effect_key=str(row.get("effect_key") or key),
        effect_type=str(row.get("effect_type") or effect_type),
        provider_id=(str(row["provider_id"]) if row.get("provider_id") else None),
        state=str(row.get("state") or "failed"),
        reconciled=bool(row.get("reconciled", 0)),
        actual_target=(str(row["actual_target"]) if row.get("actual_target") else None),
        transcript_id=(int(row["transcript_id"]) if row.get("transcript_id") is not None else None),
        error_code=(str(row["last_error_code"]) if row.get("last_error_code") else None),
        attempt_count=int(row.get("attempt_count") or 0),
    )


def _error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    candidate = str(code or "").strip().lower()
    return candidate if candidate in _SAFE_ERROR_CODES else "provider_error"


def _mark_failed(key: str, code: str, owner: str | None) -> None:
    transcript_log.mark_apple_effect_failed(
        key,
        code,
        quarantine=code in _TERMINAL_ERROR_CODES,
        lease_owner=owner,
    )


def _provider_id_target(value: Any, default_target: str) -> tuple[str | None, str]:
    if isinstance(value, reminders.ProviderReceipt):
        return value.provider_id.strip() or None, value.actual_target or default_target
    if isinstance(value, dict):
        provider_id = str(
            value.get("provider_id") or value.get("id") or ""
        ).strip() or None
        actual = str(
            value.get("actual_target") or value.get("target") or default_target
        ).strip()
        return provider_id, actual
    if isinstance(value, (tuple, list)) and value:
        provider_id = str(value[0] or "").strip() or None
        actual = str(value[1] or default_target).strip() if len(value) > 1 else default_target
        return provider_id, actual
    provider_id = str(value or "").strip() or None
    return provider_id, default_target


def _match_ids(value: Any) -> list[tuple[str, str | None]]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    matches: list[tuple[str, str | None]] = []
    for entry in values:
        provider, actual = _provider_id_target(entry, "")
        if provider:
            matches.append((provider, actual or None))
    return matches


def _mark_uncertain(key: str, code: str, owner: str | None) -> None:
    try:
        transcript_log.mark_apple_effect_uncertain(key, code, lease_owner=owner)
    except Exception:
        log.error("Apple effect uncertainty could not be persisted")


def _ensure_effect(
    *,
    transcript_id: int | None,
    effect_type: str,
    text: str,
    requested_target: str,
    fallback_target: str,
    source: str = "",
    find: Callable[[], Any],
    create: Callable[[], Any],
) -> AppleEffectReceipt:
    if not isinstance(transcript_id, int) or transcript_id <= 0:
        raise AppleEffectError("canonical_id_required")
    payload_hash = normalized_payload_sha256(text)
    key = effect_key_for(
        transcript_id,
        effect_type,
        requested_target,
        fallback_target,
        payload_sha256=payload_hash,
    )
    claim = transcript_log.claim_apple_effect(
        effect_key=key,
        transcript_id=transcript_id,
        effect_type=effect_type,
        requested_target=_normalize_text(requested_target),
        fallback_target=_normalize_text(fallback_target),
        payload_sha256=payload_hash,
    )
    if not claim.get("claimable"):
        error = claim.get("error_code")
        if error and error not in {"active_claim"}:
            raise AppleEffectError(str(error))
        return _receipt(claim, key=key, effect_type=effect_type)

    owner = claim.get("lease_owner")
    try:
        # Exact marker query is mandatory before every create and every retry.
        matches = _match_ids(find())
    except Exception as exc:
        code = _error_code(exc)
        ambiguous = bool(getattr(exc, "ambiguous", False) or code == "timeout_uncertain")
        if ambiguous:
            code = "timeout_uncertain"
            _mark_uncertain(key, "timeout_uncertain", owner)
        else:
            _mark_failed(key, code, owner)
        raise AppleEffectError(code) from None

    if len(matches) > 1:
        _mark_failed(key, "marker_conflict", owner)
        raise AppleEffectError("marker_conflict")

    if matches:
        provider_id, actual_target = matches[0]
        actual_target = actual_target or _normalize_text(requested_target)
        try:
            persisted = transcript_log.mark_apple_effect_succeeded(
                key, provider_id, actual_target, reconciled=True, lease_owner=owner
            )
        except Exception:
            persisted = False
        if not persisted:
            current = transcript_log.get_apple_effect(key)
            if current and current.get("state") == "quarantined":
                raise AppleEffectError(
                    str(current.get("last_error_code") or "provider_conflict")
                )
            _mark_uncertain(key, "database_unavailable", owner)
            raise AppleEffectError("database_unavailable")
        return _receipt(
            transcript_log.get_apple_effect(key), key=key, effect_type=effect_type
        )

    try:
        created = create()
        provider_id, actual_target = _provider_id_target(created, requested_target)
        if not provider_id:
            raise reminders.AppleScriptError("provider_error", ambiguous=True)
    except Exception as exc:
        code = _error_code(exc)
        ambiguous = bool(getattr(exc, "ambiguous", False) or code == "timeout_uncertain")
        if ambiguous:
            code = "timeout_uncertain"
            _mark_uncertain(key, "timeout_uncertain", owner)
        else:
            _mark_failed(key, code, owner)
        raise AppleEffectError(code) from None

    # A create response is not a durable provider receipt by itself.  Read the
    # exact marker back immediately and require one matching object with the
    # same opaque provider id before committing local success.
    try:
        readback = _match_ids(find())
    except Exception as exc:
        code = _error_code(exc)
        if getattr(exc, "ambiguous", False) or code == "timeout_uncertain":
            code = "timeout_uncertain"
            _mark_uncertain(key, code, owner)
        else:
            _mark_failed(key, code, owner)
        raise AppleEffectError(code) from None
    if len(readback) > 1:
        _mark_failed(key, "marker_conflict", owner)
        raise AppleEffectError("marker_conflict")
    if len(readback) != 1:
        _mark_uncertain(key, "timeout_uncertain", owner)
        raise AppleEffectError("timeout_uncertain")
    if readback[0][0] != provider_id:
        _mark_failed(key, "provider_conflict", owner)
        raise AppleEffectError("provider_conflict")
    if readback[0][1]:
        actual_target = readback[0][1]

    try:
        persisted = transcript_log.mark_apple_effect_succeeded(
            key, provider_id, actual_target, reconciled=False, lease_owner=owner
        )
    except Exception:
        persisted = False
    if not persisted:
        current = transcript_log.get_apple_effect(key)
        if current and current.get("state") == "quarantined":
            raise AppleEffectError(
                str(current.get("last_error_code") or "provider_conflict")
            )
        # Provider create succeeded but local receipt did not.  Mark uncertain
        # best-effort so the next retry queries the exact marker first.
        _mark_uncertain(key, "database_unavailable", owner)
        raise AppleEffectError("database_unavailable")
    return _receipt(
        transcript_log.get_apple_effect(key), key=key, effect_type=effect_type
    )


def ensure_note(
    transcript_id: int | None = None,
    text: str = "",
    folder: str = "Penny",
    source: str = "",
    *,
    folder_name: str | None = None,
    effect_key: str | None = None,
) -> AppleEffectReceipt:
    """Ensure one marked Note for a canonical transcript row."""
    if folder_name is not None:
        folder = folder_name
    if effect_key is not None and transcript_id is None:
        raise AppleEffectError("canonical_id_required")
    derived_key = effect_key_for(
        int(transcript_id) if isinstance(transcript_id, int) else 0,
        "note",
        folder,
        "",
        normalized_payload_sha256(text),
    ) if isinstance(transcript_id, int) else None
    if effect_key is not None and effect_key != derived_key:
        raise AppleEffectError("invalid_effect")
    return _ensure_effect(
        transcript_id=transcript_id,
        effect_type="note",
        text=text,
        requested_target=folder,
        fallback_target="",
        source=source,
        find=lambda: reminders.find_note_by_marker(
            effect_key_for(int(transcript_id), "note", folder, "", normalized_payload_sha256(text)),
            folder,
        ),
        create=lambda: reminders.create_note_with_marker(
            effect_key_for(int(transcript_id), "note", folder, "", normalized_payload_sha256(text)),
            text,
            folder,
            source,
        ),
    )


def ensure_reminder(
    transcript_id: int | None = None,
    text: str = "",
    list_name: str = "Inbox",
    fallback: str = "Inbox",
    *,
    fallback_list: str | None = None,
    effect_key: str | None = None,
) -> AppleEffectReceipt:
    """Ensure one marked Reminder, searching requested and fallback lists."""
    if fallback_list is not None:
        fallback = fallback_list
    if effect_key is not None and transcript_id is None:
        raise AppleEffectError("canonical_id_required")
    derived_key = effect_key_for(
        int(transcript_id) if isinstance(transcript_id, int) else 0,
        "reminder",
        list_name,
        fallback,
        normalized_payload_sha256(text),
    ) if isinstance(transcript_id, int) else None
    if effect_key is not None and effect_key != derived_key:
        raise AppleEffectError("invalid_effect")
    return _ensure_effect(
        transcript_id=transcript_id,
        effect_type="reminder",
        text=text,
        requested_target=list_name,
        fallback_target=fallback,
        find=lambda: reminders.find_reminders_by_marker(
            effect_key_for(
                int(transcript_id), "reminder", list_name, fallback,
                normalized_payload_sha256(text),
            ),
            list_name,
            fallback,
        ),
        create=lambda: reminders.create_reminder_with_marker(
            effect_key_for(
                int(transcript_id), "reminder", list_name, fallback,
                normalized_payload_sha256(text),
            ),
            text,
            list_name,
            fallback,
        ),
    )
