"""Feature engineering — matches notebooks/train_colab_v4.ipynb.

Produces the FULL v4 feature set (Nifty + intraday + VIX + BankNifty + rolling stats),
then subsets to whatever feature list the trained model expects (read from
models/label_thresholds.json if present).

Falls back to safe defaults if VIX/BNF CSVs aren't available locally.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator, EMAIndicator, MACD
from ta.volatility import AverageTrueRange, BollingerBands


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "models"


# ---------- Feature group definitions (match v4 notebook) ----------

FEATURES_NIFTY = [
    "rsi_14", "macd_hist", "ema_cross_9_21", "ema_cross_21_50", "atr_14", "bb_pct_b", "adx_14",
    "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d",
    "vol_5d", "vol_10d", "vol_20d",
    "mean_5d", "mean_10d", "mean_20d",
    "high_5d_dist", "high_10d_dist", "high_20d_dist",
    "low_5d_dist", "low_10d_dist", "low_20d_dist",
    "vol_regime", "atr_pct",
    "log_vol", "vol_vs_ma20", "vol_zscore",
    "gap_pct", "rsi_divergence",
    "day_of_week", "dte",
]
FEATURES_INTRADAY = [
    "intraday_total_return", "intraday_max_drawdown", "intraday_vol",
    "intraday_volume_total", "intraday_n_bars",
]
FEATURES_VIX = [
    "vix", "vix_change_1d", "vix_change_5d", "vix_vs_ma20", "vix_high", "vix_low",
]
FEATURES_BNF = [
    "bnf_ret_1d", "bnf_ret_5d", "bnf_ret_20d", "bnf_nifty_corr_20", "bnf_nifty_divergence",
]
ALL_V4_FEATURES = FEATURES_NIFTY + FEATURES_INTRADAY + FEATURES_VIX + FEATURES_BNF


def _load_feature_columns() -> list[str]:
    """Read the trained model's expected feature list from label_thresholds.json.
    Falls back to the full v4 set if the file isn't present."""
    meta_path = MODELS_DIR / "label_thresholds.json"
    if meta_path.exists():
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            feats = meta.get("features")
            if feats and isinstance(feats, list):
                return list(feats)
        except Exception as exc:
            print(f"[feature_engineering] failed to read {meta_path}: {exc}")
    return ALL_V4_FEATURES


FEATURE_COLUMNS = _load_feature_columns()
print(f"[feature_engineering] {len(FEATURE_COLUMNS)} features expected by the trained model")


# ---------- Helpers ----------

def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [c.strip().lower() for c in out.columns]
    if "datetime" not in out.columns:
        for cand in ("date", "timestamp", "time"):
            if cand in out.columns:
                out = out.rename(columns={cand: "datetime"})
                break
    out["datetime"] = pd.to_datetime(out["datetime"])
    out = out.sort_values("datetime").reset_index(drop=True)
    out["date"] = (
        out["datetime"].dt.tz_localize(None) if out["datetime"].dt.tz is not None
        else out["datetime"]
    ).dt.normalize()
    return out


def _find_local_csv(patterns: list[str]) -> Optional[Path]:
    for path in DATA_DIR.glob("*.csv"):
        for pat in patterns:
            if re.search(pat, path.name, re.IGNORECASE):
                return path
    return None


def _try_load_vix() -> Optional[pd.DataFrame]:
    p = _find_local_csv([r"india.*vix", r"^vix", r"_vix\.csv"])
    if p is None:
        return None
    try:
        return pd.read_csv(p)
    except Exception:
        return None


def _try_load_bnf() -> Optional[pd.DataFrame]:
    p = _find_local_csv([r"bank.*nifty", r"nifty.*bank"])
    if p is None:
        return None
    try:
        return pd.read_csv(p)
    except Exception:
        return None


# ---------- Feature engineering functions ----------

