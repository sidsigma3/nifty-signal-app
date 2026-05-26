"""Fetch daily OHLCV for all Nifty 50 constituent stocks from Upstox V3.

Creates data/stocks/ directory with one CSV per stock.

Run: python -m backend.fetch_nifty50_stocks
"""
from __future__ import annotations

import csv
import os
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "stocks"
DATA_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN}"}

# Nifty 50 constituents (as of 2025) — Upstox instrument keys
# Format: NSE_EQ|INE... or we can use the simpler symbol-based lookup
NIFTY50_SYMBOLS = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BPCL",
    "BHARTIARTL", "BRITANNIA", "CIPLA", "COALINDIA", "DRREDDY",
    "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK",
    "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK",
    "ITC", "INDUSINDBK", "INFY", "JSWSTEEL", "KOTAKBANK",
    "LT", "M&M", "MARUTI", "NTPC", "NESTLEIND",
    "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN",
    "SHRIRAMFIN", "SUNPHARMA", "TCS", "TATACONSUM", "TATAMOTORS",
    "TATASTEEL", "TECHM", "TITAN", "ULTRACEMCO", "WIPRO",
]


def search_instrument_key(symbol: str) -> str | None:
    """Use Upstox instrument search to find the exact instrument_key for an NSE equity."""
    url = "https://api.upstox.com/v3/instruments/search"
    params = {"query": symbol, "source": "NSE_EQ"}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        instruments = r.json().get("data", [])
        # Find exact NSE equity match
        for inst in instruments:
            ts = inst.get("trading_symbol", "")
            exchange = inst.get("exchange", "")
            if ts == symbol and exchange == "NSE_EQ":
                return inst.get("instrument_key")
        # Fallback: first NSE_EQ result
        for inst in instruments:
            if inst.get("exchange") == "NSE_EQ":
                return inst.get("instrument_key")
    except Exception:
        pass
    return None


def fetch_daily(instrument_key: str, from_date: date, to_date: date) -> list:
    """Fetch daily candles from Upstox V3 historical endpoint."""
    inst = quote(instrument_key, safe="")
    url = (
        f"https://api.upstox.com/v3/historical-candle/{inst}/"
        f"days/1/{to_date.isoformat()}/{from_date.isoformat()}"
    )
    r = requests.get(url, headers=HEADERS, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json().get("data", {}).get("candles", [])


def fetch_chunked(instrument_key: str, total_days: int = 365 * 5,
                  chunk_days: int = 365 * 2) -> list:
    """Fetch in chunks to handle Upstox limits."""
    all_candles = []
    end = date.today()
    remaining = total_days
    while remaining > 0:
        window = min(chunk_days, remaining)
        start = end - timedelta(days=window)
        try:
            candles = fetch_daily(instrument_key, start, end)
        except Exception as exc:
            print(f"    chunk {start}..{end} failed: {exc}")
            break
        if not candles:
            break
        all_candles.extend(candles)
        remaining -= window
        end = start - timedelta(days=1)
    return all_candles


def save_csv(candles: list, path: Path) -> int:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        for c in reversed(candles):  # newest-first -> oldest-first
            ts, o, h, l, cl, vol, *_ = c
            w.writerow([ts, o, h, l, cl, vol])
    return len(candles)


def main():
    if not TOKEN:
        print("UPSTOX_ACCESS_TOKEN missing. Run: python -m backend.upstox_auth")
        return

    print(f"Fetching daily data for {len(NIFTY50_SYMBOLS)} Nifty 50 stocks")
    print(f"Output: {DATA_DIR}/\n")

    succeeded = 0
    failed = []

    for i, symbol in enumerate(NIFTY50_SYMBOLS, 1):
        out_path = DATA_DIR / f"{symbol}.csv"

        # Skip if already fetched today (file exists and > 10KB)
        if out_path.exists() and out_path.stat().st_size > 10_000:
            print(f"  [{i:2d}/{len(NIFTY50_SYMBOLS)}] {symbol:15s} — already exists, skipping")
            succeeded += 1
            continue

        print(f"  [{i:2d}/{len(NIFTY50_SYMBOLS)}] {symbol:15s} — ", end="", flush=True)

        # Step 1: Find instrument key
        inst_key = search_instrument_key(symbol)
        if not inst_key:
            # Fallback: try constructing it directly
            inst_key = f"NSE_EQ|{symbol}"
            print(f"search failed, trying {inst_key}... ", end="", flush=True)

        # Step 2: Fetch 5 years of daily data
        try:
            candles = fetch_chunked(inst_key, total_days=365 * 5)
            if not candles:
                print("empty response")
                failed.append(symbol)
                continue
            n = save_csv(candles, out_path)
            print(f"{n} bars saved")
            succeeded += 1
        except Exception as exc:
            print(f"ERROR: {exc}")
            failed.append(symbol)

        time.sleep(0.3)  # Rate limit courtesy

    print(f"\nDone: {succeeded} succeeded, {len(failed)} failed")
    if failed:
        print(f"Failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
