"""Twelve Data client (standard library only) and the on-disk H1 candle cache.

The radar builds Daily and H4 candles from H1 candles (see candles.py), so one H1 request per
pair is enough. The API key is never written to files or error messages.
"""
from __future__ import annotations

import csv
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from .candles import _dedupe, load_csv, market_closed, parse_time
from .models import Candle
from .pairs import td_symbol

API = "https://api.twelvedata.com/time_series"
MAX_ROWS = 5000
KEEP_ROWS = 4200          # cached H1 rows per pair (weekend hours are not cached)


class DataError(Exception):
    """A data problem. The message never contains the API key."""


def parse_values(payload: dict) -> list[Candle]:
    """Turn a Twelve Data JSON answer into candles (oldest first)."""
    if payload.get("status") == "error" or "values" not in payload:
        raise DataError(f"Twelve Data error {payload.get('code')}: {payload.get('message')}")
    out = [
        Candle(
            time=parse_time(v["datetime"]),
            open=float(v["open"]),
            high=float(v["high"]),
            low=float(v["low"]),
            close=float(v["close"]),
        )
        for v in payload["values"]
    ]
    out.sort(key=lambda c: c.time)
    return out


def fetch_h1(
    pair: str,
    api_key: str,
    outputsize: int = MAX_ROWS,
    opener=urllib.request.urlopen,
    retries: int = 3,
    wait: float = 62.0,
    sleep=time.sleep,
) -> list[Candle]:
    """Fetch H1 candles (UTC). Waits and retries when the per-minute limit is hit (code 429)."""
    q = {
        "symbol": td_symbol(pair),
        "interval": "1h",
        "outputsize": min(int(outputsize), MAX_ROWS),
        "timezone": "UTC",
        "format": "JSON",
        "apikey": api_key,
    }
    url = API + "?" + urllib.parse.urlencode(q)
    last_err = "unknown"
    for attempt in range(retries):
        try:
            with opener(url, timeout=30) as r:
                payload = json.load(r)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            last_err = type(e).__name__
            sleep(5 * (attempt + 1))
            continue
        if payload.get("code") == 429:
            last_err = "rate limit (429)"
            sleep(wait)
            continue
        return parse_values(payload)
    raise DataError(f"{pair}: could not fetch candles ({last_err})")


# --------------------------------------------------------------------------- cache


def cache_path(cache_dir: str, pair: str) -> str:
    return os.path.join(cache_dir, f"{pair}_H1.csv")


def load_cache(cache_dir: str, pair: str) -> list[Candle]:
    p = cache_path(cache_dir, pair)
    return load_csv(p) if os.path.exists(p) else []


def save_cache(cache_dir: str, pair: str, candles: list[Candle]) -> None:
    os.makedirs(cache_dir, exist_ok=True)
    keep = [c for c in _dedupe(sorted(candles, key=lambda c: c.time)) if not market_closed(c.time)]
    keep = keep[-KEEP_ROWS:]
    tmp = cache_path(cache_dir, pair) + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close"])
        for c in keep:
            w.writerow([c.time.isoformat(), repr(c.open), repr(c.high), repr(c.low), repr(c.close)])
    os.replace(tmp, cache_path(cache_dir, pair))


def rows_needed(cached: list[Candle], now: datetime) -> int:
    """How many H1 rows to ask for: a full history for a new pair, otherwise just enough to cover
    the gap since the last cached candle (the feed also sends weekend hours, hence the margin)."""
    if not cached:
        return MAX_ROWS
    gap_h = max(1, int((now - cached[-1].time) / timedelta(hours=1)))
    return min(MAX_ROWS, int(gap_h * 1.5) + 36)


def update_candles(
    pair: str, api_key: str, cache_dir: str, now: datetime | None = None, fetch=fetch_h1
) -> list[Candle]:
    """Merge fresh candles into the cache and return all cached candles."""
    now = now or datetime.now(timezone.utc)
    cached = load_cache(cache_dir, pair)
    fresh = fetch(pair, api_key, rows_needed(cached, now))
    merged = _dedupe(sorted(cached + fresh, key=lambda c: c.time))
    save_cache(cache_dir, pair, merged)
    return load_cache(cache_dir, pair)
