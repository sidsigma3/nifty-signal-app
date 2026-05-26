"""Backtest: 52-week high breakout strategy on Nifty 50.

Implements the Investors Way strategy logic:
- Entry: when close breaks above 52-week (252 trading day) high
- Stop Loss: X% below entry (test 3%, 5%, 8%)
- Target 1: R:R >= 2x (book 50%)
- Target 2: R:R >= 3x (book remaining 50%)
- After T1 hit: move SL to breakeven

Also tests:
- Simple breakout (buy & hold N days)
- Breakout + ATR-based SL/target
- Various holding periods
- Drawdown analysis
- Comparison vs buy-and-hold

Run: python -m backend.backtest_52w_breakout
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_nifty_daily() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "nifty50_daily.csv")
    df.columns = [c.strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.sort_values("date").reset_index(drop=True)
    return df


def load_vix_daily() -> Optional[pd.DataFrame]:
    p = DATA_DIR / "india_vix_daily.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df.columns = [c.strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.sort_values("date").reset_index(drop=True)
    df = df.rename(columns={"close": "vix_close"})
    return df[["date", "vix_close"]]


# ---------------------------------------------------------------------------
# 52-week high detection
# ---------------------------------------------------------------------------

def add_52w_high(df: pd.DataFrame, lookback: int = 252) -> pd.DataFrame:
    """Add rolling 52-week (252 trading day) high and breakout flag."""
    df = df.copy()
    # Rolling high of the PREVIOUS lookback days (excludes today)
    df["high_52w"] = df["high"].shift(1).rolling(lookback).max()
    # Breakout: today's close exceeds the previous 52-week high
    df["breakout"] = (df["close"] > df["high_52w"]).astype(int)
    # Distance from 52w high (how far above/below)
    df["dist_from_52w"] = (df["close"] - df["high_52w"]) / df["high_52w"]
    # ATR for dynamic SL/target
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr_14"] = tr.rolling(14).mean()
    df["atr_pct"] = df["atr_14"] / df["close"]
    return df


# ---------------------------------------------------------------------------
# Trade dataclass
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    entry_date: str
    entry_price: float
    sl_price: float
    t1_price: float
    t2_price: float
    sl_pct: float
    rr_t1: float
    rr_t2: float

    # Outcome
    exit_date: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""  # sl_hit, t1_hit, t2_hit, t1_then_sl, t1_then_t2, time_exit
    pnl_pct: float = 0.0
    holding_days: int = 0
    t1_hit: bool = False
    t2_hit: bool = False
    max_drawdown_pct: float = 0.0
    max_runup_pct: float = 0.0


# ---------------------------------------------------------------------------
# Strategy backtester
# ---------------------------------------------------------------------------

def backtest_breakout(
    df: pd.DataFrame,
    sl_pct: float = 0.05,       # 5% stop loss
    rr_t1: float = 2.0,         # R:R for T1
    rr_t2: float = 3.0,         # R:R for T2
    max_hold_days: int = 60,    # Max holding period
    book_pct_t1: float = 0.50,  # Book 50% at T1
    min_rr_filter: bool = True, # Apply R:R >= 2x/3x filter (Investors Way GO criteria)
    sl_to_breakeven_after_t1: bool = True,
    cooldown_days: int = 5,     # Min days between trades
    use_atr_sl: bool = False,   # Use ATR-based SL instead of fixed %
    atr_sl_mult: float = 2.0,   # ATR multiplier for SL
) -> tuple[list[Trade], pd.DataFrame]:
    """Run the breakout backtest. Returns (trades, daily_equity_curve)."""

    trades: list[Trade] = []
    in_trade = False
    cooldown_until = -1

    for i in range(len(df)):
        row = df.iloc[i]

        if pd.isna(row.get("high_52w")):
            continue

        # --- If in a trade, manage it ---
        if in_trade:
            t = trades[-1]
            current_high = row["high"]
            current_low = row["low"]
            current_close = row["close"]
            days_held = i - trade_entry_idx

            # Track drawdown/runup from entry
            dd = (current_low - t.entry_price) / t.entry_price
            ru = (current_high - t.entry_price) / t.entry_price
            t.max_drawdown_pct = min(t.max_drawdown_pct, dd)
            t.max_runup_pct = max(t.max_runup_pct, ru)

            active_sl = t.sl_price
            if t.t1_hit and sl_to_breakeven_after_t1:
                active_sl = t.entry_price  # SL moved to breakeven

            # Check SL (use low for intraday touch)
            if current_low <= active_sl:
                t.exit_date = str(row["date"].date())
                t.exit_price = active_sl  # Assume fill at SL
                t.holding_days = days_held
                if t.t1_hit:
                    # Already booked 50% at T1, remaining 50% stopped at breakeven
                    t1_profit = book_pct_t1 * (t.t1_price - t.entry_price) / t.entry_price
                    remaining_profit = (1 - book_pct_t1) * (active_sl - t.entry_price) / t.entry_price
                    t.pnl_pct = t1_profit + remaining_profit
                    t.exit_reason = "t1_then_be" if active_sl >= t.entry_price else "t1_then_sl"
                else:
                    t.pnl_pct = (active_sl - t.entry_price) / t.entry_price
                    t.exit_reason = "sl_hit"
                in_trade = False
                cooldown_until = i + cooldown_days
                continue

            # Check T2 (if T1 already hit)
            if t.t1_hit and current_high >= t.t2_price:
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

            # Check T1 (if not yet hit)
            if not t.t1_hit and current_high >= t.t1_price:
                t.t1_hit = True
                # Don't exit yet — continue holding remaining 50% toward T2

            # Time exit
            if days_held >= max_hold_days:
                t.exit_date = str(row["date"].date())
                t.exit_price = current_close
                t.holding_days = days_held
                if t.t1_hit:
                    t1_profit = book_pct_t1 * (t.t1_price - t.entry_price) / t.entry_price
                    remaining_profit = (1 - book_pct_t1) * (current_close - t.entry_price) / t.entry_price
                    t.pnl_pct = t1_profit + remaining_profit
                    t.exit_reason = "t1_then_time"
                else:
                    t.pnl_pct = (current_close - t.entry_price) / t.entry_price
                    t.exit_reason = "time_exit"
                in_trade = False
                cooldown_until = i + cooldown_days
                continue

            continue

        # --- Not in a trade: look for breakout entry ---
        if i <= cooldown_until:
            continue

        if row["breakout"] != 1:
            continue

        entry_price = row["close"]

        # Compute SL
        if use_atr_sl:
            atr = row.get("atr_14", 0)
            if pd.isna(atr) or atr <= 0:
                continue
            actual_sl_pct = (atr * atr_sl_mult) / entry_price
        else:
            actual_sl_pct = sl_pct

        sl_price = entry_price * (1 - actual_sl_pct)
        risk = entry_price - sl_price
        t1_price = entry_price + risk * rr_t1
        t2_price = entry_price + risk * rr_t2

        computed_rr_t1 = rr_t1
        computed_rr_t2 = rr_t2

        # Investors Way GO filter
        if min_rr_filter:
            if computed_rr_t1 < 2.0 or computed_rr_t2 < 3.0 or actual_sl_pct > 0.08:
                continue

        trade = Trade(
            entry_date=str(row["date"].date()),
            entry_price=entry_price,
            sl_price=sl_price,
            t1_price=t1_price,
            t2_price=t2_price,
            sl_pct=actual_sl_pct,
            rr_t1=computed_rr_t1,
            rr_t2=computed_rr_t2,
        )
        trades.append(trade)
        in_trade = True
        trade_entry_idx = i

    # Close any open trade at last bar
    if in_trade and trades:
        t = trades[-1]
        last = df.iloc[-1]
        t.exit_date = str(last["date"].date())
        t.exit_price = last["close"]
        t.holding_days = len(df) - 1 - trade_entry_idx
        t.pnl_pct = (last["close"] - t.entry_price) / t.entry_price
        t.exit_reason = "open"

    return trades, df


# ---------------------------------------------------------------------------
# Analysis & reporting
# ---------------------------------------------------------------------------

def analyze_trades(trades: list[Trade], label: str = "") -> dict:
    if not trades:
        return {"label": label, "total_trades": 0}

    pnls = [t.pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    holding = [t.holding_days for t in trades]

    # Exit reason breakdown
    reasons = {}
    for t in trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1

    # Consecutive losses
    max_consec_loss = 0
    curr_consec = 0
    for p in pnls:
        if p <= 0:
            curr_consec += 1
            max_consec_loss = max(max_consec_loss, curr_consec)
        else:
            curr_consec = 0

    # Equity curve
    equity = 100.0
    peak = 100.0
    max_dd = 0.0
    for p in pnls:
        equity *= (1 + p)
        peak = max(peak, equity)
        dd = (equity - peak) / peak
        max_dd = min(max_dd, dd)

    total_return = (equity - 100) / 100
    n_years = len(trades) / 50 if trades else 1  # rough: ~50 trades/year max
    # Use actual date range for annualization
    if len(trades) >= 2:
        first_date = pd.to_datetime(trades[0].entry_date)
        last_date = pd.to_datetime(trades[-1].exit_date) if trades[-1].exit_date else first_date
        days = (last_date - first_date).days
        n_years = max(days / 365.25, 0.5)

    cagr = (equity / 100) ** (1 / n_years) - 1 if n_years > 0 else 0

    return {
        "label": label,
        "total_trades": len(trades),
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
        "avg_holding_days": np.mean(holding),
        "median_holding_days": np.median(holding),
        "max_consec_losses": max_consec_loss,
        "exit_reasons": reasons,
        "sharpe_approx": (np.mean(pnls) / np.std(pnls)) * np.sqrt(len(trades) / n_years) if np.std(pnls) > 0 else 0,
    }


def print_report(stats: dict):
    if stats["total_trades"] == 0:
        print(f"\n{'='*60}")
        print(f"  {stats['label']}")
        print(f"  NO TRADES generated.")
        print(f"{'='*60}")
        return

    print(f"\n{'='*70}")
    print(f"  {stats['label']}")
    print(f"{'='*70}")
    print(f"  Total trades:       {stats['total_trades']}")
    print(f"  Wins / Losses:      {stats['wins']} / {stats['losses']}")
    print(f"  Win rate:           {stats['win_rate']:.1%}")
    print(f"  Avg win:            {stats['avg_win']:+.2%}")
    print(f"  Avg loss:           {stats['avg_loss']:+.2%}")
    print(f"  Best / Worst:       {stats['best_trade']:+.2%} / {stats['worst_trade']:+.2%}")
    print(f"  Avg P&L per trade:  {stats['avg_pnl']:+.2%}")
    print(f"  Median P&L:         {stats['median_pnl']:+.2%}")
    print(f"  Profit factor:      {stats['profit_factor']:.2f}")
    print(f"  Expectancy:         {stats['expectancy']:+.4f}")
    print(f"  Sharpe (approx):    {stats['sharpe_approx']:.2f}")
    print()
    print(f"  Total return:       {stats['total_return_pct']:+.1f}%")
    print(f"  CAGR:               {stats['cagr_pct']:+.1f}%")
    print(f"  Max drawdown:       {stats['max_drawdown_pct']:.1f}%")
    print(f"  Max consec losses:  {stats['max_consec_losses']}")
    print()
    print(f"  Avg holding:        {stats['avg_holding_days']:.1f} days")
    print(f"  Median holding:     {stats['median_holding_days']:.0f} days")
    print()
    print(f"  Exit reasons:")
    for reason, count in sorted(stats["exit_reasons"].items(), key=lambda x: -x[1]):
        print(f"    {reason:20s}  {count:4d}  ({count/stats['total_trades']:.0%})")
    print(f"{'='*70}")


def buy_and_hold_return(df: pd.DataFrame, start_idx: int = 252) -> dict:
    """Compute buy-and-hold return for the same period."""
    subset = df.iloc[start_idx:]
    entry = subset.iloc[0]["close"]
    exit_p = subset.iloc[-1]["close"]
    total_ret = (exit_p - entry) / entry
    days = (subset.iloc[-1]["date"] - subset.iloc[0]["date"]).days
    years = days / 365.25
    cagr = (1 + total_ret) ** (1 / years) - 1 if years > 0 else 0

    # Max drawdown of buy and hold
    cummax = subset["close"].cummax()
    dd = (subset["close"] - cummax) / cummax
    max_dd = dd.min()

    return {
        "entry_date": str(subset.iloc[0]["date"].date()),
        "exit_date": str(subset.iloc[-1]["date"].date()),
        "total_return": total_ret * 100,
        "cagr": cagr * 100,
        "max_drawdown": max_dd * 100,
        "years": years,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("  52-WEEK HIGH BREAKOUT STRATEGY — BACKTEST ON NIFTY 50 DAILY DATA")
    print("=" * 70)

    df = load_nifty_daily()
    df = add_52w_high(df)

    print(f"\nData: {df.iloc[0]['date'].date()} to {df.iloc[-1]['date'].date()} ({len(df)} bars)")
    print(f"Tradeable period (after 252-day warmup): {df.iloc[252]['date'].date()} to {df.iloc[-1]['date'].date()}")

    # Count breakout days
    tradeable = df.iloc[252:]
    n_breakouts = tradeable["breakout"].sum()
    print(f"Total breakout days: {n_breakouts} out of {len(tradeable)} trading days ({n_breakouts/len(tradeable):.1%})")

    # Buy and hold benchmark
    bh = buy_and_hold_return(df, 252)
    print(f"\n--- BUY & HOLD BENCHMARK ---")
    print(f"  Period:       {bh['entry_date']} to {bh['exit_date']} ({bh['years']:.1f} years)")
    print(f"  Total return: {bh['total_return']:+.1f}%")
    print(f"  CAGR:         {bh['cagr']:+.1f}%")
    print(f"  Max drawdown: {bh['max_drawdown']:.1f}%")

    # ===== Test Suite =====

    configs = [
        # (label, params)
        ("Strategy 1: Investors Way Exact (SL=5%, R:R 2x/3x, 60d max)",
         dict(sl_pct=0.05, rr_t1=2.0, rr_t2=3.0, max_hold_days=60, min_rr_filter=True)),

        ("Strategy 2: Tight SL (SL=3%, R:R 2x/3x, 60d)",
         dict(sl_pct=0.03, rr_t1=2.0, rr_t2=3.0, max_hold_days=60, min_rr_filter=True)),

        ("Strategy 3: Wide SL (SL=8%, R:R 2x/3x, 60d)",
         dict(sl_pct=0.08, rr_t1=2.0, rr_t2=3.0, max_hold_days=60, min_rr_filter=True)),

        ("Strategy 4: ATR-based SL (2x ATR, R:R 2x/3x, 60d)",
         dict(use_atr_sl=True, atr_sl_mult=2.0, rr_t1=2.0, rr_t2=3.0, max_hold_days=60, min_rr_filter=False)),

        ("Strategy 5: No R:R filter, just breakout (SL=5%, T1=2x, T2=3x, 60d)",
         dict(sl_pct=0.05, rr_t1=2.0, rr_t2=3.0, max_hold_days=60, min_rr_filter=False)),

        ("Strategy 6: Longer hold (SL=5%, R:R 2x/3x, 120d max)",
         dict(sl_pct=0.05, rr_t1=2.0, rr_t2=3.0, max_hold_days=120, min_rr_filter=True)),

        ("Strategy 7: Conservative (SL=3%, R:R 3x/5x, 90d, no BE move)",
         dict(sl_pct=0.03, rr_t1=3.0, rr_t2=5.0, max_hold_days=90, min_rr_filter=True,
              sl_to_breakeven_after_t1=False)),

        ("Strategy 8: Aggressive (SL=8%, R:R 1.5x/2.5x, 30d)",
         dict(sl_pct=0.08, rr_t1=1.5, rr_t2=2.5, max_hold_days=30, min_rr_filter=False)),

        ("Strategy 9: ATR-based tight (1.5x ATR, R:R 2x/3x, 45d)",
         dict(use_atr_sl=True, atr_sl_mult=1.5, rr_t1=2.0, rr_t2=3.0, max_hold_days=45, min_rr_filter=False)),
    ]

    all_stats = []
    for label, params in configs:
        trades, _ = backtest_breakout(df, **params)
        stats = analyze_trades(trades, label)
        print_report(stats)
        all_stats.append(stats)

        # Print first 5 trades as examples
        if trades and len(trades) >= 3:
            print(f"\n  Sample trades (first 3):")
            for t in trades[:3]:
                print(f"    {t.entry_date} @ {t.entry_price:.2f} → {t.exit_reason} on {t.exit_date} "
                      f"@ {t.exit_price:.2f}  P&L={t.pnl_pct:+.2%}  held={t.holding_days}d "
                      f"(T1={'Y' if t.t1_hit else 'N'} T2={'Y' if t.t2_hit else 'N'})")

    # ===== Summary comparison table =====
    print(f"\n\n{'='*100}")
    print(f"  COMPARISON SUMMARY")
    print(f"{'='*100}")
    print(f"{'Strategy':<55} {'Trades':>6} {'WinR':>6} {'AvgP&L':>8} {'TotRet':>8} {'CAGR':>7} {'MaxDD':>7} {'PF':>6} {'Sharpe':>7}")
    print(f"{'-'*100}")
    for s in all_stats:
        if s["total_trades"] == 0:
            print(f"{s['label'][:54]:<55} {'0':>6}")
            continue
        print(f"{s['label'][:54]:<55} {s['total_trades']:>6} {s['win_rate']:>5.0%} "
              f"{s['avg_pnl']:>+7.2%} {s['total_return_pct']:>+7.1f}% {s['cagr_pct']:>+6.1f}% "
              f"{s['max_drawdown_pct']:>6.1f}% {s['profit_factor']:>5.2f} {s['sharpe_approx']:>6.2f}")
    print(f"\n  Buy & Hold:  Total={bh['total_return']:+.1f}%  CAGR={bh['cagr']:+.1f}%  MaxDD={bh['max_drawdown']:.1f}%")
    print(f"{'='*100}")

    # ===== Year-by-year breakdown for best strategy =====
    best_idx = max(range(len(all_stats)),
                   key=lambda i: all_stats[i].get("total_return_pct", -999) if all_stats[i]["total_trades"] > 0 else -999)
    best_label = configs[best_idx][0]
    best_params = configs[best_idx][1]
    best_trades, _ = backtest_breakout(df, **best_params)

    if best_trades:
        print(f"\n\n{'='*70}")
        print(f"  YEAR-BY-YEAR BREAKDOWN: {best_label[:50]}")
        print(f"{'='*70}")
        print(f"{'Year':>6} {'Trades':>7} {'Wins':>5} {'WinR':>6} {'AvgP&L':>8} {'TotalP&L':>9} {'MaxDD':>7}")
        print(f"{'-'*50}")

        by_year: dict[int, list[Trade]] = {}
        for t in best_trades:
            yr = int(t.entry_date[:4])
            by_year.setdefault(yr, []).append(t)

        for yr in sorted(by_year):
            yt = by_year[yr]
            pnls = [t.pnl_pct for t in yt]
            wins = sum(1 for p in pnls if p > 0)
            eq = 1.0
            peak = 1.0
            mdd = 0.0
            for p in pnls:
                eq *= (1 + p)
                peak = max(peak, eq)
                mdd = min(mdd, (eq - peak) / peak)
            total = (eq - 1) * 100
            print(f"{yr:>6} {len(yt):>7} {wins:>5} {wins/len(yt):>5.0%} "
                  f"{np.mean(pnls):>+7.2%} {total:>+8.1f}% {mdd*100:>6.1f}%")

    # ===== VIX regime analysis =====
    vix_df = load_vix_daily()
    if vix_df is not None and best_trades:
        print(f"\n\n{'='*70}")
        print(f"  VIX REGIME ANALYSIS (best strategy)")
        print(f"{'='*70}")

        vix_map = dict(zip(vix_df["date"].dt.date, vix_df["vix_close"]))

        low_vix, high_vix = [], []
        for t in best_trades:
            entry_d = pd.to_datetime(t.entry_date).date()
            v = vix_map.get(entry_d)
            if v is None:
                continue
            if v < 15:
                low_vix.append(t.pnl_pct)
            elif v > 20:
                high_vix.append(t.pnl_pct)

        if low_vix:
            print(f"  VIX < 15 (calm):  {len(low_vix)} trades, win rate {sum(1 for p in low_vix if p>0)/len(low_vix):.0%}, "
                  f"avg P&L {np.mean(low_vix):+.2%}")
        if high_vix:
            print(f"  VIX > 20 (fear):  {len(high_vix)} trades, win rate {sum(1 for p in high_vix if p>0)/len(high_vix):.0%}, "
                  f"avg P&L {np.mean(high_vix):+.2%}")


if __name__ == "__main__":
    main()
