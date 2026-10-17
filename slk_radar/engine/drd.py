"""DRD (Daily Reject Daily): a Daily candle rejects a Daily key level.

A DRD is "clean" (it sets bias and can alert) when it rejects a valid level with a STRONG
rejection (the close is beyond the far side of the zone). An unclear (weak) rejection never sets
bias and never alerts. There is no points score in what you see. Internally a number is still kept
only to RANK DRDs: it is higher when the DRD also swept PDH/PDL (preferred).

Several DRDs: the one with the PDH/PDL sweep first, then the candle colour that matches the
direction, then the level closer to price. An active DRD is cancelled only by (1) its level being
disrespected, (2) a later opposing clean DRD.
(The third rule, an H4 close against the confirming swing, lives in h4.py.)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Candle
from ..settings import Settings
from .levels import Level, build_levels, reaction_grade, valid_for_drd


@dataclass
class DRD:
    index: int
    direction: str            # "bull" | "bear"
    level: Level
    score: int
    grade: str                # "strong" | "medium" | "weak"
    rejection: str            # "strong" | "weak"
    sweep: bool
    quality_pts: int
    rejection_pts: int
    sweep_pts: int

    @property
    def actionable(self) -> bool:
        """Clean DRD: valid level (always true here) and a strong rejection."""
        return self.rejection == "strong"


@dataclass
class DrdScan:
    drds: list[DRD] = field(default_factory=list)                 # every DRD found in the window
    active: DRD | None = None
    cancelled: list[tuple[DRD, str]] = field(default_factory=list)


def grade_of(score: int, st: Settings) -> str:
    if score >= st.strong_score:
        return "strong"
    if score >= st.medium_score:
        return "medium"
    return "weak"


def pd_sweep(c: list[Candle], i: int, direction: str) -> bool:
    """The Daily wick takes the previous Daily low (bull) / high (bear) and the candle closes
    back inside the previous Daily range."""
    if i < 1:
        return False
    p, x = c[i - 1], c[i]
    inside = p.low <= x.close <= p.high
    if direction == "bull":
        return x.low < p.low and inside
    return x.high > p.high and inside


def rank(d: "DRD", price: float, st: Settings, candle: Candle | None = None) -> tuple:
    """Sort key: higher is better. Score first; then, by the `tiebreak` setting: the DRD that
    agrees with the colour of the Daily candle first and then the closest level (default), the
    closest level only, or more history first."""
    dist = -d.level.distance(price)
    if st.tiebreak == "history":
        return (d.score, d.level.history, dist)
    if st.tiebreak == "candle" and candle is not None:
        agrees = (candle.close > candle.open) if d.direction == "bull" else (candle.close < candle.open)
        return (d.score, int(agrees), dist)
    return (d.score, dist)


def detect_at(
    c: list[Candle], atr: list[float], st: Settings, i: int, levels: list[Level] | None = None
) -> DRD | None:
    """Best DRD made by candle i against levels known before i (highest score, then the level
    closest to the close)."""
    if levels is None:
        levels = build_levels(c, atr, st, upto=i)
    x = c[i]
    best: DRD | None = None
    for lv in levels:
        if not valid_for_drd(lv, i, st, st.age_limit):
            continue
        g = reaction_grade(lv, x, atr[i], st)
        if g is None:
            continue
        direction = "bull" if lv.side == "buy" else "bear"
        sweep = pd_sweep(c, i, direction)
        q = st.fresh_points
        r = st.strong_rejection_points if g == "strong" else st.weak_rejection_points
        s = st.sweep_points if sweep else 0
        score = q + r + s
        d = DRD(i, direction, lv, score, grade_of(score, st), g, sweep, q, r, s)
        if best is None or rank(d, x.close, st, x) > rank(best, x.close, st, x):
            best = d
    return best


def scan(c: list[Candle], atr: list[float], st: Settings) -> DrdScan:
    """Look for DRDs in the last `drd_scan` closed Daily candles and pick the active one."""
    n = len(c)
    res = DrdScan()
    if n < 3:
        return res
    for i in range(max(1, n - st.drd_scan), n):
        d = detect_at(c, atr, st, i)
        if d:
            res.drds.append(d)
    cands = [d for d in res.drds if d.actionable]
    levels_now = build_levels(c, atr, st, upto=n)
    by_key = {lv.key: lv for lv in levels_now}
    alive: list[DRD] = []
    for d in cands:
        cur = by_key.get(d.level.key)
        if cur is not None and cur.state == "disrespected" and (cur.disrespected_at or 0) > d.index:
            res.cancelled.append((d, "its key level was disrespected"))
            continue
        later_opposite = [o for o in cands if o.index > d.index and o.direction != d.direction]
        if later_opposite:
            res.cancelled.append((d, "a later opposing DRD appeared"))
            continue
        alive.append(d)
    if alive:
        last_close = c[-1].close
        res.active = max(alive, key=lambda d: rank(d, last_close, st, c[d.index]) + (d.index,))
    return res