def add_nifty_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    c, h, l, v = out["close"], out["high"], out["low"], out["volume"]

    out["rsi_14"] = RSIIndicator(c, 14).rsi()
    out["macd_hist"] = MACD(c, 26, 12, 9).macd_diff()
    ema9, ema21, ema50 = (
        EMAIndicator(c, 9).ema_indicator(),
        EMAIndicator(c, 21).ema_indicator(),
        EMAIndicator(c, 50).ema_indicator(),
    )
    out["ema_cross_9_21"] = (ema9 > ema21).astype(int)
    out["ema_cross_21_50"] = (ema21 > ema50).astype(int)
    out["atr_14"] = AverageTrueRange(h, l, c, 14).average_true_range()
    bb = BollingerBands(c, 20, 2)
    out["bb_pct_b"] = (c - bb.bollinger_lband()) / (bb.bollinger_hband() - bb.bollinger_lband())
    out["adx_14"] = ADXIndicator(h, l, c, 14).adx()

    for lag in (1, 3, 5, 10, 20):
        out[f"ret_{lag}d"] = c.pct_change(lag)

    rets = c.pct_change()
    for w in (5, 10, 20):
        out[f"vol_{w}d"] = rets.rolling(w).std()
        out[f"mean_{w}d"] = rets.rolling(w).mean()
        out[f"high_{w}d_dist"] = (c - h.rolling(w).max()) / h.rolling(w).max()
        out[f"low_{w}d_dist"] = (c - l.rolling(w).min()) / l.rolling(w).min()

    atr_50 = AverageTrueRange(h, l, c, 50).average_true_range()
    out["vol_regime"] = out["atr_14"] / atr_50
    out["atr_pct"] = out["atr_14"] / c

    v_safe = v.replace(0, np.nan)
    out["log_vol"] = np.log1p(v_safe).fillna(0)
    vma20 = v_safe.rolling(20).mean()
    vstd20 = v_safe.rolling(20).std()
    out["vol_vs_ma20"] = (v_safe / vma20).fillna(1.0)
    out["vol_zscore"] = ((v_safe - vma20) / vstd20).fillna(0.0)

    out["gap_pct"] = (out["open"] - c.shift(1)) / c.shift(1)
    out["rsi_divergence"] = (np.sign(c.pct_change(14)) * np.sign(out["rsi_14"].diff(14))).fillna(0)

    dt = pd.to_datetime(out["datetime"])
    out["day_of_week"] = dt.dt.dayofweek
    out["dte"] = (3 - dt.dt.dayofweek) % 7

    return out


def hourly_to_daily_features(hourly_df: pd.DataFrame) -> pd.DataFrame:
    h = _normalize(hourly_df)
    h["intraday_ret"] = (h["close"] - h["open"]) / h["open"]
    grouped = h.groupby("date").agg(
        intraday_total_return=("close", lambda s: (s.iloc[-1] - s.iloc[0]) / s.iloc[0] if len(s) > 1 else 0),
        intraday_max_drawdown=("close", lambda s: (s.min() - s.iloc[0]) / s.iloc[0] if len(s) > 1 else 0),
        intraday_vol=("intraday_ret", "std"),
        intraday_volume_total=("volume", "sum"),
        intraday_n_bars=("close", "count"),
    ).reset_index()
    grouped["intraday_volume_total"] = np.log1p(grouped["intraday_volume_total"].fillna(0))
    grouped["intraday_vol"] = grouped["intraday_vol"].fillna(0)
    return grouped


def build_vix_features(vix_df: pd.DataFrame) -> pd.DataFrame:
    v = _normalize(vix_df)
    vix_col = "close" if "close" in v.columns else ("value" if "value" in v.columns else None)
    if vix_col is None:
        raise ValueError(f"VIX CSV needs close/value column. Got: {list(v.columns)}")
    v = v[["date", vix_col]].rename(columns={vix_col: "vix"})
    v["vix_change_1d"] = v["vix"].pct_change(1)
    v["vix_change_5d"] = v["vix"].pct_change(5)
    v["vix_ma20"] = v["vix"].rolling(20).mean()
    v["vix_vs_ma20"] = v["vix"] / v["vix_ma20"]
    v["vix_high"] = (v["vix"] > 20).astype(int)
    v["vix_low"] = (v["vix"] < 14).astype(int)
    return v.drop(columns=["vix_ma20"])


