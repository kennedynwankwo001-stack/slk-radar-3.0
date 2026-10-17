"""Telegram commands, answered at the start of every scan run:
  /radar EURAUD   the full radar read
  /results        how the alerted setups ended (won, lost, open)
Only messages from your own chat are answered."""
from __future__ import annotations

import re
from datetime import datetime

from .notify import NotifyError
from .pairs import PAIRS
from .radar import analyze, radar_text
from .results import results_text
from .settings import Settings
from .state import State

HELP = "Commands: /radar EURAUD (full read) · /results (how alerts ended). The radar gives bias only, no entries."


def reply_for(text: str, get_h1, now: datetime, st: Settings, state: State | None = None) -> str | None:
    t = (text or "").strip()
    if re.match(r"^/results(?:@\w+)?\s*$", t):
        return results_text(state, st) if state is not None else HELP
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
            log(f"ignored a message from another chat ({(msg.get('chat') or {}).get('id')}); your TELEGRAM_CHAT_ID is {str(notifier.chat_id).strip()!r}")
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
