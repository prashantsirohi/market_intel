from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    db_path: str = "./data/market_intel.duckdb"
    data_dir: str = "./data"

    telegram_bot_token: str = os.environ.get("TELEGRAM_BOT_TOKEN") or "8624342423:AAHhfybomXMcDXKZQ06HfPUspeEc6gsaMpk"
    telegram_chat_id: str  = os.environ.get("TELEGRAM_CHAT_ID") or "1282288492"

    alerts_enabled: bool = os.environ.get("ALERTS_ENABLED", "1").lower() in ("1", "true", "yes")
    critical_immediate: bool = True
    batch_interval_minutes: int = 15

    openrouter_api_key: str = os.environ.get("OPENROUTER_API_KEY", "") or "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"
    openrouter_model: str = "openrouter/free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_max_tokens: int = 1024

    pytesseract_cmd: str | None = os.environ.get("PYTESSERACT_CMD")

    scheduler_rss_interval_minutes: int = 5
    scheduler_api_interval_minutes: int = 15
    scheduler_llm_interval_minutes: int = 30
    scheduler_backfill_on_start: bool = False

    backfill_max_days: int = 30
    backfill_batch_size: int = 100

    def __post_init__(self) -> None:
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def openrouter_configured(self) -> bool:
        return bool(self.openrouter_api_key and self.openrouter_api_key.startswith("sk-or-v1-"))


def get_settings() -> Settings:
    return Settings()


settings = Settings()