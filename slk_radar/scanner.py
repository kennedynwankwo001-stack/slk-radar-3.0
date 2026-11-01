"""The live scan: after each H4 close, read every pair, send each new stage once.

Stages per setup (each sent once, remembered in State):
  early      clean DRD on the still-open Daily candle + H4 BO + H4 sweep (Daily not closed yet)
  confirmed  clean DRD on a closed Daily candle + external H4 BO + H4 sweep -> the one bias alert
             (at most `max_alerts_per_day` per Daily day, best first)
  cancelled  the setup died (3 rules) before its target
  target     the target was reached
Plus one daily summary at each Daily close, and a weekly scorecard at the Friday close.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .candles import latest_daily_boundary, latest_h4_boundary
from .notify import NotifyError
from .pairs import PAIRS
from . import results as res_mod
from .radar import Analysis, _fmt, _when, alert_text, analyze, cancelled_text, target_text
from .settings import Settings
from .state import State

STALE_H4 = 3   # a breakout older than this many H4 candles is not announced as new (after downtime)


def _late(now: datetime, t: datetime | None) -> str:
    """A warning line when a message goes out long after the candle that caused it closed."""
    if t is None or now - t < timedelta(minutes=45):
        return ""
    m = int((now - t).total_seconds() // 60)
    return f"\n⚠️ Sent {m // 60}h {m % 60}m after the candle closed (late run). Check price before acting."


def board_row(a: Analysis) -> dict | None:
    """One line of the board: a completed storyline (DRD + external H4 BO) that is still alive,
    or a DRD still waiting for its H4 BO. None if there is nothing to show for this pair."""
    d = a.drd
    if d is None or not d.actionable or a.status == "cancelled":
        return None
    bull = d.direction == "bull"
    base = {"symbol": a.symbol, "dir": d.direction, "sweep": bool(d.sweep),
            "level": f"{_fmt(d.level.lo)}-{_fmt(d.level.hi)}"}
    if a.status == "watching":
        return {**base, "kind": "watching", "note": "waiting for H4 BO"}
    if a.status == "bo_wait":
        return {**base, "kind": "watching", "note": "BO done, waiting for H4 sweep"}
    if a.status != "confirmed" or a.bo_time is None:
        return None
    tgt = a.target[0] if a.target else None
    if tgt is not None and any(c.end > a.bo_time and ((bull and c.high >= tgt) or (not bull and c.low <= tgt)) for c in a.h4):
        return None                                                   # target already reached
    return {**base, "kind": "active", "bo": _when(a.bo_time, a.st), "target": tgt}


def board_line(r: dict) -> str:
    arrow = "🟢" if r["dir"] == "bull" else "🔴"
    head = f"{arrow} {r['symbol']} {'buy' if r['dir'] == 'bull' else 'sell'}{' · sweep' if r['sweep'] else ''} · Daily {r['level']}"
    if r["kind"] == "watching":
        return head + " · " + r.get("note", "waiting for H4 BO")
    tail = f" · BO {r['bo']}" + (f" · target {_fmt(r['target'])}" if r.get("target") else "")
    return head + tail


def board_text(rows: list[dict], kind: str, updated: str | None) -> str:
    rows = [r for r in rows if r["kind"] == kind]
    title = "📡 SLK RADAR · completed storylines" if kind == "active" else "👀 SLK RADAR · DRD waiting for H4 breakout"
    if not rows:
        return title + "\n\nNone right now."
    rows.sort(key=lambda r: (-int(r["sweep"]), r["symbol"]))
    out = [title, ""] + [board_line(r) for r in rows]
    if updated:
        out += ["", f"As of the scan at {updated}"]
    return "\n".join(out)


def _summary_text(day: datetime, active: list, watching: list, st: Settings) -> str:
    """One message at each Daily close."""
    lines = [f"📋 SLK RADAR · daily summary · {day.astimezone(ZoneInfo(st.display_tz)):%a %d %b}"]
    if not (active or watching):
        lines += ["", "Nothing active and nothing developing right now."]
        return "\n".join(lines)

    def row(a: Analysis, tail: str) -> str:
        d = a.drd
        arrow = "🟢" if d.direction == "bull" else "🔴"
        return f"{arrow} {a.symbol} {'buy' if d.direction == 'bull' else 'sell'}{' · sweep' if d.sweep else ''}{tail}"

    if active:
        lines += ["", "STILL VALID (alerted before)"]
        lines += [row(a, "") for a in active]
    if watching:
        lines += ["", "WATCHING (not complete yet)"]
        lines += [row(a, "") for a in watching]
    return "\n".join(lines)


def run_scan(
    now: datetime,
    state: State,
    notifier,
    get_h1,                       # get_h1(pair) -> list[Candle]
    pairs: list[str] | None = None,
    st: Settings | None = None,
    spacing: float = 8.0,
    sleep=time.sleep,
    log=print,
) -> dict:
    st = st or Settings()
    pairs = pairs or PAIRS
    boundary = latest_h4_boundary(now)
    b_iso = boundary.astimezone(timezone.utc).isoformat()
    same = state.last_boundary == b_iso
    todo = state.retry if same else list(pairs)
    if same and not todo:
        log("This H4 candle was already scanned. Nothing to do.")
        return {"skipped": True, "sent": 0, "failed": []}

    baseline = state.is_new
    daily_close = boundary == latest_daily_boundary(now)
    sent, failed, analyses = 0, [], {}

    def send(key: str, text: str) -> bool:
        nonlocal sent
        if state.was_sent(key):
            return False
        if baseline:
            state.mark_sent(key, now)
            return False
        try:
            notifier.send(text)
        except NotifyError as e:
            log(f"send failed: {e}")
            return None
        state.mark_sent(key, now)
        sent += 1
        return True

    cands: list[tuple[Analysis, str]] = []      # new bias alerts waiting for the daily cap
    for n, pair in enumerate(todo):
        if n and spacing:
            sleep(spacing)
        try:
            h1 = get_h1(pair)
            a = analyze(pair, h1, st, now=now)
        except Exception as e:                                   # one bad pair must not stop the scan
            log(f"{pair}: skipped ({type(e).__name__}: {e})")
            failed.append(pair)
            continue
        analyses[pair] = a
        d = a.drd
        if d is None or not a.alertable:
            continue
        key = a.setup_key
        fresh = a.confirm_time is not None and a.confirm_time >= boundary - timedelta(hours=4 * STALE_H4)
        if a.forming:
            if st.early_alert and fresh and not state.was_sent(key + "|confirmed") and not state.was_sent(key + "|early"):
                cands.append((a, "early"))
        else:
            if state.was_sent(key + "|early"):
                state.mark_sent(key + "|confirmed", now)          # already told; the Daily candle held
            elif not state.was_sent(key + "|confirmed"):
                if fresh:
                    cands.append((a, "confirmed"))
                else:
                    state.mark_sent(key + "|confirmed", now)      # old breakout: no flood after downtime

    # bias alerts: best first, at most `max_alerts_per_day` per Daily day
    day = latest_daily_boundary(now)
    room = max(0, st.max_alerts_per_day - state.day_count(day))
    for a, stage in sorted(cands, key=lambda x: x[0].rank_key, reverse=True):
        if not baseline and room <= 0:
            log(f"{a.symbol}: daily cap of {st.max_alerts_per_day} reached, not sent")
            continue
        r = send(a.setup_key + "|" + stage, alert_text(a) + _late(now, a.confirm_time))
        if r is None:
            failed.append(a.symbol)
        elif r:
            state.add_setup(a.setup_key, a.symbol, now, res_mod.setup_info(a))
            state.bump_day(day)
            room -= 1

    # results: cancelled / target reached / expired
    for key, v in list(state.data["setups"].items()):
        if not v.get("notified") or v.get("closed") or "bo_end" not in v:
            continue
        a = analyses.get(v["symbol"])
        if a is None:
            continue
        out = res_mod.evaluate(v, key, a, now, st)
        if out is None:
            continue
        outcome, when, reason, price = out
        if outcome == "win":
            r = send("res|" + key, target_text(v["symbol"], v["direction"], price, when, st))
        elif outcome == "loss":
            r = send("res|" + key, cancelled_text(v["symbol"], v["direction"], reason, when, st))
        else:
            r = True
        if r is None:
            failed.append(v["symbol"])
            continue
        state.close_setup(key, outcome, now)

    if daily_close and not failed:
        dboundary = latest_daily_boundary(now)
        active = []
        for key, v in state.due_reminders(dboundary):
            a = analyses.get(v["symbol"])
            if a is None:
                continue
            if a.setup_key == key and a.status == "confirmed":
                active.append(a)
            state.mark_reminded(key)
        watching = sorted(
            [a for a in analyses.values() if a.status in ("watching", "bo_wait") and a.drd and a.drd.actionable],
            key=lambda a: (-int(a.drd.sweep), a.symbol),
        )[:3]
        tag = dboundary.astimezone(timezone.utc).isoformat()
        if baseline:
            state.mark_sent("watch|" + tag, now)
        else:
            send("watch|" + tag, _summary_text(dboundary, active, watching, st))
            if dboundary.astimezone(ZoneInfo(st.daily_close_tz)).weekday() == 4:   # Friday close: the week is over
                send("score|" + tag, res_mod.scorecard_text(state, now, st))

    rows = [r for r in (board_row(a) for a in analyses.values()) if r]
    old = {r["symbol"]: r for r in state.data.get("board", []) if r["symbol"] not in analyses}
    state.data["board"] = rows + list(old.values())
    state.data["scan_info"] = {"at": _when(now, st), "boundary": b_iso, "ok": len(todo) - len(failed), "total": len(todo),
                               "failed": list(failed)}
    if baseline and not failed:
        try:
            msg = "✅ SLK Radar is on. Starting point saved. New alerts begin from the next H4 close."
            if any(r["kind"] == "active" for r in rows):
                act = sorted((r for r in rows if r["kind"] == "active"), key=lambda r: (-int(r["sweep"]), r["symbol"]))
                msg += "\n\nAlready completed and still alive:\n" + "\n".join(board_line(r) for r in act)
            notifier.send(msg)
        except NotifyError as e:
            log(f"send failed: {e}")

    state.last_boundary = boundary
    state.retry = failed
    state.prune(now)
    state.save()
    log(f"Scanned {len(todo) - len(failed)}/{len(todo)} pairs, sent {sent} message(s)" + (f", retry: {failed}" if failed else ""))
    return {"skipped": False, "sent": sent, "failed": failed}
