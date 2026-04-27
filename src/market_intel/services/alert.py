from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import requests
from market_intel.settings import Settings
from market_intel.storage.repositories import (
    AlertLog,
    AlertLogRepository,
    ResolvedEvent,
    ResolvedEventRepository,
)

logger = logging.getLogger(__name__)


@dataclass
class AlertMessage:
    resolved_event_id: int
    title: str
    symbol: str | None
    category: str
    alert_level: str
    importance: float
    trust: float
    summary: str | None
    link: str | None


class TelegramAlerter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.bot_token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id

    def is_configured(self) -> bool:
        return self.settings.telegram_configured

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
        emoji = {
            "critical": "🔴",
            "important": "🟡",
            "info": "🔵",
        }.get(alert.alert_level, "⚪")

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


class AlertService:
    def __init__(
        self,
        settings: Settings,
        resolved_repo: ResolvedEventRepository,
        alert_repo: AlertLogRepository,
    ):
        self.settings = settings
        self.resolved_repo = resolved_repo
        self.alert_repo = alert_repo
        self.alerter = TelegramAlerter(settings)

    def send_critical(self, resolved_event: ResolvedEvent) -> bool:
        alert = AlertMessage(
            resolved_event_id=resolved_event.resolved_event_id,
            title=resolved_event.summary_text or "Corporate Filing",
            symbol=None,
            category=resolved_event.primary_category or "Unknown",
            alert_level=resolved_event.alert_level or "info",
            importance=resolved_event.importance_score or 0.0,
            trust=resolved_event.trust_score or 0.0,
            summary=resolved_event.summary_text,
            link=None,
        )

        if self.alert_repo.is_duplicate(resolved_event.resolved_event_id, "telegram"):
            logger.debug(f"Alert already sent: {resolved_event.resolved_event_id}")
            return True

        message = self._format_message(alert)
        success = self.alerter._send_message(message)

        self.alert_repo.create(
            resolved_event_id=resolved_event.resolved_event_id,
            channel="telegram",
            alert_status="sent" if success else "failed",
            payload_json='{"message": ' + repr(message) + '}',
        )

        return success

    def route(self) -> dict[str, int]:
        if not self.settings.alerts_enabled:
            logger.info("Alerts disabled, skipping")
            return {"critical": 0, "important": 0, "info": 0, "skipped": 1}

        stats = {"critical": 0, "important": 0, "info": 0, "failed": 0}

        critical_events = self.resolved_repo.list_by_alert_level("critical", limit=10)
        important_events = self.resolved_repo.list_by_alert_level("important", limit=20)

        for event in critical_events:
            if self.alert_repo.is_duplicate(event.resolved_event_id, "telegram"):
                continue
            if self.send_critical(event):
                stats["critical"] += 1
            else:
                stats["failed"] += 1

        important_ids = [
            e.resolved_event_id
            for e in important_events
            if not self.alert_repo.is_duplicate(e.resolved_event_id, "telegram")
        ]

        if self.settings.critical_immediate:
            logger.info(
                f"Batch mode: {len(important_ids)} important events queued (send with --flush)"
            )
        else:
            for event in important_events:
                if self.alert_repo.is_duplicate(event.resolved_event_id, "telegram"):
                    continue
                if self.send_critical(event):
                    stats["important"] += 1

        return stats

    def flush_batched(self) -> dict[str, int]:
        if not self.settings.alerts_enabled:
            return {"sent": 0, "failed": 0}

        important_events = self.resolved_repo.list_by_alert_level("important", limit=20)
        stats = {"sent": 0, "failed": 0}

        for event in important_events:
            if self.alert_repo.is_duplicate(event.resolved_event_id, "telegram"):
                continue
            if self.send_critical(event):
                stats["sent"] += 1
            else:
                stats["failed"] += 1

        return stats

    def _format_message(self, alert: AlertMessage) -> str:
        return self.alerter._format_message(alert)