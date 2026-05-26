"""Portfolio-level 52-week breakout backtest with realistic constraints.

Features:
- Position sizing (% risk per trade)
- Max concurrent positions
- Sector diversification
- Chronological trade ordering across all stocks
- Equity curve tracking
- Live scanner: which stocks are at 52-week highs RIGHT NOW

Run standalone: python -m backend.portfolio_backtest
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STOCKS_DIR = DATA_DIR / "stocks"

from backend.stock_universe import SECTOR_MAP as SECTORS


@dataclass
class Trade:
    symbol: str
    sector: str
    entry_date: str
    entry_price: float
    sl_price: float
    t1_price: float
    t2_price: float
    sl_pct: float
    rr_t1: float
    rr_t2: float
    qty: int
    capital_used: float

    exit_date: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl_pct: float = 0.0
    pnl_abs: float = 0.0
    holding_days: int = 0
    t1_hit: bool = False
    t2_hit: bool = False
    max_dd_pct: float = 0.0
    max_ru_pct: float = 0.0
    dist_above_52w: float = 0.0
    atr_pct: float = 0.0
    rsi_14: float = 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "sector": self.sector,
            "entry_date": self.entry_date, "entry_price": round(self.entry_price, 2),
            "sl_price": round(self.sl_price, 2),
            "t1_price": round(self.t1_price, 2), "t2_price": round(self.t2_price, 2),
            "sl_pct": round(self.sl_pct * 100, 2), "rr_t1": self.rr_t1, "rr_t2": self.rr_t2,
            "qty": self.qty, "capital_used": round(self.capital_used, 0),
            "exit_date": self.exit_date, "exit_price": round(self.exit_price, 2),
            "exit_reason": self.exit_reason,
            "pnl_pct": round(self.pnl_pct * 100, 2), "pnl_abs": round(self.pnl_abs, 0),
            "holding_days": self.holding_days,
            "t1_hit": self.t1_hit, "t2_hit": self.t2_hit,
            "max_dd_pct": round(self.max_dd_pct * 100, 2),
            "max_ru_pct": round(self.max_ru_pct * 100, 2),
        }


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def load_stock(path: Path) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_csv(path)
        df.columns = [c.strip().lower() for c in df.columns]
        if "date" not in df.columns:
            for c in ("datetime", "timestamp"):
                if c in df.columns:
                    df = df.rename(columns={c: "date"})
                    break
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.sort_values("date").reset_index(drop=True)
        return df if len(df) >= 300 else None
    except Exception:
        return None


def add_indicators(df: pd.DataFrame, lookback: int = 252) -> pd.DataFrame:
    df = df.copy()
    df["high_52w"] = df["high"].shift(1).rolling(lookback).max()
    df["low_52w"] = df["low"].shift(1).rolling(lookback).min()
    df["breakout"] = (df["close"] > df["high_52w"]).astype(int)
    df["dist_above_52w"] = (df["close"] - df["high_52w"]) / df["high_52w"]

    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr_14"] = tr.rolling(14).mean()
    df["atr_pct"] = df["atr_14"] / df["close"]
    df["vol_ma20"] = df["volume"].rolling(20).mean()

    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss_s = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss_s.replace(0, np.nan)
    df["rsi_14"] = 100 - (100 / (1 + rs))
    df["ret_20d"] = df["close"].pct_change(20)
    return df


def load_all_stocks() -> dict[str, pd.DataFrame]:
    stocks = {}
    for path in sorted(STOCKS_DIR.glob("*.csv")):
        sym = path.stem.upper()
        df = load_stock(path)
        if df is not None:
            stocks[sym] = add_indicators(df)
    return stocks


# ---------------------------------------------------------------------------
# Breakout signal scanner (daily)
# ---------------------------------------------------------------------------

@dataclass
class BreakoutSignal:
    date: str
    symbol: str
    sector: str
    close: float
    high_52w: float
    dist_above_52w: float
    atr_pct: float
    rsi_14: float
    volume: float
    vol_ma20: float

    def to_dict(self) -> dict:
        return {
            "date": self.date, "symbol": self.symbol, "sector": self.sector,
            "close": round(self.close, 2), "high_52w": round(self.high_52w, 2),
            "dist_pct": round(self.dist_above_52w * 100, 2),
            "atr_pct": round(self.atr_pct * 100, 2),
            "rsi": round(self.rsi_14, 1),
            "volume": int(self.volume), "vol_ma20": int(self.vol_ma20),
        }


def scan_breakouts(stocks: dict[str, pd.DataFrame], date_str: Optional[str] = None) -> list[BreakoutSignal]:
    """Find all stocks at 52-week highs on a given date (or latest)."""
    signals = []
    for sym, df in stocks.items():
        if date_str:
            target = pd.to_datetime(date_str)
            row_idx = df.index[df["date"] == target]
            if len(row_idx) == 0:
                continue
            row = df.iloc[row_idx[0]]
        else:
            row = df.iloc[-1]

        if pd.isna(row.get("high_52w")) or row.get("breakout", 0) != 1:
            continue

        signals.append(BreakoutSignal(
            date=str(row["date"].date()),
            symbol=sym,
            sector=SECTORS.get(sym, "Other"),
            close=float(row["close"]),
            high_52w=float(row["high_52w"]),
            dist_above_52w=float(row.get("dist_above_52w", 0)),
            atr_pct=float(row.get("atr_pct", 0)),
            rsi_14=float(row.get("rsi_14", 50)),
            volume=float(row.get("volume", 0)),
            vol_ma20=float(row.get("vol_ma20", 0)),
        ))
    signals.sort(key=lambda s: -s.dist_above_52w)
    return signals


# ---------------------------------------------------------------------------
# Portfolio backtester
# ---------------------------------------------------------------------------

@dataclass
class BacktestConfig:
    initial_capital: float = 500000.0
    risk_per_trade_pct: float = 0.02    # Risk 2% of capital per trade
    sl_pct: float = 0.05
    rr_t1: float = 2.0
    rr_t2: float = 3.0
    max_hold_days: int = 60
    book_pct_t1: float = 0.50
    sl_to_breakeven: bool = True
    max_open_positions: int = 5
    max_per_sector: int = 2
    cooldown_days: int = 10
    max_sl_pct: float = 0.08
    min_rsi: float = 0.0
    # New filters from factor analysis
    regime_filter: bool = False         # Only trade when Nifty > 200 DMA
    min_volume_ratio: float = 0.0       # Min volume vs 20-day avg (e.g. 1.2 = 20% above avg)
    avoid_months: str = ""              # Comma-separated months to avoid, e.g. "2,9"
    max_dist_above_52w: float = 0.0     # Max distance above 52w high (0=disabled, e.g. 0.03=3%)

    def to_dict(self) -> dict:
        return {
            "initial_capital": self.initial_capital,
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "sl_pct": self.sl_pct, "rr_t1": self.rr_t1, "rr_t2": self.rr_t2,
            "max_hold_days": self.max_hold_days,
            "book_pct_t1": self.book_pct_t1,
            "sl_to_breakeven": self.sl_to_breakeven,
            "max_open_positions": self.max_open_positions,
            "max_per_sector": self.max_per_sector,
            "cooldown_days": self.cooldown_days,
            "max_sl_pct": self.max_sl_pct,
            "min_rsi": self.min_rsi,
            "regime_filter": self.regime_filter,
            "min_volume_ratio": self.min_volume_ratio,
            "avoid_months": self.avoid_months,
            "max_dist_above_52w": self.max_dist_above_52w,
        }


@dataclass
class EquityPoint:
    date: str
    equity: float
    cash: float
    invested: float
    open_positions: int
    trade_event: str = ""  # "entry SYMBOL" or "exit SYMBOL +X%"


def _load_nifty_regime() -> dict[pd.Timestamp, bool]:
    """Load Nifty daily data and compute whether each day is above 200 DMA."""
    nifty_path = DATA_DIR / "nifty50_daily.csv"
    if not nifty_path.exists():
        return {}
    df = pd.read_csv(nifty_path)
    df.columns = [c.strip().lower() for c in df.columns]
    col = "date" if "date" in df.columns else "datetime"
    df[col] = pd.to_datetime(df[col]).dt.tz_localize(None)
    df = df.sort_values(col).reset_index(drop=True)
    df["dma_200"] = df["close"].rolling(200).mean()
    df["above_200dma"] = df["close"] > df["dma_200"]
    return dict(zip(df[col], df["above_200dma"]))


def run_portfolio_backtest(
    stocks: dict[str, pd.DataFrame],
    cfg: BacktestConfig,
) -> tuple[list[Trade], list[EquityPoint]]:

    # Build a unified daily timeline
    all_dates = set()
    for df in stocks.values():
        all_dates.update(df["date"].tolist())
    timeline = sorted(all_dates)

    # Index each stock's data by date for O(1) lookup
    stock_data: dict[str, dict] = {}
    for sym, df in stocks.items():
        stock_data[sym] = {row["date"]: row for _, row in df.iterrows()}

    # Market regime: Nifty above 200 DMA
    nifty_regime = _load_nifty_regime() if cfg.regime_filter else {}

    # Parse avoid_months
    avoid_months_set: set[int] = set()
    if cfg.avoid_months:
        try:
            avoid_months_set = {int(m.strip()) for m in cfg.avoid_months.split(",") if m.strip()}
        except ValueError:
            pass

    trades: list[Trade] = []
    equity_curve: list[EquityPoint] = []
    open_trades: list[Trade] = []
    cooldowns: dict[str, pd.Timestamp] = {}
    capital = cfg.initial_capital
    cash = cfg.initial_capital

    for day in timeline:
        event_msgs = []

        # --- 1) Manage open trades ---
        closed_today = []
        for t in open_trades:
            row = stock_data.get(t.symbol, {}).get(day)
            if row is None:
                continue

            days_held = (day - pd.to_datetime(t.entry_date)).days
            dd = (row["low"] - t.entry_price) / t.entry_price
            ru = (row["high"] - t.entry_price) / t.entry_price
            t.max_dd_pct = min(t.max_dd_pct, dd)
            t.max_ru_pct = max(t.max_ru_pct, ru)

            active_sl = t.sl_price
            if t.t1_hit and cfg.sl_to_breakeven:
                active_sl = t.entry_price

            exit_price = None
            reason = ""

            if row["low"] <= active_sl:
                exit_price = active_sl
                reason = "t1_then_be" if (t.t1_hit and active_sl >= t.entry_price) else ("t1_then_sl" if t.t1_hit else "sl_hit")
            elif t.t1_hit and row["high"] >= t.t2_price:
                exit_price = t.t2_price
                reason = "t1_then_t2"
                t.t2_hit = True
            elif not t.t1_hit and row["high"] >= t.t1_price:
                t.t1_hit = True

            if exit_price is None and days_held >= cfg.max_hold_days:
                exit_price = row["close"]
                reason = "t1_then_time" if t.t1_hit else "time_exit"

            if exit_price is not None:
                t.exit_date = str(day.date()) if hasattr(day, 'date') else str(day)[:10]
                t.exit_price = exit_price
                t.exit_reason = reason
                t.holding_days = days_held

                if t.t1_hit and reason != "sl_hit":
                    t1_p = cfg.book_pct_t1 * (t.t1_price - t.entry_price) / t.entry_price
                    rem_p = (1 - cfg.book_pct_t1) * (exit_price - t.entry_price) / t.entry_price
                    t.pnl_pct = t1_p + rem_p
                else:
                    t.pnl_pct = (exit_price - t.entry_price) / t.entry_price

                t.pnl_abs = t.pnl_pct * t.capital_used
                cash += t.capital_used + t.pnl_abs
                closed_today.append(t)
                cooldowns[t.symbol] = day + pd.Timedelta(days=cfg.cooldown_days)
                event_msgs.append(f"exit {t.symbol} {t.pnl_pct:+.1%}")

        for t in closed_today:
            open_trades.remove(t)

        # --- 2) Look for new entries ---
        if len(open_trades) < cfg.max_open_positions:
            # Market regime filter: skip entries when Nifty is below 200 DMA
            if cfg.regime_filter and nifty_regime:
                above = nifty_regime.get(day)
                if above is not None and not above:
                    # Record equity and skip to next day
                    invested = sum(t.capital_used for t in open_trades)
                    mtm_pnl = 0.0
                    for t in open_trades:
                        row = stock_data.get(t.symbol, {}).get(day)
                        if row is not None:
                            mtm_pnl += (row["close"] - t.entry_price) / t.entry_price * t.capital_used
                    equity_curve.append(EquityPoint(
                        date=str(day.date()) if hasattr(day, 'date') else str(day)[:10],
                        equity=round(cash + invested + mtm_pnl, 0),
                        cash=round(cash, 0), invested=round(invested, 0),
                        open_positions=len(open_trades), trade_event="regime:bear",
                    ))
                    continue

            # Month filter
            day_month = day.month if hasattr(day, 'month') else pd.to_datetime(day).month
            if avoid_months_set and day_month in avoid_months_set:
                invested = sum(t.capital_used for t in open_trades)
                mtm_pnl = 0.0
                for t in open_trades:
                    row = stock_data.get(t.symbol, {}).get(day)
                    if row is not None:
                        mtm_pnl += (row["close"] - t.entry_price) / t.entry_price * t.capital_used
                equity_curve.append(EquityPoint(
                    date=str(day.date()) if hasattr(day, 'date') else str(day)[:10],
                    equity=round(cash + invested + mtm_pnl, 0),
                    cash=round(cash, 0), invested=round(invested, 0),
                    open_positions=len(open_trades), trade_event="month:skip",
                ))
                continue

            candidates = []
            for sym, data_map in stock_data.items():
                row = data_map.get(day)
                if row is None:
                    continue
                if pd.isna(row.get("high_52w")) or row.get("breakout", 0) != 1:
                    continue
                if sym in [t.symbol for t in open_trades]:
                    continue
                if sym in cooldowns and day < cooldowns[sym]:
                    continue
                if cfg.min_rsi > 0 and (pd.isna(row.get("rsi_14")) or row["rsi_14"] < cfg.min_rsi):
                    continue

                # Volume filter
                if cfg.min_volume_ratio > 0:
                    vol = row.get("volume", 0)
                    vol_ma = row.get("vol_ma20", 0)
                    if pd.isna(vol_ma) or vol_ma <= 0:
                        continue
                    if vol / vol_ma < cfg.min_volume_ratio:
                        continue

                # Max distance above 52w high filter (reject over-extended breakouts)
                if cfg.max_dist_above_52w > 0:
                    dist = row.get("dist_above_52w", 0)
                    if not pd.isna(dist) and dist > cfg.max_dist_above_52w:
                        continue

                candidates.append((sym, row))

            # Sort by distance above 52w high (prefer fresh breakouts)
            candidates.sort(key=lambda x: x[1].get("dist_above_52w", 0))

            for sym, row in candidates:
                if len(open_trades) >= cfg.max_open_positions:
                    break

                sector = SECTORS.get(sym, "Other")
                sector_count = sum(1 for t in open_trades if t.sector == sector)
                if sector_count >= cfg.max_per_sector:
                    continue

                entry_price = row["close"]
                sl_price = entry_price * (1 - cfg.sl_pct)
                risk_per_share = entry_price - sl_price

                # Position sizing: risk cfg.risk_per_trade_pct of current equity
                current_equity = cash + sum(t.capital_used for t in open_trades)
                risk_amount = current_equity * cfg.risk_per_trade_pct
                qty = max(1, int(risk_amount / risk_per_share))
                capital_needed = qty * entry_price

                if capital_needed > cash:
                    qty = max(1, int(cash / entry_price))
                    capital_needed = qty * entry_price
                if capital_needed > cash or qty < 1:
                    continue

                t1_price = entry_price + risk_per_share * cfg.rr_t1
                t2_price = entry_price + risk_per_share * cfg.rr_t2

                trade = Trade(
                    symbol=sym, sector=sector,
                    entry_date=str(day.date()) if hasattr(day, 'date') else str(day)[:10],
                    entry_price=entry_price,
                    sl_price=sl_price, t1_price=t1_price, t2_price=t2_price,
                    sl_pct=cfg.sl_pct, rr_t1=cfg.rr_t1, rr_t2=cfg.rr_t2,
                    qty=qty, capital_used=capital_needed,
                    dist_above_52w=float(row.get("dist_above_52w", 0)),
                    atr_pct=float(row.get("atr_pct", 0)),
                    rsi_14=float(row.get("rsi_14", 0)),
                )
                open_trades.append(trade)
                trades.append(trade)
                cash -= capital_needed
                event_msgs.append(f"entry {sym}")

        # --- 3) Record equity ---
        invested = sum(t.capital_used for t in open_trades)
        # Mark to market: approximate using entry capital (exact MTM needs current price)
        mtm_pnl = 0.0
        for t in open_trades:
            row = stock_data.get(t.symbol, {}).get(day)
            if row is not None:
                mtm_pnl += (row["close"] - t.entry_price) / t.entry_price * t.capital_used

        equity = cash + invested + mtm_pnl

        equity_curve.append(EquityPoint(
            date=str(day.date()) if hasattr(day, 'date') else str(day)[:10],
            equity=round(equity, 0),
            cash=round(cash, 0),
            invested=round(invested, 0),
            open_positions=len(open_trades),
            trade_event="; ".join(event_msgs) if event_msgs else "",
        ))

    # Close any remaining open trades at last price
    for t in open_trades:
        last_row = stock_data.get(t.symbol, {})
        if not last_row:
            continue
        last_date = max(last_row.keys())
        row = last_row[last_date]
        t.exit_date = str(last_date.date()) if hasattr(last_date, 'date') else str(last_date)[:10]
        t.exit_price = row["close"]
        t.exit_reason = "open"
        t.holding_days = (last_date - pd.to_datetime(t.entry_date)).days
        t.pnl_pct = (row["close"] - t.entry_price) / t.entry_price
        t.pnl_abs = t.pnl_pct * t.capital_used

    return trades, equity_curve


# ---------------------------------------------------------------------------
# Stats computation
# ---------------------------------------------------------------------------

def compute_stats(
    trades: list[Trade],
    equity_curve: list[EquityPoint],
    cfg: BacktestConfig,
) -> dict:
    if not trades:
        return {"total_trades": 0, "config": cfg.to_dict()}

    pnls = [t.pnl_pct for t in trades]
    abs_pnls = [t.pnl_abs for t in trades]
    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]

    reasons = {}
    for t in trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1

    # Equity curve stats
    equities = [e.equity for e in equity_curve if e.equity > 0]
    peak = equities[0] if equities else cfg.initial_capital
    max_dd = 0.0
    for e in equities:
        peak = max(peak, e)
        dd = (e - peak) / peak
        max_dd = min(max_dd, dd)

    final_equity = equities[-1] if equities else cfg.initial_capital
    total_return = (final_equity - cfg.initial_capital) / cfg.initial_capital

    if len(equity_curve) >= 2:
        days = (pd.to_datetime(equity_curve[-1].date) - pd.to_datetime(equity_curve[0].date)).days
        n_years = max(days / 365.25, 0.5)
    else:
        n_years = 1
    cagr = (final_equity / cfg.initial_capital) ** (1 / n_years) - 1

    # Max consecutive losses
    max_consec = 0
    curr = 0
    for p in pnls:
        if p <= 0:
            curr += 1
            max_consec = max(max_consec, curr)
        else:
            curr = 0

    # By sector
    by_sector: dict[str, dict] = {}
    for t in trades:
        s = by_sector.setdefault(t.sector, {"trades": 0, "wins": 0, "pnl": 0.0})
        s["trades"] += 1
        if t.pnl_pct > 0:
            s["wins"] += 1
        s["pnl"] += t.pnl_abs

    # By year
    by_year: dict[str, dict] = {}
    for t in trades:
        yr = t.entry_date[:4]
        y = by_year.setdefault(yr, {"trades": 0, "wins": 0, "pnl": 0.0})
        y["trades"] += 1
        if t.pnl_pct > 0:
            y["wins"] += 1
        y["pnl"] += t.pnl_abs

    # Per stock
    by_stock: dict[str, dict] = {}
    for t in trades:
        s = by_stock.setdefault(t.symbol, {"trades": 0, "wins": 0, "pnl": 0.0, "sector": t.sector})
        s["trades"] += 1
        if t.pnl_pct > 0:
            s["wins"] += 1
        s["pnl"] += t.pnl_abs

    win_pnls = [t.pnl_pct for t in wins]
    loss_pnls = [t.pnl_pct for t in losses]

    return {
        "config": cfg.to_dict(),
        "total_trades": len(trades),
        "stocks_traded": len(set(t.symbol for t in trades)),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "avg_win_pct": round(np.mean(win_pnls) * 100, 2) if win_pnls else 0,
        "avg_loss_pct": round(np.mean(loss_pnls) * 100, 2) if loss_pnls else 0,
        "best_trade_pct": round(max(pnls) * 100, 2),
        "worst_trade_pct": round(min(pnls) * 100, 2),
        "avg_pnl_pct": round(np.mean(pnls) * 100, 2),
        "profit_factor": round(abs(sum(win_pnls) / sum(loss_pnls)), 2) if loss_pnls else 999,
        "t1_hit_rate": round(sum(1 for t in trades if t.t1_hit) / len(trades) * 100, 1),
        "t2_hit_rate": round(sum(1 for t in trades if t.t2_hit) / len(trades) * 100, 1),
        "initial_capital": cfg.initial_capital,
        "final_equity": round(final_equity, 0),
        "total_return_pct": round(total_return * 100, 1),
        "cagr_pct": round(cagr * 100, 1),
        "max_drawdown_pct": round(max_dd * 100, 1),
        "max_consec_losses": max_consec,
        "avg_holding_days": round(np.mean([t.holding_days for t in trades]), 1),
        "total_pnl_abs": round(sum(abs_pnls), 0),
        "n_years": round(n_years, 1),
        "exit_reasons": reasons,
        "by_sector": {k: {**v, "pnl": round(v["pnl"], 0)} for k, v in sorted(by_sector.items(), key=lambda x: -x[1]["pnl"])},
        "by_year": {k: {**v, "pnl": round(v["pnl"], 0)} for k, v in sorted(by_year.items())},
        "by_stock": {k: {**v, "pnl": round(v["pnl"], 0)} for k, v in sorted(by_stock.items(), key=lambda x: -x[1]["pnl"])[:20]},
    }


# ---------------------------------------------------------------------------
# Main (standalone)
# ---------------------------------------------------------------------------

def main():
    print("Loading stocks...")
    stocks = load_all_stocks()
    print(f"Loaded {len(stocks)} stocks\n")

    cfg = BacktestConfig(
        initial_capital=500000,
        risk_per_trade_pct=0.02,
        sl_pct=0.05,
        rr_t1=2.0,
        rr_t2=3.0,
        max_hold_days=60,
        max_open_positions=5,
        max_per_sector=2,
    )

    print(f"Running portfolio backtest: {json.dumps(cfg.to_dict(), indent=2)}\n")
    trades, equity_curve = run_portfolio_backtest(stocks, cfg)
    stats = compute_stats(trades, equity_curve, cfg)

    print(f"Trades: {stats['total_trades']}")
    print(f"Win rate: {stats['win_rate']}%")
    print(f"Profit factor: {stats['profit_factor']}")
    print(f"Total P&L: ₹{stats['total_pnl_abs']:,.0f}")
    print(f"Final equity: ₹{stats['final_equity']:,.0f}")
    print(f"CAGR: {stats['cagr_pct']}%")
    print(f"Max drawdown: {stats['max_drawdown_pct']}%")

    print(f"\nYear-by-year:")
    for yr, y in stats["by_year"].items():
        wr = round(y["wins"] / y["trades"] * 100) if y["trades"] else 0
        print(f"  {yr}: {y['trades']} trades, {wr}% win rate, ₹{y['pnl']:+,.0f}")

    print(f"\nTop sectors:")
    for sec, s in list(stats["by_sector"].items())[:8]:
        wr = round(s["wins"] / s["trades"] * 100) if s["trades"] else 0
        print(f"  {sec:15s}: {s['trades']} trades, {wr}% win rate, ₹{s['pnl']:+,.0f}")

    # Current breakout scanner
    print(f"\n--- Current 52-week breakout candidates ---")
    signals = scan_breakouts(stocks)
    if signals:
        for s in signals[:10]:
            print(f"  {s.symbol:15s} ₹{s.close:>10,.2f}  +{s.dist_above_52w*100:.1f}% above 52w  "
                  f"RSI={s.rsi_14:.0f}  ATR={s.atr_pct*100:.1f}%  [{s.sector}]")
    else:
        print("  No breakouts today")


if __name__ == "__main__":
    main()
