"""Allowlisted, metadata-only workflow artifacts.

Workflow artifacts are safe coordination records, not content containers.  The
boundary is deliberately small: callers may persist or forward identifiers,
requirements, decisions, references, commands, statuses, summarized findings,
and explicit placeholders.  Audio, transcript, provider, credential, token,
and personal-message content is rejected without including the value in the
exception.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

ARTIFACT_TYPES = frozenset({"plan", "progress", "review_prompt", "verification"})

# This is also the machine-readable contract used by integrations that need to
# inspect the boundary without importing implementation details.
WORKFLOW_ARTIFACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["artifact_type", "artifact_id"],
    "additionalProperties": False,
    "properties": {
        "artifact_type": {"enum": sorted(ARTIFACT_TYPES)},
        "artifact_id": {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"},
        "metadata": {"type": "object", "additionalProperties": False},
        "identifiers": {"type": "object", "additionalProperties": False},
        "requirements": {"type": "array", "items": {"type": "string", "maxLength": 512}},
        "decisions": {"type": "array", "items": {"type": "string", "maxLength": 512}},
        "file_refs": {"type": "array", "items": {"type": "string", "maxLength": 512}},
        "symbol_refs": {"type": "array", "items": {"type": "string", "maxLength": 256}},
        "commands": {"type": "array", "items": {"type": "string", "maxLength": 512}},
        "statuses": {"type": "object", "additionalProperties": False},
        "findings": {"type": "object", "additionalProperties": False},
        "placeholders": {"type": "object", "additionalProperties": False},
    },
}

_ALLOWED_FIELDS = frozenset(WORKFLOW_ARTIFACT_SCHEMA["properties"])
_METADATA_FIELDS = frozenset(
    {"source", "owner", "scope", "revision", "parent_id", "created_at", "updated_at", "labels"}
)
_IDENTIFIER_FIELDS = frozenset(
    {"id", "row_id", "delivery_id", "request_id", "artifact_id", "source_id", "backup_set_id", "catalog_sha256"}
)
_STATUS_FIELDS = frozenset({"state", "status", "outcome", "result", "valid", "complete"})
_SENSITIVE_TERMS = frozenset(
    {
        "audio",
        "credential",
        "credentials",
        "cookie",
        "message",
        "password",
        "personal",
        "payload",
        "provider",
        "response",
        "secret",
        "token",
        "transcript",
        "transcription",
    }
)
_PLACEHOLDER_RE = re.compile(
    r"^(?:<|\[)(?:redacted|placeholder)(?::[a-z0-9_-]+)?(?:>|\])$", re.IGNORECASE
)
_SAFE_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")
_SAFE_STRING_RE = re.compile(r"^[^\x00-\x1f\x7f]{0,512}$")
_SECRET_VALUE_RE = re.compile(
    r"(?:bearer\s+[A-Za-z0-9._~-]{8,}|(?:sk|xox[baprs]|ghp|github_pat)[_-][A-Za-z0-9_-]{8,}|-----BEGIN [A-Z ]+-----)",
    re.IGNORECASE,
)


class WorkflowArtifactError(ValueError):
    """A metadata-only workflow artifact violated the allowlist."""

    def __init__(self, *, artifact_type: str, field: str, reason: str) -> None:
        self.artifact_type = artifact_type
        self.field = field
        self.reason = reason
        # Never include the rejected value.  This exception is safe for logs.
        super().__init__(f"workflow_artifact_rejected category={artifact_type} field={field} reason={reason}")


def _reject(artifact_type: str, field: str, reason: str) -> None:
    raise WorkflowArtifactError(artifact_type=artifact_type, field=field, reason=reason)


def _field_has_sensitive_term(field: str) -> str | None:
    terms = re.split(r"[^a-z0-9]+", field.casefold())
    for term in terms:
        if term in _SENSITIVE_TERMS:
            return term
    return None


def _validate_string(value: Any, *, artifact_type: str, field: str, limit: int = 512) -> str:
    if not isinstance(value, str):
        _reject(artifact_type, field, "string_required")
    if len(value) > limit or not _SAFE_STRING_RE.fullmatch(value):
        _reject(artifact_type, field, "string_invalid")
    sensitive_term = _field_has_sensitive_term(field)
    if sensitive_term is not None and not _PLACEHOLDER_RE.fullmatch(value.strip()):
        _reject(artifact_type, field, f"sensitive_category:{sensitive_term}")
    if _SECRET_VALUE_RE.search(value):
        _reject(artifact_type, field, "sensitive_category:credential")
    return value


def _validate_scalar_map(
    value: Any,
    *,
    artifact_type: str,
    field: str,
    allowed_keys: frozenset[str] | None = None,
    allow_sensitive_keys: bool = False,
    depth: int = 0,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _reject(artifact_type, field, "object_required")
    if depth > 4:
        _reject(artifact_type, field, "nesting_too_deep")
    result: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str) or not _SAFE_KEY_RE.fullmatch(raw_key):
            _reject(artifact_type, field, "key_invalid")
        key = raw_key
        sensitive_term = _field_has_sensitive_term(key)
        if sensitive_term is not None and not allow_sensitive_keys:
            _reject(artifact_type, f"{field}.{key}", f"sensitive_category:{sensitive_term}")
        if allowed_keys is not None and key not in allowed_keys:
            _reject(artifact_type, f"{field}.{key}", "field_not_allowlisted")
        child_field = f"{field}.{key}"
        if isinstance(raw_value, bool) or raw_value is None or isinstance(raw_value, (int, float)):
            result[key] = raw_value
        elif isinstance(raw_value, str):
            result[key] = _validate_string(raw_value, artifact_type=artifact_type, field=child_field)
        elif isinstance(raw_value, Mapping):
            result[key] = _validate_scalar_map(
                raw_value,
                artifact_type=artifact_type,
                field=child_field,
                allow_sensitive_keys=allow_sensitive_keys,
                depth=depth + 1,
            )
        elif isinstance(raw_value, list) and all(isinstance(item, str) for item in raw_value):
            result[key] = [
                _validate_string(item, artifact_type=artifact_type, field=child_field)
                for item in raw_value
            ]
        else:
            _reject(artifact_type, child_field, "scalar_or_string_list_required")
    return result


def validate_workflow_artifact(
    artifact: Mapping[str, Any],
    *,
    expected_type: str | None = None,
) -> dict[str, Any]:
    """Validate and return a detached metadata-only artifact.

    Errors identify only the artifact category, field, and rejection reason;
    rejected values are never copied into an exception or log message.
    """

    if not isinstance(artifact, Mapping):
        _reject(expected_type or "unknown", "artifact", "object_required")
    raw_type = artifact.get("artifact_type")
    artifact_type = raw_type if isinstance(raw_type, str) else (expected_type or "unknown")
    if artifact_type not in ARTIFACT_TYPES:
        _reject(str(artifact_type), "artifact_type", "value_not_allowlisted")
    if expected_type is not None and artifact_type != expected_type:
        _reject(artifact_type, "artifact_type", "unexpected_category")
    unknown = set(artifact) - _ALLOWED_FIELDS
    if unknown:
        key = sorted(str(item) for item in unknown)[0]
        _reject(artifact_type, key, "field_not_allowlisted")
    artifact_id = artifact.get("artifact_id")
    if not isinstance(artifact_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", artifact_id):
        _reject(artifact_type, "artifact_id", "identifier_invalid")

    result: dict[str, Any] = {"artifact_type": artifact_type, "artifact_id": artifact_id}
    if "metadata" in artifact:
        result["metadata"] = _validate_scalar_map(
            artifact["metadata"], artifact_type=artifact_type, field="metadata", allowed_keys=_METADATA_FIELDS
        )
    if "identifiers" in artifact:
        result["identifiers"] = _validate_scalar_map(
            artifact["identifiers"], artifact_type=artifact_type, field="identifiers", allowed_keys=_IDENTIFIER_FIELDS
        )
    for field in ("requirements", "decisions", "file_refs", "symbol_refs", "commands"):
        if field not in artifact:
            continue
        raw_values = artifact[field]
        if not isinstance(raw_values, list):
            _reject(artifact_type, field, "list_required")
        limit = 256 if field == "symbol_refs" else 512
        result[field] = [
            _validate_string(item, artifact_type=artifact_type, field=field, limit=limit)
            for item in raw_values
        ]
    for field, allowed_keys in (("statuses", _STATUS_FIELDS), ("findings", None)):
        if field in artifact:
            result[field] = _validate_scalar_map(
                artifact[field], artifact_type=artifact_type, field=field, allowed_keys=allowed_keys
            )
    if "placeholders" in artifact:
        placeholders = _validate_scalar_map(
            artifact["placeholders"],
            artifact_type=artifact_type,
            field="placeholders",
            allow_sensitive_keys=True,
        )
        for key, value in placeholders.items():
            if not isinstance(value, str) or not _PLACEHOLDER_RE.fullmatch(value):
                _reject(artifact_type, f"placeholders.{key}", "placeholder_required")
        result["placeholders"] = placeholders
    return json.loads(json.dumps(result, sort_keys=True))


def build_review_prompt_artifact(*, artifact_id: str, source_id: str | None = None) -> dict[str, Any]:
    """Build the only prompt shape allowed across the external-agent boundary."""

    artifact: dict[str, Any] = {
        "artifact_type": "review_prompt",
        "artifact_id": artifact_id,
        "requirements": ["Review the referenced work item using metadata only."],
        "placeholders": {"private_content": "<redacted:personal-content>"},
    }
    if source_id is not None:
        artifact["identifiers"] = {"source_id": source_id}
    return validate_workflow_artifact(artifact, expected_type="review_prompt")


def serialize_workflow_artifact(artifact: Mapping[str, Any], *, expected_type: str | None = None) -> str:
    """Validate before serialization for persistence or external forwarding."""

    validated = validate_workflow_artifact(artifact, expected_type=expected_type)
    return json.dumps(validated, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "ARTIFACT_TYPES",
    "WORKFLOW_ARTIFACT_SCHEMA",
    "WorkflowArtifactError",
    "build_review_prompt_artifact",
    "serialize_workflow_artifact",
    "validate_workflow_artifact",
]
