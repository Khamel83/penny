#!/usr/bin/env python3
"""
Penny Core Logic
Shared pipeline, notifications, and deduplication for all Penny services.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import logging.handlers
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import requests

from apple_effects import AppleEffectError, AppleEffectReceipt, ensure_note, ensure_reminder
from classifier import classify, detect_content_type
from config import get_config
from reminders import add_note, add_reminder
from transcript_log import (
    get_transcript,
    mark_failed,
    mark_routed,
    update_transcript_progress,
    update_transcript_stages,
)

cfg = get_config()

LOG_DIR = Path("~/.penny/logs").expanduser()

SOURCE_EMOJI = {
    "iCloud": "☁️",
    "Shortcut": "📱",
    "text": "💬",
    "HA": "🏠",
    "Google Tasks": "🗒️",
}

CATEGORY_EMOJI = {
    "groceries": "🛒",
    "errands": "🚗",
    "home": "🏠",
    "health": "🏥",
    "work": "💼",
    "kids": "👧",
    "inbox": "📝",
}

WHISPER_TOKEN_RE = re.compile(r"<\|[^>]+?\|>")
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_ROUTE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_MAYA_CLIENT_REF_RE = re.compile(r"^penny:[0-9]{1,12}$")
_MAYA_ROUTE_STATES = frozenset({"attempting", "accepted", "rejected", "failed"})
_MAYA_ERROR_CODES = frozenset(
    {
        "transport_error",
        "http_error",
        "invalid_response",
        "invalid_acceptance",
        "acceptance_unrecorded",
        "routed_mark_unrecorded",
    }
)
_SAFE_CONTENT_TYPES = frozenset({"action_items", "long_note", "unclear"})
_SAFE_NOTE_FOLDERS = frozenset(
    {"Penny", "Inbox", "Groceries", "Errands", "Home", "Health", "Work", "Kids"}
)


class RoutingError(RuntimeError):
    """Raised when Penny successfully transcribes/classifies but cannot persist the result."""


def _safe_exception_class(exc: BaseException) -> str:
    """Return a bounded exception class name without exposing its message."""
    name = type(exc).__name__
    if name and len(name) <= 48 and name[0].isalpha() and all(
        character.isalnum() or character == "_" for character in name
    ):
        return name
    return "Exception"


def _safe_identifier(value: object, *, limit: int = 128) -> str | None:
    """Keep only bounded opaque identifiers in progress metadata."""
    candidate = str(value or "").strip()
    if len(candidate) > limit or not _SAFE_IDENTIFIER_RE.fullmatch(candidate):
        return None
    return candidate


def _safe_maya_timestamp(value: object) -> str | None:
    candidate = str(value or "").strip()
    if len(candidate) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _bounded_maya_route_details(details: dict[str, Any]) -> dict[str, Any]:
    """Whitelist compact Maya acceptance metadata for legacy progress storage."""
    bounded: dict[str, Any] = {}
    state = details.get("state")
    if state in _MAYA_ROUTE_STATES:
        bounded["state"] = state

    for key in ("attempted_at", "accepted_at"):
        if key in details:
            timestamp = _safe_maya_timestamp(details[key])
            if timestamp is not None:
                bounded[key] = timestamp

    client_ref = details.get("client_ref")
    if isinstance(client_ref, str) and _MAYA_CLIENT_REF_RE.fullmatch(client_ref.strip()):
        bounded["client_ref"] = client_ref.strip()

    status_code = details.get("status_code")
    if type(status_code) is int and 100 <= status_code <= 599:
        bounded["status_code"] = status_code

    routed_to = details.get("routed_to")
    if isinstance(routed_to, str) and _SAFE_ROUTE_RE.fullmatch(routed_to.strip().lower()):
        bounded["routed_to"] = routed_to.strip().lower()

    error_code = details.get("error_code")
    if isinstance(error_code, str) and error_code in _MAYA_ERROR_CODES:
        bounded["error_code"] = error_code
    return bounded


def setup_logging(service_name: str) -> logging.Logger:
    """Setup rotating file logging for a service."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{service_name}.log"

    level = getattr(logging, cfg.logging.level.upper(), logging.INFO)

    logger = logging.getLogger()
    logger.setLevel(level)

    # Reset handlers so multiple imports / re-entry do not duplicate logs.
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logging.getLogger(service_name)


