"""Liquidity map: PDH/PDL, PH4, equal highs/lows, unbroken swings, ERL (target) and IRL (fuel),
sweeps and premium/discount. Info and targets only, never used to block an alert."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Candle
from ..settings import Settings
from .drd import pd_sweep
from .structure import Structure


@dataclass
class Pool:
    price: float
    label: str


@dataclass
class LiquidityMap:
    above: list[Pool] = field(default_factory=list)
    below: list[Pool] = field(default_factory=list)
    erl: Pool | None = None            # the target in the bias direction
    irl: Pool | None = None            # internal pullback liquidity (the fuel)
    sweeps: list[str] = field(default_factory=list)
    premium_discount: str | None = None


def _cluster(prices: list[float], tol: float) -> list[tuple[float, int]]:
    """Group prices that are within tol of each other. Returns (extreme-less mean, count)."""
    out: list[list[float]] = []
    for p in sorted(prices):
        if out and p - out[-1][-1] <= tol:
            out[-1].append(p)
        else:
            out.append([p])
    return [(sum(g) / len(g), len(g)) for g in out]


def build(
    daily: list[Candle],
    h4: list[Candle],
    atr_d: float,
    st: Settings,
    structure: Structure,
    bias: str,
    price: float,
) -> LiquidityMap:
    pools: list[Pool] = []
    if daily:
        pools.append(Pool(daily[-1].high, "PDH"))
        pools.append(Pool(daily[-1].low, "PDL"))
    if h4:
        pools.append(Pool(h4[-1].high, "PH4 high"))
        pools.append(Pool(h4[-1].low, "PH4 low"))

    tol = st.equal_atr * atr_d
    sw_h = [s for s in structure.swings if s.kind == "high"][-12:]
    sw_l = [s for s in structure.swings if s.kind == "low"][-12:]
    for mean, count in _cluster([s.price for s in sw_h], tol):
        if count >= 2:
            pools.append(Pool(mean, f"equal highs x{count}"))
    for mean, count in _cluster([s.price for s in sw_l], tol):
        if count >= 2:
            pools.append(Pool(mean, f"equal lows x{count}"))
    for s in structure.open_highs[-3:]:
        pools.append(Pool(s.price, "unbroken swing high"))
    for s in structure.open_lows[-3:]:
        pools.append(Pool(s.price, "unbroken swing low"))
    if structure.major_high is not None:
        pools.append(Pool(structure.major_high, "major high"))
    if structure.major_low is not None:
        pools.append(Pool(structure.major_low, "major low"))

    # de-duplicate pools that sit at the same price
    uniq: list[Pool] = []
    for p in sorted(pools, key=lambda p: p.price):
        if uniq and abs(uniq[-1].price - p.price) < 1e-9:
            if p.label not in uniq[-1].label:
                uniq[-1] = Pool(p.price, uniq[-1].label + " + " + p.label)
        else:
            uniq.append(p)

    lm = LiquidityMap()
    lm.above = sorted([p for p in uniq if p.price > price], key=lambda p: p.price)[:4]
    lm.below = sorted([p for p in uniq if p.price < price], key=lambda p: -p.price)[:4]

    # ERL = nearest pool in the bias direction, skipping the tiny PH4 pools
    big = lambda p: not p.label.startswith("PH4")
    if bias == "bullish":
        lm.erl = next((p for p in lm.above if big(p)), None)
        lm.irl = lm.below[0] if lm.below else None
    elif bias == "bearish":
        lm.erl = next((p for p in lm.below if big(p)), None)
        lm.irl = lm.above[0] if lm.above else None

    if len(daily) >= 2:
        for d in ("bull", "bear"):
            if pd_sweep(daily, len(daily) - 1, d):
                lm.sweeps.append("PDL swept (wick below the previous Daily low, closed back inside)" if d == "bull"
                                 else "PDH swept (wick above the previous Daily high, closed back inside)")

    if structure.major_high is not None and structure.major_low is not None and structure.major_high > structure.major_low:
        rng = structure.major_high - structure.major_low
        eq = structure.major_low + rng / 2
        pct = (price - structure.major_low) / rng * 100
        lm.premium_discount = f"{'premium' if price > eq else 'discount'} ({pct:.0f}% of the Daily range, equilibrium {eq:.5f})"
    return lm
