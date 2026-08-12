#!/usr/bin/env python3
"""Narrow, read-after-write Apple Notes and Reminders transports.

The effect ledger in :mod:`apple_effects` owns idempotency.  This module only
builds escaped AppleScript and returns opaque provider identifiers/targets; it
never logs user text, provider stderr, or provider object contents.
"""

from __future__ import annotations

import html
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

log = logging.getLogger(__name__)


class AppleScriptError(RuntimeError):
    """Safe transport error; ``ambiguous`` means Apple may have created it."""

    def __init__(self, code: str = "provider_error", *, ambiguous: bool = False):
        self.code = code
        self.ambiguous = ambiguous
        super().__init__(code)


@dataclass(frozen=True)
class ProviderReceipt:
    provider_id: str
    actual_target: str


def _escape_applescript(value: str, *, preserve_newlines: bool = False) -> str:
    """Escape a string literal without allowing control characters into script."""
    text = str(value or "")
    if preserve_newlines:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\n", " ")
    else:
        text = " ".join(text.replace("\r", "\n").split("\n"))
    text = "".join(ch if ch >= " " and ch != "\x7f" else " " for ch in text)
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _run_osascript(script: str) -> str:
    """Run one script and return stdout only; never expose stderr in errors."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired as exc:
        raise AppleScriptError("timeout_uncertain", ambiguous=True) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise AppleScriptError("provider_error") from exc
    if result.returncode != 0:
        stderr = str(result.stderr or "").lower()
        permission_patterns = (
            "-1743",
            "not authorized to send apple events",
            "not authorised to send apple events",
            "not authorized to send appleevents",
            "not permitted to send apple events",
            "automation permission",
        )
        if any(pattern in stderr for pattern in permission_patterns):
            raise AppleScriptError("permission_denied")
        raise AppleScriptError("provider_error")
    return str(result.stdout or "").strip()


def _provider_ids(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        values = raw
    else:
        values = str(raw).replace("\r", "\n").split("\n")
    return [str(value).strip() for value in values if str(value).strip()]


def _marker(effect_key: str) -> str:
    if not isinstance(effect_key, str) or len(effect_key) != 64:
        raise ValueError("invalid_effect")
    try:
        int(effect_key, 16)
    except ValueError as exc:
        raise ValueError("invalid_effect") from exc
    return f"penny-effect:{effect_key}"


def _note_marker_html(effect_key: str, text: str) -> str:
    marker = _marker(effect_key)
    # Keep the legacy comment for older readers, but also include a small
    # visible text marker.  Notes may discard comments and hidden elements
    # during sync; ordinary text survives ``body of n as text`` readback.
    # The marker contains only the opaque effect key and is placed on its own
    # low-contrast line so it remains unobtrusive without being invisible.
    marker_html = (
        f"<!-- {marker} -->"
        f"<br><span style=\"color:#8a8a8a;font-size:9px\">"
        f"{html.escape(marker, quote=True)}</span>"
    )
    body = "<br>" + html.escape(str(text or ""), quote=True)
    body = body.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    return marker_html + body


def find_note_by_marker(effect_key: str, folder_name: str = "Penny") -> list[str]:
    marker = _marker(effect_key)
    folder = _escape_applescript(folder_name)
    needle = _escape_applescript(marker)
    script = f'''
tell application "Notes"
    set matches to {{}}
    if exists folder "{folder}" then
        repeat with n in notes of folder "{folder}"
            if (body of n as text) contains "{needle}" then set end of matches to (id of n as text)
        end repeat
    end if
    set AppleScript's text item delimiters to linefeed
    return matches as text
end tell
'''
    return _provider_ids(_run_osascript(script))


def find_notes_by_marker(effect_key: str, folder_name: str = "Penny") -> list[str]:
    return find_note_by_marker(effect_key, folder_name)


def create_note_with_marker(
    effect_key: str,
    text: str,
    folder_name: str = "Penny",
    source: str = "",
) -> ProviderReceipt:
    """Create a marked Note and return its read-only provider identity."""
    del source  # provenance belongs in the canonical transcript/archive row
    marker_body = _note_marker_html(effect_key, text)
    folder = _escape_applescript(folder_name)
    title = _escape_applescript(datetime.now().strftime("%Y-%m-%d %H:%M"))
    body = _escape_applescript(marker_body)
    script = f'''
tell application "Notes"
    set targetFolder to missing value
    repeat with f in folders
        if name of f is "{folder}" then set targetFolder to f
    end repeat
    if targetFolder is missing value then set targetFolder to (make new folder with properties {{name:"{folder}"}})
    set createdNote to make new note at targetFolder with properties {{name:"{title}", body:"{body}"}}
    return (id of createdNote as text)
end tell
'''
    provider_id = _run_osascript(script).strip()
    if not provider_id:
        raise AppleScriptError("provider_error", ambiguous=True)
    # A successful create script returns the provider id; read-after-write is
    # performed by the effect orchestrator through the marker search on retry.
    return ProviderReceipt(provider_id=provider_id, actual_target=folder_name)


def read_note_by_marker(effect_key: str, folder_name: str = "Penny") -> list[str]:
    return find_note_by_marker(effect_key, folder_name)


def _reminder_rows(raw: Any, default_target: str = "") -> list[ProviderReceipt]:
    rows: list[ProviderReceipt] = []
    if raw is None:
        return rows
    values: Iterable[Any]
    if isinstance(raw, (list, tuple, set)):
        values = raw
    else:
        values = str(raw).replace("\r", "\n").split("\n")
    for value in values:
        if isinstance(value, ProviderReceipt):
            if value.provider_id:
                rows.append(value)
            continue
        line = str(value).strip()
        if not line:
            continue
        provider_id, sep, actual = line.partition("\t")
        rows.append(
            ProviderReceipt(
                provider_id=provider_id.strip(),
                actual_target=(actual.strip() if sep else default_target),
            )
        )
    return [row for row in rows if row.provider_id]


def find_reminders_by_marker(
    effect_key: str,
    list_name: str,
    fallback_list: str = "Inbox",
) -> list[ProviderReceipt]:
    marker = _escape_applescript(_marker(effect_key))
    requested = _escape_applescript(list_name)
    fallback = _escape_applescript(fallback_list)
    # Search both identities on every replay.  This prevents a previously
    # created fallback reminder from being duplicated when the requested list
    # appears later.
    script = f'''
tell application "Reminders"
    set outputRows to {{}}
    repeat with targetList in lists
        set targetName to name of targetList as text
        if targetName is "{requested}" or targetName is "{fallback}" then
            repeat with r in reminders of targetList
                if (body of r as text) contains "{marker}" then
                    set end of outputRows to ((id of r as text) & tab & targetName)
                end if
            end repeat
        end if
    end repeat
    set AppleScript's text item delimiters to linefeed
    return outputRows as text
end tell
'''
    return _reminder_rows(_run_osascript(script), fallback_list)


def find_reminder_by_marker(
    effect_key: str,
    list_name: str,
    fallback_list: str = "Inbox",
) -> list[ProviderReceipt]:
    return find_reminders_by_marker(effect_key, list_name, fallback_list)


def create_reminder_with_marker(
    effect_key: str,
    text: str,
    list_name: str,
    fallback_list: str = "Inbox",
) -> ProviderReceipt:
    marker = _marker(effect_key)
    item = _escape_applescript(f"{marker} {str(text or '').strip()}", preserve_newlines=True)
    requested = _escape_applescript(list_name)
    fallback = _escape_applescript(fallback_list)
    script = f'''
tell application "Reminders"
    set actualName to "{requested}"
    if exists list "{requested}" then
        set targetList to list "{requested}"
    else
        set actualName to "{fallback}"
        set targetList to list "{fallback}"
    end if
    set createdReminder to make new reminder at end of targetList with properties {{name:"{_escape_applescript(str(text or '').strip(), preserve_newlines=True)}", body:"{item}"}}
    return ((id of createdReminder as text) & tab & actualName)
end tell
'''
    rows = _reminder_rows(_run_osascript(script), fallback_list)
    if not rows:
        raise AppleScriptError("provider_error", ambiguous=True)
    return rows[0]


def read_reminder_by_marker(
    effect_key: str,
    list_name: str,
    fallback_list: str = "Inbox",
) -> list[ProviderReceipt]:
    return find_reminders_by_marker(effect_key, list_name, fallback_list)


def add_note(text: str, folder_name: str = "Penny", source: str = "") -> bool:
    """Legacy boolean wrapper; kept for callers not yet on the receipt API."""
    del source
    safe_folder = _escape_applescript(folder_name)
    timestamp = _escape_applescript(datetime.now().strftime("%Y-%m-%d %H:%M"))
    body_html = "<br>" + html.escape(str(text or ""), quote=True)
    body_html = body_html.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    safe_body_html = _escape_applescript(body_html)
    script = f'''
tell application "Notes"
    set targetFolder to missing value
    repeat with f in folders
        if name of f is "{safe_folder}" then
            set targetFolder to f
            exit repeat
        end if
    end repeat
    if targetFolder is missing value then
        set targetFolder to (make new folder with properties {{name:"{safe_folder}"}})
    end if
    make new note at targetFolder with properties {{name:"{timestamp}", body:"{safe_body_html}"}}
end tell
'''
    try:
        _run_osascript(script)
        log.info("Legacy Apple note operation completed")
        return True
    except AppleScriptError as exc:
        log.error("Apple note operation failed code=%s", exc.code)
        return False


def add_reminder(item_text: str, list_name: str, fallback_list: str = "Inbox") -> bool:
    """Legacy boolean wrapper with redacted logs."""
    safe_item = _escape_applescript(item_text, preserve_newlines=True)
    safe_list = _escape_applescript(list_name)
    safe_fallback = _escape_applescript(fallback_list)
    script = f'''
tell application "Reminders"
    if exists list "{safe_list}" then
        set targetList to list "{safe_list}"
    else
        set targetList to list "{safe_fallback}"
    end if
    make new reminder at end of targetList with properties {{name:"{safe_item}"}}
end tell
'''
    try:
        _run_osascript(script)
        log.info("Legacy Apple reminder operation completed")
        return True
    except AppleScriptError as exc:
        log.error("Apple reminder operation failed code=%s", exc.code)
        return False