# ===== Hashing =====


def get_file_hash(path: Path, *, source_root: Path | None = None) -> str:
    """Get an MD5 identity from a regular file rooted without symlink walks."""
    hasher = hashlib.md5()
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )
    absolute_path = path if path.is_absolute() else path.absolute()
    if source_root is None:
        absolute_root = absolute_path.parent.resolve(strict=True)
        absolute_path = absolute_root / absolute_path.name
    else:
        absolute_root = (
            source_root if source_root.is_absolute() else source_root.absolute()
        )
    try:
        relative = absolute_path.relative_to(absolute_root)
    except ValueError as exc:
        raise OSError("source_outside_root") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise OSError("source_unavailable")
    directory_descriptor = os.open(absolute_root, directory_flags)
    try:
        for component in relative.parts[:-1]:
            child_descriptor = os.open(
                component,
                directory_flags,
                dir_fd=directory_descriptor,
            )
            os.close(directory_descriptor)
            directory_descriptor = child_descriptor
        descriptor = os.open(
            relative.parts[-1],
            file_flags,
            dir_fd=directory_descriptor,
        )
    finally:
        os.close(directory_descriptor)
    with os.fdopen(descriptor, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise OSError("source_not_regular")
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


# ===== Telegram =====


def send_telegram(message: str, *, force: bool = False) -> bool:
    if not force and not cfg.notifications.telegram_enabled:
        return False
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        return False

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage",
            json={"chat_id": cfg.telegram_chat_id, "text": message},
            timeout=30,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logging.getLogger("penny.core").error(
            "Telegram send failed class=%s", _safe_exception_class(e)
        )
        return False


def _notify_hermes(
    transcript_text: str,
    routed_items: List[Dict[str, Any]],
    source: str = "voice_memo",
) -> bool:
    """Best-effort Hermes webhook notification. Never blocks Penny for long."""
    hermes_url = os.getenv(
        "HERMES_WEBHOOK_URL", "http://100.126.13.70:7778/webhooks/penny"
    )
    secret = os.getenv("PENNY_HERMES_WEBHOOK_SECRET", "")
    if not hermes_url or not secret:
        return False

    payload = {
        "source": source,
        "transcript": transcript_text,
        "routed_items": routed_items,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature = hmac.new(
        secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    request_id = hashlib.sha256(
        f"{source}\0{transcript_text}\0{body}".encode("utf-8")
    ).hexdigest()[:32]

    try:
        resp = requests.post(
            hermes_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": signature,
                "X-Request-ID": request_id,
            },
            timeout=3,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logging.getLogger("penny.core").warning(
            "Hermes notify failed class=%s", _safe_exception_class(e)
        )
        return False


def _hermes_items(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = result.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    if result.get("skip"):
        return [{"type": "skip", "reason": str(result.get("reason", ""))}]
    return []


def _finish_route(transcript: str, result: Dict[str, Any], source: str) -> Dict[str, Any]:
    try:
        _notify_hermes(transcript, _hermes_items(result), source=source)
    except Exception as e:
        logging.getLogger("penny.core").warning(
            "Hermes notify failed class=%s", _safe_exception_class(e)
        )
    return result


def build_result_message(transcript: str, result: Dict[str, Any], source: str) -> str:
    emoji = SOURCE_EMOJI.get(source, "📱")
    excerpt = transcript[:200] + ("..." if len(transcript) > 200 else "")

    if result.get("skip"):
        return f'⏭️ Not a reminder ({emoji} {source}):\n\n📋 "{excerpt}"'

    items = result.get("items", [])
    fallback = result.get("fallback", False)

    by_category: Dict[str, List[str]] = {}
    for entry in items:
        category = entry.get("category", "inbox")
        item_text = str(entry.get("item", "")).strip()
        if not item_text:
            continue
        by_category.setdefault(category, []).append(item_text)

    prefix = (
        f"⚠️ Classification failed — added to Inbox ({emoji} {source}):"
        if fallback
        else f"✅ {len(items)} item(s) added ({emoji} {source}):"
    )
    lines = [prefix, ""]
    for cat, cat_items in by_category.items():
        e = CATEGORY_EMOJI.get(cat, "📝")
        lines.append(f"  {e} {cat.capitalize()}: {', '.join(cat_items)}")
    lines += ["", f'📋 "{excerpt}"']
    return "\n".join(lines)


# ===== Pipeline =====


def normalize_transcript_text(transcript: str) -> str:
    """Strip common Whisper control-token artifacts while preserving line breaks."""
    raw = str(transcript or "")
    cleaned = WHISPER_TOKEN_RE.sub(" ", raw)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[^\S\n]+", " ", cleaned)
    cleaned = "\n".join(line.strip() for line in cleaned.split("\n")).strip()

    # Heuristic: near-empty remnants from token-heavy output (e.g. "SE<|hr|><|hr|>").
    if "<|" in raw and len(cleaned) <= 3:
        return ""
    if cleaned and not any(ch.isalnum() for ch in cleaned):
        return ""
    return cleaned


def _target_reminders_list(category: str) -> str:
    target_list = category.capitalize()
    if target_list not in cfg.apple_reminders.lists:
        return cfg.apple_reminders.default_list
    return target_list


def _persisted_transcript_body(row_id: int | None, fallback: str) -> str:
    if row_id is None:
        return fallback
    row = get_transcript(row_id)
    stored = row.get("transcript") if row else None
    if stored is None:
        raise RoutingError(
            f"persisted transcript unavailable for Maya-routed row_id={row_id}"
        )
    return str(stored)


def _load_routing_progress(row_id: int | None) -> dict[str, Any]:
    if row_id is None:
        return {}
    row = get_transcript(row_id)
    if not row or not row.get("routing_progress"):
        return {}
    try:
        parsed = json.loads(row["routing_progress"])
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _short_excerpt(text: str, limit: int = 60) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _reference_reminder_text(transcript: str, row_id: int | None = None) -> str:
    if row_id is None:
        raise RoutingError("canonical_id_required")
    row = get_transcript(row_id)
    if not row:
        raise RoutingError("canonical_id_required")
    raw_timestamp = row.get("recorded_at") or row.get("created_at")
    try:
        captured = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
        timestamp = captured.astimezone(timezone.utc).strftime("%Y-%m-%d %-I:%M %p UTC")
    except (TypeError, ValueError):
        timestamp = "recorded"
    excerpt = _short_excerpt(transcript) or "voice memo"
    return f"Review Penny note ({timestamp}): {excerpt}"


def _require_effect_row(row_id: int | None) -> int:
    if not isinstance(row_id, int) or row_id <= 0:
        raise RoutingError("canonical_id_required")
    return row_id


def _receipt_or_error(receipt: AppleEffectReceipt) -> AppleEffectReceipt:
    if receipt.state != "succeeded" or not receipt.provider_id:
        raise RoutingError(receipt.error_code or "provider_error")
    return receipt


def _record_effect_progress(
    row_id: int,
    *,
    effect_name: str,
    receipt: AppleEffectReceipt,
    **summary: Any,
) -> bool:
    payload: dict[str, Any] = {f"{effect_name}_created": True}
    effect_key = _safe_identifier(receipt.effect_key)
    provider_id = _safe_identifier(receipt.provider_id)
    if effect_key is not None:
        payload[f"{effect_name}_effect_key"] = effect_key
    if provider_id is not None:
        payload[f"{effect_name}_provider_id"] = provider_id

    # Legacy routing_progress is metadata only.  Never persist Apple/provider
    # response bodies, reminder text, item text, paths, or user-controlled data.
    content_type = summary.get("content_type")
    if content_type in _SAFE_CONTENT_TYPES:
        payload["content_type"] = content_type
    note_folder = summary.get("note_folder")
    if note_folder in _SAFE_NOTE_FOLDERS:
        payload["note_folder"] = note_folder
    return bool(update_transcript_progress(row_id, payload))


def _record_maya_route_state(row_id: int | None, **details: Any) -> bool:
    if row_id is None:
        return True
    return bool(
        update_transcript_progress(
            row_id,
            {"maya_route": _bounded_maya_route_details(details)},
        )
    )


def _is_valid_maya_acceptance(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and bool(data.get("ok"))
        and isinstance(data.get("routed_to"), str)
        and bool(_SAFE_ROUTE_RE.fullmatch(str(data.get("routed_to")).strip().lower()))
    )


def _confirm_maya_acceptance(
    row_id: int | None,
    *,
    attempted_at: str,
    client_ref: str | None,
    source: str,
    status_code: int,
    data: dict[str, Any],
) -> bool:
    log = logging.getLogger("penny.core")
    accepted_at = datetime.now(timezone.utc).isoformat()
    accepted_recorded = _record_maya_route_state(
        row_id,
        state="accepted",
        attempted_at=attempted_at,
        accepted_at=accepted_at,
        client_ref=client_ref,
        status_code=status_code,
        routed_to=data.get("routed_to"),
    )
    if not accepted_recorded:
        _record_maya_route_state(
            row_id,
            state="failed",
            attempted_at=attempted_at,
            client_ref=client_ref,
            status_code=status_code,
            routed_to=data.get("routed_to"),
            error_code="acceptance_unrecorded",
        )
        log.error("Maya acceptance could not be recorded locally for row_id=%s", row_id)
        return False

    routed_recorded = True
    if row_id is not None:
        routed_recorded = mark_routed(row_id, data, "maya")
    if not routed_recorded:
        _record_maya_route_state(
            row_id,
            state="failed",
            attempted_at=attempted_at,
            accepted_at=accepted_at,
            client_ref=client_ref,
            status_code=status_code,
            routed_to=data.get("routed_to"),
            error_code="routed_mark_unrecorded",
        )
        log.error("Maya routed status could not be recorded locally for row_id=%s", row_id)
        return False

    return True


def _route_to_maya(
    transcript: str,
    source: str,
    row_id: int | None = None,
    duration_seconds: float | None = None,
) -> bool:
    """Fail closed: Phase A Maya delivery is owned by the durable v2 outbox."""
    if row_id is None:
        raise RoutingError("canonical_id_required")
    return False



def classify_and_route(
    transcript: str,
    source: str,
    row_id: int | None = None,
    duration_seconds: float | None = None,
    allow_maya: bool = False,
) -> Dict[str, Any]:
    """
    Core pipeline: Content type detection -> Classifier -> Reminders/Notes.

    Three-way routing:
    - action_items: extract todos via classifier -> add to Reminders
    - long_note: save to Apple Notes (no reminders)
    - unclear: save to Notes + create reference reminder in Inbox

    If row_id is provided, updates the transcript log status on success/failure.

    Raises RoutingError when Apple-side writes fail so callers do not mark items as processed.
    Returns the classifier result on success.
    """
    log = logging.getLogger("penny.core")
    transcript = normalize_transcript_text(transcript)
    progress = _load_routing_progress(row_id)
    # Retained as an input compatibility shim. Phase A never invokes the
    # receiptless legacy Maya POST; the durable Maya v2 outbox is authoritative.
    allow_maya = False

    if not transcript:
        if row_id is not None:
            error_message = "empty transcript after normalization"
            mark_failed(row_id, error_message)
            raise RoutingError(error_message)
        return {"skip": True, "reason": "empty transcript"}

    if row_id is None:
        raise RoutingError("canonical_id_required")

    if row_id is not None:
        update_transcript_stages(
            row_id,
            ingest_state="routing",
            duration_seconds=duration_seconds,
            routing_started_at=datetime.now().isoformat(),
        )

    content_type = detect_content_type(
        transcript,
        cfg.openrouter_api_key,
        cfg.llm.model,
        duration_seconds=duration_seconds,
    )

    try:
        if content_type == "long_note":
            log.info("Routing as long note to Apple Notes")
            effect_row_id = _require_effect_row(row_id)
            try:
                note_receipt = _receipt_or_error(
                    ensure_note(
                        effect_row_id,
                        transcript,
                        folder="Penny",
                        source=source,
                    )
                )
            except AppleEffectError as exc:
                raise RoutingError(exc.code) from None
            if not _record_effect_progress(
                effect_row_id,
                effect_name="note",
                receipt=note_receipt,
                note_folder="Penny",
                content_type="long_note",
            ):
                raise RoutingError("receipt_persistence_failed")
            if not mark_routed(
                effect_row_id,
                {"type": "long_note"},
                "note in Penny",
            ):
                raise RoutingError("receipt_persistence_failed")
            return _finish_route(
                transcript, {"skip": True, "reason": "long_note"}, source
            )

        if content_type == "unclear":
            log.info("Unclear content — saving to Notes with reference reminder")
            effect_row_id = _require_effect_row(row_id)
            try:
                note_receipt = _receipt_or_error(
                    ensure_note(
                        effect_row_id,
                        transcript,
                        folder="Penny",
                        source=source,
                    )
                )
            except AppleEffectError as exc:
                raise RoutingError(exc.code) from None
            if not _record_effect_progress(
                effect_row_id,
                effect_name="note",
                receipt=note_receipt,
                note_folder="Penny",
                content_type="unclear",
            ):
                raise RoutingError("receipt_persistence_failed")

            ref_text = _reference_reminder_text(transcript, effect_row_id)
            try:
                reminder_receipt = _receipt_or_error(
                    ensure_reminder(
                        effect_row_id,
                        ref_text,
                        "Inbox",
                        cfg.apple_reminders.default_list,
                    )
                )
            except AppleEffectError as exc:
                raise RoutingError(exc.code) from None
            if not _record_effect_progress(
                effect_row_id,
                effect_name="reference_reminder",
                receipt=reminder_receipt,
                reference_reminder_text=ref_text,
            ):
                raise RoutingError("receipt_persistence_failed")

            if not mark_routed(
                effect_row_id,
                {"type": "unclear", "ref_reminder": ref_text},
                "note + ref reminder",
            ):
                raise RoutingError("receipt_persistence_failed")
            result = {
                "skip": True,
                "reason": "unclear content, saved to Notes with reference",
            }
            return _finish_route(transcript, result, source)

        # action_items — use the existing item extractor
        result = classify(
            transcript,
            cfg.openrouter_api_key,
            cfg.llm.model,
            duration_seconds=duration_seconds,
        )

        if result.get("skip"):
            log.info("Skipping routing for non-reminder classifier result")
            note_text = transcript or "(No intelligible speech detected.)"
            effect_row_id = _require_effect_row(row_id)
            try:
                note_receipt = _receipt_or_error(
                    ensure_note(
                        effect_row_id,
                        note_text,
                        folder="Penny",
                        source=source,
                    )
                )
            except AppleEffectError as exc:
                raise RoutingError(exc.code) from None
            if not _record_effect_progress(
                effect_row_id,
                effect_name="note",
                receipt=note_receipt,
                note_folder="Penny",
            ):
                raise RoutingError("receipt_persistence_failed")
            if not mark_routed(effect_row_id, result, "note in Penny"):
                raise RoutingError("receipt_persistence_failed")
            return _finish_route(transcript, result, source)

        items = result.get("items", [])
        if not isinstance(items, list) or not items:
            raise RoutingError("Classifier returned no routable items")

        routed_count = 0
        created_reminders: set[str] = set()
        for entry in items:
            item_text = re.sub(r"\s+", " ", str(entry.get("item", ""))).strip()
            category = str(entry.get("category", "inbox")).strip().lower()
            if not item_text:
                continue
            target_list = _target_reminders_list(category)
            reminder_key = f"{target_list}|{item_text}"
            if reminder_key in created_reminders:
                continue
            effect_row_id = _require_effect_row(row_id)
            try:
                reminder_receipt = _receipt_or_error(
                    ensure_reminder(
                        effect_row_id,
                        item_text,
                        target_list,
                        cfg.apple_reminders.default_list,
                    )
                )
            except AppleEffectError as exc:
                raise RoutingError(exc.code) from None
            created_reminders.add(reminder_key)
            safe_effect_key = _safe_identifier(reminder_receipt.effect_key)
            safe_provider_id = _safe_identifier(reminder_receipt.provider_id)
            progress_patch: dict[str, Any] = {
                "created_reminder_count": len(created_reminders),
            }
            if safe_effect_key is not None:
                progress_patch["last_reminder_effect_key"] = safe_effect_key
            if safe_provider_id is not None:
                progress_patch["last_reminder_provider_id"] = safe_provider_id
            if not update_transcript_progress(
                effect_row_id,
                progress_patch,
            ):
                raise RoutingError("receipt_persistence_failed")
            routed_count += 1

        effect_row_id = _require_effect_row(row_id)
        if not mark_routed(effect_row_id, result, f"{routed_count} reminder(s)"):
            raise RoutingError("receipt_persistence_failed")

        return _finish_route(transcript, result, source)

    except RoutingError as e:
        if row_id is not None:
            mark_failed(row_id, e.args[0] if e.args else "routing_failed")
        raise
