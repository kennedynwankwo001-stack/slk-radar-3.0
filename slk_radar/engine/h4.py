"""H4 confirmation of a DRD: external breakout + H4 sweep, then cancellation.

- H4 breakout (BO): after the DRD candle has closed, an H4 candle BODY closes beyond the last H4
  swing made BEFORE the Daily level was touched (swing high for a bull DRD, swing low for a bear
  DRD). That is the external breakout; internal swings never count (MSNR/SLK rule).
- The swing that was broken is the "confirming swing". An H4 body close back through it,
  against the bias, cancels the setup (rule 3).
- H4 sweep (required): an H4 wick of any length takes liquidity (the latest far-side H4 swing, or the
  Daily level extreme) and the candle closes back on the bias side. It can come after the Daily touch and
  before the BO, or up to `h4_rejection_window` candles after the BO. BO + sweep = confirmed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..models import Candle, Swing
from ..settings import Settings
from .drd import DRD
from .indicators import close_swings, swings



def h4_swings(h4: list[Candle], st: Settings) -> list[Swing]:
    """Swings the H4 breakout is measured against: on the close line (default) or on candles."""
    if st.h4_swing_mode == "close":
        return close_swings(h4, st.h4_swing_n)
    return swings(h4, st.swing_n)


@dataclass
class H4Result:
    status: str                       # "waiting" | "waiting_sweep" | "confirmed" | "cancelled"
    bo_index: int | None = None
    bo_swing: Swing | None = None
    cancel_index: int | None = None
    sweep_index: int | None = None
    sweep_text: str | None = None
    external: bool = True             # the breakout is always external (swing made before the Daily touch)


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

    # H4 sweep (required): liquidity taken by an H4 WICK (any length) that closes back on the bias side.
    # It can come before the BO (after the Daily touch) or up to `h4_rejection_window` candles after it.
    # Taken: the latest H4 swing on the far side (wick or close swing), or the Daily level extreme.
    far = "low" if bull else "high"
    cw = swings(h4, 1)
    last = min(len(h4) - 1, bo + st.h4_rejection_window)
    stop = (res.cancel_index - 1) if res.cancel_index is not None else last
    for j in range(touch, min(last, stop) + 1):
        x = h4[j]
        if bull and x.low < lvl.lo and x.close >= lvl.lo:
            res.sweep_index, res.sweep_text = j, f"H4 wick below the level at {x.low:.5f}, closed back above"
            break
        if not bull and x.high > lvl.hi and x.close <= lvl.hi:
            res.sweep_index, res.sweep_text = j, f"H4 wick above the level at {x.high:.5f}, closed back below"
            break
        hit = None
        for pool in (sw, cw):
            prior = [q for q in pool if q.kind == far and q.confirmed_at <= j - 1]
            if prior:
                p = max(prior, key=lambda q: q.index).price
                if (bull and x.low < p < x.close) or (not bull and x.high > p > x.close):
                    hit = p
                    break
        if hit is not None:
            side_word = "low" if bull else "high"
            res.sweep_index = j
            res.sweep_text = f"H4 swept the swing {side_word} {hit:.5f} and closed back {'above' if bull else 'below'}"
            break
    if res.status != "cancelled":
        res.status = "confirmed" if res.sweep_index is not None else "waiting_sweep"
    return res
