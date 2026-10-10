"""Candle loading and aggregation.

Daily and H4 candles are built from H1 candles aligned to 17:00 America/New_York, the same
boundary TradingView uses for forex. That makes the radar see the same candles as the chart:
Daily closes at 17:00 New York (21:00 UTC in summer, 22:00 UTC in winter) and H4 bars start at
17, 21, 01, 05, 09 and 13 New York time.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .models import Candle

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
SHIFT = timedelta(hours=7)  # shifting New York local time by +7h moves 17:00 to 00:00


def parse_time(value: str) -> datetime:
    """Parse an epoch (seconds or ms) or an ISO date/time. Naive times are taken as UTC."""
    s = str(value).strip()
    try:
        x = float(s)
        if x > 1e11:  # milliseconds
            x /= 1000.0
        return datetime.fromtimestamp(x, tz=UTC)
    except ValueError:
        pass
    s = s.replace("Z", "+00:00").replace("z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def load_csv(path: str) -> list[Candle]:
    """Load candles from a CSV with columns time/datetime/date, open, high, low, close."""
    out: list[Candle] = []
    with open(path, newline="") as f:
        first = f.readline()
        f.seek(0)
        delim = ";" if first.count(";") > first.count(",") else ","  # Twelve Data CSV uses ";"
        reader = csv.DictReader(f, delimiter=delim)
        if reader.fieldnames is None:
            return out
        names = {n.strip().lower(): n for n in reader.fieldnames}
        tkey = next((names[k] for k in ("time", "datetime", "date", "timestamp") if k in names), None)
        if tkey is None or not all(k in names for k in ("open", "high", "low", "close")):
            raise ValueError("CSV needs columns: time (or datetime/date), open, high, low, close")
        for row in reader:
            out.append(
                Candle(
                    time=parse_time(row[tkey]),
                    open=float(row[names["open"]]),
                    high=float(row[names["high"]]),
                    low=float(row[names["low"]]),
                    close=float(row[names["close"]]),
                )
            )
    out.sort(key=lambda c: c.time)
    return _dedupe(out)


def _dedupe(candles: list[Candle]) -> list[Candle]:
    seen: dict[datetime, Candle] = {}
    for c in candles:
        seen[c.time] = c  # later duplicates win
    return [seen[t] for t in sorted(seen)]


def bucket_start(t_utc: datetime, hours: int) -> datetime:
    """Start (UTC) of the 17:00-New-York-aligned bucket of `hours` (4 or 24) containing t."""
    local = t_utc.astimezone(NY).replace(tzinfo=None) + SHIFT
    if hours == 24:
        start_shifted = local.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start_shifted = local.replace(hour=(local.hour // hours) * hours, minute=0, second=0, microsecond=0)
    start_local = start_shifted - SHIFT
    return start_local.replace(tzinfo=NY).astimezone(UTC)


def market_closed(t_utc: datetime) -> bool:
    """True from Friday 17:00 to Sunday 17:00 New York time (forex is closed)."""
    shifted = t_utc.astimezone(NY).replace(tzinfo=None) + SHIFT
    return shifted.weekday() >= 5


def aggregate(
    h1: list[Candle], hours: int, now: datetime | None = None, drop_weekend: bool = True
) -> list[Candle]:
    """Build closed `hours`-hour candles (4 = H4, 24 = Daily) from H1 candles.

    H1 candles that have not closed yet (open + 1h > now) are dropped, and so is a last bucket
    that is not complete yet. With `drop_weekend`, hours while the market is closed (Friday
    17:00 to Sunday 17:00 New York) are removed, so the week has 5 Daily candles like on
    TradingView even if the data feed fills the weekend.
    """
    one_hour = timedelta(hours=1)
    src = sorted(_dedupe(list(h1)), key=lambda c: c.time)
    if drop_weekend:
        src = [c for c in src if not market_closed(c.time)]
    if now is not None:
        src = [c for c in src if c.time + one_hour <= now]
    if not src:
        return []
    groups: dict[datetime, list[Candle]] = {}
    for c in src:
        groups.setdefault(bucket_start(c.time, hours), []).append(c)
    last_h1_end = src[-1].time + one_hour
    out: list[Candle] = []
    for start in sorted(groups):
        g = groups[start]
        end = start + timedelta(hours=hours)
        if end > last_h1_end:  # bucket still forming
            continue
        out.append(
            Candle(
                time=start,
                open=g[0].open,
                high=max(x.high for x in g),
                low=min(x.low for x in g),
                close=g[-1].close,
                end=end,
            )
        )
    return out


def forming_candle(
    h1: list[Candle], hours: int, now: datetime | None = None
) -> tuple[Candle, list[Candle]] | None:
    """The `hours`-hour candle that is still open (4 = H4, 24 = Daily), built from the H1
    candles closed so far, plus those H1 candles. None if the market is closed or the bucket is
    already complete."""
    one_hour = timedelta(hours=1)
    src = sorted(_dedupe(list(h1)), key=lambda c: c.time)
    src = [c for c in src if not market_closed(c.time)]
    if now is not None:
        src = [c for c in src if c.time + one_hour <= now]
    if not src:
        return None
    start = bucket_start(src[-1].time, hours)
    end = start + timedelta(hours=hours)
    if src[-1].time + one_hour >= end:  # bucket complete, nothing is forming
        return None
    grp = [c for c in src if bucket_start(c.time, hours) == start]
    cand = Candle(
        time=start,
        open=grp[0].open,
        high=max(x.high for x in grp),
        low=min(x.low for x in grp),
        close=grp[-1].close,
        end=end,
    )
    return cand, grp


def to_weekly(daily: list[Candle]) -> list[Candle]:
    """Build Weekly candles from Daily candles. The week opens with the Sunday 17:00 New York
    Daily candle (which is Monday's Daily candle), so no Sunday merge is needed."""
    groups: dict[datetime, list[Candle]] = {}
    for c in daily:
        shifted = c.time.astimezone(NY).replace(tzinfo=None) + SHIFT
        monday = (shifted - timedelta(days=shifted.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        groups.setdefault(monday, []).append(c)
    out = []
    for monday in sorted(groups):
        g = groups[monday]
        out.append(
            Candle(
                time=g[0].time,
                open=g[0].open,
                high=max(x.high for x in g),
                low=min(x.low for x in g),
                close=g[-1].close,
                end=g[-1].end,
            )
        )
    return out


def latest_h4_boundary(now: datetime) -> datetime:
    """The most recent H4 close time (UTC) at or before `now`."""
    return bucket_start(now, 4)


def latest_daily_boundary(now: datetime) -> datetime:
    return bucket_start(now, 24)
