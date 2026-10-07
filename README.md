# API to Google Sheets to Telegram

[![test](https://github.com/CastelDazur/api-to-sheets-telegram/actions/workflows/test.yml/badge.svg)](https://github.com/CastelDazur/api-to-sheets-telegram/actions/workflows/test.yml)

A small job that runs once a day: it takes exchange rates from a public API, adds them to a table, and sends a Telegram message when a rate jumps more than you set. The same pattern works for any API: orders, leads, stock levels, prices.

A bounded demo; the sample history is made up, the rates are real.

## Run

```bash
python rates_to_sheet.py --symbols USD,GBP,CHF --out out
python -m unittest -v
```

No install needed for the CSV version (Python 3.9+, standard library only). On Windows, use `py` instead of `python`.

The tests run in CI on Windows, macOS and Linux with Python 3.9 to 3.14. They use stand-ins for the API, Telegram and Google Sheets, so CI never touches the network.

Google Sheets instead of CSV:

```bash
pip install -r requirements.txt
python rates_to_sheet.py --sheet "Rates" --creds service_account.json
```

(Share the sheet with the service account's email first. Keep `service_account.json` out of git; it is in `.gitignore`.)

Telegram: set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Without them the message goes to `out/outbox.txt`, so you can see exactly what would be sent.

## What it does

- Gets the latest ECB reference rates from the free Frankfurter API (no key).
- Adds one row per date and currency. Run it ten times a day and you still get one row per day.
- Compares each rate with the last stored day and sends one alert per new day if the move is at or above `--threshold` % (default 0.5).
- If the API is down, it tries 4 times with growing pauses, then stops with a clear message instead of writing half a result.

## The sample

`sample/history_before.csv` is a made-up previous day, there only to show an alert. `expected_output/` is a real run on the ECB rates of 2026-10-06 with `--threshold 0.3` on top of that history: 3 new rows and an alert for USD (+0.80%) and GBP (+0.34%) in `outbox.txt`.

## Tests

8 tests, no network: first day, rerun on the same day, big move alerts once, small move doesn't, the Google Sheets path (with a stand-in worksheet), Telegram sending, retry then success, and giving up with a clear error.

## Limits

The Google Sheets path is tested against a stand-in worksheet, not a live sheet; it needs your own service account. To run it every day, use Windows Task Scheduler or cron.

## Support scope

Issues are welcome for reproducible defects in this demo: a command from this README that fails, or a test that fails. Please include the Python version, OS and the exact command.

Connecting a different API, a different sheet layout or another messenger is separate work, not a bug fix.

## Using it for a real job

Before it runs on real data, the source API, the columns, the alert rule and who receives the messages are agreed in writing. Keys and tokens stay with you, in environment variables or a file outside the repository.

## License

[MIT](LICENSE)

---

[castel.studio](https://castel.studio/)
