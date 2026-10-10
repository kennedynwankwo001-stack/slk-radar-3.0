"""ATR and swing detection."""
from __future__ import annotations

from ..models import Candle, Swing


def true_ranges(c: list[Candle]) -> list[float]:
    out: list[float] = []
    for i, x in enumerate(c):
        if i == 0:
            out.append(x.high - x.low)
        else:
            pc = c[i - 1].close
            out.append(max(x.high - x.low, abs(x.high - pc), abs(x.low - pc)))
    return out


def atr_series(c: list[Candle], period: int = 14) -> list[float]:
    """Wilder ATR. Before `period` candles exist, the running mean of true range is used,
    so every candle gets a usable value (no look-ahead: value at i uses candles <= i)."""
    tr = true_ranges(c)
    out: list[float] = []
    a = 0.0
    for i, t in enumerate(tr):
        if i < period:
            a = sum(tr[: i + 1]) / (i + 1)
        else:
            a = (a * (period - 1) + t) / period
        out.append(a)
    return out


def _pivots(values: list[float], n: int, kind: str) -> list[Swing]:
    out: list[Swing] = []
    for i in range(n, len(values) - n):
        left = values[i - n : i]
        right = values[i + 1 : i + n + 1]
        v = values[i]
        if kind == "high":
            if v > max(left) and v >= max(right):
                out.append(Swing(i, "high", v, i + n))
        else:
            if v < min(left) and v <= min(right):
                out.append(Swing(i, "low", v, i + n))
    return out


def swings(c: list[Candle], n: int) -> list[Swing]:
    """Structure swings from candle highs/lows, `n` candles each side. A swing is only known
    `n` candles later (confirmed_at). With equal highs/lows the first one is the swing."""
    out = _pivots([x.high for x in c], n, "high") + _pivots([x.low for x in c], n, "low")
    return sorted(out, key=lambda s: (s.index, s.kind))


def close_swings(c: list[Candle], n: int) -> list[Swing]:
    """A/V shape swings from CLOSES only (line chart): peak = close higher than the `n`
    closes before and after, valley = lower."""
    closes = [x.close for x in c]
    out = _pivots(closes, n, "high") + _pivots(closes, n, "low")
    return sorted(out, key=lambda s: (s.index, s.kind))
