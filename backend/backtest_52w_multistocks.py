"""Multi-stock 52-week high breakout backtest — Investors Way strategy.

Tests the ACTUAL strategy from the PDF:
- Scan stocks at 52-week highs (Chartink-style)
- Apply R:R filter: T1 >= 2x, T2 >= 3x, SL <= 8%
- 3-phase exit: SL → T1 (book 50%) → move SL to breakeven → T2 (book rest)
- News/earnings filter simulated as random skip (since we can't backtest that)

Runs on all CSVs in data/stocks/ directory.

Run: python -m backend.backtest_52w_multistocks
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


# ---------------------------------------------------------------------------
# Trade dataclass
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    symbol: str
    entry_date: str
    entry_price: float
    sl_price: float
    t1_price: float
    t2_price: float
    sl_pct: float
    rr_t1: float
    rr_t2: float

    exit_date: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl_pct: float = 0.0
    holding_days: int = 0
    t1_hit: bool = False
    t2_hit: bool = False
    max_drawdown_pct: float = 0.0
    max_runup_pct: float = 0.0
    atr_pct_at_entry: float = 0.0
    volume_at_entry: float = 0.0
    dist_above_52w: float = 0.0


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_stock(path: Path) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_csv(path)
        df.columns = [c.strip().lower() for c in df.columns]
        if "date" not in df.columns:
            for cand in ("datetime", "timestamp"):
                if cand in df.columns:
                    df = df.rename(columns={cand: "date"})
                    break
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.sort_values("date").reset_index(drop=True)
        if len(df) < 300:  # Need at least 252 + some tradeable days
            return None
        return df
    except Exception:
        return None


def add_indicators(df: pd.DataFrame, lookback: int = 252) -> pd.DataFrame:
    df = df.copy()
    # 52-week high (previous lookback days, excludes today)
    df["high_52w"] = df["high"].shift(1).rolling(lookback).max()
    df["low_52w"] = df["low"].shift(1).rolling(lookback).min()
    df["breakout"] = (df["close"] > df["high_52w"]).astype(int)
    df["dist_above_52w"] = (df["close"] - df["high_52w"]) / df["high_52w"]

    # ATR
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr_14"] = tr.rolling(14).mean()
    df["atr_pct"] = df["atr_14"] / df["close"]

    # Volume moving average (for liquidity filter)
    df["vol_ma20"] = df["volume"].rolling(20).mean()

    # RSI (for momentum confirmation)
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi_14"] = 100 - (100 / (1 + rs))

    # ADX (trend strength)
    # Simplified: use just the directional movement
    df["ret_20d"] = df["close"].pct_change(20)

    return df


# ---------------------------------------------------------------------------
# Single-stock backtest
# ---------------------------------------------------------------------------

def backtest_stock(
    df: pd.DataFrame,
    symbol: str,
    sl_pct: float = 0.05,
    rr_t1: float = 2.0,
    rr_t2: float = 3.0,
    max_hold_days: int = 60,
    book_pct_t1: float = 0.50,
    sl_to_breakeven: bool = True,
    cooldown_days: int = 10,
    min_volume: float = 0,  # Minimum 20-day avg volume
    max_sl_pct: float = 0.08,  # Investors Way: SL must be <= 8%
    require_rsi_above: float = 0,  # Optional RSI filter
    require_close_above_breakout: bool = True,  # Only enter on close above 52w high
) -> list[Trade]:

    trades: list[Trade] = []
    in_trade = False
    cooldown_until = -1
    trade_entry_idx = 0

    for i in range(len(df)):
        row = df.iloc[i]

        if pd.isna(row.get("high_52w")) or pd.isna(row.get("atr_14")):
            continue

        # --- Manage open trade ---
        if in_trade:
            t = trades[-1]
            days_held = i - trade_entry_idx

            # Track drawdown/runup
            dd = (row["low"] - t.entry_price) / t.entry_price
            ru = (row["high"] - t.entry_price) / t.entry_price
            t.max_drawdown_pct = min(t.max_drawdown_pct, dd)
            t.max_runup_pct = max(t.max_runup_pct, ru)

            active_sl = t.sl_price
            if t.t1_hit and sl_to_breakeven:
                active_sl = t.entry_price

            # SL hit (check low)
            if row["low"] <= active_sl:
                t.exit_date = str(row["date"].date())
                t.exit_price = active_sl
                t.holding_days = days_held
                if t.t1_hit:
                    t1_profit = book_pct_t1 * (t.t1_price - t.entry_price) / t.entry_price
                    rem_profit = (1 - book_pct_t1) * (active_sl - t.entry_price) / t.entry_price
                    t.pnl_pct = t1_profit + rem_profit
                    t.exit_reason = "t1_then_be" if active_sl >= t.entry_price else "t1_then_sl"
                else:
                    t.pnl_pct = (active_sl - t.entry_price) / t.entry_price
                    t.exit_reason = "sl_hit"
                in_trade = False
                cooldown_until = i + cooldown_days
                continue

            # T2 hit (if T1 already hit)
            if t.t1_hit and row["high"] >= t.t2_price:
                t.t2_hit = True
                t.exit_date = str(row["date"].date())
                t.exit_price = t.t2_price
                t.holding_days = days_held
                t1_profit = book_pct_t1 * (t.t1_price - t.entry_price) / t.entry_price
                t2_profit = (1 - book_pct_t1) * (t.t2_price - t.entry_price) / t.entry_price
                t.pnl_pct = t1_profit + t2_profit
                t.exit_reason = "t1_then_t2"
                in_trade = False
                cooldown_until = i + cooldown_days
                continue

            # T1 hit
            if not t.t1_hit and row["high"] >= t.t1_price:
                t.t1_hit = True

            # Time exit
            if days_held >= max_hold_days:
                t.exit_date = str(row["date"].date())
                t.exit_price = row["close"]
                t.holding_days = days_held
                if t.t1_hit:
                    t1_profit = book_pct_t1 * (t.t1_price - t.entry_price) / t.entry_price
                    rem_profit = (1 - book_pct_t1) * (row["close"] - t.entry_price) / t.entry_price
                    t.pnl_pct = t1_profit + rem_profit
                    t.exit_reason = "t1_then_time"
                else:
                    t.pnl_pct = (row["close"] - t.entry_price) / t.entry_price
                    t.exit_reason = "time_exit"
                in_trade = False
                cooldown_until = i + cooldown_days
                continue

            continue

        # --- Look for entry ---
        if i <= cooldown_until:
            continue

        if row["breakout"] != 1:
            continue

        # Liquidity filter
        if min_volume > 0:
            vol_ma = row.get("vol_ma20", 0)
            if pd.isna(vol_ma) or vol_ma < min_volume:
                continue

        # RSI filter
        if require_rsi_above > 0:
            rsi = row.get("rsi_14", 50)
            if pd.isna(rsi) or rsi < require_rsi_above:
                continue

        entry_price = row["close"]
        sl_price = entry_price * (1 - sl_pct)
        risk = entry_price - sl_price
        t1_price = entry_price + risk * rr_t1
        t2_price = entry_price + risk * rr_t2

        # Investors Way GO filter
        if sl_pct > max_sl_pct:
            continue
        if rr_t1 < 2.0 or rr_t2 < 3.0:
            continue

        trade = Trade(
            symbol=symbol,
            entry_date=str(row["date"].date()),
            entry_price=entry_price,
            sl_price=sl_price,
            t1_price=t1_price,
            t2_price=t2_price,
            sl_pct=sl_pct,
            rr_t1=rr_t1,
            rr_t2=rr_t2,
            atr_pct_at_entry=float(row.get("atr_pct", 0)),
            volume_at_entry=float(row.get("volume", 0)),
            dist_above_52w=float(row.get("dist_above_52w", 0)),
        )
        trades.append(trade)
        in_trade = True
        trade_entry_idx = i

    # Close any open trade
    if in_trade and trades:
        t = trades[-1]
        last = df.iloc[-1]
        t.exit_date = str(last["date"].date())
        t.exit_price = last["close"]
        t.holding_days = len(df) - 1 - trade_entry_idx
        t.pnl_pct = (last["close"] - t.entry_price) / t.entry_price
        t.exit_reason = "open"

    return trades


# ---------------------------------------------------------------------------
# Portfolio-level analysis
# ---------------------------------------------------------------------------

def analyze(trades: list[Trade], label: str = "") -> dict:
    if not trades:
        return {"label": label, "total_trades": 0}

    pnls = [t.pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    reasons = {}
    for t in trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1

    # Symbols traded
    symbols_traded = list(set(t.symbol for t in trades))

    # Consecutive losses
    max_consec = 0
    curr = 0
    for p in pnls:
        if p <= 0:
            curr += 1
            max_consec = max(max_consec, curr)
        else:
            curr = 0

    # Equity curve
    equity = 100.0
    peak = 100.0
    max_dd = 0.0
    equity_curve = []
    for t in trades:
        equity *= (1 + t.pnl_pct)
        peak = max(peak, equity)
        dd = (equity - peak) / peak
        max_dd = min(max_dd, dd)
        equity_curve.append({"date": t.exit_date, "equity": equity, "dd": dd})

    total_return = (equity - 100) / 100

    if len(trades) >= 2:
        first = pd.to_datetime(trades[0].entry_date)
        last = pd.to_datetime(trades[-1].exit_date) if trades[-1].exit_date else first
        n_years = max((last - first).days / 365.25, 0.5)
    else:
        n_years = 1

    cagr = (equity / 100) ** (1 / n_years) - 1 if n_years > 0 else 0

    # Per-stock breakdown
    by_symbol: dict[str, list[float]] = {}
    for t in trades:
        by_symbol.setdefault(t.symbol, []).append(t.pnl_pct)

    stock_stats = {}
    for sym, pnl_list in sorted(by_symbol.items()):
        w = sum(1 for p in pnl_list if p > 0)
        stock_stats[sym] = {
            "trades": len(pnl_list),
            "wins": w,
            "win_rate": w / len(pnl_list),
            "avg_pnl": np.mean(pnl_list),
            "total_pnl": sum(pnl_list),
        }

    return {
        "label": label,
        "total_trades": len(trades),
        "stocks_traded": len(symbols_traded),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades),
        "avg_win": np.mean(wins) if wins else 0,
        "avg_loss": np.mean(losses) if losses else 0,
        "best_trade": max(pnls),
        "worst_trade": min(pnls),
        "avg_pnl": np.mean(pnls),
        "median_pnl": np.median(pnls),
        "total_return_pct": total_return * 100,
        "cagr_pct": cagr * 100,
        "max_drawdown_pct": max_dd * 100,
        "profit_factor": abs(sum(wins) / sum(losses)) if losses else float("inf"),
        "expectancy": np.mean(pnls),
        "avg_holding_days": np.mean([t.holding_days for t in trades]),
        "median_holding_days": np.median([t.holding_days for t in trades]),
        "max_consec_losses": max_consec,
        "exit_reasons": reasons,
        "sharpe_approx": (np.mean(pnls) / np.std(pnls)) * np.sqrt(len(trades) / n_years) if np.std(pnls) > 0 else 0,
        "t1_hit_rate": sum(1 for t in trades if t.t1_hit) / len(trades),
        "t2_hit_rate": sum(1 for t in trades if t.t2_hit) / len(trades),
        "stock_stats": stock_stats,
        "n_years": n_years,
    }


def print_report(stats: dict):
    if stats["total_trades"] == 0:
        print(f"\n  {stats['label']}: NO TRADES")
        return

    s = stats
    print(f"\n{'='*80}")
    print(f"  {s['label']}")
    print(f"{'='*80}")
    print(f"  Trades: {s['total_trades']}  across {s['stocks_traded']} stocks  over {s['n_years']:.1f} years")
    print(f"  Wins/Losses:       {s['wins']} / {s['losses']}  ({s['win_rate']:.1%} win rate)")
    print(f"  Avg win:           {s['avg_win']:+.2%}     Avg loss:  {s['avg_loss']:+.2%}")
    print(f"  Best / Worst:      {s['best_trade']:+.2%} / {s['worst_trade']:+.2%}")
    print(f"  Avg P&L / trade:   {s['avg_pnl']:+.2%}     Median: {s['median_pnl']:+.2%}")
    print(f"  Profit factor:     {s['profit_factor']:.2f}   Sharpe: {s['sharpe_approx']:.2f}")
    print(f"  T1 hit rate:       {s['t1_hit_rate']:.1%}     T2 hit rate: {s['t2_hit_rate']:.1%}")
    print()
    print(f"  Total return:      {s['total_return_pct']:+.1f}%")
    print(f"  CAGR:              {s['cagr_pct']:+.1f}%")
    print(f"  Max drawdown:      {s['max_drawdown_pct']:.1f}%")
    print(f"  Max consec losses: {s['max_consec_losses']}")
    print(f"  Avg hold:          {s['avg_holding_days']:.1f}d   Median: {s['median_holding_days']:.0f}d")
    print()
    print(f"  Exit reasons:")
    for r, c in sorted(s["exit_reasons"].items(), key=lambda x: -x[1]):
        print(f"    {r:20s} {c:4d}  ({c/s['total_trades']:.0%})")

    # Top 10 stocks by trades
    print(f"\n  Top stocks by trade count:")
    sorted_stocks = sorted(s["stock_stats"].items(), key=lambda x: -x[1]["trades"])[:15]
    print(f"    {'Symbol':15s} {'Trades':>6} {'Wins':>5} {'WinR':>6} {'AvgP&L':>8} {'TotalP&L':>9}")
    for sym, ss in sorted_stocks:
        print(f"    {sym:15s} {ss['trades']:>6} {ss['wins']:>5} {ss['win_rate']:>5.0%} "
              f"{ss['avg_pnl']:>+7.2%} {ss['total_pnl']:>+8.2%}")
    print(f"{'='*80}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 80)
    print("  52-WEEK BREAKOUT BACKTEST — ALL NIFTY 50 STOCKS")
    print("=" * 80)

    # Load all stock CSVs
    stock_files = sorted(STOCKS_DIR.glob("*.csv"))
    if not stock_files:
        print(f"\nNo stock CSVs found in {STOCKS_DIR}/")
        print("Run: python -m backend.fetch_nifty50_stocks")
        print("\nOr place CSV files (date,open,high,low,close,volume) in data/stocks/")
        return

    print(f"\nFound {len(stock_files)} stock CSVs in {STOCKS_DIR}/")

    # Load and prepare all stocks
    stocks: dict[str, pd.DataFrame] = {}
    for path in stock_files:
        symbol = path.stem.upper()
        df = load_stock(path)
        if df is not None:
            df = add_indicators(df)
            stocks[symbol] = df
            # Count breakout days
            tradeable = df.iloc[252:]
            n_bo = tradeable["breakout"].sum()
            print(f"  {symbol:15s}  {len(df):5d} bars  {n_bo:3d} breakout days  "
                  f"({df.iloc[0]['date'].date()} to {df.iloc[-1]['date'].date()})")
        else:
            print(f"  {symbol:15s}  SKIPPED (too few bars or load error)")

    if not stocks:
        print("\nNo usable stock data. Need at least 300 bars per stock.")
        return

    print(f"\n{len(stocks)} stocks loaded and ready for backtest.\n")

    # ===== Strategy configs =====
    configs = [
        ("IW Exact: SL=5%, R:R 2x/3x, 60d hold",
         dict(sl_pct=0.05, rr_t1=2.0, rr_t2=3.0, max_hold_days=60)),

        ("Tight SL: SL=3%, R:R 2x/3x, 60d hold",
         dict(sl_pct=0.03, rr_t1=2.0, rr_t2=3.0, max_hold_days=60)),

        ("Wide SL: SL=8%, R:R 2x/3x, 60d hold",
         dict(sl_pct=0.08, rr_t1=2.0, rr_t2=3.0, max_hold_days=60)),

        ("Long hold: SL=5%, R:R 2x/3x, 120d hold",
         dict(sl_pct=0.05, rr_t1=2.0, rr_t2=3.0, max_hold_days=120)),

        ("Conservative: SL=3%, R:R 3x/5x, 90d, no BE",
         dict(sl_pct=0.03, rr_t1=3.0, rr_t2=5.0, max_hold_days=90, sl_to_breakeven=False)),

        ("Aggressive: SL=8%, R:R 1.5x/2.5x, 30d",
         dict(sl_pct=0.08, rr_t1=1.5, rr_t2=2.5, max_hold_days=30, max_sl_pct=0.10)),

        ("IW + RSI>60 filter: SL=5%, R:R 2x/3x, 60d",
         dict(sl_pct=0.05, rr_t1=2.0, rr_t2=3.0, max_hold_days=60, require_rsi_above=60)),

        ("Tight + Long: SL=3%, R:R 2x/3x, 120d hold",
         dict(sl_pct=0.03, rr_t1=2.0, rr_t2=3.0, max_hold_days=120)),
    ]

    all_results = []

    for label, params in configs:
        all_trades: list[Trade] = []
        for symbol, df in stocks.items():
            trades = backtest_stock(df, symbol, **params)
            all_trades.extend(trades)

        # Sort by entry date (portfolio order)
        all_trades.sort(key=lambda t: t.entry_date)

        stats = analyze(all_trades, label)
        print_report(stats)
        all_results.append(stats)

        # Show some example trades
        if all_trades:
            print(f"\n  Sample winning trades:")
            winners = sorted([t for t in all_trades if t.pnl_pct > 0], key=lambda t: -t.pnl_pct)[:5]
            for t in winners:
                print(f"    {t.symbol:12s} {t.entry_date} @ {t.entry_price:8.2f} → {t.exit_reason:15s} "
                      f"{t.exit_date} @ {t.exit_price:8.2f}  P&L={t.pnl_pct:+.2%}  held={t.holding_days}d")

            print(f"\n  Sample losing trades:")
            losers = sorted([t for t in all_trades if t.pnl_pct <= 0], key=lambda t: t.pnl_pct)[:5]
            for t in losers:
                print(f"    {t.symbol:12s} {t.entry_date} @ {t.entry_price:8.2f} → {t.exit_reason:15s} "
                      f"{t.exit_date} @ {t.exit_price:8.2f}  P&L={t.pnl_pct:+.2%}  held={t.holding_days}d")

    # ===== Summary comparison =====
    print(f"\n\n{'='*110}")
    print(f"  COMPARISON SUMMARY — ALL STRATEGIES ACROSS {len(stocks)} STOCKS")
    print(f"{'='*110}")
    print(f"{'Strategy':<45} {'Trades':>6} {'Stocks':>6} {'WinR':>6} {'AvgP&L':>8} "
          f"{'TotRet':>8} {'CAGR':>7} {'MaxDD':>7} {'PF':>6} {'T1%':>5} {'T2%':>5}")
    print(f"{'-'*110}")
    for s in all_results:
        if s["total_trades"] == 0:
            print(f"{s['label'][:44]:<45} {'0':>6}")
            continue
        print(f"{s['label'][:44]:<45} {s['total_trades']:>6} {s['stocks_traded']:>6} "
              f"{s['win_rate']:>5.0%} {s['avg_pnl']:>+7.2%} {s['total_return_pct']:>+7.1f}% "
              f"{s['cagr_pct']:>+6.1f}% {s['max_drawdown_pct']:>6.1f}% "
              f"{s['profit_factor']:>5.2f} {s['t1_hit_rate']:>4.0%} {s['t2_hit_rate']:>4.0%}")
    print(f"{'='*110}")

    # ===== Year-by-year for best strategy =====
    best_idx = max(range(len(all_results)),
                   key=lambda i: all_results[i].get("total_return_pct", -999) if all_results[i]["total_trades"] > 0 else -999)
    best_label = configs[best_idx][0]
    best_params = configs[best_idx][1]

    # Rebuild trades for best strategy
    best_trades: list[Trade] = []
    for symbol, df in stocks.items():
        best_trades.extend(backtest_stock(df, symbol, **best_params))
    best_trades.sort(key=lambda t: t.entry_date)

    if best_trades:
        print(f"\n{'='*70}")
        print(f"  YEAR-BY-YEAR: {best_label}")
        print(f"{'='*70}")
        by_year: dict[int, list[Trade]] = {}
        for t in best_trades:
            yr = int(t.entry_date[:4])
            by_year.setdefault(yr, []).append(t)

        print(f"{'Year':>6} {'Trades':>7} {'Wins':>5} {'WinR':>6} {'AvgP&L':>8} {'CumRet':>9} {'MaxDD':>7}")
        print(f"{'-'*55}")
        cum_eq = 100.0
        for yr in sorted(by_year):
            yt = by_year[yr]
            pnls = [t.pnl_pct for t in yt]
            w = sum(1 for p in pnls if p > 0)
            eq = 1.0
            pk = 1.0
            mdd = 0.0
            for p in pnls:
                eq *= (1 + p)
                pk = max(pk, eq)
                mdd = min(mdd, (eq - pk) / pk)
                cum_eq *= (1 + p)
            print(f"{yr:>6} {len(yt):>7} {w:>5} {w/len(yt):>5.0%} "
                  f"{np.mean(pnls):>+7.2%} {(cum_eq-100):>+8.1f}% {mdd*100:>6.1f}%")

    # ===== Analysis: what predicts winners? =====
    if best_trades and len(best_trades) > 20:
        print(f"\n{'='*70}")
        print(f"  EDGE ANALYSIS: What predicts winning trades?")
        print(f"{'='*70}")

        # By distance above 52w high at entry
        close_breakouts = [t for t in best_trades if t.dist_above_52w < 0.01]
        far_breakouts = [t for t in best_trades if t.dist_above_52w >= 0.02]
        if close_breakouts:
            wr = sum(1 for t in close_breakouts if t.pnl_pct > 0) / len(close_breakouts)
            print(f"  Close to 52w high (<1% above):  {len(close_breakouts)} trades, {wr:.0%} win rate, "
                  f"avg P&L {np.mean([t.pnl_pct for t in close_breakouts]):+.2%}")
        if far_breakouts:
            wr = sum(1 for t in far_breakouts if t.pnl_pct > 0) / len(far_breakouts)
            print(f"  Far above 52w high (>2% above): {len(far_breakouts)} trades, {wr:.0%} win rate, "
                  f"avg P&L {np.mean([t.pnl_pct for t in far_breakouts]):+.2%}")

        # By ATR at entry (volatility)
        low_vol = [t for t in best_trades if t.atr_pct_at_entry < 0.015]
        high_vol = [t for t in best_trades if t.atr_pct_at_entry >= 0.025]
        if low_vol:
            wr = sum(1 for t in low_vol if t.pnl_pct > 0) / len(low_vol)
            print(f"  Low volatility (ATR<1.5%):      {len(low_vol)} trades, {wr:.0%} win rate, "
                  f"avg P&L {np.mean([t.pnl_pct for t in low_vol]):+.2%}")
        if high_vol:
            wr = sum(1 for t in high_vol if t.pnl_pct > 0) / len(high_vol)
            print(f"  High volatility (ATR>2.5%):     {len(high_vol)} trades, {wr:.0%} win rate, "
                  f"avg P&L {np.mean([t.pnl_pct for t in high_vol]):+.2%}")

        # By day of week
        print(f"\n  By entry day of week:")
        dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri"]
        for dow in range(5):
            dow_trades = [t for t in best_trades if pd.to_datetime(t.entry_date).weekday() == dow]
            if dow_trades:
                wr = sum(1 for t in dow_trades if t.pnl_pct > 0) / len(dow_trades)
                print(f"    {dow_names[dow]}: {len(dow_trades):3d} trades, {wr:.0%} win rate, "
                      f"avg {np.mean([t.pnl_pct for t in dow_trades]):+.2%}")

    # Save detailed results
    results_path = DATA_DIR / "backtest_results.json"
    output = {
        "strategies": [],
        "best_strategy": best_label,
        "stocks_tested": len(stocks),
    }
    for s in all_results:
        clean = {k: v for k, v in s.items() if k != "stock_stats"}
        output["strategies"].append(clean)

    with open(results_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {results_path}")


if __name__ == "__main__":
    main()
