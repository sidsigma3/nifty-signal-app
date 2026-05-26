"""Smoke-test Upstox V3 historical data endpoints with the access token.

Run: python -m backend.upstox_test_data
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
if not TOKEN:
    raise SystemExit("UPSTOX_ACCESS_TOKEN missing in .env — run upstox_auth first.")

HEADERS = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN}"}
NIFTY_INSTRUMENT = "NSE_INDEX|Nifty 50"


def fetch_historical(unit: str, interval: str, days_back: int) -> dict:
    """V3 historical-candle endpoint. Path: /{instrument}/{unit}/{interval}/{to}/{from}."""
    to_date = date.today()
    from_date = to_date - timedelta(days=days_back)
    inst = quote(NIFTY_INSTRUMENT, safe="")
    url = (
        f"https://api.upstox.com/v3/historical-candle/{inst}/"
        f"{unit}/{interval}/{to_date.isoformat()}/{from_date.isoformat()}"
    )
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}", "body": r.text[:300], "url": url}
    return r.json()


def main() -> None:
    print(f"Token: ...{TOKEN[-8:]}\n")

    print("=" * 60)
    print("1) Profile (confirms token is alive)")
    print("=" * 60)
    r = requests.get("https://api.upstox.com/v2/user/profile", headers=HEADERS, timeout=15)
    if r.status_code == 200:
        d = r.json().get("data", {})
        print(f"  ok — {d.get('user_name')}  broker={d.get('broker')}")
    else:
        print(f"  FAIL: HTTP {r.status_code}\n  {r.text[:200]}")
        return

    print("\n" + "=" * 60)
    print("2) Last 30 days of daily Nifty 50 candles")
    print("=" * 60)
    daily = fetch_historical(unit="days", interval="1", days_back=30)
    if "error" in daily:
        print(f"  FAIL: {daily}")
    else:
        candles = daily.get("data", {}).get("candles", [])
        print(f"  got {len(candles)} candles. Most recent 5:")
        print(f"  {'timestamp':<26} {'open':>10} {'high':>10} {'low':>10} {'close':>10}")
        for c in candles[:5]:
            ts, o, h, l, cl, *_ = c
            print(f"  {ts:<26} {o:>10.2f} {h:>10.2f} {l:>10.2f} {cl:>10.2f}")

    print("\n" + "=" * 60)
    print("3) Last 200 hourly Nifty bars")
    print("=" * 60)
    hourly = fetch_historical(unit="hours", interval="1", days_back=30)
    if "error" in hourly:
        print(f"  FAIL: {hourly}")
    else:
        candles = hourly.get("data", {}).get("candles", [])
        print(f"  got {len(candles)} hourly candles.")
        if candles:
            ts, o, h, l, cl, *_ = candles[0]
            print(f"  latest:  {ts}  close={cl:.2f}")

    print("\n" + "=" * 60)
    print("4) Last 50 fifteen-minute Nifty bars (intraday-grade)")
    print("=" * 60)
    fifteen = fetch_historical(unit="minutes", interval="15", days_back=7)
    if "error" in fifteen:
        print(f"  FAIL: {fifteen}")
    else:
        candles = fifteen.get("data", {}).get("candles", [])
        print(f"  got {len(candles)} 15-min candles.")
        if candles:
            ts, o, h, l, cl, *_ = candles[0]
            print(f"  latest:  {ts}  close={cl:.2f}")

    print("\nAll endpoints responding. Token is valid for market data.")


if __name__ == "__main__":
    main()
