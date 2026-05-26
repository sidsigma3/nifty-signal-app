"""Auto paper trader using REAL Nifty weekly option contracts via Upstox.

Behavior:
- Every signal_interval (default 60s), runs the trained model on the latest features.
- If confidence >= min_confidence AND no open position:
    * Reads current Nifty spot from the live feed
    * Picks ATM strike for the nearest weekly expiry
    * Selects the CE (for BUY_CALL) or PE (for BUY_PUT) contract
    * Sizes position based on capital_inr budget and current premium
    * Opens a paper position at the current premium
- Every tick_interval (default 5s), polls each open position's live premium and
  applies target_pct / stop_pct / max-hold-time exits.
- Stop() closes ALL open positions at the live premium before halting (no orphans).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

from backend.feature_engineering import FEATURE_COLUMNS, build_features
from backend.intraday_aggregator import inject_today_bar
from backend.signal_engine import get_engine
from backend.upstox_options import (
    LOT_SIZE,
    fetch_option_ltp,
    select_option_for_budget,
    size_position,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


@dataclass
class OptionTrade:
    id: int
    entry_time: str
    direction: str            # BUY_CALL or BUY_PUT
    confidence: float
    spot_at_entry: float

    # Option contract details
    instrument_key: str
    strike: int
    expiry: str
    option_side: str          # CE or PE
    moneyness: str            # ATM or OTM
    entry_premium: float
    target_premium: float
    stop_premium: float

    # Sizing
    n_lots: int
    qty: int
    capital_used: float

    # Live / exit fields
    current_premium: Optional[float] = None
    status: str = "open"      # open | win_target | loss_stop | exit_time | exit_manual
    exit_time: Optional[str] = None
    exit_premium: Optional[float] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0


class AutoTrader:
    def __init__(self) -> None:
        self.running: bool = False
        self.min_confidence: float = 0.40
        self.capital_inr: float = 10000.0
        self.target_pct: float = 0.50          # +50% on premium (typical ATM target)
        self.stop_pct: float = 0.30            # -30% on premium
        self.signal_interval_sec: int = 60
        self.tick_interval_sec: int = 5
        self.max_hold_sec: int = 60 * 60  # 1 hour (was 30 min — too aggressive for daily-model signals)
        self.trades: list[OptionTrade] = []
        self.next_id: int = 1
        self._task: Optional[asyncio.Task] = None
        self._last_signal_at: Optional[datetime] = None
        self._get_spot: Optional[Callable[[], Optional[float]]] = None
        self.last_status_msg: str = "idle"

    def set_ltp_provider(self, fn: Callable[[], Optional[float]]) -> None:
        """Callback returning current Nifty SPOT (for ATM strike selection)."""
        self._get_spot = fn

    async def start(
        self,
        min_confidence: float = 0.40,
        capital_inr: float = 10000.0,
        target_pct: float = 0.50,
        stop_pct: float = 0.30,
    ) -> None:
        if self.running:
            return
        self.min_confidence = min_confidence
        self.capital_inr = capital_inr
        self.target_pct = target_pct
        self.stop_pct = stop_pct
        self.running = True
        self._last_signal_at = None
        self.last_status_msg = "started"
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        # First, close any open positions at the current premium (no orphans)
        open_trades = [t for t in self.trades if t.status == "open"]
        if open_trades:
            now = datetime.now()
            for t in open_trades:
                try:
                    prem = await asyncio.to_thread(fetch_option_ltp, t.instrument_key)
                except Exception:
                    prem = None
                if prem is None:
                    prem = t.current_premium or t.entry_premium
                t.current_premium = prem
                t.exit_premium = prem
                t.exit_time = now.isoformat(timespec="seconds")
                t.status = "exit_manual"
                t.pnl_pct = (prem - t.entry_premium) / t.entry_premium
                t.pnl = (prem - t.entry_premium) * t.qty
                print(f"[auto_trader] STOP-EXIT #{t.id} {t.option_side} @ premium {prem:.2f}  pnl={t.pnl:+.0f}")

        self.running = False
        self.last_status_msg = f"stopped — closed {len(open_trades)} open position(s)"
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None

    async def _run(self) -> None:
        print(f"[auto_trader] started  min_conf={self.min_confidence}  capital=₹{self.capital_inr:.0f}  "
              f"target={self.target_pct*100:.0f}%  stop={self.stop_pct*100:.0f}%")
        while self.running:
            try:
                # 1) Update mark-to-market on open positions
                if any(t.status == "open" for t in self.trades):
                    await self._update_open_positions(datetime.now())

                # 2) Periodically try to open a new position
                now = datetime.now()
                if self._last_signal_at is None or (now - self._last_signal_at).total_seconds() >= self.signal_interval_sec:
                    self._last_signal_at = now
                    await self._maybe_open_trade(now)
            except Exception as exc:
                self.last_status_msg = f"loop error: {exc}"
                print(f"[auto_trader] loop error: {exc}")
            await asyncio.sleep(self.tick_interval_sec)

    def _has_open(self) -> bool:
        return any(t.status == "open" for t in self.trades)

    async def _maybe_open_trade(self, now: datetime) -> None:
        if self._has_open():
            self.last_status_msg = "waiting (position open)"
            return

        spot = self._get_spot() if self._get_spot else None
        if spot is None:
            self.last_status_msg = "no live Nifty spot yet"
            return

        # Run the model
        try:
            daily_path = DATA_DIR / "nifty50_daily.csv"
            hourly_path = DATA_DIR / "nifty50_hourly.csv"
            if not daily_path.exists():
                self.last_status_msg = "daily CSV missing"
                return
            df = pd.read_csv(daily_path)
            # Inject today's live intraday bar so features change as the market moves
            df = await asyncio.to_thread(inject_today_bar, df)
            hourly_df = pd.read_csv(hourly_path) if hourly_path.exists() else None
            feats = await asyncio.to_thread(build_features, df, hourly_df=hourly_df)
            if feats.empty:
                self.last_status_msg = "no usable features"
                return
            X = feats.tail(1)[FEATURE_COLUMNS]
            result = await asyncio.to_thread(get_engine().predict, X)
        except Exception as exc:
            self.last_status_msg = f"predict error: {exc}"
            return

        if result.prediction not in ("BUY_CALL", "BUY_PUT"):
            self.last_status_msg = f"signal={result.prediction} (non-directional)"
            return
        if result.confidence < self.min_confidence:
            self.last_status_msg = f"{result.prediction} conf={result.confidence:.0%} below {self.min_confidence:.0%}"
            return

        side = "CE" if result.prediction == "BUY_CALL" else "PE"

        # Pick the option that FITS the capital budget (walks ATM -> OTM until affordable)
        try:
            opt = await asyncio.to_thread(
                select_option_for_budget,
                float(spot), side, self.capital_inr,
            )
        except Exception as exc:
            self.last_status_msg = f"option chain error: {exc}"
            return

        n_lots, qty, capital_used = size_position(self.capital_inr, opt["ltp"])
        if n_lots == 0:
            self.last_status_msg = (
                f"sizing failed: premium ₹{opt['ltp']:.2f} × {LOT_SIZE} > capital ₹{self.capital_inr:.0f}"
            )
            return

        entry_premium = opt["ltp"]
        target_premium = entry_premium * (1 + self.target_pct)
        stop_premium = entry_premium * (1 - self.stop_pct)

        trade = OptionTrade(
            id=self.next_id,
            entry_time=now.isoformat(timespec="seconds"),
            direction=result.prediction,
            confidence=result.confidence,
            spot_at_entry=float(spot),
            instrument_key=opt["instrument_key"],
            strike=opt["strike"],
            expiry=opt["expiry"],
            option_side=side,
            moneyness=opt.get("moneyness", "ATM"),
            entry_premium=entry_premium,
            target_premium=target_premium,
            stop_premium=stop_premium,
            n_lots=n_lots,
            qty=qty,
            capital_used=capital_used,
            current_premium=entry_premium,
        )
        self.trades.append(trade)
        self.next_id += 1
        self.last_status_msg = (
            f"OPENED #{trade.id} {side} {opt['strike']} ({trade.moneyness}) @ premium ₹{entry_premium:.2f}  "
            f"{n_lots}x{LOT_SIZE}={qty}qty  capital ₹{capital_used:.0f}"
        )
        print(f"[auto_trader] {self.last_status_msg}")

    async def _update_open_positions(self, now: datetime) -> None:
        for t in self.trades:
            if t.status != "open":
                continue

            # Try to fetch live premium; update mark-to-market if we got one
            try:
                prem = await asyncio.to_thread(fetch_option_ltp, t.instrument_key)
            except Exception:
                prem = None
            if prem is not None and prem > 0:
                t.current_premium = prem
                t.pnl_pct = (prem - t.entry_premium) / t.entry_premium
                t.pnl = (prem - t.entry_premium) * t.qty

            # Always evaluate exit conditions, even if premium fetch failed this tick.
            # For target/stop we need a valid premium; for time-exit we just need a clock.
            check_prem = t.current_premium  # last known good (or entry, if never fetched)
            entry_dt = datetime.fromisoformat(t.entry_time)
            time_elapsed = (now - entry_dt).total_seconds()

            new_status: Optional[str] = None
            if check_prem is not None and check_prem >= t.target_premium:
                new_status = "win_target"
            elif check_prem is not None and check_prem <= t.stop_premium:
                new_status = "loss_stop"
            elif time_elapsed >= self.max_hold_sec:
                new_status = "exit_time"

            if new_status:
                t.status = new_status
                t.exit_time = now.isoformat(timespec="seconds")
                t.exit_premium = check_prem if check_prem is not None else t.entry_premium
                print(f"[auto_trader] CLOSED #{t.id} {t.option_side} {t.strike} -> {new_status}  "
                      f"pnl={t.pnl:+.0f} ({t.pnl_pct*100:+.1f}%)  (held {time_elapsed/60:.1f}min)")

    def stats(self) -> dict[str, Any]:
        closed = [t for t in self.trades if t.status != "open"]
        open_trades = [t for t in self.trades if t.status == "open"]
        wins = sum(1 for t in closed if t.status == "win_target")
        losses = sum(1 for t in closed if t.status == "loss_stop")
        timeouts = sum(1 for t in closed if t.status == "exit_time")
        manuals = sum(1 for t in closed if t.status == "exit_manual")
        decisive = wins + losses
        win_rate = (wins / decisive) if decisive else 0.0
        realized = sum(t.pnl for t in closed)
        total = realized + sum(t.pnl for t in open_trades)

        def serialize(t: OptionTrade) -> dict[str, Any]:
            return {
                "id": t.id,
                "entry_time": t.entry_time,
                "direction": t.direction,
                "confidence": t.confidence,
                "spot_at_entry": t.spot_at_entry,
                "instrument_key": t.instrument_key,
                "strike": t.strike,
                "expiry": t.expiry,
                "option_side": t.option_side,
                "moneyness": t.moneyness,
                "entry_premium": t.entry_premium,
                "current_premium": t.current_premium,
                "target_premium": t.target_premium,
                "stop_premium": t.stop_premium,
                "n_lots": t.n_lots,
                "qty": t.qty,
                "capital_used": t.capital_used,
                "status": t.status,
                "exit_time": t.exit_time,
                "exit_premium": t.exit_premium,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
            }

        return {
            "running": self.running,
            "min_confidence": self.min_confidence,
            "capital_inr": self.capital_inr,
            "target_pct": self.target_pct,
            "stop_pct": self.stop_pct,
            "max_hold_sec": self.max_hold_sec,
            "lot_size": LOT_SIZE,
            "status_msg": self.last_status_msg,
            "trades_total": len(self.trades),
            "trades_open": len(open_trades),
            "trades_closed": len(closed),
            "wins": wins,
            "losses": losses,
            "timeouts": timeouts,
            "manuals": manuals,
            "win_rate": win_rate,
            "realized_pnl": realized,
            "total_pnl_incl_open": total,
            "open_positions": [serialize(t) for t in open_trades],
            "recent_closed": [serialize(t) for t in closed[-20:][::-1]],
        }

    def reset(self) -> None:
        self.trades = []
        self.next_id = 1
        self.last_status_msg = "reset"


_trader: Optional[AutoTrader] = None


def get_auto_trader() -> AutoTrader:
    global _trader
    if _trader is None:
        _trader = AutoTrader()
    return _trader
