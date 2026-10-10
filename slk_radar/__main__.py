"""Command line.

  python -m slk_radar radar FILE.csv --symbol EURAUD [--as-of 2026-10-01T12:00] [--entry]
  python -m slk_radar replay FILE.csv --symbol EURAUD --from 2026-09-28 --to 2026-10-01
  python -m slk_radar scan [--dry-run]

`scan` reads TWELVE_DATA_API_KEY, TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from the environment
(GitHub repo secrets). State and candle cache live in --data-dir (default: ./radar_data).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from .candles import load_csv
from .data import DataError, update_candles
from .notify import PrintNotifier, TelegramNotifier
from .radar import alert_text, analyze, entry_plan, radar_text, retest_text
from .commands import handle_commands
from .scanner import run_scan
from .state import State


def _t(s: str) -> datetime:
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="slk_radar")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("radar"); r.add_argument("file"); r.add_argument("--symbol", required=True)
    r.add_argument("--as-of"); r.add_argument("--entry", action="store_true")
    rp = sub.add_parser("replay"); rp.add_argument("file"); rp.add_argument("--symbol", required=True)
    rp.add_argument("--from", dest="start", required=True); rp.add_argument("--to", dest="end", required=True)
    s = sub.add_parser("scan"); s.add_argument("--dry-run", action="store_true")
    s.add_argument("--data-dir", default="radar_data"); s.add_argument("--pairs")
    a = p.parse_args(argv)

    if a.cmd == "radar":
        h1 = load_csv(a.file)
        an = analyze(a.symbol, h1, now=_t(a.as_of) if a.as_of else None)
        print(radar_text(an))
        if a.entry:
            print("\n" + entry_plan(an, h1))
        return 0

    if a.cmd == "replay":
        h1 = load_csv(a.file)
        t, end, seen = _t(a.start), _t(a.end), set()
        while t <= end:
            if t.hour in (1, 5, 9, 13, 17, 21):
                an = analyze(a.symbol, h1, now=t)
                if an.alertable:
                    k = an.setup_key
                    if k + "|c" not in seen and not an.forming:
                        seen.add(k + "|c"); print(f"[{t:%a %d %b %H:%M} UTC]\n{alert_text(an)}\n")
                    if an.status == "retest" and k + "|r" not in seen:
                        seen.add(k + "|r"); print(f"[{t:%a %d %b %H:%M} UTC]\n{retest_text(an)}\n")
            t += timedelta(hours=1)
        return 0

    key = os.environ.get("TWELVE_DATA_API_KEY", "")
    if not key:
        print("Missing TWELVE_DATA_API_KEY (set it as a GitHub repo secret).", file=sys.stderr)
        return 2
    if a.dry_run:
        notifier = PrintNotifier()
    else:
        tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
        if not tok or not chat:
            print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.", file=sys.stderr)
            return 2
        notifier = TelegramNotifier(tok, chat)
    now = datetime.now(timezone.utc)
    cache = os.path.join(a.data_dir, "candles")
    state = State(os.path.join(a.data_dir, "state.json"))
    pairs = a.pairs.split(",") if a.pairs else None
    get_h1 = lambda pair: update_candles(pair, key, cache, now)
    try:
        if isinstance(notifier, TelegramNotifier):
            handle_commands(notifier, state, get_h1, now)
        res = run_scan(now, state, notifier, get_h1, pairs=pairs)
    except DataError as e:
        print(f"Data error: {e}", file=sys.stderr)
        return 1
    return 1 if res["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
