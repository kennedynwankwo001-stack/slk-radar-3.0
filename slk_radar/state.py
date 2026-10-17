"""What the scanner remembers between runs: which messages were already sent, which setups are
waiting for their next-day reminder, and which H4 candle was last scanned. One small JSON file."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat()


class State:
    def __init__(self, path: str):
        self.path = path
        self.data: dict = {"sent": {}, "setups": {}, "last_boundary": None, "retry": [], "days": {}, "results": []}
        self.is_new = not os.path.exists(path)
        if not self.is_new:
            with open(path) as f:
                self.data.update(json.load(f))

    # ---- sent messages
    def was_sent(self, key: str) -> bool:
        return key in self.data["sent"]

    def mark_sent(self, key: str, when: datetime) -> None:
        self.data["sent"][key] = _iso(when)

    # ---- setups waiting for a reminder
    def add_setup(self, key: str, symbol: str, when: datetime, info: dict | None = None) -> None:
        v = {"symbol": symbol, "alerted": _iso(when), "reminded": False, "notified": True}
        v.update(info or {})
        self.data["setups"].setdefault(key, v)

    def has_setup(self, key: str) -> bool:
        v = self.data["setups"].get(key)
        return bool(v and v.get("notified") and not v.get("closed"))

    def close_setup(self, key: str, outcome: str, when: datetime) -> None:
        """Move a setup to the results list (kept for the scorecard)."""
        v = self.data["setups"].pop(key, None)
        if v is None:
            return
        self.data.setdefault("results", []).append({
            "key": key, "symbol": v["symbol"], "direction": v.get("direction"), "alerted": v["alerted"],
            "closed": _iso(when), "outcome": outcome, "sweep": v.get("sweep"), "external": v.get("external")})
        self.data["results"] = self.data["results"][-500:]

    # ---- alerts per Daily day (the daily cap)
    def day_count(self, day: datetime) -> int:
        return self.data.setdefault("days", {}).get(_iso(day), 0)

    def bump_day(self, day: datetime) -> None:
        d = self.data.setdefault("days", {})
        d[_iso(day)] = d.get(_iso(day), 0) + 1

    def due_reminders(self, daily_boundary: datetime) -> list[tuple[str, dict]]:
        """Setups alerted before the latest Daily close that have not been reminded yet."""
        out = []
        for k, v in self.data["setups"].items():
            if v.get("notified") and not v["reminded"] and datetime.fromisoformat(v["alerted"]) < daily_boundary:
                out.append((k, v))
        return out

    def mark_reminded(self, key: str) -> None:
        self.data["setups"][key]["reminded"] = True

    # ---- scan bookkeeping
    @property
    def last_boundary(self) -> str | None:
        return self.data.get("last_boundary")

    @last_boundary.setter
    def last_boundary(self, t: datetime) -> None:
        self.data["last_boundary"] = _iso(t)

    @property
    def retry(self) -> list[str]:
        return list(self.data.get("retry", []))

    @retry.setter
    def retry(self, pairs: list[str]) -> None:
        self.data["retry"] = list(pairs)

    def prune(self, now: datetime, days: int = 10) -> None:
        """Forget old keys so a new setup on the same level weeks later can alert again."""
        cut = _iso(now - timedelta(days=days))
        self.data["sent"] = {k: v for k, v in self.data["sent"].items() if v >= cut}
        self.data["setups"] = {k: v for k, v in self.data["setups"].items() if v["alerted"] >= cut}
        self.data["days"] = {k: v for k, v in self.data.get("days", {}).items() if k >= cut}

    def save(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=1, sort_keys=True)
        os.replace(tmp, self.path)
