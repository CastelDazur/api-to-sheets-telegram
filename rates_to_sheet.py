"""Daily exchange rates -> table (CSV or Google Sheets) -> Telegram alert on a big move.

Source: Frankfurter API (free, no key, ECB reference rates).
Table:  one row per date and currency. Running it twice on the same day adds nothing.
Alert:  if a rate moved more than --threshold % since the previous stored day, a Telegram
        message is sent. Without a bot token it is written to outbox.txt instead (dry run).

Usage:
  python rates_to_sheet.py --symbols USD,GBP,CHF --out out
  python rates_to_sheet.py --sheet "Rates" --creds service_account.json   (Google Sheets)
Env for Telegram: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Protocol

API = "https://api.frankfurter.dev/v1/latest"
HEADER = ["date", "base", "currency", "rate"]


class Table(Protocol):
    def rows(self) -> list[list[str]]: ...
    def append(self, rows: list[list[str]]) -> None: ...


class CsvTable:
    def __init__(self, path: Path):
        self.path = path

    def rows(self) -> list[list[str]]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8", newline="") as fh:
            return list(csv.reader(fh))[1:]

    def append(self, rows: list[list[str]]) -> None:
        new = not self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(HEADER)
            w.writerows(rows)


class SheetTable:
    """Google Sheets via gspread and a service account (pip install gspread)."""

    def __init__(self, worksheet):
        self.ws = worksheet
        if not self.ws.row_values(1):
            self.ws.append_row(HEADER)

    @classmethod
    def open(cls, title: str, creds: Path) -> "SheetTable":
        import gspread  # optional dependency, only needed for Google Sheets
        return cls(gspread.service_account(filename=str(creds)).open(title).sheet1)

    def rows(self) -> list[list[str]]:
        return self.ws.get_all_values()[1:]

    def append(self, rows: list[list[str]]) -> None:
        if rows:
            self.ws.append_rows(rows, value_input_option="RAW")


def http_json(url: str, tries: int = 4, pause: float = 2.0, opener: Callable = urllib.request.urlopen) -> dict:
    """GET with retries and growing pauses; a clear error after the last try."""
    req = urllib.request.Request(url, headers={"User-Agent": "castel-demo/1.0"})
    last = None
    for attempt in range(1, tries + 1):
        try:
            with opener(req, timeout=15) as resp:
                return json.load(resp)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            last = e
            if attempt < tries:
                time.sleep(pause * attempt)
    raise RuntimeError(f"API not reachable after {tries} tries: {last}")


def fetch_rates(base: str, symbols: list[str], get: Callable = http_json) -> tuple[str, dict[str, float]]:
    data = get(f"{API}?base={base}&symbols={','.join(symbols)}")
    return data["date"], {k: float(v) for k, v in data["rates"].items()}


def new_rows(table_rows: list[list[str]], date: str, base: str, rates: dict[str, float]) -> list[list[str]]:
    have = {(r[0], r[2]) for r in table_rows if len(r) >= 4}
    return [[date, base, cur, f"{rate:.4f}"] for cur, rate in sorted(rates.items()) if (date, cur) not in have]


def big_moves(table_rows: list[list[str]], date: str, rates: dict[str, float], threshold: float) -> list[str]:
    """Compare with the latest earlier date stored for each currency."""
    prev: dict[str, tuple[str, float]] = {}
    for d, _base, cur, rate in (r[:4] for r in table_rows if len(r) >= 4):
        if d < date and (cur not in prev or d > prev[cur][0]):
            prev[cur] = (d, float(rate))
    msgs = []
    for cur, rate in sorted(rates.items()):
        if cur in prev:
            old = prev[cur][1]
            change = (rate - old) / old * 100
            if abs(change) >= threshold:
                msgs.append(f"{cur}: {old:.4f} -> {rate:.4f} ({change:+.2f}%) since {prev[cur][0]}")
    return msgs


def notify(text: str, outbox: Path, post: Callable = http_json) -> str:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        outbox.parent.mkdir(parents=True, exist_ok=True)
        with outbox.open("a", encoding="utf-8") as fh:
            fh.write(text + "\n---\n")
        return "dry-run"
    q = urllib.parse.urlencode({"chat_id": chat, "text": text})
    post(f"https://api.telegram.org/bot{token}/sendMessage?{q}")
    return "sent"


def run(table: Table, base: str, symbols: list[str], threshold: float, outbox: Path,
        get: Callable = http_json) -> dict:
    date, rates = fetch_rates(base, symbols, get)
    existing = table.rows()
    moves = big_moves(existing, date, rates, threshold)
    rows = new_rows(existing, date, base, rates)
    table.append(rows)
    alert = None
    if moves and rows:  # alert once per new date, not on every rerun
        alert = notify(f"{base} rates {date}, moved {threshold}% or more:\n" + "\n".join(moves), outbox)
    return {"date": date, "added": len(rows), "moves": moves, "alert": alert}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="EUR")
    ap.add_argument("--symbols", default="USD,GBP,CHF")
    ap.add_argument("--threshold", type=float, default=0.5, help="alert when a rate moves this many %%")
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--sheet", help="Google Sheet title (instead of CSV)")
    ap.add_argument("--creds", type=Path, help="service account JSON for Google Sheets")
    a = ap.parse_args()
    tbl = SheetTable.open(a.sheet, a.creds) if a.sheet else CsvTable(a.out / "rates.csv")
    print(run(tbl, a.base, a.symbols.split(","), a.threshold, a.out / "outbox.txt"))
