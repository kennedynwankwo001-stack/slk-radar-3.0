"""The radar: puts candles, structure, levels, DRD, H4 confirmation and liquidity together and
formats the radar text and the three messages (bias alert, H4 R H4, cancelled). It never gives entries."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .candles import NY, aggregate, bucket_start, forming_candle, market_closed
from .engine import drd as drd_mod
from .engine import h4 as h4_mod
from .engine import liquidity as liq_mod
from .engine import structure as struct_mod
from .engine.indicators import atr_series
from .engine.levels import Level, build_levels, valid_for_drd
from .models import Candle
from .settings import Settings


def setup_key_for(symbol: str, d: drd_mod.DRD) -> str:
    lv = d.level
    return f"{symbol}:{d.direction}:{lv.kind}:{lv.side}:{lv.lo:.5f}:{lv.hi:.5f}"


@dataclass
class Analysis:
    symbol: str
    as_of: datetime                    # end time (UTC) of the last closed H4 candle used
    price: float
    daily: list[Candle]
    h4: list[Candle]
    atr_d: float
    atr4: list[float]
    structure: struct_mod.Structure
    scan: drd_mod.DrdScan
    drd: drd_mod.DRD | None
    bias: str                          # "bullish" | "bearish" | "neutral"
    bias_source: str                   # "DRD" | "structure" | "none"
    levels: list[Level]
    top_levels: list[Level]
    liquidity: liq_mod.LiquidityMap
    h4_result: h4_mod.H4Result | None
    status: str                        # "no_setup" | "watching" | "confirmed" | "retest" | "cancelled"
    st: Settings = field(default_factory=Settings)
    forming: bool = False              # the DRD comes from the Daily candle that is still open
    forming_candle: Candle | None = None
    target: tuple | None = None        # (price, label) next Daily key level in the bias direction

    # ---- helpers used by the formatters and the scanner
    def day_label(self, i: int) -> str:
        """Trading-day label of Daily candle i as TradingView shows it (opens 17:00 New York)."""
        c = self.daily[i] if i < len(self.daily) else self.forming_candle
        return (c.time.astimezone(NY) + timedelta(hours=7)).strftime("%a %d %b")

    @property
    def setup_key(self) -> str:
        """Identifies one setup (pair, direction, level) so each stage is sent only once."""
        d = self.drd
        if d is None:
            return f"{self.symbol}:none"
        return setup_key_for(self.symbol, d)

    @property
    def bo_time(self) -> datetime | None:
        r = self.h4_result
        if r and r.bo_index is not None:
            return self.h4[r.bo_index].end
        return None

    @property
    def alertable(self) -> bool:
        return self.status in ("confirmed", "retest") and self.drd is not None and self.drd.actionable

    @property
    def external(self) -> bool:
        return bool(self.h4_result and self.h4_result.external)

    @property
    def rank_key(self) -> tuple:
        """Best-first order when more setups qualify than the daily cap allows:
        PDH/PDL sweep, then an external H4 breakout, then the most recent breakout."""
        d = self.drd
        t = self.bo_time.timestamp() if self.bo_time else 0.0
        return (int(bool(d and d.sweep)), int(self.external), t)


def daily_target(levels: list[Level], daily_len: int, st: Settings, direction: str, price: float, atr_d: float):
    """Target = the next Daily key level on the far side, at least half a Daily ATR away."""
    bull = direction == "bull"
    far = 0.5 * atr_d
    cand = [lv for lv in levels
            if valid_for_drd(lv, daily_len, st, st.age_limit)
            and ((bull and lv.side == "sell" and lv.lo > price + far)
                 or (not bull and lv.side == "buy" and lv.hi < price - far))]
    if not cand:
        return None
    lv = min(cand, key=lambda x: x.lo) if bull else max(cand, key=lambda x: x.hi)
    return (lv.lo if bull else lv.hi, f"Daily {lv.label} {_fmt(lv.lo)}-{_fmt(lv.hi)}")


def _local(t: datetime, st: Settings) -> str:
    return t.astimezone(ZoneInfo(st.display_tz)).strftime("%d %b %H:%M")


def _when(t: datetime, st: Settings) -> str:
    """Thu 08 Oct 02:00 in Lagos time (candle CLOSE time)."""
    return t.astimezone(ZoneInfo(st.display_tz)).strftime("%a %d %b %H:%M")


def _early_drd(h1, daily, atr_d, h4, st, now, active):
    """Early DRD from the Daily candle that is still open. It must already be a clean DRD (clear
    rejection) and beat the active closed DRD, if there is one. The H4 breakout then has
    to come after the H4 candle that holds the rejection extreme (the low for a buy, the high for
    a sell). Returns (drd, forming candle, time from which an H4 breakout counts) or None."""
    fc = forming_candle(h1, 24, now)
    if fc is None:
        return None
    cand, grp = fc
    i = len(daily)
    d = drd_mod.detect_at(daily + [cand], atr_d + [atr_d[-1]], st, i)
    if d is None or not d.actionable:
        return None
    if active is not None and d.score <= active.score:
        return None
    ext = min(grp, key=lambda x: x.low) if d.direction == "bull" else max(grp, key=lambda x: x.high)
    since = bucket_start(ext.time, 4) + timedelta(hours=4)
    return d, cand, since


def analyze(symbol: str, h1: list[Candle], st: Settings | None = None, now: datetime | None = None) -> Analysis:
    st = st or Settings()
    daily_all = aggregate(h1, 24, now)
    h4_all = aggregate(h1, 4, now)
    daily = daily_all[-st.lookback_daily:]
    h4 = h4_all[-st.h4_lookback:]
    if len(daily) < 20 or len(h4) < 12:
        raise ValueError(f"{symbol}: not enough candles (Daily {len(daily)}, H4 {len(h4)}); need at least 20 Daily and 12 H4")
    atr_d = atr_series(daily, st.atr_period)
    atr4 = atr_series(h4, st.atr_period)
    price = h4[-1].close
    structure = struct_mod.analyze(daily, st.swing_n)
    scan = drd_mod.scan(daily, atr_d, st)
    active = scan.active
    forming, forming_c, drd_end = False, None, None
    if st.early_alert:
        early = _early_drd(h1, daily, atr_d, h4, st, now, active)
        if early is not None:
            active, forming_c, drd_end = early
            forming = True

    if active is not None:
        bias = "bullish" if active.direction == "bull" else "bearish"
        source = "DRD"
    else:
        bias = structure.bias()
        source = "structure" if bias != "neutral" else "none"

    levels = build_levels(daily, atr_d, st, upto=len(daily))
    shown = [lv for lv in levels if valid_for_drd(lv, len(daily), st, st.age_limit)]
    shown.sort(key=lambda lv: (-lv.history, lv.distance(price)))
    top = shown[: st.top_levels]

    liq = liq_mod.build(daily, h4, atr_d[-1], st, structure, bias, price)

    h4r = None
    status = "no_setup"
    if active is not None:
        if drd_end is None:
            drd_end = daily[active.index].end
        h4r = h4_mod.confirm(h4, atr4, st, active, drd_end)
        status = {"waiting": "watching", "confirmed": "confirmed", "retest": "retest", "cancelled": "cancelled"}[h4r.status]

    target = None
    if h4r is not None and h4r.bo_index is not None:
        target = daily_target(levels, len(daily), st, active.direction, h4[h4r.bo_index].close, atr_d[-1])
        if target is None and liq.erl is not None:
            target = (liq.erl.price, liq.erl.label)
    return Analysis(symbol, h4[-1].end, price, daily, h4, atr_d[-1], atr4, structure, scan, active,
                    bias, source, levels, top, liq, h4r, status, st, forming=forming, forming_candle=forming_c,
                    target=target)


# --------------------------------------------------------------------------- text


def _fmt(p: float) -> str:
    return f"{p:.3f}" if p > 20 else f"{p:.5f}"


def _level_line(lv: Level) -> str:
    return f"{_fmt(lv.lo)}-{_fmt(lv.hi)} {lv.label} · {lv.status_text()}"


def structure_text(a: Analysis) -> str:
    e = a.structure.last_external()
    if e is None:
        return "No external break yet, no clear Daily structure"
    arrow = "up" if e.direction == "up" else "down"
    tag = " (CHoCH, not confirmed)" if e.choch and not e.confirmed else (" (CHoCH, confirmed)" if e.choch else "")
    return f"Last external break {arrow} on {a.day_label(e.index)} at {_fmt(e.level)}{tag}; trend {a.structure.trend}"


def drd_text(a: Analysis) -> str:
    d = a.drd
    if d is None:
        weak = [x for x in a.scan.drds if not x.actionable]
        return "None active" + (f" ({len(weak)} unclear rejection(s) ignored)" if weak else "")
    early = "FORMING, Daily candle not closed yet: " if a.forming else ""
    return (f"{early}Clean DRD on {a.day_label(d.index)} "
            f"({'bullish' if d.direction == 'bull' else 'bearish'}, rejection of {d.level.label} "
            f"{_fmt(d.level.lo)}-{_fmt(d.level.hi)}{', PDL/PDH swept' if d.sweep else ''})")


def h4_text(a: Analysis) -> str:
    r = a.h4_result
    if r is None:
        return "No active DRD to confirm"
    if r.status == "waiting":
        return "Waiting: no H4 body close through the latest H4 swing in the DRD direction yet"
    bo = a.h4[r.bo_index]
    word = "above" if a.drd.direction == "bull" else "below"
    out = f"H4 BO ({'external' if r.external else 'internal'}): H4 body close {word} {_fmt(r.bo_swing.price)} at {_local(bo.end, a.st)} Lagos time"
    if r.sweep_text:
        out += f"; {r.sweep_text}"
    if r.rej_text:
        out += f"; H4 R H4 at {_local(a.h4[r.rej_index].end, a.st)}: {r.rej_text}"
    if r.status == "cancelled":
        out += f"; CANCELLED: H4 closed back through {_fmt(r.bo_swing.price)} at {_local(a.h4[r.cancel_index].end, a.st)}"
    return out


def summary_text(a: Analysis) -> str:
    if a.bias == "neutral":
        return "No clear direction. No clean DRD and no confirmed external break on Daily."
    word = a.bias.capitalize()
    if a.status == "no_setup":
        return f"{word} from Daily structure only. No DRD, no setup."
    if a.status == "watching":
        return f"{word} DRD is active. Waiting for the H4 BO."
    if a.status == "confirmed":
        return f"{word} bias confirmed by the H4 BO. Waiting for H4 R H4, no entry yet."
    if a.status == "retest":
        return f"{word} bias confirmed and H4 R H4 has closed. You can look for an entry on the lower timeframe."
    return f"{word} setup was cancelled by an H4 close against it."


def radar_text(a: Analysis) -> str:
    L = a.liquidity
    lines = [
        f"Pair: {a.symbol}",
        f"Price: {_fmt(a.price)}  (as of {_local(a.as_of, a.st)} Lagos, last closed H4)",
        f"Daily Structure: {structure_text(a)}",
        f"Daily Bias: {a.bias.capitalize()}" + (f" (from {a.bias_source})" if a.bias_source != "none" else ""),
        f"DRD: {drd_text(a)}",
        "",
        "Priority Key Levels:",
    ]
    if a.top_levels:
        lines += [f"{i}. {_level_line(lv)}" for i, lv in enumerate(a.top_levels, 1)]
    else:
        lines.append("None valid")
    lines += ["", "Liquidity Map:"]
    lines.append("- Above price: " + (", ".join(f"{_fmt(p.price)} {p.label}" for p in L.above) or "none"))
    lines.append("- Below price: " + (", ".join(f"{_fmt(p.price)} {p.label}" for p in L.below) or "none"))
    if L.erl:
        lines.append(f"- Target (ERL): {_fmt(L.erl.price)} {L.erl.label}")
    if L.irl:
        lines.append(f"- Fuel (IRL): {_fmt(L.irl.price)} {L.irl.label}")
    for s in L.sweeps:
        lines.append(f"- {s}")
    if L.premium_discount:
        lines.append(f"- Price is in {L.premium_discount}")
    lines += ["", f"H4 Status: {h4_text(a)}", "", f"Radar Summary: {summary_text(a)}"]
    return "\n".join(lines)


def level_tag(lv: Level) -> str:
    if lv.is_flip:
        return "Flip"
    if lv.history >= 2:
        return f"{lv.history} reactions"
    if lv.history == 1:
        return "1 reaction"
    return "Fresh" if lv.touches == 0 else "Tested"


def alert_text(a: Analysis) -> str:
    """The bias alert: clean DRD + closed H4 BO. It starts the wait for H4 R H4."""
    d, r = a.drd, a.h4_result
    assert d is not None and r is not None and r.bo_index is not None
    arrow = "🟢" if d.direction == "bull" else "🔴"
    side = "BUY" if d.direction == "bull" else "SELL"
    bo = a.h4[r.bo_index]
    head = f"{arrow} SLK BIAS ALERT" + (" · EARLY (Daily not closed)" if a.forming else "")
    lines = [head, f"Pair: {a.symbol}", f"Direction: {side}",
             f"Daily Level: {_fmt(d.level.lo)} - {_fmt(d.level.hi)} ({d.level.kind} {d.level.side} · {level_tag(d.level)})"]
    why = []
    if d.sweep:
        why.append("PDL swept" if d.direction == "bull" else "PDH swept")
    if r.sweep_text:
        why.append(r.sweep_text)
    if why:
        lines.append("Why: " + " + ".join(why))
    lines.append(f"DRD: Daily candle {a.day_label(d.index)}" + (" (still open)" if a.forming else ""))
    lines.append(f"H4 BO: {_fmt(r.bo_swing.price)} ({'external' if r.external else 'internal'}) · {_when(bo.end, a.st)} Lagos")
    if a.target:
        lines.append(f"Target: {_fmt(a.target[0])} ({a.target[1]})")
    lines.append("Status: Waiting for H4 R H4")
    if a.forming:
        lines.append("The Daily candle is still open, this can change.")
    lines.append("Bias only, not an entry signal.")
    return "\n".join(lines)


def h4rh4_text(a: Analysis, info: dict | None = None) -> str:
    """H4 Reject H4: the stage you wait for before looking at the lower timeframe."""
    r = a.h4_result
    assert a.drd is not None and r is not None and r.rej_index is not None
    side = "BUY" if a.drd.direction == "bull" else "SELL"
    lo, hi = r.rej_lo, r.rej_hi
    level = _fmt(lo) if lo is None or hi is None or abs(hi - lo) < 1e-9 else f"{_fmt(lo)} - {_fmt(hi)}"
    lines = ["🔁 SLK H4 R H4", f"Pair: {a.symbol}", f"Direction: {side}",
             f"H4 Level Rejected: {level}",
             f"Time: {_when(a.h4[r.rej_index].end, a.st)} Lagos",
             "Status: Now look for a lower timeframe entry"]
    tgt = (info["target"], info.get("target_label", "")) if info and info.get("target") else a.target
    if tgt:
        lines.append(f"Target still: {_fmt(tgt[0])}" + (f" ({tgt[1]})" if tgt[1] else ""))
    return "\n".join(lines)


retest_text = h4rh4_text      # old name


def cancelled_text(symbol: str, direction: str, reason: str, when: datetime, st: Settings) -> str:
    side = "BUY" if direction == "bull" else "SELL"
    return "\n".join(["❌ SLK CANCELLED", f"Pair: {symbol}", f"Direction: {side}", f"Reason: {reason}",
                      f"Time: {_when(when, st)} Lagos"])


def target_text(symbol: str, direction: str, target: float, when: datetime, st: Settings) -> str:
    side = "BUY" if direction == "bull" else "SELL"
    return "\n".join(["✅ SLK TARGET REACHED", f"Pair: {symbol}", f"Direction: {side}",
                      f"Target: {_fmt(target)}", f"Time: {_when(when, st)} Lagos"])
