"""The radar: puts candles, structure, levels, DRD, H4 confirmation and liquidity together and
formats the radar text, the alert and the (on request) entry plan."""
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
        lv = d.level
        return f"{self.symbol}:{d.direction}:{lv.kind}:{lv.side}:{lv.lo:.5f}:{lv.hi:.5f}"

    @property
    def bo_time(self) -> datetime | None:
        r = self.h4_result
        if r and r.bo_index is not None:
            return self.h4[r.bo_index].end
        return None

    @property
    def alertable(self) -> bool:
        return self.status in ("confirmed", "retest") and self.drd is not None and self.drd.actionable


def _local(t: datetime, st: Settings) -> str:
    return t.astimezone(ZoneInfo(st.display_tz)).strftime("%d %b %H:%M")


def _early_drd(h1, daily, atr_d, h4, st, now, active):
    """Early DRD from the Daily candle that is still open. It must already grade `early_min_grade`
    (Strong by default) and beat the active closed DRD, if there is one. The H4 breakout then has
    to come after the H4 candle that holds the rejection extreme (the low for a buy, the high for
    a sell). Returns (drd, forming candle, time from which an H4 breakout counts) or None."""
    fc = forming_candle(h1, 24, now)
    if fc is None:
        return None
    cand, grp = fc
    i = len(daily)
    d = drd_mod.detect_at(daily + [cand], atr_d + [atr_d[-1]], st, i)
    if d is None or d.grade != st.early_min_grade:
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

    return Analysis(symbol, h4[-1].end, price, daily, h4, atr_d[-1], atr4, structure, scan, active,
                    bias, source, levels, top, liq, h4r, status, st, forming=forming, forming_candle=forming_c)


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
        weak = [x for x in a.scan.drds if x.grade == "weak"]
        return "None active" + (f" ({len(weak)} Weak DRD(s) ignored)" if weak else "")
    early = "FORMING, Daily candle not closed yet: " if a.forming else ""
    return (f"{early}{d.grade.capitalize()} {d.score}/5 on {a.day_label(d.index)} "
            f"({'bullish' if d.direction == 'bull' else 'bearish'}, {d.rejection} rejection of {d.level.label} "
            f"{_fmt(d.level.lo)}-{_fmt(d.level.hi)}{', PDL/PDH swept' if d.sweep else ''})")


def h4_text(a: Analysis) -> str:
    r = a.h4_result
    if r is None:
        return "No active DRD to confirm"
    if r.status == "waiting":
        return "Waiting: no H4 body close through the latest H4 swing in the DRD direction yet"
    bo = a.h4[r.bo_index]
    word = "above" if a.drd.direction == "bull" else "below"
    out = f"Breakout: H4 body close {word} {_fmt(r.bo_swing.price)} at {_local(bo.end, a.st)} Lagos time"
    if r.sweep_text:
        out += f"; {r.sweep_text}"
    if r.rej_text:
        out += f"; H4 rejection at {_local(a.h4[r.rej_index].end, a.st)}: {r.rej_text}"
    if r.status == "cancelled":
        out += f"; CANCELLED: H4 closed back through {_fmt(r.bo_swing.price)} at {_local(a.h4[r.cancel_index].end, a.st)}"
    return out


def summary_text(a: Analysis) -> str:
    if a.bias == "neutral":
        return "No clear direction. No Strong/Medium DRD and no confirmed external break on Daily."
    word = a.bias.capitalize()
    if a.status == "no_setup":
        return f"{word} from Daily structure only. No DRD, no setup."
    if a.status == "watching":
        return f"{word} DRD is active. Waiting for the H4 breakout to confirm."
    if a.status == "confirmed":
        return f"{word} setup confirmed by an H4 breakout. Retest not seen yet."
    if a.status == "retest":
        return f"{word} setup confirmed and the H4 rejection (retest) has closed."
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


