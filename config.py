#!/usr/bin/env python3
"""
Penny configuration loader.

Loads config.toml for non-secret settings.
Reads secrets from environment variables (set in launchd plist or local secrets.env).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        sys.exit("ERROR: Python 3.11+ required (or: pip install tomli)")

CONFIG_PATH = Path(__file__).parent / "config.toml"

_config: "Config | None" = None


@dataclass
class LLMConfig:
    model: str


@dataclass
class GoogleTasksConfig:
    list_name: str
    poll_interval_seconds: int


@dataclass
class AppleRemindersConfig:
    lists: List[str]
    default_list: str


@dataclass
class VoiceMemosConfig:
    max_file_size_mb: int
    whisper_model: str
    poll_interval_seconds: int
    startup_process_limit: int


@dataclass
class WebhookConfig:
    port: int
    host: str
    ingest_token: str
    max_request_bytes: int


@dataclass
class LoggingConfig:
    level: str


@dataclass
class NotificationsConfig:
    telegram_enabled: bool


@dataclass
class MayaConfig:
    transcript_url: str = ""
    ingest_token: str = ""
    delivery_timeout_seconds: float = 10.0


@dataclass
class Config:
    llm: LLMConfig
    google_tasks: GoogleTasksConfig
    apple_reminders: AppleRemindersConfig
    voice_memos: VoiceMemosConfig
    webhook: WebhookConfig
    logging: LoggingConfig
    notifications: NotificationsConfig
    maya: MayaConfig
    # Secrets — from environment variables
    openrouter_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    google_credentials_file: Path
    google_token_file: Path


def get_config() -> Config:
    global _config
    if _config is not None:
        return _config

    if not CONFIG_PATH.exists():
        sys.exit(f"ERROR: config.toml not found at {CONFIG_PATH}")

    with open(CONFIG_PATH, "rb") as f:
        raw = tomllib.load(f)

    notifications_enabled = raw.get("notifications", {}).get("telegram_enabled", True)

    def env(key: str, default: str = "", warn_if_missing: bool = True) -> str:
        val = os.environ.get(key, default)
        if not val and warn_if_missing:
            print(f"WARNING: {key} not set in environment", file=sys.stderr)
        return val

    # Env vars win so the ingest token stays out of the repo-managed toml.
    maya_section = raw.get("maya", {})
    raw_maya_timeout = os.environ.get(
        "MAYA_DELIVERY_TIMEOUT_SECONDS",
        str(maya_section.get("delivery_timeout_seconds", 10.0)),
    )
    try:
        maya_timeout = float(raw_maya_timeout)
    except (TypeError, ValueError):
        maya_timeout = 10.0
    maya_timeout = max(1.0, min(maya_timeout, 30.0))

    maya = MayaConfig(
        transcript_url=os.environ.get(
            "MAYA_TRANSCRIPT_URL", maya_section.get("transcript_url", "")
        ),
        ingest_token=os.environ.get(
            "MAYA_INGEST_TOKEN", maya_section.get("ingest_token", "")
        ),
        delivery_timeout_seconds=maya_timeout,
    )

    _config = Config(
        llm=LLMConfig(
            model=raw["llm"]["model"],
        ),
        google_tasks=GoogleTasksConfig(
            list_name=raw["google_tasks"]["list_name"],
            poll_interval_seconds=raw["google_tasks"]["poll_interval_seconds"],
        ),
        apple_reminders=AppleRemindersConfig(
            lists=raw["apple_reminders"]["lists"],
            default_list=raw["apple_reminders"]["default_list"],
        ),
        voice_memos=VoiceMemosConfig(
            max_file_size_mb=raw["voice_memos"]["max_file_size_mb"],
            whisper_model=raw["voice_memos"]["whisper_model"],
            poll_interval_seconds=raw["voice_memos"]["poll_interval_seconds"],
            startup_process_limit=raw["voice_memos"]["startup_process_limit"],
        ),
        webhook=WebhookConfig(
            port=raw["webhook"]["port"],
            host=os.environ.get("PENNY_WEBHOOK_HOST", raw["webhook"]["host"]),
            ingest_token=env("PENNY_INGEST_TOKEN"),
            max_request_bytes=(raw["voice_memos"]["max_file_size_mb"] + 1)
            * 1024
            * 1024,
        ),
        logging=LoggingConfig(
            level=raw["logging"]["level"],
        ),
        notifications=NotificationsConfig(
            telegram_enabled=notifications_enabled,
        ),
        maya=maya,
        openrouter_api_key=env("OPENROUTER_API_KEY"),
        telegram_bot_token=env("TELEGRAM_BOT_TOKEN", warn_if_missing=notifications_enabled),
        telegram_chat_id=env("TELEGRAM_CHAT_ID", warn_if_missing=notifications_enabled),
        google_credentials_file=Path(
            os.environ.get("GOOGLE_CREDENTIALS_FILE", "~/.penny/google_credentials.json")
        ).expanduser(),
        google_token_file=Path(
            os.environ.get("GOOGLE_TOKEN_FILE", "~/.penny/google_token.json")
        ).expanduser(),
    )
    return _config
