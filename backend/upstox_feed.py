"""Upstox V3 live feed via HTTP LTP polling.

We use polling rather than WebSocket because:
1. No protobuf decoding needed — much simpler code
2. 2-second tick is plenty for a signal dashboard
3. Same auth as the rest of the V3 endpoints

Falls back to a stub heartbeat if UPSTOX_ACCESS_TOKEN is missing or expired.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any, Optional

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
NIFTY_INSTRUMENT_KEY = "NSE_INDEX|Nifty 50"
POLL_INTERVAL_SEC = 2.0
LTP_URL = "https://api.upstox.com/v3/market-quote/ltp"


class UpstoxFeed:
    def __init__(self, instrument_keys: Optional[list[str]] = None) -> None:
        self.instrument_keys = instrument_keys or [NIFTY_INSTRUMENT_KEY]
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._task: Optional[asyncio.Task] = None
        self.latest: dict[str, Any] = {}
        self.mode: str = "stub"  # 'live' once polling starts successfully

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _run(self) -> None:
        if not UPSTOX_ACCESS_TOKEN:
            print("[upstox_feed] UPSTOX_ACCESS_TOKEN missing; running stubbed feed.")
            await self._stub_loop()
            return

        self.mode = "live"
        print(f"[upstox_feed] Live polling started for {self.instrument_keys} every {POLL_INTERVAL_SEC}s")
        tick = 0
        consecutive_errors = 0
        while True:
            try:
                price = await asyncio.to_thread(self._fetch_ltp)
                if price is not None:
                    tick += 1
                    consecutive_errors = 0
                    self.latest = {
                        "ltp": price,
                        "instrument": self.instrument_keys[0],
                        "tick": tick,
                        "ts": datetime.now().isoformat(timespec="seconds"),
                        "mode": "live",
                    }
                    try:
                        self.queue.put_nowait(self.latest)
                    except asyncio.QueueFull:
                        pass
            except Exception as exc:
                consecutive_errors += 1
                if consecutive_errors <= 3 or consecutive_errors % 30 == 0:
                    print(f"[upstox_feed] poll error #{consecutive_errors}: {exc}")
                if consecutive_errors >= 30:
                    # 30 consecutive errors (~1 minute) — token probably expired
                    print("[upstox_feed] too many errors; falling back to stub. Re-run upstox_auth and restart backend.")
                    self.mode = "stub"
                    await self._stub_loop()
                    return
            await asyncio.sleep(POLL_INTERVAL_SEC)

    def _fetch_ltp(self) -> Optional[float]:
        params = {"instrument_key": ",".join(self.instrument_keys)}
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {UPSTOX_ACCESS_TOKEN}",
        }
        r = requests.get(LTP_URL, params=params, headers=headers, timeout=10)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        data = r.json().get("data", {})
        # Upstox returns the instrument key with ':' instead of '|' (e.g., "NSE_INDEX:Nifty 50")
        for _key, info in data.items():
            last_price = info.get("last_price")
            if last_price is not None:
                return float(last_price)
        return None

    async def _stub_loop(self) -> None:
        tick = 0
        while True:
            tick += 1
            self.latest = {"stub": True, "tick": tick, "mode": "stub"}
            try:
                self.queue.put_nowait(self.latest)
            except asyncio.QueueFull:
                pass
            await asyncio.sleep(5)