def alert_text(a: Analysis) -> str:
    d, r = a.drd, a.h4_result
    assert d is not None and r is not None and r.bo_index is not None
    arrow = "🟢" if d.direction == "bull" else "🔴"
    bo = a.h4[r.bo_index]
    word = "above" if d.direction == "bull" else "below"
    L = a.liquidity
    lines = [
        f"{arrow} SLK RADAR · {a.symbol}" + (" · EARLY, Daily not closed" if a.forming else ""),
        f"Bias: {a.bias.capitalize()} (Daily DRD, {d.grade} {d.score}/5)",
        f"Level: {_fmt(d.level.lo)}-{_fmt(d.level.hi)} · {d.level.label} · {d.level.status_text() if d.level.history else 'first reaction'}",
        f"DRD candle: {a.day_label(d.index)}" + (" (still open, can change)" if a.forming else ""),
        f"H4: body close {word} {_fmt(r.bo_swing.price)} · {_local(bo.end, a.st)} Lagos",
    ]
    if L.sweeps:
        lines.append("Sweep: " + L.sweeps[0].split(" (")[0])
    if r.sweep_text:
        lines.append("H4 sweep: " + r.sweep_text)
    if L.erl:
        lines.append(f"Target: {_fmt(L.erl.price)} ({L.erl.label})")
    return "\n".join(lines)


def retest_text(a: Analysis) -> str:
    r = a.h4_result
    assert a.drd is not None and r is not None and r.rej_index is not None
    return (f"🔁 SLK RADAR · {a.symbol} retest confirmed\n"
            f"H4 rejection {_local(a.h4[r.rej_index].end, a.st)} Lagos: {r.rej_text}\n"
            f"Bias still {a.bias}.")


def reminder_text(a: Analysis) -> str:
    d = a.drd
    if d is None:
        return f"SLK RADAR · {a.symbol}: no active DRD any more."
    state = {"cancelled": "BROKEN (cancelled)", "retest": "still valid, retest confirmed",
             "confirmed": "still valid", "watching": "still valid, H4 breakout not seen yet"}.get(a.status, a.status)
    return f"SLK RADAR reminder · {a.symbol} {a.bias}: setup is {state}. Price {_fmt(a.price)}."


# --------------------------------------------------------------------------- entry plan


def entry_plan(a: Analysis, h1: list[Candle], st: Settings | None = None) -> str:
    """Entry plan on request: nearest H1 key level on the right side below/above price, stop
    beyond its extreme, target the next external liquidity. Only for a valid, confirmed setup."""
    st = st or a.st
    if a.drd is None or a.status not in ("confirmed", "retest"):
        return f"{a.symbol}: no confirmed setup, so no entry plan."
    bull = a.drd.direction == "bull"
    h1c = [c for c in h1 if not market_closed(c.time) and c.time + timedelta(hours=1) <= a.as_of][-400:]
    atr1 = atr_series(h1c, st.atr_period)
    price = a.price
    levels = build_levels(h1c, atr1, st, upto=len(h1c))
    side = "buy" if bull else "sell"
    cand = [lv for lv in levels if lv.side == side and lv.state == "live"
            and ((bull and lv.hi <= price) or (not bull and lv.lo >= price))]
    if not cand:
        return f"{a.symbol}: no H1 {side} level found between the setup and price."
    lv = min(cand, key=lambda l: l.distance(price))
    buf = st.stop_buffer_atr * atr1[-1]
    if bull:
        entry, stop = lv.hi, lv.lo - buf
    else:
        entry, stop = lv.lo, lv.hi + buf
    tgt = a.liquidity.erl.price if a.liquidity.erl else None
    risk = abs(entry - stop)
    lines = [f"{a.symbol} {'buy' if bull else 'sell'} plan (not advice, your call)",
             f"Zone: {_fmt(lv.lo)}-{_fmt(lv.hi)} ({lv.label}, H1)",
             f"Entry: {_fmt(entry)} when an H1 candle closes away from the zone",
             f"Stop: {_fmt(stop)}"]
    if tgt is not None and risk > 0:
        rr = abs(tgt - entry) / risk
        lines.append(f"Target: {_fmt(tgt)} ({a.liquidity.erl.label}) · R:R {rr:.1f}" + ("" if rr >= st.rr_min else f" (below {st.rr_min:.0f})"))
    else:
        lines.append("Target: no external liquidity found")
    lines.append("Inducement (IDM): not checked by the radar yet. Look on H1 for a minor swing high/low taken just before the rejection.")
    lines.append(f"Cancel if: an H4 candle closes {'below' if bull else 'above'} {_fmt(a.h4_result.bo_swing.price)}, or the Daily level is disrespected.")
    return "\n".join(lines)
