"""Upstox V3 option-chain helpers for Nifty weekly options.

Lets the auto-trader:
- find the nearest weekly expiry (Thursday)
- fetch the chain for that expiry
- pick the ATM strike (closest to current Nifty spot, rounded to 50)
- get the actual option contract's instrument_key + premium
- poll the option's live LTP throughout the position's life
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any, Optional

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

NIFTY = "NSE_INDEX|Nifty 50"
LOT_SIZE = int(os.getenv("LOT_SIZE", "25"))
CHAIN_URL = "https://api.upstox.com/v2/option/chain"
CONTRACT_URL = "https://api.upstox.com/v2/option/contract"
LTP_URL = "https://api.upstox.com/v3/market-quote/ltp"


def _headers() -> dict[str, str]:
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("UPSTOX_ACCESS_TOKEN missing")
    return {"Accept": "application/json", "Authorization": f"Bearer {token}"}


def next_weekly_expiry(today: Optional[date] = None) -> str:
    """Naive next-Thursday calculation. Doesn't account for holidays — use
    list_expiries() / nearest_future_expiry() for the authoritative date."""
    if today is None:
        today = date.today()
    days_ahead = (3 - today.weekday()) % 7  # Mon=0, Thu=3
    return (today + timedelta(days=days_ahead)).isoformat()


def list_expiries() -> list[str]:
    """Ask Upstox for the list of ACTUAL valid Nifty option expiry dates.
    Handles holiday shifts (sometimes weekly expiry moves to Wed/Tue)."""
    params = {"instrument_key": NIFTY}
    r = requests.get(CONTRACT_URL, params=params, headers=_headers(), timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"contract list HTTP {r.status_code}: {r.text[:200]}")
    contracts = r.json().get("data", [])
    expiries = sorted({c.get("expiry") for c in contracts if c.get("expiry")})
    return expiries


def nearest_future_expiry() -> str:
    """The first expiry date >= today, as reported by Upstox itself."""
    expiries = list_expiries()
    today_str = date.today().isoformat()
    future = [e for e in expiries if e >= today_str]
    if not future:
        raise RuntimeError(f"No future expiries available. All known: {expiries[:5]}")
    return future[0]


def fetch_option_chain(expiry: Optional[str] = None) -> list[dict[str, Any]]:
    """Fetch Nifty option chain. If expiry is None, asks Upstox for the nearest valid one."""
    if expiry is None:
        expiry = nearest_future_expiry()
    params = {"instrument_key": NIFTY, "expiry_date": expiry}
    r = requests.get(CHAIN_URL, params=params, headers=_headers(), timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"option chain HTTP {r.status_code}: {r.text[:200]}")
    data = r.json().get("data", [])
    return data


def find_atm_strike(spot: float, step: int = 50) -> int:
    """Round to nearest Nifty strike (50-pt increments)."""
    return int(round(spot / step) * step)


def select_option_for_budget(
    spot: float,
    side: str,
    capital_inr: float,
    lot_size: int = LOT_SIZE,
    expiry: Optional[str] = None,
) -> dict[str, Any]:
    """Pick an option that fits the capital budget for at least 1 lot.

    Starts at ATM and walks OUTWARD (OTM only — never ITM) until a strike
    with premium <= (capital_inr / lot_size) is found. Among affordable
    strikes, picks the one CLOSEST to ATM (most likely to be profitable).

    Returns {instrument_key, strike, expiry, ltp, side, moneyness}.
    """
    if side not in ("CE", "PE"):
        raise ValueError(f"side must be CE or PE, got {side}")

    max_premium = capital_inr / lot_size
    atm = find_atm_strike(spot)

    # Resolve candidate expiries (nearest first)
    if expiry is not None:
        candidates = [expiry]
    else:
        try:
            all_future = [e for e in list_expiries() if e >= date.today().isoformat()]
            candidates = all_future[:4] if all_future else []
        except Exception as exc:
            candidates = [next_weekly_expiry()]
            print(f"[upstox_options] list_expiries failed ({exc}); guessing {candidates[0]}")

    if not candidates:
        raise RuntimeError("No expiry candidates available")

    errors: list[str] = []

    for exp in candidates:
        try:
            chain = fetch_option_chain(exp)
        except Exception as exc:
            errors.append(f"{exp}: fetch failed ({exc})")
            continue
        if not chain:
            errors.append(f"{exp}: empty")
            continue

        # Collect ATM + OTM liquid strikes only (skip ITM for cleaner paper trading)
        liquid: list[tuple[int, dict, float]] = []
        for row in chain:
            strike = row.get("strike_price", 0)
            if not strike:
                continue
            # OTM-only filter
            if side == "CE" and strike < atm:
                continue
            if side == "PE" and strike > atm:
                continue
            leg = row.get("call_options" if side == "CE" else "put_options", {})
            md = leg.get("market_data", {})
            ltp = md.get("ltp")
            if ltp is None or ltp <= 0:
                continue
            liquid.append((int(strike), leg, float(ltp)))

        if not liquid:
            errors.append(f"{exp}: no liquid ATM/OTM {side} for spot {spot:.0f}")
            continue

        affordable = [(s, l, p) for s, l, p in liquid if p <= max_premium]
        if not affordable:
            cheapest = min(liquid, key=lambda x: x[2])
            errors.append(
                f"{exp}: cheapest {side} is {cheapest[0]}@₹{cheapest[2]:.2f} (cost ₹{cheapest[2]*lot_size:.0f}/lot); "
                f"need premium ≤ ₹{max_premium:.2f}"
            )
            continue

        # Among affordable, pick closest to ATM (least OTM, most directional)
        strike, leg, ltp = min(affordable, key=lambda x: abs(x[0] - atm))
        moneyness = "ATM" if strike == atm else "OTM"

        return {
            "instrument_key": leg.get("instrument_key"),
            "strike": strike,
            "expiry": exp,
            "ltp": ltp,
            "side": side,
            "target_atm_strike": atm,
            "moneyness": moneyness,
        }

    raise RuntimeError(
        f"No affordable {side} strike. capital ₹{capital_inr:.0f} ÷ {lot_size} = "
        f"max ₹{max_premium:.2f}/unit. Tried: " + " | ".join(errors)
    )


def select_atm_option(spot: float, side: str, expiry: Optional[str] = None) -> dict[str, Any]:
    """Find the ATM contract for the given side and return its key info.

    side: 'CE' for BUY_CALL or 'PE' for BUY_PUT.
    Tries up to 4 expiries (nearest first) so a holiday-shifted or empty
    expiry doesn't kill the whole signal.
    """
    if side not in ("CE", "PE"):
        raise ValueError(f"side must be CE or PE, got {side}")

    # Resolve a list of expiries to try (nearest first)
    if expiry is not None:
        candidates = [expiry]
    else:
        try:
            all_future = [e for e in list_expiries() if e >= date.today().isoformat()]
            candidates = all_future[:4] if all_future else []
        except Exception as exc:
            # Fallback: guess next Thursday
            candidates = [next_weekly_expiry()]
            print(f"[upstox_options] list_expiries failed ({exc}); guessing {candidates[0]}")

    if not candidates:
        raise RuntimeError("No expiry candidates available")

    target = find_atm_strike(spot)
    errors: list[str] = []

    for exp in candidates:
        try:
            chain = fetch_option_chain(exp)
        except Exception as exc:
            errors.append(f"{exp}: fetch failed ({exc})")
            continue
        if not chain:
            errors.append(f"{exp}: empty chain")
            continue
        # Sort by distance from ATM and walk outward looking for a liquid strike
        ranked = sorted(chain, key=lambda row: abs(row.get("strike_price", 0) - target))
        for row in ranked[:5]:  # try the 5 nearest strikes
            leg = row.get("call_options" if side == "CE" else "put_options", {})
            md = leg.get("market_data", {})
            ltp = md.get("ltp")
            if ltp is None or ltp <= 0:
                continue
            return {
                "instrument_key": leg.get("instrument_key"),
                "strike": int(row.get("strike_price", 0)),
                "expiry": row.get("expiry"),
                "ltp": float(ltp),
                "side": side,
                "target_atm_strike": target,
            }
        errors.append(f"{exp}: no liquid {side} near {target}")

    raise RuntimeError("No usable strike found. Tried: " + " | ".join(errors))


def fetch_option_ltp(instrument_key: str) -> Optional[float]:
    """Current LTP (premium) for a specific option contract."""
    params = {"instrument_key": instrument_key}
    r = requests.get(LTP_URL, params=params, headers=_headers(), timeout=10)
    if r.status_code != 200:
        return None
    data = r.json().get("data", {})
    for _k, info in data.items():
        lp = info.get("last_price")
        if lp is not None:
            return float(lp)
    return None


def size_position(capital_inr: float, premium: float, lot_size: int = LOT_SIZE) -> tuple[int, int, float]:
    """Compute (n_lots, total_qty, capital_used) given a capital budget."""
    if premium <= 0:
        return 0, 0, 0.0
    cost_per_lot = premium * lot_size
    n_lots = int(capital_inr // cost_per_lot)
    if n_lots < 1:
        return 0, 0, 0.0
    total_qty = n_lots * lot_size
    capital_used = n_lots * cost_per_lot
    return n_lots, total_qty, capital_used
