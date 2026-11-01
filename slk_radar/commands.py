"""Telegram commands, answered at the start of every scan run:
  /radar EURAUD   the full radar read
  /results        how the alerted setups ended (won, lost, open)
  /active         completed storylines still alive      /watching  DRD waiting for the H4 BO
  /status         last scan time, open setups, alerts today      /help
Only messages from your own chat are answered."""
from __future__ import annotations

import re
from datetime import datetime

from .notify import NotifyError
from .pairs import PAIRS
from .radar import analyze, radar_text
from .results import results_text
from .scanner import board_text
from .settings import Settings
from .state import State

HELP = ("Commands:\n/active · completed storylines still alive\n/watching · DRD waiting for the H4 breakout\n"
        "/radar EURAUD · full read of one pair\n/results · how alerts ended\n/status · is the radar running\n"
        "/help · this list\nThe radar gives bias only, no entries.")


def reply_for(text: str, get_h1, now: datetime, st: Settings, state: State | None = None) -> str | None:
    t = (text or "").strip()
    if re.match(r"^/results(?:@\w+)?\s*$", t):
        return results_text(state, st) if state is not None else HELP
    if state is not None:
        if re.match(r"^/(active|storylines)(?:@\w+)?\s*$", t):
            return board_text(state.data.get("board", []), "active", (state.data.get("scan_info") or {}).get("at"))
        if re.match(r"^/(watching|watch)(?:@\w+)?\s*$", t):
            return board_text(state.data.get("board", []), "watching", (state.data.get("scan_info") or {}).get("at"))
        if re.match(r"^/status(?:@\w+)?\s*$", t):
            return status_text(state, st, now)
    if re.match(r"^/(help|start)(?:@\w+)?\s*$", t):
        return HELP
    m = re.match(r"^/radar(?:@\w+)?(?:\s+([A-Za-z/]+))?\s*$", t)
    if not m:
        return HELP if t.startswith("/") else None
    pair = (m.group(1) or "").replace("/", "").upper()
    if pair not in PAIRS:
        return f"Pair not in the list. Try one of: {', '.join(PAIRS[:6])} ...\n{HELP}"
    try:
        h1 = get_h1(pair)
        return radar_text(analyze(pair, h1, st, now=now))
    except Exception as e:
        return f"{pair}: could not read data right now ({type(e).__name__}). Try again later."


def status_text(state: State, st: Settings, now: datetime) -> str:
    from .results import open_count
    from .scanner import latest_daily_boundary
    info = state.data.get("scan_info")
    if not info:
        return "SLK Radar has not finished a scan yet."
    day = latest_daily_boundary(now)
    lines = ["🟢 SLK RADAR · status", "",
             f"Last scan: {info['at']} Lagos ({info['ok']}/{info['total']} pairs read)",
             f"Open setups: {open_count(state)}",
             f"Alerts today: {state.day_count(day)}/{st.max_alerts_per_day}"]
    if info.get("failed"):
        lines.append("Pairs that failed last time: " + ", ".join(info["failed"]))
    lines.append("Scans run about 4 minutes after each H4 close, Mon-Fri.")
    return "\n".join(lines)


def handle_commands(notifier, state: State, get_h1, now: datetime, st: Settings | None = None, log=print) -> int:
    st = st or Settings()
    offset = state.data.get("tg_offset")
    try:
        updates = notifier.get_updates(offset)
    except NotifyError as e:
        log(str(e))
        return 0
    done = 0
    for u in updates:
        state.data["tg_offset"] = u["update_id"] + 1
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")).strip() != str(notifier.chat_id).strip():
            log("ignored a message from a chat that is not your TELEGRAM_CHAT_ID")
            continue
        log(f"command: {msg.get('text', '')[:40]!r}")
        text = reply_for(msg.get("text", ""), get_h1, now, st, state)
        if text:
            try:
                notifier.send(text)
                done += 1
            except NotifyError as e:
                log(str(e))
    state.save()
    return done
