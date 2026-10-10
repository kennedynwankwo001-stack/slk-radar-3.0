import io, json, os, tempfile, unittest, urllib.error
from datetime import datetime, timedelta, timezone

from slk_radar.candles import aggregate, bucket_start, forming_candle, load_csv, market_closed
from slk_radar.data import DataError, fetch_h1, parse_values, update_candles
from slk_radar.models import Candle
from slk_radar.notify import NotifyError, PrintNotifier, TelegramNotifier
from slk_radar.pairs import PAIRS, td_symbol
from slk_radar.radar import analyze
from slk_radar.scanner import run_scan
from slk_radar.state import State

U = timezone.utc
HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")


def utc(*a):
    return datetime(*a, tzinfo=U)


class Candles(unittest.TestCase):
    def test_summer_daily_and_h4_boundaries(self):
        self.assertEqual(bucket_start(utc(2026, 10, 1, 12), 24), utc(2026, 9, 30, 21))
        self.assertEqual(bucket_start(utc(2026, 10, 1, 12), 4), utc(2026, 10, 1, 9))

    def test_winter_boundaries(self):
        self.assertEqual(bucket_start(utc(2026, 12, 1, 12), 24), utc(2026, 11, 30, 22))
        self.assertEqual(bucket_start(utc(2026, 12, 1, 12), 4), utc(2026, 12, 1, 10))

    def test_weekend_dropped(self):
        self.assertTrue(market_closed(utc(2026, 10, 10, 12)))
        self.assertFalse(market_closed(utc(2026, 10, 9, 12)))

    def test_pairs(self):
        self.assertEqual(len(PAIRS), 23)
        self.assertEqual(td_symbol("EURUSD"), "EUR/USD")

    def test_aggregate_h4_ohlc(self):
        h1 = [Candle(utc(2026, 10, 1, 9 + i), 1 + i, 2 + i, 0 + i, 1.5 + i, utc(2026, 10, 1, 10 + i)) for i in range(4)]
        out = aggregate(h1, 4, drop_weekend=True)
        self.assertEqual(len(out), 1)
        c = out[0]
        self.assertEqual((c.open, c.high, c.low, c.close), (1, 5, 0, 4.5))

    def test_forming_candle_partial(self):
        h1 = [Candle(utc(2026, 10, 1, 9 + i), 1, 2, 0.5, 1.5, utc(2026, 10, 1, 10 + i)) for i in range(2)]
        f = forming_candle(h1, 4, now=utc(2026, 10, 1, 11))
        self.assertIsNotNone(f)
        self.assertEqual(f[0].time, utc(2026, 10, 1, 9))


class EurAud(unittest.TestCase):
    def test_replay_matches_trade(self):
        h1 = load_csv(os.path.join(DATA, "EURAUD_H1.csv"))
        a = analyze("EURAUD", h1, now=utc(2026, 9, 29, 9))
        self.assertEqual(a.bias, "bullish")
        self.assertEqual(a.drd.grade, "strong")
        self.assertEqual(a.status, "confirmed")
        self.assertAlmostEqual(a.drd.level.lo, 1.61675, places=4)
        self.assertAlmostEqual(a.drd.level.hi, 1.61746, places=4)
        self.assertAlmostEqual(a.h4_result.bo_swing.price, 1.62130, places=4)
        self.assertEqual(a.bo_time, utc(2026, 9, 29, 9))
        a2 = analyze("EURAUD", h1, now=utc(2026, 9, 29, 9) - timedelta(hours=4))
        self.assertEqual(a2.status, "watching")


class CadChf(unittest.TestCase):
    def setUp(self):
        self.h1 = load_csv(os.path.join(DATA, "CADCHF_H1.csv"))

    def test_bear_drd_confirmed_then_cancelled(self):
        a = analyze("CADCHF", self.h1, now=utc(2026, 10, 8, 1))
        self.assertEqual((a.bias, a.drd.grade, a.drd.score, a.status), ("bearish", "strong", 5, "confirmed"))
        self.assertAlmostEqual(a.h4_result.bo_swing.price, 0.58409, places=4)
        a = analyze("CADCHF", self.h1, now=utc(2026, 10, 8, 9))
        self.assertEqual(a.status, "cancelled")


class Data(unittest.TestCase):
    PAY = {"values": [{"datetime": "2026-10-01 10:00:00", "open": "1", "high": "2", "low": "0.5", "close": "1.5"},
                      {"datetime": "2026-10-01 09:00:00", "open": "1", "high": "2", "low": "0.5", "close": "1.2"}]}

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def test_parse_sorted(self):
        c = parse_values(self.PAY)
        self.assertLess(c[0].time, c[1].time)

    def test_error_payload(self):
        with self.assertRaises(DataError):
            parse_values({"status": "error", "code": 401, "message": "bad key"})

    def test_retry_on_429_and_key_hidden(self):
        calls = []
        def opener(url, timeout):
            calls.append(url)
            body = {"code": 429, "message": "limit"} if len(calls) == 1 else self.PAY
            return self.Resp(json.dumps(body).encode())
        out = fetch_h1("EURUSD", "SECRETKEY", opener=opener, sleep=lambda s: None)
        self.assertEqual(len(out), 2)
        self.assertEqual(len(calls), 2)

    def test_network_failure_message_has_no_key(self):
        def opener(url, timeout):
            raise urllib.error.URLError("boom SECRETKEY")
        with self.assertRaises(DataError) as cm:
            fetch_h1("EURUSD", "SECRETKEY", opener=opener, sleep=lambda s: None)
        self.assertNotIn("SECRETKEY", str(cm.exception))

    def test_cache_merge(self):
        with tempfile.TemporaryDirectory() as d:
            fetch = lambda pair, key, n: parse_values(self.PAY)
            update_candles("EURUSD", "k", d, now=utc(2026, 10, 1, 12), fetch=fetch)
            out = update_candles("EURUSD", "k", d, now=utc(2026, 10, 1, 12), fetch=fetch)
            self.assertEqual(len(out), 2)


