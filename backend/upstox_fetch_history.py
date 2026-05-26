"""Download full Nifty 50 historical OHLC from Upstox V3 and save to data/.

Backs up any existing CSVs to *.bak first.

Run: python -m backend.upstox_fetch_history
"""
from __future__ import annotations

import csv
import os
import shutil
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
if not TOKEN:
    raise SystemExit("UPSTOX_ACCESS_TOKEN missing — run upstox_auth first.")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
HEADERS = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN}"}
NIFTY = "NSE_INDEX|Nifty 50"
INDIA_VIX = "NSE_INDEX|India VIX"
BANK_NIFTY = "NSE_INDEX|Nifty Bank"


def fetch(unit: str, interval: str, from_date: date, to_date: date,
          instrument: str = NIFTY) -> list:
    inst = quote(instrument, safe="")
    url = (
        f"https://api.upstox.com/v3/historical-candle/{inst}/"
        f"{unit}/{interval}/{to_date.isoformat()}/{from_date.isoformat()}"
    )
    r = requests.get(url, headers=HEADERS, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} for {url}\n{r.text[:300]}")
    return r.json().get("data", {}).get("candles", [])


def save(candles: list, out_path: Path) -> int:
    """Write CSV in chronological (oldest-first) order with our standard schema."""
    if out_path.exists():
        bak = out_path.with_suffix(out_path.suffix + ".bak")
        shutil.copy2(out_path, bak)
        print(f"  backed up existing -> {bak.name}")
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        for c in reversed(candles):  # Upstox returns newest-first
            ts, o, h, l, cl, vol, *_ = c
            w.writerow([ts, o, h, l, cl, vol])
    return len(candles)


def fetch_chunked(unit: str, interval: str, total_days: int, per_window_days: int,
                  instrument: str = NIFTY) -> list:
    """Pull `total_days` worth of bars in `per_window_days` chunks.
    Stops early if a chunk fails (Upstox retention limits older intraday data)."""
    all_candles: list = []
    end = date.today()
    remaining = total_days
    while remaining > 0:
        window = min(per_window_days, remaining)
        start = end - timedelta(days=window)
        try:
            candles = fetch(unit, interval, start, end, instrument=instrument)
        except RuntimeError as exc:
            print(f"  chunk {start}..{end} unavailable ({str(exc).splitlines()[0]}). Stopping.")
            break
        if not candles:
            print(f"  chunk {start}..{end} returned empty. Stopping.")
            break
        all_candles.extend(candles)
        remaining -= window
        end = start - timedelta(days=1)
    return all_candles


def main() -> None:
    today = date.today()

    # ----- Nifty 50 daily (10 years, chunked) -----
    print(f"Fetching Nifty 50 daily candles (10 years up to {today}, chunked 5y/window)...")
    daily = fetch_chunked("days", "1", total_days=365 * 10, per_window_days=365 * 5, instrument=NIFTY)
    n = save(daily, DATA_DIR / "nifty50_daily.csv")
    print(f"  saved {n} rows -> nifty50_daily.csv")

    # ----- India VIX daily (10 years) -----
    print(f"\nFetching India VIX daily candles (10 years, chunked 5y/window)...")
    vix = fetch_chunked("days", "1", total_days=365 * 10, per_window_days=365 * 5, instrument=INDIA_VIX)
    n = save(vix, DATA_DIR / "india_vix_daily.csv")
    print(f"  saved {n} rows -> india_vix_daily.csv")

    # ----- Bank Nifty daily (10 years) -----
    print(f"\nFetching Bank Nifty daily candles (10 years, chunked 5y/window)...")
    bnf = fetch_chunked("days", "1", total_days=365 * 10, per_window_days=365 * 5, instrument=BANK_NIFTY)
    n = save(bnf, DATA_DIR / "bank_nifty_daily.csv")
    print(f"  saved {n} rows -> bank_nifty_daily.csv")

    # ----- Nifty hourly (1 year, for intraday features) -----
    print(f"\nFetching Nifty 50 hourly candles (365 days, chunked 90d/window)...")
    hourly = fetch_chunked("hours", "1", total_days=365, per_window_days=90, instrument=NIFTY)
    n = save(hourly, DATA_DIR / "nifty50_hourly.csv")
    print(f"  saved {n} rows -> nifty50_hourly.csv")

    print("\nAll done. Backups saved as *.csv.bak alongside.")
    print("Next: upload these 4 CSVs to /MyDrive/nifty_signal/data/ in Colab, then re-run v5 notebook.")


if __name__ == "__main__":
    main()
