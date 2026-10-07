import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import rates_to_sheet as m


def fake_api(date, rates):
    return lambda url: {"date": date, "rates": rates}


class FakeWorksheet:
    """Stands in for a gspread worksheet."""
    def __init__(self):
        self.data = []

    def row_values(self, i):
        return self.data[i - 1] if len(self.data) >= i else []

    def append_row(self, row):
        self.data.append(row)

    def append_rows(self, rows, value_input_option=None):
        self.data.extend(rows)

    def get_all_values(self):
        return self.data


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.table = m.CsvTable(self.dir / "rates.csv")
        self.outbox = self.dir / "outbox.txt"
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_day_writes_rows_no_alert(self):
        r = m.run(self.table, "EUR", ["USD", "GBP"], 0.5, self.outbox, get=fake_api("2026-10-05", {"USD": 1.12, "GBP": 0.85}))
        self.assertEqual(r["added"], 2)
        self.assertIsNone(r["alert"])

    def test_rerun_same_day_adds_nothing(self):
        api = fake_api("2026-10-05", {"USD": 1.12})
        m.run(self.table, "EUR", ["USD"], 0.5, self.outbox, get=api)
        r = m.run(self.table, "EUR", ["USD"], 0.5, self.outbox, get=api)
        self.assertEqual(r["added"], 0)
        self.assertEqual(len(self.table.rows()), 1)

    def test_big_move_alerts_once(self):
        m.run(self.table, "EUR", ["USD"], 0.5, self.outbox, get=fake_api("2026-10-05", {"USD": 1.1200}))
        api = fake_api("2026-10-06", {"USD": 1.1300})  # +0.89%
        r = m.run(self.table, "EUR", ["USD"], 0.5, self.outbox, get=api)
        self.assertEqual(r["alert"], "dry-run")
        self.assertIn("+0.89%", self.outbox.read_text(encoding="utf-8"))
        r2 = m.run(self.table, "EUR", ["USD"], 0.5, self.outbox, get=api)
        self.assertIsNone(r2["alert"])

    def test_small_move_no_alert(self):
        m.run(self.table, "EUR", ["USD"], 0.5, self.outbox, get=fake_api("2026-10-05", {"USD": 1.1200}))
        r = m.run(self.table, "EUR", ["USD"], 0.5, self.outbox, get=fake_api("2026-10-06", {"USD": 1.1220}))
        self.assertEqual(r["moves"], [])

    def test_google_sheet_path(self):
        ws = FakeWorksheet()
        table = m.SheetTable(ws)
        m.run(table, "EUR", ["USD"], 0.5, self.outbox, get=fake_api("2026-10-05", {"USD": 1.12}))
        m.run(table, "EUR", ["USD"], 0.5, self.outbox, get=fake_api("2026-10-05", {"USD": 1.12}))
        self.assertEqual(ws.data, [m.HEADER, ["2026-10-05", "EUR", "USD", "1.1200"]])

    def test_telegram_sent_when_token_set(self):
        calls = []
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"}):
            self.assertEqual(m.notify("hello", self.outbox, post=calls.append), "sent")
        self.assertIn("sendMessage", calls[0])
        self.assertFalse(self.outbox.exists())


class RetryTests(unittest.TestCase):
    def test_retries_then_succeeds(self):
        attempts = []

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"ok": true}'

        def opener(req, timeout):
            attempts.append(1)
            if len(attempts) < 3:
                raise urllib.error.URLError("down")
            return Resp()

        with mock.patch("time.sleep"):
            self.assertEqual(m.http_json("http://x", opener=opener), {"ok": True})
        self.assertEqual(len(attempts), 3)

    def test_gives_up_with_clear_error(self):
        def opener(req, timeout):
            raise urllib.error.URLError("down")
        with mock.patch("time.sleep"), self.assertRaises(RuntimeError) as e:
            m.http_json("http://x", tries=2, opener=opener)
        self.assertIn("not reachable after 2 tries", str(e.exception))


if __name__ == "__main__":
    unittest.main()
