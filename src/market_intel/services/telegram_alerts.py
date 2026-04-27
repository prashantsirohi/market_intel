from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from market_intel.storage import Database, AlertLogRepository, ResolvedEventRepository


logger = logging.getLogger(__name__)


@dataclass
class AlertMessage:
    resolved_event_id: int
    title: str
    symbol: Optional[str]
    category: str
    alert_level: str
    importance: float
    trust: float
    summary: Optional[str]
    link: Optional[str]


class TelegramAlertError(Exception):
    pass


class TelegramAlerter:
    def __init__(self, db: Database):
        self.db = db
        self.alert_repo = AlertLogRepository(db)
        self.resolved_repo = ResolvedEventRepository(db)
        self.bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram credentials not configured")

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def _send_message(self, text: str) -> bool:
        if not self.is_configured():
            logger.warning("Telegram not configured, skipping alert")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                return True
            logger.error("Telegram API error: %s", response.text)
            return False
        except requests.RequestException as exc:
            logger.error("Telegram request failed: %s", exc)
            return False

    def _format_message(self, alert: AlertMessage) -> str:
        emoji = self._get_emoji(alert.alert_level)

        lines = [
            f"{emoji} <b>{alert.alert_level.upper()}</b> - {alert.symbol or 'N/A'}",
            f"<b>{alert.title}</b>",
            f"Category: {alert.category}",
            f"Importance: {alert.importance:.1f} | Trust: {alert.trust:.0f}%",
        ]

        if alert.summary:
            lines.append(f"_{alert.summary}_")

        if alert.link:
            lines.append(f"<a href=\"{alert.link}\">View Details</a>")

        return "\n".join(lines)

    @staticmethod
    def _get_emoji(level: str) -> str:
        return {
            "critical": "🔴",
            "important": "🟡",
            "info": "🔵",
        }.get(level, "⚪")

    def send_alert(self, resolved_event_id: int) -> bool:
        resolved = self.resolved_repo.get_by_raw_id(resolved_event_id)
        if not resolved:
            logger.warning("Resolved event not found: %s", resolved_event_id)
            return False

        alert = AlertMessage(
            resolved_event_id=resolved.resolved_event_id,
            title=resolved.summary_text or "Corporate Filing",
            symbol=None,
            category=resolved.primary_category or "Unknown",
            alert_level=resolved.alert_level or "info",
            importance=resolved.importance_score or 0.0,
            trust=resolved.trust_score or 0.0,
            summary=resolved.summary_text,
            link=None,
        )

        message = self._format_message(alert)
        success = self._send_message(message)

        self.alert_repo.create(
            resolved_event_id=resolved.resolved_event_id,
            channel="telegram",
            alert_status="sent" if success else "failed",
            payload_json={"message": message},
        )

        return success

    def send_batch(self, resolved_event_ids: list[int]) -> dict[str, int]:
        if not resolved_event_ids:
            return {"sent": 0, "failed": 0, "skipped": 0}

        sent = 0
        failed = 0

        for event_id in resolved_event_ids:
            if self.alert_repo.is_duplicate(event_id, "telegram"):
                continue

            if self.send_alert(event_id):
                sent += 1
            else:
                failed += 1

        return {"sent": sent, "failed": failed, "skipped": len(resolved_event_ids) - sent - failed}


class AlertScheduler:
    def __init__(self, db: Database):
        self.db = db
        self.alerter = TelegramAlerter(db)
        self.alert_repo = AlertLogRepository(db)
        self.critical_immediate = True
        self.batch_interval_minutes = 15

    def check_and_send(self) -> dict[str, Any]:
        resolved_repo = ResolvedEventRepository(self.db)

        critical = resolved_repo.list_by_alert_level("critical", limit=10)
        important = resolved_repo.list_by_alert_level("important", limit=20)

        results = {"critical": 0, "important": 0, "failed": 0}

        for event in critical:
            if self.alert_repo.is_duplicate(event.resolved_event_id, "telegram"):
                continue

            if self.alerter.send_alert(event.raw_event_id):
                results["critical"] += 1
            else:
                results["failed"] += 1

        important_ids = [e.resolved_event_id for e in important if not self.alert_repo.is_duplicate(e.resolved_event_id, "telegram")]

        if important_ids:
            batch_result = self.alerter.send_batch(important_ids)
            results["important"] = batch_result.get("sent", 0)
            results["failed"] += batch_result.get("failed", 0)

        return results