class Notify(unittest.TestCase):
    def test_telegram_ok_and_token_hidden(self):
        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): pass
        t = TelegramNotifier("TOKEN123", "42", opener=lambda req, timeout: R(b'{"ok": true}'))
        t.send("hi")
        self.assertEqual(t.sent, ["hi"])
        def bad(req, timeout): raise urllib.error.URLError("x TOKEN123")
        with self.assertRaises(NotifyError) as cm:
            TelegramNotifier("TOKEN123", "42", opener=bad).send("hi")
        self.assertNotIn("TOKEN123", str(cm.exception))


class Scanner(unittest.TestCase):
    def setUp(self):
        self.h1 = {"CADCHF": load_csv(os.path.join(DATA, "CADCHF_H1.csv"))}
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "state.json")

    def tearDown(self):
        self.tmp.cleanup()

    def run_at(self, now, notifier=None):
        n = notifier or PrintNotifier()
        run_scan(now, State(self.path), n, lambda p: self.h1[p], pairs=["CADCHF"], spacing=0, log=lambda *a: None)
        return n

    def test_cold_start_is_silent_then_alert_once(self):
        n = self.run_at(utc(2026, 10, 7, 21, 30))              # baseline
        self.assertEqual(len(n.sent), 1)                       # only the "radar is on" message
        n = self.run_at(utc(2026, 10, 8, 1, 30))               # BO closes 01:00 UTC boundary
        self.assertEqual(len(n.sent), 1)
        self.assertIn("SLK RADAR · CADCHF", n.sent[0])
        n = self.run_at(utc(2026, 10, 8, 1, 40))               # same candle again
        self.assertEqual(n.sent, [])

    def test_no_double_alert_next_candle(self):
        self.run_at(utc(2026, 10, 7, 21, 30))
        self.run_at(utc(2026, 10, 8, 1, 30))
        n = self.run_at(utc(2026, 10, 8, 5, 30))
        self.assertEqual(len(n.sent), 1)
        self.assertIn("retest confirmed", n.sent[0])

    def test_daily_close_sends_reminder_and_watchlist(self):
        self.run_at(utc(2026, 10, 7, 21, 30))
        self.run_at(utc(2026, 10, 8, 1, 30))
        n = self.run_at(utc(2026, 10, 8, 21, 30))
        text = "\n".join(n.sent)
        self.assertIn("reminder", text)
        self.assertIn("SLK RADAR", text)

    def test_failed_pair_retried_same_candle(self):
        def boom(p): raise DataError("down")
        st = State(self.path)
        run_scan(utc(2026, 10, 7, 21, 30), st, PrintNotifier(), boom, pairs=["CADCHF"], spacing=0, log=lambda *a: None)
        self.assertEqual(State(self.path).retry, ["CADCHF"])
        n = self.run_at(utc(2026, 10, 7, 21, 45))
        self.assertEqual(State(self.path).retry, [])


if __name__ == "__main__":
    unittest.main()


class Commands(unittest.TestCase):
    def test_entry_command_answers_own_chat_only(self):
        from slk_radar.commands import handle_commands
        h1 = load_csv(os.path.join(DATA, "EURAUD_H1.csv"))
        class N(PrintNotifier):
            chat_id = "42"
            def get_updates(self, offset=None):
                return [{"update_id": 1, "message": {"chat": {"id": 42}, "text": "/entry EURAUD"}},
                        {"update_id": 2, "message": {"chat": {"id": 99}, "text": "/entry EURAUD"}},
                        {"update_id": 3, "message": {"chat": {"id": 42}, "text": "/entry XXXYYY"}}]
        with tempfile.TemporaryDirectory() as d:
            st = State(os.path.join(d, "s.json"))
            n = N()
            done = handle_commands(n, st, lambda p: h1, utc(2026, 9, 29, 13), log=lambda *a: None)
            self.assertEqual(done, 2)
            self.assertIn("EURAUD", n.sent[0] + n.sent[1])
            self.assertEqual(st.data["tg_offset"], 4)


class NoFlood(unittest.TestCase):
    def test_baseline_setups_get_no_reminder(self):
        h1 = {"CADCHF": load_csv(os.path.join(DATA, "CADCHF_H1.csv"))}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            for now in (utc(2026, 10, 8, 5, 30), utc(2026, 10, 8, 21, 30)):   # baseline, then a Daily close
                n = PrintNotifier()
                run_scan(now, State(path), n, lambda p: h1[p], pairs=["CADCHF"], spacing=0, log=lambda *a: None)
            self.assertFalse(any("reminder" in t for t in n.sent))

    def test_chat_id_with_space_still_answers(self):
        from slk_radar.commands import handle_commands
        class N(PrintNotifier):
            chat_id = "42 \n"
            def get_updates(self, offset=None):
                return [{"update_id": 1, "message": {"chat": {"id": 42}, "text": "/help"}}]
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(handle_commands(N(), State(os.path.join(d, "s.json")), None, utc(2026, 10, 8), log=lambda *a: None), 1)
