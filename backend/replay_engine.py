"""Replay engine: stream a historical CSV as if it were live, fire predictions
each bar, score the outcome against the next bar, accumulate stats.

This is a backtest visualized in real time — gives an honest out-of-sample
view of the trained model without needing Upstox to be live.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from backend.feature_engineering import FEATURE_COLUMNS, build_features
from backend.signal_engine import get_engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# How big a move counts as a real direction (vs noise) when scoring outcomes
OUTCOME_THRESHOLD = 0.002  # 0.2% on daily bars


@dataclass
class Prediction:
    idx: int
    datetime: str
    close: float
    prediction: str
    confidence: float
    next_close: Optional[float] = None
    actual_move_pct: Optional[float] = None
    outcome: Optional[str] = None  # WIN | LOSS | NEUTRAL


@dataclass
class ReplayState:
    running: bool = False
    csv_name: str = "nifty50_daily.csv"
    speed_seconds: float = 2.0
    start_idx: int = 0
    current_idx: int = 0
    total_bars: int = 0
    invert: bool = False  # flip BUY_CALL <-> BUY_PUT before scoring
    predictions: list[Prediction] = field(default_factory=list)


class ReplayEngine:
    def __init__(self) -> None:
        self.state = ReplayState()
        self._task: Optional[asyncio.Task] = None
        self._feats: Optional[pd.DataFrame] = None
        self.latest_bar: dict = {}

    def _load(self, csv_name: str, last_n: int) -> None:
        csv_path = DATA_DIR / csv_name
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV not found: {csv_path}")
        df = pd.read_csv(csv_path)
        self._feats = build_features(df)
        if self._feats.empty:
            raise ValueError("No usable rows after feature engineering")
        self.state.csv_name = csv_name
        self.state.total_bars = len(self._feats)
        # Start last_n bars before end (or from beginning if data is shorter)
        self.state.start_idx = max(0, self.state.total_bars - last_n - 1)
        self.state.current_idx = self.state.start_idx

    async def start(self, csv_name: str, speed_seconds: float, last_n: int, invert: bool = False) -> None:
        if self.state.running:
            return
        self._load(csv_name, last_n)
        self.state.speed_seconds = speed_seconds
        self.state.invert = invert
        self.state.predictions = []
        self.state.running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self.state.running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None

    async def _run(self) -> None:
        assert self._feats is not None
        engine = get_engine()
        try:
            while self.state.running and self.state.current_idx < self.state.total_bars - 1:
                idx = self.state.current_idx
                row = self._feats.iloc[idx]
                next_row = self._feats.iloc[idx + 1]
                close = float(row["close"])
                next_close = float(next_row["close"])
                move_pct = (next_close - close) / close

                # Publish current bar to feed consumers
                dt = row["datetime"] if "datetime" in row.index else str(idx)
                self.latest_bar = {
                    "datetime": str(dt),
                    "ltp": close,
                    "tick": idx,
                    "replay": True,
                }

                # Run prediction on this bar's features
                X = self._feats.iloc[[idx]][FEATURE_COLUMNS]
                result = engine.predict(X)
                pred_label = result.prediction
                if self.state.invert:
                    # Flip directional calls only; NO_TRADE stays
                    if pred_label == "BUY_CALL":
                        pred_label = "BUY_PUT"
                    elif pred_label == "BUY_PUT":
                        pred_label = "BUY_CALL"

                # Score outcome vs next bar (we know it because it's historical)
                outcome = self._score(pred_label, move_pct)

                pred = Prediction(
                    idx=idx,
                    datetime=str(dt),
                    close=close,
                    prediction=pred_label,
                    confidence=result.confidence,
                    next_close=next_close,
                    actual_move_pct=move_pct,
                    outcome=outcome,
                )
                self.state.predictions.append(pred)
                self.state.current_idx += 1

                await asyncio.sleep(self.state.speed_seconds)
        except asyncio.CancelledError:
            pass
        finally:
            self.state.running = False

    @staticmethod
    def _score(prediction: str, move_pct: float) -> str:
        if abs(move_pct) < OUTCOME_THRESHOLD:
            # Move was within noise band
            return "WIN" if prediction == "NO_TRADE" else "LOSS_SMALL_MOVE"
        if prediction == "BUY_CALL":
            return "WIN" if move_pct > 0 else "LOSS"
        if prediction == "BUY_PUT":
            return "WIN" if move_pct < 0 else "LOSS"
        if prediction == "NO_TRADE":
            # Move was significant but we said NO_TRADE — we missed it
            return "MISSED"
        return "NEUTRAL"

    def stats(self) -> dict:
        preds = self.state.predictions
        if not preds:
            return {
                "running": self.state.running,
                "total": 0, "wins": 0, "losses": 0,
                "win_rate": 0.0, "decisive_trades": 0,
                "current_idx": self.state.current_idx,
                "start_idx": self.state.start_idx,
                "total_bars": self.state.total_bars,
                "latest": [],
                "by_class": {},
            }

        wins = sum(1 for p in preds if p.outcome == "WIN")
        losses = sum(1 for p in preds if p.outcome in ("LOSS", "LOSS_SMALL_MOVE"))
        missed = sum(1 for p in preds if p.outcome == "MISSED")
        decisive = wins + losses  # neutral / missed don't count
        wr = (wins / decisive) if decisive else 0.0

        # Breakdown by predicted class
        by_class: dict = {}
        for cls in ("BUY_CALL", "BUY_PUT", "NO_TRADE"):
            subset = [p for p in preds if p.prediction == cls]
            cls_wins = sum(1 for p in subset if p.outcome == "WIN")
            cls_losses = sum(1 for p in subset if p.outcome in ("LOSS", "LOSS_SMALL_MOVE"))
            cls_decisive = cls_wins + cls_losses
            by_class[cls] = {
                "n": len(subset),
                "wins": cls_wins,
                "losses": cls_losses,
                "precision": (cls_wins / cls_decisive) if cls_decisive else 0.0,
            }

        latest = [
            {
                "idx": p.idx,
                "datetime": p.datetime,
                "close": p.close,
                "prediction": p.prediction,
                "confidence": p.confidence,
                "move_pct": p.actual_move_pct,
                "outcome": p.outcome,
            }
            for p in preds[-12:][::-1]
        ]

        # Threshold sweep: if you only took trades above a confidence floor,
        # how would precision change? This is the most important diagnostic.
        threshold_sweep = []
        for thresh in (0.0, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90):
            directional = [
                p for p in preds
                if p.prediction in ("BUY_CALL", "BUY_PUT") and p.confidence >= thresh
            ]
            tw = sum(1 for p in directional if p.outcome == "WIN")
            tl = sum(1 for p in directional if p.outcome in ("LOSS", "LOSS_SMALL_MOVE"))
            td = tw + tl
            threshold_sweep.append({
                "threshold": thresh,
                "trades": len(directional),
                "wins": tw,
                "losses": tl,
                "win_rate": (tw / td) if td else 0.0,
            })

        return {
            "running": self.state.running,
            "total": len(preds),
            "wins": wins,
            "losses": losses,
            "missed": missed,
            "decisive_trades": decisive,
            "win_rate": wr,
            "current_idx": self.state.current_idx,
            "start_idx": self.state.start_idx,
            "total_bars": self.state.total_bars,
            "latest": latest,
            "by_class": by_class,
            "threshold_sweep": threshold_sweep,
        }


_engine: Optional[ReplayEngine] = None


def get_replay() -> ReplayEngine:
    global _engine
    if _engine is None:
        _engine = ReplayEngine()
    return _engine
