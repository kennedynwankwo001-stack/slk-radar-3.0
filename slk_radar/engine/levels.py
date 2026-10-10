"""Key levels: A (sell), V (buy) and OCL (open-close) zones, reactions, history, fresh,
fake breakout, disrespected and flip.

All evaluation is "as of" a candle index `upto` (candles with index < upto), so a level is
never judged with candles from the future.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Candle
from ..settings import Settings
from .indicators import close_swings


@dataclass
class Level:
    kind: str                 # "A" | "V" | "OCL"
    side: str                 # "buy" | "sell"
    lo: float
    hi: float
    formed: int               # index of the candle that made the level
    known: int                # index from which it exists (candles after this can react to it)
    is_flip: bool = False
    origin: str = ""          # for flips: label of the level it came from
    reactions: list[tuple[int, str]] = field(default_factory=list)  # (candle index, "strong"/"weak")
    touches: int = 0
    state: str = "live"       # "live" | "disrespected"
    pending: int | None = None          # index of a body close through the zone not yet resolved
    disrespected_at: int | None = None
    fake_breaks: list[int] = field(default_factory=list)
    late_reclaims: list[int] = field(default_factory=list)

    @property
    def key(self) -> tuple:
        return (self.kind, self.side, round(self.lo, 6), round(self.hi, 6), self.formed, self.is_flip)

    @property
    def width(self) -> float:
        return self.hi - self.lo

    @property
    def mid(self) -> float:
        return (self.lo + self.hi) / 2

    @property
    def history(self) -> int:
        return len(self.reactions)

    @property
    def label(self) -> str:
        if self.is_flip:
            return f"Flip {self.side} (was {self.origin})"
        if self.kind == "OCL":
            return f"OCL {'bull' if self.side == 'buy' else 'bear'} {self.side}"
        return f"{self.kind} {self.side}"

    def last_event(self) -> int:
        if self.reactions:
            return max(i for i, _ in self.reactions)
        return self.known if self.is_flip else self.formed

    def status_text(self) -> str:
        if self.state == "disrespected":
            return "Disrespected"
        if self.pending is not None:
            return "Under test (body close through, not resolved yet)"
        if self.history >= 2:
            return f"History: {self.history} reactions, respected"
        if self.history == 1:
            return "1 reaction"
        if self.touches == 0:
            return "Fresh"
        return "Tested, no rejection"

    def distance(self, price: float) -> float:
        if self.lo <= price <= self.hi:
            return 0.0
        return min(abs(price - self.lo), abs(price - self.hi))


# --------------------------------------------------------------------------- rejection


def touched(level: Level, x: Candle, tol: float) -> bool:
    """The candle reached the zone (within tolerance) coming from the side it acts from."""
    if level.side == "sell":
        return x.high >= level.lo - tol and x.open <= level.hi
    return x.low <= level.hi + tol and x.open >= level.lo


def grade(level: Level, x: Candle, st: Settings, atr_k: float) -> str | None:
    """Grade a rejection by the CLOSE. Strong: closed clear of the zone, away from it (beyond its
    edge by more than 10% of the zone width or 0.1 x ATR, whichever is larger). Weak: closed
    outside but within that margin, or closed inside the near half of the zone with a candle
    colour against the approach."""
    width = max(level.width, 1e-12)
    margin = max(st.strong_margin * width, st.strong_margin_atr * atr_k)
    if level.side == "sell":
        if x.close < level.lo:
            return "strong" if x.close <= level.lo - margin else "weak"
        if x.close <= level.mid and x.close < x.open:
            return "weak"
    else:
        if x.close > level.hi:
            return "strong" if x.close >= level.hi + margin else "weak"
        if x.close >= level.mid and x.close > x.open:
            return "weak"
    return None


def reaction_grade(level: Level, x: Candle, atr_k: float, st: Settings) -> str | None:
    """Rejection grade of candle x against the level (None if no touch or no rejection)."""
    if not touched(level, x, st.touch_atr * atr_k):
        return None
    return grade(level, x, st, atr_k)


# --------------------------------------------------------------------------- evaluation


def _breached(level: Level, x: Candle) -> bool:
    return x.close > level.hi if level.side == "sell" else x.close < level.lo


def _back_inside(level: Level, x: Candle) -> bool:
    return x.close <= level.hi if level.side == "sell" else x.close >= level.lo


def evaluate(level: Level, c: list[Candle], atr: list[float], st: Settings, upto: int) -> None:
    """Walk the candles after the level exists and fill in reactions, touches, fake breakouts,
    late reclaims and disrespect. Uses candles with index < upto only."""
    last_react: int | None = None
    k0: int | None = None
    for k in range(level.known + 1, upto):
        x = c[k]
        if k0 is not None:
            steps = k - k0
            if _back_inside(level, x):
                (level.fake_breaks if steps <= st.fake_window else level.late_reclaims).append(k0)
                k0 = None  # this candle is then judged as a normal candle below
            else:
                if steps >= st.disrespect_hold:
                    level.state = "disrespected"
                    level.disrespected_at = k
                    level.pending = None
                    return
                continue
        if _breached(level, x):
            k0 = k
            continue
        tol = st.touch_atr * atr[k]
        if not touched(level, x, tol):
            continue
        level.touches += 1
        g = grade(level, x, st, atr[k])
        if g and (last_react is None or k - last_react >= st.min_reaction_gap):
            level.reactions.append((k, g))
            last_react = k
    level.pending = k0


# --------------------------------------------------------------------------- building


def _widen(lo: float, hi: float, min_w: float, anchor: str) -> tuple[float, float]:
    if hi - lo >= min_w:
        return lo, hi
    if anchor == "top":      # sell zone: keep the wick extreme, extend downward
        return hi - min_w, hi
    if anchor == "bottom":   # buy zone: keep the wick extreme, extend upward
        return lo, lo + min_w
    mid = (lo + hi) / 2
    return mid - min_w / 2, mid + min_w / 2


def find_levels(c: list[Candle], atr: list[float], st: Settings, upto: int) -> list[Level]:
    """Create A/V/OCL zones from candles with index < upto (not evaluated yet)."""
    out: list[Level] = []
    seg = c[:upto]
    for s in close_swings(seg, st.av_swing_n):
        x = c[s.index]
        min_w = st.min_zone_atr * atr[s.index]
        if s.kind == "high":
            lo, hi = _widen(x.body_high, x.high, min_w, "top")
            out.append(Level("A", "sell", lo, hi, s.index, s.confirmed_at))
        else:
            lo, hi = _widen(x.low, x.body_low, min_w, "bottom")
            out.append(Level("V", "buy", lo, hi, s.index, s.confirmed_at))
    for j in range(upto - 1):
        a, b = c[j], c[j + 1]
        need = st.ocl_min_body_atr * atr[j + 1]
        if abs(a.close - a.open) < need or abs(b.close - b.open) < need:
            continue
        min_w = st.min_zone_atr * atr[j + 1]
        if a.bullish and b.bullish:
            lo, hi = _widen(min(a.close, b.open), max(a.close, b.open), min_w, "mid")
            out.append(Level("OCL", "buy", lo, hi, j + 1, j + 1))
        elif a.bearish and b.bearish:
            lo, hi = _widen(min(a.close, b.open), max(a.close, b.open), min_w, "mid")
            out.append(Level("OCL", "sell", lo, hi, j + 1, j + 1))
    return out


def build_levels(
    c: list[Candle], atr: list[float], st: Settings, upto: int, max_flip_depth: int = 2
) -> list[Level]:
    """All levels as known after candle upto-1, evaluated, plus flips of disrespected levels."""
    base = find_levels(c, atr, st, upto)
    for lv in base:
        evaluate(lv, c, atr, st, upto)
    out = list(base)
    current = base
    for _ in range(max_flip_depth):
        flips: list[Level] = []
        for lv in current:
            if lv.state == "disrespected" and lv.disrespected_at is not None:
                f = Level(
                    lv.kind,
                    "buy" if lv.side == "sell" else "sell",
                    lv.lo,
                    lv.hi,
                    lv.formed,
                    lv.disrespected_at,
                    is_flip=True,
                    origin=lv.label if not lv.is_flip else lv.origin,
                )
                evaluate(f, c, atr, st, upto)
                flips.append(f)
        out.extend(flips)
        current = flips
        if not flips:
            break
    return out


def valid_for_drd(level: Level, i: int, st: Settings, age_limit: int | None) -> bool:
    """A level can start a DRD at candle i if it is live, not in the middle of a break, and
    (on Daily) not older than the age limit counted from its last reaction or formation."""
    if level.state != "live" or level.pending is not None:
        return False
    if level.is_flip and not st.use_flips_for_drd:
        return False
    if age_limit is not None and i - level.last_event() > age_limit:
        return False
    return True
