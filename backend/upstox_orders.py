"""Upstox order placement with kill switch + LIVE_TRADE flag.

CRITICAL: kill switch checks DAILY_LOSS_LIMIT before every order.
When LIVE_TRADE=false (default), orders are logged only — no live API call.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional

from dotenv import load_dotenv

load_dotenv()

LIVE_TRADE = os.getenv("LIVE_TRADE", "false").lower() == "true"
DAILY_LOSS_LIMIT = float(os.getenv("DAILY_LOSS_LIMIT", "-2000"))
LOT_SIZE = int(os.getenv("LOT_SIZE", "25"))
UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "")


@dataclass
class OrderRequest:
    instrument_token: str
    side: Literal["BUY", "SELL"]
    quantity: int
    order_type: Literal["MARKET", "LIMIT", "SL"] = "MARKET"
    price: float = 0.0
    product: Literal["I", "D"] = "I"  # I = intraday, D = delivery


@dataclass
class OrderResult:
    accepted: bool
    paper: bool
    reason: str
    order_id: Optional[str] = None


class KillSwitch:
    """Tracks daily PnL and blocks orders once DAILY_LOSS_LIMIT is hit."""

    def __init__(self, limit: float = DAILY_LOSS_LIMIT) -> None:
        self.limit = limit
        self.daily_pnl = 0.0
        self.day = date.today()
        self.tripped = False

    def _rollover_if_new_day(self) -> None:
        today = date.today()
        if today != self.day:
            self.day = today
            self.daily_pnl = 0.0
            self.tripped = False

    def update_pnl(self, delta: float) -> None:
        self._rollover_if_new_day()
        self.daily_pnl += delta
        if self.daily_pnl <= self.limit:
            self.tripped = True

    def can_trade(self) -> tuple[bool, str]:
        self._rollover_if_new_day()
        if self.tripped or self.daily_pnl <= self.limit:
            return False, f"Kill switch: daily PnL {self.daily_pnl:.2f} ≤ limit {self.limit:.2f}"
        return True, "ok"


kill_switch = KillSwitch()


def place_order(req: OrderRequest) -> OrderResult:
    ok, reason = kill_switch.can_trade()
    if not ok:
        return OrderResult(accepted=False, paper=not LIVE_TRADE, reason=reason)

    if not LIVE_TRADE:
        msg = f"[PAPER] {req.side} {req.quantity} {req.instrument_token} @ {req.order_type} {req.price}"
        print(msg)
        return OrderResult(accepted=True, paper=True, reason=msg, order_id="paper-001")

    if not UPSTOX_ACCESS_TOKEN:
        return OrderResult(accepted=False, paper=False, reason="UPSTOX_ACCESS_TOKEN missing")

    try:
        import upstox_client
        from upstox_client.api.order_api_v3 import OrderApiV3
        from upstox_client.models.place_order_v3_request import PlaceOrderV3Request
    except ImportError:
        return OrderResult(accepted=False, paper=False, reason="upstox-python-sdk not installed")

    config = upstox_client.Configuration()
    config.access_token = UPSTOX_ACCESS_TOKEN
    api = OrderApiV3(upstox_client.ApiClient(config))

    body = PlaceOrderV3Request(
        quantity=req.quantity,
        product=req.product,
        validity="DAY",
        price=req.price,
        instrument_token=req.instrument_token,
        order_type=req.order_type,
        transaction_type=req.side,
        disclosed_quantity=0,
        trigger_price=0.0,
        is_amo=False,
    )
    try:
        resp = api.place_order(body)
        order_id = getattr(resp, "data", {}).get("order_ids", [None])[0] if hasattr(resp, "data") else None
        return OrderResult(accepted=True, paper=False, reason="placed", order_id=order_id)
    except Exception as exc:
        return OrderResult(accepted=False, paper=False, reason=f"upstox error: {exc}")
