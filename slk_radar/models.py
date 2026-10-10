"""Basic data types shared by the whole radar."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Candle:
    """One OHLC candle. `time` is the OPEN time in UTC, `end` the close time in UTC."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    end: datetime | None = None

    @property
    def body_high(self) -> float:
        return max(self.open, self.close)

    @property
    def body_low(self) -> float:
        return min(self.open, self.close)

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def bearish(self) -> bool:
        return self.close < self.open

    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass(frozen=True)
class Swing:
    """A swing point. `index` is the candle index, `confirmed_at` the candle index at which
    the swing becomes known (after `n` candles on its right side)."""

    index: int
    kind: str  # "high" or "low"
    price: float
    confirmed_at: int
