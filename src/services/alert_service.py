from __future__ import annotations


class AlertService:
    def __init__(self, alert_repo, telegram_client, dry_run: bool = False) -> None:
        self.alert_repo = alert_repo
        self.telegram_client = telegram_client
        self.dry_run = dry_run
        self.batched: list[dict] = []

    def route(self, resolved_event: dict, channel: str = "telegram") -> None:
        level = resolved_event.get("alert_level")
        if level == "critical":
            self.send_if_needed(resolved_event, channel)
        elif level in {"important", "info"}:
            self.batched.append(resolved_event)

    def flush_batched(self, channel: str = "telegram") -> None:
        important = [e for e in self.batched if e.get("alert_level") == "important"]
        if not important:
            self.batched.clear()
            return
        summary = [f"IMPORTANT alerts this run: {len(important)}"]
        for event in important[:20]:
            summary.append(f"- {event.get('symbol')}: {event.get('summary_text')}")
        message = "\n".join(summary)
        if not self.dry_run and self.telegram_client:
            self.telegram_client.send(message)
        self.batched.clear()

    def send_if_needed(self, resolved_event: dict, channel: str = "telegram") -> None:
        if resolved_event["alert_level"] not in {"critical", "important"}:
            return
        if self.alert_repo.already_sent(resolved_event["resolved_event_id"], channel):
            return
        payload = {
            "symbol": resolved_event.get("symbol"),
            "category": resolved_event.get("primary_category"),
            "alert_level": resolved_event.get("alert_level"),
            "summary_text": resolved_event.get("summary_text"),
        }
        alert_id = self.alert_repo.create_pending(resolved_event["resolved_event_id"], channel, payload)
        try:
            if not self.dry_run and self.telegram_client:
                self.telegram_client.send(self._build_message(payload))
            self.alert_repo.mark_sent(alert_id)
        except Exception as exc:
            self.alert_repo.mark_failed(alert_id, str(exc))
            raise

    def _build_message(self, payload: dict) -> str:
        prefix = "CRITICAL" if payload["alert_level"] == "critical" else "IMPORTANT"
        return f"{prefix} Alert\nSymbol: {payload.get('symbol')}\nCategory: {payload.get('category')}\n{payload.get('summary_text')}"