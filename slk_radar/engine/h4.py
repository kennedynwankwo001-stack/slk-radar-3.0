"""H4 confirmation of a DRD: sweep (info), breakout, rejection after the breakout, cancellation.

- H4 breakout (BO): after the DRD candle has closed, an H4 candle BODY closes beyond the last H4
  swing made BEFORE the Daily level was touched (swing high for a bull DRD, swing low for a bear
  DRD). That is the external breakout; internal swings never count (MSNR/SLK rule).
- The swing that was broken is the "confirming swing". An H4 body close back through it,
  against the bias, cancels the setup (rule 3).
- H4 R H4 (required stage after the BO): within `h4_rejection_window` H4 candles after the BO, an
  H4 candle closes rejecting the broken swing (retest) or any H4 key level on the right side.
- H4 sweep (info): before the BO, an H4 wick took the extreme of the Daily level or an H4 swing
  and the candle closed back.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..models import Candle, Swing
from ..settings import Settings
from .drd import DRD
from .indicators import close_swings, swings
from .levels import Level, build_levels, reaction_grade, valid_for_drd


def h4_swings(h4: list[Candle], st: Settings) -> list[Swing]:
    """Swings the H4 breakout is measured against: on the close line (default) or on candles."""
    if st.h4_swing_mode == "close":
        return close_swings(h4, st.h4_swing_n)
    return swings(h4, st.swing_n)


@dataclass
class H4Result:
    status: str                       # "waiting" | "confirmed" | "retest" | "cancelled"
    bo_index: int | None = None
    bo_swing: Swing | None = None
    cancel_index: int | None = None
    sweep_index: int | None = None
    sweep_text: str | None = None
    rej_index: int | None = None
    rej_text: str | None = None
    rej_lo: float | None = None       # the H4 level that was rejected (lo == hi for a broken swing)
    rej_hi: float | None = None
    external: bool = False            # the broken swing was the furthest H4 swing of the last 30 H4 candles


def confirm(h4: list[Candle], atr4: list[float], st: Settings, drd: DRD, drd_end: datetime) -> H4Result:
    bull = drd.direction == "bull"
    sw = h4_swings(h4, st)
    # The reference swing is the last swing made BEFORE the Daily level was touched (SLK external
    # breakout). Swings formed after the touch, inside the move, are internal and never count.
    lvl = drd.level
    tol = st.touch_atr * atr4[-1]
    window = [k for k, x in enumerate(h4) if drd_end - timedelta(hours=24) <= x.time < drd_end]
    touch = None
    for k in window:
        x = h4[k]
        if (bull and x.low <= lvl.hi + tol) or (not bull and x.high >= lvl.lo - tol):
            touch = k
            break
    if touch is None:
        if not window:
            return H4Result("waiting")
        touch = min(window, key=lambda k: h4[k].low) if bull else max(window, key=lambda k: h4[k].high)
    kind = "high" if bull else "low"
    before = [s for s in sw if s.kind == kind and s.index < touch]
    if not before:
        return H4Result("waiting")
    ref = max(before, key=lambda s: s.index)
    bo: int | None = None
    for k, x in enumerate(h4):
        if x.time >= drd_end and k > ref.index and ((bull and x.close > ref.price) or (not bull and x.close < ref.price)):
            bo = k
            break
    if bo is None:
        return H4Result("waiting")

    res = H4Result("confirmed", bo_index=bo, bo_swing=ref, external=True)

    # cancellation: H4 body close back through the confirming swing, against the bias
    for k in range(bo + 1, len(h4)):
        if (bull and h4[k].close < ref.price) or (not bull and h4[k].close > ref.price):
            res.cancel_index = k
            res.status = "cancelled"
            break

    # H4 sweep (info) in the 12 H4 candles before the BO
    for j in range(bo - 1, max(-1, bo - 13), -1):
        x = h4[j]
        if bull and x.low < lvl.lo and x.close >= lvl.lo:
            res.sweep_index, res.sweep_text = j, f"H4 wick below the level at {x.low:.5f}, closed back above"
            break
        if not bull and x.high > lvl.hi and x.close <= lvl.hi:
            res.sweep_index, res.sweep_text = j, f"H4 wick above the level at {x.high:.5f}, closed back below"
            break
        prior = [s for s in sw if s.confirmed_at <= j - 1 and s.kind == ("low" if bull else "high")]
        if prior:
            p = max(prior, key=lambda s: s.index).price
            if bull and x.low < p < x.close:
                res.sweep_index, res.sweep_text = j, f"H4 swept the swing low {p:.5f} and closed back above"
                break
            if not bull and x.high > p > x.close:
                res.sweep_index, res.sweep_text = j, f"H4 swept the swing high {p:.5f} and closed back below"
                break

    # H4 rejection after the BO (retest of the broken swing, or any H4 key level)
    last = min(len(h4) - 1, bo + st.h4_rejection_window)
    stop = (res.cancel_index - 1) if res.cancel_index is not None else last
    side = "buy" if bull else "sell"
    for j in range(bo + 1, min(last, stop) + 1):
        x = h4[j]
        r = st.retest_zone_atr * atr4[bo]
        retest = Level("SWING", side, ref.price - r, ref.price + r, ref.index, ref.index)
        g = reaction_grade(retest, x, atr4[j], st)
        text = f"retest of the broken swing {ref.price:.5f}"
        lo, hi = ref.price, ref.price
        if g is None:
            for lv in build_levels(h4, atr4, st, upto=j):
                if lv.side == side and valid_for_drd(lv, j, st, None):
                    g = reaction_grade(lv, x, atr4[j], st)
                    if g:
                        text = f"H4 {lv.label} {lv.lo:.5f}-{lv.hi:.5f}"
                        lo, hi = lv.lo, lv.hi
                        break
        if g:
            res.rej_index, res.rej_text = j, text
            res.rej_lo, res.rej_hi = lo, hi
            if res.status != "cancelled":
                res.status = "retest"
            break
    return res
