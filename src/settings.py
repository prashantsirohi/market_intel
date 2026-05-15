from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_env_file() -> None:
    for env_path in [Path(__file__).parent / ".env", Path(__file__).parent.parent / ".env"]:
        if env_path.exists():
            for line in env_path.read_text().strip().splitlines():
                if "=" in line:
                    key, val = line.split("=", 1)
                    if key and val:
                        os.environ.setdefault(key, val)
            break


_load_env_file()


@dataclass
class Settings:
    db_path: str = "./data/market_intel.duckdb"
    data_dir: str = "./data"

    telegram_bot_token: str | None = field(default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN"))
    telegram_chat_id: str | None = field(default_factory=lambda: os.environ.get("TELEGRAM_CHAT_ID"))

    alerts_enabled: bool = field(default_factory=lambda: os.environ.get("ALERTS_ENABLED", "1").lower() in ("1", "true", "yes"))
    critical_immediate: bool = True
    batch_interval_minutes: int = 15

    openrouter_api_key: str | None = field(default_factory=lambda: os.environ.get("OPENROUTER_API_KEY"))
    openrouter_model: str = "deepseek/deepseek-v4-flash:free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_max_tokens: int = 1024

    pytesseract_cmd: str | None = field(default_factory=lambda: os.environ.get("PYTESSERACT_CMD"))

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

    @property
    def ocr_available(self) -> bool:
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False


def get_settings() -> Settings:
    return Settings()


settings = Settings()