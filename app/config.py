"""Settings, read from the environment (and a .env file). Values are never logged."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _flag(name: str, default: str) -> bool:
    return _str(name, default) == "1"


def _int(name: str, default: int) -> int:
    raw = _str(name)
    return int(raw) if raw.isdigit() else default


@dataclass(frozen=True)
class Settings:
    # Brain: Cerebras models, or a scripted stand-in with OFFLINE_MODE=1 (Kane always runs for real)
    offline_mode: bool = field(default_factory=lambda: _flag("OFFLINE_MODE", "0"))
    cerebras_api_key: str = field(default_factory=lambda: _str("CEREBRAS_API_KEY"))
    cerebras_base_url: str = field(default_factory=lambda: _str("CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1"))
    persona_model: str = field(default_factory=lambda: _str("PERSONA_MODEL", "gpt-oss-120b"))
    flag_model: str = field(default_factory=lambda: _str("FLAG_MODEL", "qwen-3.8-27b"))
    persona_rpm: int = field(default_factory=lambda: _int("CEREBRAS_RPM_OSS", 5))
    flag_rpm: int = field(default_factory=lambda: _int("CEREBRAS_RPM_QWEN", 5))

    # OpenAI: Decisions second opinion, moderation, report fallback, live voice on phone calls (optional; features
    # that need it report themselves unavailable without it)
    openai_api_key: str = field(default_factory=lambda: _str("OPENAI_API_KEY"))
    decisions_model: str = field(default_factory=lambda: _str("DECISIONS_MODEL", "gpt-6-luna"))
    live_model: str = field(default_factory=lambda: _str("LIVE_MODEL", "gpt-live-1"))

    # Phone calls (Twilio). The auth token verifies X-Twilio-Signature on every webhook.
    twilio_account_sid: str = field(default_factory=lambda: _str("TWILIO_ACCOUNT_SID"))
    twilio_auth_token: str = field(default_factory=lambda: _str("TWILIO_AUTH_TOKEN"))
    twilio_phone_number: str = field(default_factory=lambda: _str("TWILIO_PHONE_NUMBER"))
    call_batch_seconds: int = field(default_factory=lambda: _int("CALL_BATCH_SECONDS", 20))

    # Storage
    db_path: str = field(default_factory=lambda: _str("DB_PATH", "scambait.db"))
    data_dir: str = field(default_factory=lambda: _str("DATA_DIR", "out"))

    # Server
    public_base_url: str = field(default_factory=lambda: _str("PUBLIC_BASE_URL").rstrip("/"))
    api_key: str = field(default_factory=lambda: _str("API_KEY"))
    console_enabled: bool = field(default_factory=lambda: _flag("CONSOLE_ENABLED", "1"))

    # Telegram
    telegram_bot_token: str = field(default_factory=lambda: _str("TELEGRAM_BOT_TOKEN"))
    telegram_webhook_secret: str = field(default_factory=lambda: _str("TELEGRAM_WEBHOOK_SECRET"))
    telegram_auto_webhook: bool = field(default_factory=lambda: _flag("TELEGRAM_AUTO_WEBHOOK", "1"))

    # Kane investigator
    kane_enabled: bool = field(default_factory=lambda: _flag("KANE_ENABLED", "1"))
    kane_cmd: str = field(default_factory=lambda: _str("KANE_CMD", "kane-cli"))
    kane_timeout_s: int = field(default_factory=lambda: _int("KANE_TIMEOUT_S", 240))
    kane_max_steps: int = field(default_factory=lambda: _int("KANE_MAX_STEPS", 40))
    kane_headless: bool = field(default_factory=lambda: _flag("KANE_HEADLESS", "1"))
    kane_workdir: str = field(default_factory=lambda: _str("KANE_WORKDIR", "out/kane"))
    kane_username: str = field(default_factory=lambda: _str("KANE_USERNAME"))
    kane_access_key: str = field(default_factory=lambda: _str("KANE_ACCESS_KEY"))
    live_investigation: bool = field(default_factory=lambda: _flag("LIVE_INVESTIGATION", "0"))

    def missing(self) -> list[str]:
        """Names of required settings that are empty."""
        return [] if self.offline_mode or self.cerebras_api_key else ["CEREBRAS_API_KEY"]


def get_settings() -> Settings:
    return Settings()
