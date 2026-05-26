"""Stacking-ensemble inference. Loaded once at FastAPI startup."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd

from backend.feature_engineering import FEATURE_COLUMNS

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"

LABEL_MAP = {0: "BUY_PUT", 1: "NO_TRADE", 2: "BUY_CALL"}


@dataclass
class SignalResult:
    prediction: str           # BUY_CALL / BUY_PUT / NO_TRADE
    confidence: float         # 0..1
    probabilities: dict       # {label_name: prob}
    indicators: dict          # feature snapshot used


class SignalEngine:
    def __init__(self) -> None:
        self.xgb = None
        self.lgbm = None
        self.cat = None
        self.meta = None
        self.lstm = None
        self._load()

    def _load(self) -> None:
        self.xgb = joblib.load(MODELS_DIR / "xgboost.pkl")
        self.lgbm = joblib.load(MODELS_DIR / "lightgbm.pkl")
        self.cat = joblib.load(MODELS_DIR / "catboost.pkl")
        self.meta = joblib.load(MODELS_DIR / "meta_rf.pkl")

        lstm_path = MODELS_DIR / "lstm_model.h5"
        if lstm_path.exists():
            try:
                from tensorflow.keras.models import load_model  # lazy import
                self.lstm = load_model(lstm_path)
            except Exception as exc:
                print(f"[signal_engine] LSTM load skipped: {exc}")

    def predict(self, features: pd.DataFrame) -> SignalResult:
        """`features` is a single-row DataFrame with FEATURE_COLUMNS."""
        X = features[FEATURE_COLUMNS]
        base_proba = np.hstack([
            self.xgb.predict_proba(X),
            self.lgbm.predict_proba(X),
            self.cat.predict_proba(X),
        ])
        proba = self.meta.predict_proba(base_proba)[0]
        pred_idx = int(np.argmax(proba))
        pred_label = LABEL_MAP[pred_idx]
        return SignalResult(
            prediction=pred_label,
            confidence=float(proba[pred_idx]),
            probabilities={LABEL_MAP[i]: float(p) for i, p in enumerate(proba)},
            indicators=X.iloc[0].to_dict(),
        )


_engine: Optional[SignalEngine] = None


def get_engine() -> SignalEngine:
    global _engine
    if _engine is None:
        _engine = SignalEngine()
    return _engine
