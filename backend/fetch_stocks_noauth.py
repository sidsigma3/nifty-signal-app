"""Fetch daily OHLCV for all stocks in the expanded universe from Upstox V3.

Works WITHOUT auth — Upstox V3 historical candle endpoint is public.

Run: python -m backend.fetch_stocks_noauth          (all ~200 stocks)
Run: python -m backend.fetch_stocks_noauth --nifty50 (only Nifty 50)
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

from backend.stock_universe import STOCK_UNIVERSE

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "stocks"
DATA_DIR.mkdir(parents=True, exist_ok=True)

NIFTY50_ONLY = {
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BEL", "BHARTIARTL", "BRITANNIA", "CIPLA",
    "COALINDIA", "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH",
    "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR",
    "ICICIBANK", "ITC", "INDUSINDBK", "INFY", "JSWSTEEL",
    "LT", "M&M", "MARUTI", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SUNPHARMA",
    "TCS", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TECHM",
    "TITAN", "ULTRACEMCO", "WIPRO",
}


def fetch_daily(inst_key: str, from_date: date, to_date: date) -> list:
    inst = quote(inst_key, safe="")
    url = f"https://api.upstox.com/v3/historical-candle/{inst}/days/1/{to_date.isoformat()}/{from_date.isoformat()}"
    r = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json().get("data", {}).get("candles", [])


def fetch_chunked(inst_key: str, years: int = 5) -> list:
    all_candles = []
    end = date.today()
    for _ in range(years):
        start = end - timedelta(days=365)
        try:
            candles = fetch_daily(inst_key, start, end)
            if candles:
                all_candles.extend(candles)
        except Exception:
            break
        end = start - timedelta(days=1)
    return all_candles


def save_csv(candles: list, path: Path) -> int:
    seen = set()
    unique = []
    for c in reversed(candles):
        dt = c[0][:10]
        if dt not in seen:
            seen.add(dt)
            unique.append(c)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        for c in unique:
            ts, o, h, l, cl, vol, *_ = c
            w.writerow([ts, o, h, l, cl, vol])
    return len(unique)


def main():
    nifty50_only = "--nifty50" in sys.argv
    universe = {k: v for k, v in STOCK_UNIVERSE.items() if k in NIFTY50_ONLY} if nifty50_only else STOCK_UNIVERSE

    print(f"Fetching {len(universe)} stocks (5 years daily, no auth needed)")
    print(f"Output: {DATA_DIR}/\n")

    ok = 0
    fail = []

    for i, (symbol, inst_key) in enumerate(universe.items(), 1):
        out = DATA_DIR / f"{symbol}.csv"

        if out.exists() and out.stat().st_size > 5000:
            print(f"  [{i:3d}/{len(universe)}] {symbol:15s} — exists, skip")
            ok += 1
            continue

        print(f"  [{i:3d}/{len(universe)}] {symbol:15s} — ", end="", flush=True)
        try:
            candles = fetch_chunked(inst_key, years=5)
            if not candles:
                print("empty")
                fail.append(symbol)
                continue
            n = save_csv(candles, out)
            print(f"{n} bars")
            ok += 1
        except Exception as exc:
            print(f"ERROR: {exc}")
            fail.append(symbol)

        time.sleep(0.15)

    print(f"\nDone: {ok}/{len(universe)} succeeded")
    if fail:
        print(f"Failed ({len(fail)}): {', '.join(fail)}")


if __name__ == "__main__":
    main()
