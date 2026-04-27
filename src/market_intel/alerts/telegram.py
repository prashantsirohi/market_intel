from __future__ import annotations

import requests


class TelegramAlert:
    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id

    def send(self, message: str) -> int:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": message}
        resp = requests.post(url, json=payload, timeout=20)
        resp.raise_for_status()
        return resp.status_code