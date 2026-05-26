"""Local training entry point. Mirrors notebooks/train_colab.ipynb logic.

Run: python -m backend.train_model
Outputs: models/{xgboost,lightgbm,catboost,meta_rf}.pkl
"""
from __future__ import annotations

import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split

from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from catboost import CatBoostClassifier

from backend.feature_engineering import FEATURE_COLUMNS, build_features


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "models"
MODELS_DIR.mkdir(exist_ok=True)


def load_csv(name: str) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / name)
    df.columns = [c.strip().lower() for c in df.columns]
    if "datetime" not in df.columns:
        for cand in ("date", "timestamp", "time"):
            if cand in df.columns:
                df = df.rename(columns={cand: "datetime"})
                break
    return df


def to_3class(y: pd.Series) -> pd.Series:
    """Map {-1, 0, 1} -> {0, 1, 2} for classifiers that require non-negative classes."""
    return y.map({-1: 0, 0: 1, 1: 2}).astype(int)


def train():
    df = load_csv("nifty50_daily.csv")
    feats = build_features(df)
    X = feats[FEATURE_COLUMNS]
    y = to_3class(feats["label"])

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, shuffle=False
    )

    print("== XGBoost ==")
    xgb = XGBClassifier(
        n_estimators=400, max_depth=5, learning_rate=0.05,
        objective="multi:softprob", num_class=3, eval_metric="mlogloss",
    )
    xgb.fit(X_train, y_train)
    print(classification_report(y_test, xgb.predict(X_test)))
    joblib.dump(xgb, MODELS_DIR / "xgboost.pkl")

    print("== LightGBM ==")
    lgbm = LGBMClassifier(n_estimators=400, max_depth=-1, learning_rate=0.05, num_class=3, objective="multiclass")
    lgbm.fit(X_train, y_train)
    print(classification_report(y_test, lgbm.predict(X_test)))
    joblib.dump(lgbm, MODELS_DIR / "lightgbm.pkl")

    print("== CatBoost ==")
    cat = CatBoostClassifier(iterations=400, depth=6, learning_rate=0.05, loss_function="MultiClass", verbose=0)
    cat.fit(X_train, y_train)
    print(classification_report(y_test, cat.predict(X_test)))
    joblib.dump(cat, MODELS_DIR / "catboost.pkl")

    print("== Stacking meta-learner (Random Forest) ==")
    base_proba = np.hstack([
        xgb.predict_proba(X_train),
        lgbm.predict_proba(X_train),
        cat.predict_proba(X_train),
    ])
    meta = RandomForestClassifier(n_estimators=200, max_depth=8, random_state=42)
    meta.fit(base_proba, y_train)

    base_proba_test = np.hstack([
        xgb.predict_proba(X_test),
        lgbm.predict_proba(X_test),
        cat.predict_proba(X_test),
    ])
    print("Ensemble accuracy:", accuracy_score(y_test, meta.predict(base_proba_test)))
    joblib.dump(meta, MODELS_DIR / "meta_rf.pkl")

    print(f"\nAll models saved to {MODELS_DIR}")


if __name__ == "__main__":
    train()
