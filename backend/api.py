"""FastAPI entry point.

Run: uvicorn api:app --reload --port 8000  (from backend/ directory)
or:  uvicorn backend.api:app --reload      (from project root)
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.auto_trader import get_auto_trader
from backend.feature_engineering import FEATURE_COLUMNS, build_features
from backend.intraday_aggregator import inject_today_bar
from backend.llm_explainer import explain_signal
from backend.replay_engine import get_replay
from backend.signal_engine import SignalEngine, get_engine
from backend.upstox_feed import UpstoxFeed
from backend.upstox_orders import OrderRequest, kill_switch, place_order

load_dotenv(override=True)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        state["engine"] = get_engine()
        print("[api] Models loaded.")
    except FileNotFoundError as exc:
        print(f"[api] WARNING: models not found ({exc}). Train first via notebooks/train_colab.ipynb.")
        state["engine"] = None

    feed = UpstoxFeed()
    await feed.start()
    state["feed"] = feed

    # Wire the auto-trader to read live LTP from the feed
    trader = get_auto_trader()
    trader.set_ltp_provider(lambda: feed.latest.get("ltp") if feed.latest else None)
    state["trader"] = trader

    yield
    await trader.stop()
    await feed.stop()


app = FastAPI(title="Nifty Signal API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PredictRequest(BaseModel):
    csv_name: Optional[str] = "nifty50_daily.csv"
    use_last_n: int = 1


class PredictResponse(BaseModel):
    prediction: str
    confidence: float
    probabilities: dict
    indicators: dict
    explanation: str


@app.get("/health")
def health():
    ok, reason = kill_switch.can_trade()
    return {
        "status": "ok",
        "models_loaded": state.get("engine") is not None,
        "kill_switch_armed": ok,
        "kill_switch_reason": reason,
        "live_trade": os.getenv("LIVE_TRADE", "false"),
    }


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    engine: SignalEngine | None = state.get("engine")
    if engine is None:
        raise HTTPException(503, "Models not loaded. Train first.")

    csv_path = DATA_DIR / req.csv_name
    if not csv_path.exists():
        raise HTTPException(404, f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)
    # Inject today's intraday-aggregated bar so features reflect CURRENT market state.
    # Without this, intraday predictions are frozen at yesterday's close values.
    df = inject_today_bar(df)
    # Load hourly CSV too if available so the 5 intraday features get populated
    hourly_path = DATA_DIR / "nifty50_hourly.csv"
    hourly_df = pd.read_csv(hourly_path) if hourly_path.exists() else None
    feats = build_features(df, hourly_df=hourly_df)
    if feats.empty:
        raise HTTPException(400, "No usable rows after feature engineering.")

    latest = feats.tail(1)[FEATURE_COLUMNS]
    result = engine.predict(latest)
    explanation = explain_signal(result.indicators, result.prediction, result.confidence)

    return PredictResponse(
        prediction=result.prediction,
        confidence=result.confidence,
        probabilities=result.probabilities,
        indicators=result.indicators,
        explanation=explanation,
    )


@app.get("/feed/latest")
def feed_latest():
    # If a replay is running, prefer the replayed bar over the stub feed
    replay = get_replay()
    if replay.state.running and replay.latest_bar:
        return replay.latest_bar
    feed: UpstoxFeed | None = state.get("feed")
    if feed is None:
        raise HTTPException(503, "Feed not initialised.")
    return feed.latest or {"status": "waiting for first tick"}


# ---------- Replay (historical simulation) endpoints ----------


class ReplayStartBody(BaseModel):
    csv_name: str = "nifty50_daily.csv"
    speed_seconds: float = 2.0
    last_n: int = 250  # last 1 trading year of daily bars
    invert: bool = False  # flip BUY_CALL <-> BUY_PUT


@app.post("/replay/start")
async def replay_start(body: ReplayStartBody):
    if state.get("engine") is None:
        raise HTTPException(503, "Models not loaded. Train first.")
    replay = get_replay()
    try:
        await replay.start(
            csv_name=body.csv_name,
            speed_seconds=body.speed_seconds,
            last_n=body.last_n,
            invert=body.invert,
        )
    except Exception as exc:
        raise HTTPException(400, str(exc))
    return {
        "status": "started",
        "csv_name": replay.state.csv_name,
        "speed_seconds": replay.state.speed_seconds,
        "start_idx": replay.state.start_idx,
        "total_bars": replay.state.total_bars,
        "invert": replay.state.invert,
    }


@app.post("/replay/stop")
async def replay_stop():
    replay = get_replay()
    await replay.stop()
    return {"status": "stopped", "predictions_made": len(replay.state.predictions)}


@app.get("/replay/stats")
def replay_stats():
    return get_replay().stats()


# ---------- Auto paper trader ----------


class AutoTradeStartBody(BaseModel):
    min_confidence: float = 0.40
    capital_inr: float = 10000.0
    target_pct: float = 0.50   # 50% premium target (typical for ATM options)
    stop_pct: float = 0.30     # 30% premium stop


@app.post("/auto_trade/start")
async def auto_trade_start(body: AutoTradeStartBody):
    if state.get("engine") is None:
        raise HTTPException(503, "Models not loaded.")
    trader = get_auto_trader()
    await trader.start(
        min_confidence=body.min_confidence,
        capital_inr=body.capital_inr,
        target_pct=body.target_pct,
        stop_pct=body.stop_pct,
    )
    return {"status": "started", **trader.stats()}


@app.post("/auto_trade/stop")
async def auto_trade_stop():
    trader = get_auto_trader()
    await trader.stop()
    return {"status": "stopped", "trades_closed": trader.stats()["trades_closed"]}


@app.post("/auto_trade/reset")
async def auto_trade_reset():
    trader = get_auto_trader()
    if trader.running:
        await trader.stop()
    trader.reset()
    return {"status": "reset"}


@app.get("/auto_trade/stats")
def auto_trade_stats():
    return get_auto_trader().stats()


class OrderBody(BaseModel):
    instrument_token: str
    side: str  # BUY / SELL
    quantity: int
    order_type: str = "MARKET"
    price: float = 0.0


@app.post("/order/place")
def order_place(body: OrderBody):
    req = OrderRequest(
        instrument_token=body.instrument_token,
        side=body.side.upper(),  # type: ignore
        quantity=body.quantity,
        order_type=body.order_type.upper(),  # type: ignore
        price=body.price,
    )
    res = place_order(req)
    return {
        "accepted": res.accepted,
        "paper": res.paper,
        "reason": res.reason,
        "order_id": res.order_id,
    }
