"""Automatic results, so you do not have to journal by hand.

Every alerted setup is followed on closed H4 candles after its breakout:
  Win      the target (next liquidity) is reached first
  Loss     it is cancelled first (H4 closes back through the confirming swing, the DRD level is
           disrespected, or a new opposing DRD appears)
  Expired  neither happened within `result_expiry_days` (left out of the win rate)
Same candle reaches the target and cancels: counted as a loss (the safe reading).
This measures the radar's BIAS, not your own entries."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .radar import Analysis, _fmt, setup_key_for
from .settings import Settings
from .state import State


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat()


def setup_info(a: Analysis) -> dict:
    """What must be remembered about a setup to judge it later."""
    d, r = a.drd, a.h4_result
    return {
        "direction": d.direction,
        "target": a.target[0] if a.target else None,
        "target_label": a.target[1] if a.target else "",
        "swing": r.bo_swing.price,
        "bo_end": _iso(a.bo_time),
        "sweep": bool(d.sweep),
        "external": bool(r.external),
        "closed": None,
    }


def cancel_reason_late(a: Analysis, key: str) -> str | None:
    """Rules 1 and 2: the DRD itself no longer stands. Returns the reason, or None if it stands."""
    if a.setup_key == key and a.status != "cancelled":
        return None
    for d, why in a.scan.cancelled:
        if setup_key_for(a.symbol, d) == key:
            if "disrespected" in why:
                return "the Daily key level was disrespected (Rule 1)"
            return "a new opposing DRD appeared (Rule 2)"
    dead = {setup_key_for(a.symbol, d) for d, _ in a.scan.cancelled}
    alive = {setup_key_for(a.symbol, d) for d in a.scan.drds if d.actionable} - dead
    if key in alive:
        return None                      # another DRD became the active one, this one still stands
    if a.setup_key == key:
        return None                      # cancelled by the H4 rule, handled on the candles
    return "the DRD no longer stands"


def evaluate(v: dict, key: str, a: Analysis, now: datetime, st: Settings):
    """Returns None (still open) or (outcome, when, reason, price) with outcome in
    "win" | "loss" | "expired"."""
    bull = v["direction"] == "bull"
    bo_end = datetime.fromisoformat(v["bo_end"])
    tgt, swing = v.get("target"), v["swing"]
    for c in a.h4:
        if c.end <= bo_end:
            continue
        hit = tgt is not None and ((bull and c.high >= tgt) or (not bull and c.low <= tgt))
        cancel = (bull and c.close < swing) or (not bull and c.close > swing)
        if cancel:
            word = "below" if bull else "above"
            return ("loss", c.end, f"H4 body closed back {word} {_fmt(swing)} (Rule 3)", swing)
        if hit:
            return ("win", c.end, "target reached", tgt)
    why = cancel_reason_late(a, key)
    if why:
        return ("loss", now, why, None)
    if now - datetime.fromisoformat(v["alerted"]) > timedelta(days=st.result_expiry_days):
        return ("expired", now, "no result within a week", None)
    return None


# ---------------------------------------------------------------------------- numbers and text


def stats(state: State, since: datetime | None = None) -> dict:
    rows = state.data.get("results", [])
    if since is not None:
        rows = [r for r in rows if r["closed"] >= _iso(since)]
    w = sum(1 for r in rows if r["outcome"] == "win")
    l = sum(1 for r in rows if r["outcome"] == "loss")
    e = sum(1 for r in rows if r["outcome"] == "expired")
    rate = w / (w + l) if (w + l) else None
    return {"win": w, "loss": l, "expired": e, "rate": rate}


def open_count(state: State) -> int:
    return sum(1 for v in state.data["setups"].values() if v.get("notified") and not v.get("closed"))


def _rate(x: dict, goal: float) -> str:
    if x["rate"] is None:
        return "no closed setups yet"
    return f"{x['rate'] * 100:.0f}% win rate (goal {goal * 100:.0f}%)"


def scorecard_text(state: State, now: datetime, st: Settings) -> str:
    wk = stats(state, now - timedelta(days=7))
    al = stats(state)
    return "\n".join([
        "📊 SLK RADAR · weekly scorecard",
        "",
        f"This week: {wk['win']} won · {wk['loss']} lost · {wk['expired']} expired",
        f"Week: {_rate(wk, st.win_rate_goal)}",
        f"All time: {al['win']} won · {al['loss']} lost · {al['expired']} expired",
        f"All time: {_rate(al, st.win_rate_goal)}",
        f"Open now: {open_count(state)}",
        "",
        "Measures the radar's bias (target before cancel), not your own entries.",
    ])


def results_text(state: State, st: Settings) -> str:
    al = stats(state)
    last = state.data.get("results", [])[-5:]
    lines = ["📊 SLK RADAR · results", "",
             f"{al['win']} won · {al['loss']} lost · {al['expired']} expired · {open_count(state)} open",
             _rate(al, st.win_rate_goal)]
    if last:
        lines += ["", "Latest:"]
        for r in reversed(last):
            mark = {"win": "✅", "loss": "❌", "expired": "⏳"}[r["outcome"]]
            lines.append(f"{mark} {r['symbol']} {'buy' if r['direction'] == 'bull' else 'sell'}")
    return "\n".join(lines)
