"""HTTP client for Penny's single shared Whisper supervisor."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import requests

from .protocol import (
    ClientKind,
    WhisperResult,
    WhisperUnavailable,
    decode_response,
    request_headers,
)


class SharedWhisperClient:
    """Submit one audio file without ever importing or loading MLX."""

    def __init__(
        self,
        *,
        base_url: str,
        auth_token: str,
        model_id: str,
        model_revision: str,
        timeout: float = 90.0,
        client_kind: ClientKind = ClientKind.PENNY,
        post: Callable[..., Any] = requests.post,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.model_id = model_id
        self.model_revision = model_revision
        self.timeout = max(1.0, float(timeout))
        self.client_kind = ClientKind(client_kind)
        self._post = post

    def transcribe(self, path: Path, **options: Any) -> WhisperResult:
        """Submit a request and validate the pinned model identity."""

        headers = request_headers(self.client_kind)
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        data = {
            "model": self.model_id,
            "response_format": "verbose_json",
            **options,
        }
        try:
            with path.open("rb") as audio_file:
                response = self._post(
                    f"{self.base_url}/audio/transcriptions",
                    headers=headers,
                    files={"file": (path.name, audio_file)},
                    data=data,
                    timeout=self.timeout,
                )
            payload = response.json()
        except requests.RequestException as exc:
            raise WhisperUnavailable("shared Whisper service is unreachable") from exc
        except (OSError, ValueError) as exc:
            raise RuntimeError("shared Whisper request could not be prepared") from exc
        return decode_response(
            response.status_code,
            payload,
            expected_model_id=self.model_id,
            expected_revision=self.model_revision,
        )
