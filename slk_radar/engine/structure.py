"""Market structure: external / internal breaks, CHoCH, major structure.

Rules (from slk_radar_rules_v1.md):
- A break needs a candle BODY close beyond the level. A wick only is a sweep.
- Major structure: in an uptrend the major high is the latest higher high and the major (protected)
  low is the lowest low since the last external break up (the swing low that created the latest
  higher high). A body close below the major low is an external break DOWN (and the mirror).
- A body close through a smaller unbroken swing inside the range is an internal break.
- An external break against the previous trend is a CHoCH, unconfirmed until a second body-close
  break in the new direction.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Candle, Swing
from .indicators import swings


@dataclass
class BreakEvent:
    index: int
    direction: str            # "up" | "down"
    kind: str                 # "external" | "internal"
    level: float              # price of the level that was broken
    choch: bool = False       # external break against the previous trend
    confirmed: bool = True    # a CHoCH stays False until a second break the same way


@dataclass
class Structure:
    trend: str | None         # "bull" | "bear" | None
    events: list[BreakEvent]
    major_high: float | None
    major_low: float | None
    open_highs: list[Swing]   # confirmed swing highs that no close has broken yet
    open_lows: list[Swing]
    swings: list[Swing] = field(default_factory=list)

    def last_external(self) -> BreakEvent | None:
        ext = [e for e in self.events if e.kind == "external"]
        return ext[-1] if ext else None

    def bias(self) -> str:
        """Fallback bias from structure: last external break, neutral if none or if it is a
        CHoCH that is not confirmed yet."""
        e = self.last_external()
        if e is None or (e.choch and not e.confirmed):
            return "neutral"
        return "bullish" if e.direction == "up" else "bearish"


def analyze(c: list[Candle], n: int = 3) -> Structure:
    sw = swings(c, n)
    by_conf: dict[int, list[Swing]] = {}
    for s in sw:
        by_conf.setdefault(s.confirmed_at, []).append(s)

    open_h: list[Swing] = []
    open_l: list[Swing] = []
    trend: str | None = None
    mh: float | None = None
    ml: float | None = None
    mh_idx = ml_idx = 0
    last_ext = {"up": 0, "down": 0}
    events: list[BreakEvent] = []

    def confirm_choch(direction: str, current: BreakEvent | None) -> None:
        """A second body-close break in the same direction confirms the last CHoCH."""
        for e in reversed(events):
            if e.kind != "external" or e is current:
                continue
            if e.direction == direction and e.choch and not e.confirmed:
                e.confirmed = True
            break

    for i, x in enumerate(c):
        for s in by_conf.get(i, []):
            (open_h if s.kind == "high" else open_l).append(s)

        broke_up = [s for s in open_h if x.close > s.price]
        broke_dn = [s for s in open_l if x.close < s.price]
        ext_up = (mh is None and bool(broke_up)) or (mh is not None and x.close > mh)
        ext_dn = (ml is None and bool(broke_dn)) or (ml is not None and x.close < ml)
        if ext_up and ext_dn:  # one huge candle: follow its colour
            if x.close >= x.open:
                ext_dn = False
            else:
                ext_up = False

        if ext_up:
            prior = trend
            level = mh if mh is not None else max(s.price for s in broke_up)
            choch = prior == "bear"
            ev = BreakEvent(i, "up", "external", level, choch, confirmed=not choch)
            events.append(ev)
            confirm_choch("up", ev)
            if prior == "bull":
                w0 = last_ext["up"]
                seg = c[w0 : i + 1]
                ml = min(k.low for k in seg)
                ml_idx = w0 + min(range(len(seg)), key=lambda j: seg[j].low)
                mh, mh_idx = max(mh, x.high), i
            elif prior == "bear":
                w0 = ml_idx  # the bear leg's lowest low becomes the protected low
                seg = c[w0 : i + 1]
                mh = max(k.high for k in seg)
                mh_idx = w0 + max(range(len(seg)), key=lambda j: seg[j].high)
            else:
                w0 = max(0, i - 20)
                seg = c[w0 : i + 1]
                ml = min(k.low for k in seg)
                ml_idx = w0 + min(range(len(seg)), key=lambda j: seg[j].low)
                mh = max(k.high for k in seg)
                mh_idx = w0 + max(range(len(seg)), key=lambda j: seg[j].high)
            trend = "bull"
            last_ext["up"] = i
            open_h = [s for s in open_h if x.close <= s.price]
        elif ext_dn:
            prior = trend
            level = ml if ml is not None else min(s.price for s in broke_dn)
            choch = prior == "bull"
            ev = BreakEvent(i, "down", "external", level, choch, confirmed=not choch)
            events.append(ev)
            confirm_choch("down", ev)
            if prior == "bear":
                w0 = last_ext["down"]
                seg = c[w0 : i + 1]
                mh = max(k.high for k in seg)
                mh_idx = w0 + max(range(len(seg)), key=lambda j: seg[j].high)
                ml, ml_idx = min(ml, x.low), i
            elif prior == "bull":
                w0 = mh_idx
                seg = c[w0 : i + 1]
                ml = min(k.low for k in seg)
                ml_idx = w0 + min(range(len(seg)), key=lambda j: seg[j].low)
            else:
                w0 = max(0, i - 20)
                seg = c[w0 : i + 1]
                mh = max(k.high for k in seg)
                mh_idx = w0 + max(range(len(seg)), key=lambda j: seg[j].high)
                ml = min(k.low for k in seg)
                ml_idx = w0 + min(range(len(seg)), key=lambda j: seg[j].low)
            trend = "bear"
            last_ext["down"] = i
            open_l = [s for s in open_l if x.close >= s.price]
        else:
            if broke_up:
                events.append(BreakEvent(i, "up", "internal", max(s.price for s in broke_up)))
                confirm_choch("up", None)
                open_h = [s for s in open_h if x.close <= s.price]
            if broke_dn:
                events.append(BreakEvent(i, "down", "internal", min(s.price for s in broke_dn)))
                confirm_choch("down", None)
                open_l = [s for s in open_l if x.close >= s.price]

        # running extremes in the direction of the trend (wicks included)
        if trend == "bull" and mh is not None and x.high > mh:
            mh, mh_idx = x.high, i
        if trend == "bear" and ml is not None and x.low < ml:
            ml, ml_idx = x.low, i

    return Structure(trend, events, mh, ml, open_h, open_l, sw)
