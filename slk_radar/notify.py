"""Sending messages: Telegram, or print for a dry run. The bot token never appears in errors."""
from __future__ import annotations

import json
import urllib.error
import urllib.request


class NotifyError(Exception):
    pass


class PrintNotifier:
    """Dry run: show what would be sent."""

    def __init__(self):
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)
        print("-" * 60)
        print(text)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, opener=urllib.request.urlopen):
        self._token = token
        self.chat_id = chat_id
        self._open = opener
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        body = json.dumps({"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with self._open(req, timeout=20) as r:
                ok = json.load(r).get("ok", False)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            raise NotifyError(f"Telegram send failed ({type(e).__name__})") from None
        if not ok:
            raise NotifyError("Telegram refused the message")
        self.sent.append(text)

    def get_updates(self, offset: int | None = None) -> list[dict]:
        """New messages sent to the bot (only used for the /entry and /radar commands)."""
        url = f"https://api.telegram.org/bot{self._token}/getUpdates?timeout=0" + (f"&offset={offset}" if offset else "")
        try:
            with self._open(urllib.request.Request(url), timeout=20) as r:
                data = json.load(r)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            raise NotifyError(f"Telegram read failed ({type(e).__name__})") from None
        return data.get("result", []) if data.get("ok") else []
