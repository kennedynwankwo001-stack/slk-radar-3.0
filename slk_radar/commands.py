"""Telegram commands, answered at the start of every scan run:
  /entry EURAUD   entry plan for a confirmed setup
  /radar EURAUD   the full radar read
Only messages from your own chat are answered."""
from __future__ import annotations

import re
from datetime import datetime

from .notify import NotifyError
from .pairs import PAIRS
from .radar import analyze, entry_plan, radar_text
from .settings import Settings
from .state import State

HELP = "Commands: /entry EURAUD (entry plan) · /radar EURAUD (full read)"


def reply_for(text: str, get_h1, now: datetime, st: Settings) -> str | None:
    m = re.match(r"^/(entry|radar)(?:@\w+)?(?:\s+([A-Za-z/]+))?\s*$", (text or "").strip())
    if not m:
        return HELP if (text or "").strip().startswith("/") else None
    cmd, pair = m.group(1), (m.group(2) or "").replace("/", "").upper()
    if pair not in PAIRS:
        return f"Pair not in the list. Try one of: {', '.join(PAIRS[:6])} ...\n{HELP}"
    try:
        h1 = get_h1(pair)
        a = analyze(pair, h1, st, now=now)
        return entry_plan(a, h1, st) if cmd == "entry" else radar_text(a)
    except Exception as e:
        return f"{pair}: could not read data right now ({type(e).__name__}). Try again later."


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
        if str((msg.get("chat") or {}).get("id")) != str(notifier.chat_id):
            continue
        text = reply_for(msg.get("text", ""), get_h1, now, st)
        if text:
            try:
                notifier.send(text)
                done += 1
            except NotifyError as e:
                log(str(e))
    state.save()
    return done