def build_bnf_features(bnf_df: pd.DataFrame, nifty_close: pd.Series) -> pd.DataFrame:
    b = _normalize(bnf_df)
    b = b[["date", "close", "high", "low"]].rename(columns={"close": "bnf_close"})
    b["bnf_ret_1d"] = b["bnf_close"].pct_change(1)
    b["bnf_ret_5d"] = b["bnf_close"].pct_change(5)
    b["bnf_ret_20d"] = b["bnf_close"].pct_change(20)
    bnf_rets = b["bnf_close"].pct_change()
    nifty_rets = nifty_close.pct_change()
    # Align lengths: take last N matching the bnf series
    nifty_rets_aligned = nifty_rets.iloc[-len(bnf_rets):].reset_index(drop=True)
    b["bnf_nifty_corr_20"] = bnf_rets.rolling(20).corr(nifty_rets_aligned)
    b["bnf_nifty_divergence"] = np.sign(b["bnf_ret_1d"]) - np.sign(nifty_rets_aligned)
    return b[["date", "bnf_ret_1d", "bnf_ret_5d", "bnf_ret_20d", "bnf_nifty_corr_20", "bnf_nifty_divergence"]]


def build_features(
    df: pd.DataFrame,
    datetime_col: str = "datetime",
    hourly_df: Optional[pd.DataFrame] = None,
    vix_df: Optional[pd.DataFrame] = None,
    bnf_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Full v4 pipeline. Returns rows with FEATURE_COLUMNS populated.

    Auto-loads VIX/BNF CSVs from data/ if not passed explicitly. Missing
    feature groups are filled with safe defaults (zeros) so the model can
    still predict (with degraded accuracy on those features).
    """
    df = _normalize(df)
    out = add_nifty_features(df)

    # Intraday from hourly
    if hourly_df is not None:
        try:
            intraday = hourly_to_daily_features(hourly_df)
            out = out.merge(intraday, on="date", how="left")
            for col in FEATURES_INTRADAY:
                out[col] = out[col].fillna(0)
        except Exception as exc:
            print(f"[feature_engineering] intraday merge failed: {exc}")
            for col in FEATURES_INTRADAY:
                out[col] = 0
    else:
        for col in FEATURES_INTRADAY:
            out[col] = 0

    # VIX features
    if vix_df is None:
        vix_df = _try_load_vix()
    if vix_df is not None:
        try:
            vix_feats = build_vix_features(vix_df)
            out = out.merge(vix_feats, on="date", how="left")
            for col in FEATURES_VIX:
                out[col] = out[col].ffill().bfill()
        except Exception as exc:
            print(f"[feature_engineering] VIX merge failed: {exc}")
            for col in FEATURES_VIX:
                out[col] = 0
    else:
        for col in FEATURES_VIX:
            out[col] = 0

    # Bank Nifty features
    if bnf_df is None:
        bnf_df = _try_load_bnf()
    if bnf_df is not None:
        try:
            bnf_feats = build_bnf_features(bnf_df, df.set_index("date")["close"])
            out = out.merge(bnf_feats, on="date", how="left")
            for col in FEATURES_BNF:
                out[col] = out[col].ffill().fillna(0)
        except Exception as exc:
            print(f"[feature_engineering] BNF merge failed: {exc}")
            for col in FEATURES_BNF:
                out[col] = 0
    else:
        for col in FEATURES_BNF:
            out[col] = 0

    # Sanitize: inf -> NaN -> drop warmup rows
    out[ALL_V4_FEATURES] = out[ALL_V4_FEATURES].replace([np.inf, -np.inf], np.nan)
    out = out.dropna(subset=ALL_V4_FEATURES).reset_index(drop=True)

    # Outlier clip (matches notebook)
    for col in ALL_V4_FEATURES:
        if out[col].dtype.kind in "fc":
            q01, q99 = out[col].quantile([0.001, 0.999])
            out[col] = out[col].clip(q01, q99)

    return out


def feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Subset to whatever FEATURE_COLUMNS the trained model expects."""
    missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing features for inference: {missing}")
    return df[FEATURE_COLUMNS]
