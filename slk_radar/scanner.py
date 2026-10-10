"""The live scan: after each H4 close, read every pair, send each new stage once.

Stages per setup (each sent once, remembered in State):
  early      Strong DRD on the still-open Daily candle + H4 breakout (Daily not closed yet)
  confirmed  Strong/Medium DRD on a closed Daily candle + H4 body-close breakout
  retest     H4 rejection after the breakout
  reminder   next Daily close: still valid or broken
Plus one watchlist message per Daily close: the 3 best developing setups (not confirmed).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from .candles import latest_daily_boundary, latest_h4_boundary
from .notify import NotifyError
from .pairs import PAIRS
from .radar import Analysis, alert_text, analyze, reminder_text, retest_text
from .settings import Settings
from .state import State

STALE_H4 = 3   # a breakout older than this many H4 candles is not announced as new (after downtime)


def _watch_text(items: list[Analysis]) -> str:
    if not items:
        return "SLK RADAR · watching: nothing developing right now (no Strong/Medium DRD waiting for an H4 breakout)."
    lines = ["👀 SLK RADAR · watching, not confirmed yet"]
    for a in items:
        d = a.drd
        arrow = "🟢" if d.direction == "bull" else "🔴"
        lines.append(f"{arrow} {a.symbol} {a.bias}: {d.grade} {d.score}/5 at {d.level.lo:.5f}-{d.level.hi:.5f}, waiting for the H4 breakout")
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
        fresh = a.bo_time is not None and a.bo_time >= boundary - timedelta(hours=4 * STALE_H4)
        ok = True
        if a.forming:
            if st.early_alert and d.grade == st.early_min_grade and fresh and not state.was_sent(key + "|confirmed"):
                r = send(key + "|early", alert_text(a))
                ok = r is not None
                if r:
                    state.add_setup(key, pair, now)
        else:
            if state.was_sent(key + "|early"):
                state.mark_sent(key + "|confirmed", now)          # already told; the Daily candle held
            elif fresh:
                r = send(key + "|confirmed", alert_text(a))
                ok = r is not None
                if r:
                    state.add_setup(key, pair, now)
            else:
                state.mark_sent(key + "|confirmed", now)          # old breakout: no flood after downtime
            if a.status == "retest" and a.h4_result.rej_index is not None:
                if a.h4[a.h4_result.rej_index].end >= boundary - timedelta(hours=4 * STALE_H4):
                    ok = ok and send(key + "|retest", retest_text(a)) is not None
                else:
                    state.mark_sent(key + "|retest", now)
        if not ok:
            failed.append(pair)

    if daily_close and not failed:
        dboundary = latest_daily_boundary(now)
        for key, v in state.due_reminders(dboundary):
            a = analyses.get(v["symbol"])
            if a is None:
                continue
            if a.setup_key == key:
                text = reminder_text(a)
            else:
                text = f"SLK RADAR reminder · {v['symbol']}: the earlier setup is no longer active (cancelled, or replaced by a new Daily signal)."
            if send(key + "|reminder", text) is not None:
                state.mark_reminded(key)
        best = sorted(
            [a for a in analyses.values() if a.status == "watching" and a.drd and a.drd.actionable],
            key=lambda a: (-a.drd.score, a.symbol),
        )[:3]
        send("watch|" + dboundary.astimezone(timezone.utc).isoformat(), _watch_text(best))

    if baseline and not failed:
        try:
            notifier.send("✅ SLK Radar is on. Starting point saved. Alerts begin from the next H4 close.")
        except NotifyError as e:
            log(f"send failed: {e}")

    state.last_boundary = boundary
    state.retry = failed
    state.prune(now)
    state.save()
    log(f"Scanned {len(todo) - len(failed)}/{len(todo)} pairs, sent {sent} message(s)" + (f", retry: {failed}" if failed else ""))
    return {"skipped": False, "sent": sent, "failed": failed}
