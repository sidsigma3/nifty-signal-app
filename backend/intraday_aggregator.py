"""Build a 'today so far' synthetic daily bar from Upstox intraday data.

The trained model uses daily features. Without injecting today's intraday
state, every intraday /predict returns the same answer because the inputs
(yesterday's daily close) never change. This module fetches today's 1-min
bars and aggregates them into a daily-style row that can be appended to the
historical daily CSV before features are computed.

Falls back gracefully (returns df unchanged) if token is missing, market is
closed, or Upstox returns nothing.
"""
from __future__ import annotations

import os
from typing import Optional
from urllib.parse import quote

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv(override=True)

NIFTY = "NSE_INDEX|Nifty 50"
INTRADAY_URL = "https://api.upstox.com/v3/historical-candle/intraday/{inst}/minutes/1"


def _headers() -> Optional[dict[str, str]]:
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if not token:
        return None
    return {"Accept": "application/json", "Authorization": f"Bearer {token}"}


def fetch_today_synthetic_bar() -> Optional[dict]:
    """Aggregate all of today's 1-min candles into a daily-style OHLCV row.

    Returns None if Upstox is unavailable, market hasn't opened, or token
    is missing. Caller treats None as 'no injection, use historical only'.
    """
    headers = _headers()
    if headers is None:
        return None
    url = INTRADAY_URL.format(inst=quote(NIFTY, safe=""))
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        candles = r.json().get("data", {}).get("candles", [])
        if not candles:
            return None
        # Upstox returns newest-first; reverse for chronological aggregation
        candles = list(reversed(candles))
        return {
            "datetime": candles[-1][0],
            "open": float(candles[0][1]),
            "high": float(max(c[2] for c in candles)),
            "low": float(min(c[3] for c in candles)),
            "close": float(candles[-1][4]),
            "volume": int(sum(c[5] for c in candles)),
        }
    except Exception:
        return None


def inject_today_bar(df: pd.DataFrame) -> pd.DataFrame:
    """Append (or replace) today's bar in the daily DataFrame using live intraday data.

    Idempotent — calling repeatedly during the day keeps updating the last row
    with the latest OHLC values.
    """
    today_bar = fetch_today_synthetic_bar()
    if today_bar is None:
        return df

    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    if "datetime" not in df.columns:
        for cand in ("date", "timestamp", "time"):
            if cand in df.columns:
                df = df.rename(columns={cand: "datetime"})
                break

    df["datetime"] = pd.to_datetime(df["datetime"])

    # Normalize today's date (strip tz, strip time-of-day)
    today_dt = pd.to_datetime(today_bar["datetime"])
    today_norm = (today_dt.tz_localize(None) if today_dt.tz else today_dt).normalize()

    last_dt = df["datetime"].iloc[-1]
    last_norm = (last_dt.tz_localize(None) if last_dt.tz else last_dt).normalize()

    new_row = pd.DataFrame([today_bar])
    new_row["datetime"] = pd.to_datetime(new_row["datetime"])

    if last_norm == today_norm:
        # Replace the existing today's row (refresh it with latest)
        df = pd.concat([df.iloc[:-1], new_row], ignore_index=True)
    else:
        df = pd.concat([df, new_row], ignore_index=True)

    return df
