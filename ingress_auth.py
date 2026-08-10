from __future__ import annotations

import hmac

from flask import Request


MAX_INGEST_TEXT_BYTES = 65_536


def authorize_bearer(request: Request, expected_token: str) -> bool:
    if not expected_token:
        return False
    header = request.headers.get("Authorization", "")
    scheme, separator, supplied = header.partition(" ")
    return bool(
        separator
        and scheme.lower() == "bearer"
        and supplied
        and hmac.compare_digest(supplied, expected_token)
    )
