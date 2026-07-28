#!/usr/bin/env python3
"""Durable Slack delivery for Penny voice memo transcripts."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import uuid
from dataclasses import dataclass

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
    DEFAULT_SLACK_CHANNEL_ID,
    QUALITY_FAILURE_CONTENT_KIND,
    QUALITY_FAILURE_DESTINATION,
    SLACK_API_ERROR_CODES,
    SLACK_DELIVERY_PLAN_BLOCK_KIT_V2,
    get_pending_quality_failure_deliveries,
    get_pending_slack_deliveries,
    mark_quality_failure_delivery_failed,
    mark_quality_failure_delivery_sent,
    mark_slack_delivery_chunk_sent,
    mark_slack_delivery_failed,
    mark_slack_delivery_reconciliation_required,
)

log = logging.getLogger(__name__)

SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
SLACK_DELIVERY_NAMESPACE = uuid.UUID("bc6feeb4-d1e8-4e84-8483-699c02146a2f")
DEFAULT_RETRY_AFTER_SECONDS = 60
MAX_RETRY_AFTER_SECONDS = 900
SLACK_MAX_FALLBACK_CHARACTERS = 4_000
SLACK_MAX_SECTION_CHARACTERS = 3_000
SLACK_MAX_BLOCKS_PER_MESSAGE = 50
SLACK_MAX_SECTIONS_PER_MESSAGE = SLACK_MAX_BLOCKS_PER_MESSAGE - 1
MAX_SLACK_POSTS_PER_PASS = 1
TRANSIENT_SLACK_ERRORS = frozenset(
    {"internal_error", "rate_limited", "ratelimited", "request_timeout", "service_unavailable"}
)


@dataclass(frozen=True)
class SlackTranscriptPost:
    text: str
    blocks: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class SlackTranscriptMessage(SlackTranscriptPost):
    """One deterministic parent plus any required threaded continuations."""

    continuations: tuple[SlackTranscriptPost, ...]


class SlackAPIError(RuntimeError):
    """A controlled error code returned by Slack."""

    def __init__(self, safe_error: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(safe_error)
        self.safe_error = safe_error
        self.retry_after_seconds = retry_after_seconds


class SlackConfigurationError(RuntimeError):
    """A local Slack delivery configuration error."""


def _slack_bot_token() -> str:
    return os.environ.get("PENNY_SLACK_BOT_TOKEN", "")


def _delivery_client_msg_id(delivery_id: int, chunk_index: int = 0) -> str:
    identity = f"penny:slack-delivery:{delivery_id}"
    if chunk_index:
        identity += f":chunk:{chunk_index}"
    return str(
        uuid.uuid5(
            SLACK_DELIVERY_NAMESPACE,
            identity,
        )
    )


def _quality_failure_client_msg_id(idempotency_key: str) -> str:
    return str(uuid.uuid5(SLACK_DELIVERY_NAMESPACE, idempotency_key))


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


def _retry_after_seconds(value: object) -> int | None:
    if value is None:
        return None
    try:
        seconds = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return max(1, min(seconds, MAX_RETRY_AFTER_SECONDS))


def _fallback_retry_after(attempt_count: int) -> int:
    return min(DEFAULT_RETRY_AFTER_SECONDS * max(1, 2 ** attempt_count), MAX_RETRY_AFTER_SECONDS)


def _plain_text_sections(text: str) -> list[str]:
    sections: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= SLACK_MAX_SECTION_CHARACTERS:
            sections.append(remaining)
            break

        window = remaining[:SLACK_MAX_SECTION_CHARACTERS]
        split_at = max(
            window.rfind("\n") + 1,
            window.rfind(" ") + 1,
            window.rfind("\t") + 1,
            window.rfind("\r") + 1,
        )
        if split_at <= 0:
            split_at = SLACK_MAX_SECTION_CHARACTERS
        sections.append(remaining[:split_at])
        remaining = remaining[split_at:]
    return sections


def _context_block(label: str) -> dict[str, object]:
    return {
        "type": "context",
        "elements": [
            {
                "type": "plain_text",
                "text": label,
                "emoji": False,
            }
        ],
    }


def _section_blocks(sections: list[str]) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "type": "section",
            "text": {
                "type": "plain_text",
                "text": section,
                "emoji": False,
            },
        }
        for section in sections
    )


def _transcript_post(label: str, sections: list[str]) -> SlackTranscriptPost:
    section_text = "".join(sections)
    return SlackTranscriptPost(
        text=section_text[:SLACK_MAX_FALLBACK_CHARACTERS],
        blocks=(_context_block(label), *_section_blocks(sections)),
    )


def build_transcript_message(
    transcript_id: int,
    text: str,
) -> SlackTranscriptMessage:
    """Pack an exact transcript into deterministic bounded plain-text blocks."""
    sections = _plain_text_sections(text)
    section_groups = [
        sections[index : index + SLACK_MAX_SECTIONS_PER_MESSAGE]
        for index in range(0, len(sections), SLACK_MAX_SECTIONS_PER_MESSAGE)
    ]
    if not section_groups:
        section_groups = [[]]

    parent = _transcript_post(
        f"Penny transcript {transcript_id}",
        section_groups[0],
    )
    continuation_count = len(section_groups) - 1
    continuations = tuple(
        _transcript_post(
            (
                f"Penny transcript {transcript_id} "
                f"continuation {continuation_index} of {continuation_count}"
            ),
            section_group,
        )
        for continuation_index, section_group in enumerate(
            section_groups[1:],
            start=1,
        )
    )
    return SlackTranscriptMessage(
        text=parent.text,
        blocks=parent.blocks,
        continuations=continuations,
    )


def _warning_error(data: dict) -> str | None:
    metadata = data.get("response_metadata")
    if not isinstance(metadata, dict):
        return None
    warnings = metadata.get("warnings")
    if not warnings:
        return None
    if isinstance(warnings, list) and "message_truncated" in warnings:
        return "message_truncated"
    return "provider_warning"


def _post_to_slack(
    channel_id: str,
    message: SlackTranscriptPost,
    client_msg_id: str,
    *,
    thread_ts: str | None = None,
) -> str:
    token = _slack_bot_token()
    if not token:
        raise SlackConfigurationError

    payload: dict[str, object] = {
        "channel": channel_id,
        "client_msg_id": client_msg_id,
        "text": message.text,
        "blocks": list(message.blocks),
        "unfurl_links": False,
        "unfurl_media": False,
    }
    if thread_ts is not None:
        payload["thread_ts"] = thread_ts

    resp = requests.post(
        SLACK_POST_MESSAGE_URL,
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        timeout=10,
    )
    if getattr(resp, "status_code", 200) == 429:
        raise SlackAPIError(
            "ratelimited",
            retry_after_seconds=_retry_after_seconds(
                getattr(resp, "headers", {}).get("Retry-After")
            ),
        )
    data = resp.json()
    if not data.get("ok"):
        safe_error = _safe_slack_error_code(data.get("error"))
        retry_after = None
        if safe_error in TRANSIENT_SLACK_ERRORS:
            retry_after = _retry_after_seconds(
                getattr(resp, "headers", {}).get("Retry-After")
            )
        raise SlackAPIError(safe_error, retry_after_seconds=retry_after)
    warning_error = _warning_error(data)
    if warning_error is not None:
        raise SlackAPIError(warning_error)
    provider_ts = data.get("ts")
    if not isinstance(provider_ts, str) or not provider_ts.strip():
        raise SlackAPIError("provider_response_error")
    return provider_ts


def _record_delivery_failure(
    delivery_id: int,
    safe_error: str,
    *,
    retry_after_seconds: int,
) -> None:
    try:
        mark_slack_delivery_failed(
            delivery_id,
            safe_error,
            retry_after_seconds=retry_after_seconds,
        )
    except Exception as ack_exc:
        log.error(
            "Failed to record Slack delivery failure id=%s: %s",
            delivery_id,
            _classified_error("acknowledgement_error", ack_exc),
        )
    log.warning("Slack delivery failed id=%s: %s", delivery_id, safe_error)


def process_pending_slack_deliveries(limit: int = 20) -> int:
    delivered = 0
    attempted_posts = 0
    for row in get_pending_slack_deliveries(limit=limit):
        delivery_id = int(row["id"])
        chunk_attempt_count = int(row.get("chunk_attempt_count") or 0)
        if row.get("delivery_plan_version") != SLACK_DELIVERY_PLAN_BLOCK_KIT_V2:
            try:
                mark_slack_delivery_reconciliation_required(delivery_id)
            except Exception as exc:
                log.error(
                    "Failed to reconcile Slack delivery id=%s: %s",
                    delivery_id,
                    _classified_error("acknowledgement_error", exc),
                )
                break
            log.warning(
                "Slack delivery requires reconciliation id=%s",
                delivery_id,
            )
            continue
        if str(row["channel_id"]) != DEFAULT_SLACK_CHANNEL_ID:
            _record_delivery_failure(
                delivery_id,
                "destination_mismatch",
                retry_after_seconds=_fallback_retry_after(chunk_attempt_count),
            )
            continue

        if attempted_posts >= MAX_SLACK_POSTS_PER_PASS:
            break

        message = build_transcript_message(
            int(row["transcript_row_id"]),
            str(row["message_text"]),
        )
        posts: tuple[SlackTranscriptPost, ...] = (
            message,
            *message.continuations,
        )
        chunk_index = int(row.get("next_chunk_index") or 0)
        attempted_posts += 1
        try:
            thread_ts = None
            if chunk_index > 0:
                parent_provider_ts = row.get("provider_ts")
                if parent_provider_ts is None:
                    raise ValueError("Slack parent receipt is unavailable")
                thread_ts = str(parent_provider_ts)
            provider_ts = _post_to_slack(
                DEFAULT_SLACK_CHANNEL_ID,
                posts[chunk_index],
                _delivery_client_msg_id(delivery_id, chunk_index),
                thread_ts=thread_ts,
            )
        except SlackAPIError as exc:
            _record_delivery_failure(
                delivery_id,
                exc.safe_error,
                retry_after_seconds=exc.retry_after_seconds
                or _fallback_retry_after(chunk_attempt_count),
            )
            break
        except SlackConfigurationError:
            _record_delivery_failure(
                delivery_id,
                "configuration_error",
                retry_after_seconds=_fallback_retry_after(chunk_attempt_count),
            )
            break
        except Exception as exc:
            _record_delivery_failure(
                delivery_id,
                _classified_error("provider_error", exc),
                retry_after_seconds=_fallback_retry_after(chunk_attempt_count),
            )
            break

        try:
            mark_slack_delivery_chunk_sent(
                delivery_id,
                chunk_index=chunk_index,
                chunk_count=len(posts),
                provider_ts=provider_ts,
            )
        except Exception as exc:
            _record_delivery_failure(
                delivery_id,
                _classified_error("acknowledgement_error", exc),
                retry_after_seconds=_fallback_retry_after(chunk_attempt_count),
            )
            break

        if chunk_index + 1 >= len(posts):
            delivered += 1
    return delivered


def process_pending_quality_failure_deliveries(limit: int = 20) -> int:
    """Post body-free operational metadata to the configured Maya ledger."""
    delivered = 0
    for row in get_pending_quality_failure_deliveries(limit=limit):
        delivery_id = int(row["id"])
        attempt_count = int(row.get("attempt_count") or 0)
        safe_error: str | None = None
        retry_after = _fallback_retry_after(attempt_count)
        channel_id = os.environ.get("PENNY_MAYA_LEDGER_CHANNEL_ID", "").strip()
        if (
            row.get("content_kind") != QUALITY_FAILURE_CONTENT_KIND
            or row.get("destination") != QUALITY_FAILURE_DESTINATION
        ):
            safe_error = "destination_mismatch"
        elif not channel_id:
            safe_error = "configuration_error"

        if safe_error is None:
            message = _transcript_post(
                "Penny quality failure",
                [str(row["message_text"])],
            )
            try:
                provider_ts = _post_to_slack(
                    channel_id,
                    message,
                    _quality_failure_client_msg_id(str(row["idempotency_key"])),
                )
            except SlackAPIError as exc:
                safe_error = exc.safe_error
                retry_after = (
                    exc.retry_after_seconds
                    or _fallback_retry_after(attempt_count)
                )
            except SlackConfigurationError:
                safe_error = "configuration_error"
            except Exception as exc:
                safe_error = _classified_error("provider_error", exc)
            else:
                try:
                    mark_quality_failure_delivery_sent(
                        delivery_id,
                        provider_ts,
                    )
                except Exception:
                    safe_error = "acknowledgement_error:Exception"
                else:
                    delivered += 1

        if safe_error is not None:
            try:
                mark_quality_failure_delivery_failed(
                    delivery_id,
                    safe_error,
                    retry_after_seconds=retry_after,
                )
            except Exception as exc:
                log.error(
                    "Failed to record quality-failure delivery id=%s: %s",
                    delivery_id,
                    _classified_error("acknowledgement_error", exc),
                )
            break
    return delivered


def process_pending_slack(limit: int = 20) -> int:
    transcript_deliveries = process_pending_slack_deliveries(limit=limit)
    quality_deliveries = process_pending_quality_failure_deliveries(limit=limit)
    return transcript_deliveries + quality_deliveries
