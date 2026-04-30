"""Bootstrap CI for ILS^dl.

Resamples YES-token trades within [T_open, T_event] to quantify sampling
uncertainty in the pre-event price estimate.

Paper §4.3: Bootstrap CI construction
  B = 500 replicates, seed = 20260430 (Paper 1+2 SSRN submission date)
  VWAP of resampled YES trades → p_resampled
  ILS^dl_b = (p_resampled - p_open) / (p_resolve - p_open)
  CI = [2.5th, 97.5th] percentile of the B replicates

Returns (None, None) when fewer than MIN_TRADES YES trades exist in the window.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import numpy as np
import pandas as pd

BOOTSTRAP_B = 500
BOOTSTRAP_SEED = 20260430
MIN_TRADES_FOR_CI = 50
_EPSILON = 0.05


def bootstrap_ils_dl_ci(
    trades: pd.DataFrame,
    t_open: datetime,
    t_event: datetime,
    p_open: Decimal,
    p_resolve: int,
    B: int = BOOTSTRAP_B,
    seed: int = BOOTSTRAP_SEED,
    min_trades: int = MIN_TRADES_FOR_CI,
) -> tuple[Decimal | None, Decimal | None]:
    """Return 95% bootstrap CI on ILS^dl, or (None, None) if insufficient data.

    Args:
        trades:    DataFrame with columns ts (tz-aware datetime), price (float),
                   notional_usdc (float), outcome_index (int — 1 = YES token).
        t_open:    Market creation timestamp.
        t_event:   Recovered event timestamp (T_event).
        p_open:    Opening price (Decimal) from CLOB.
        p_resolve: Binary resolution outcome (0 or 1).
        B:         Number of bootstrap replicates.
        seed:      RNG seed for reproducibility.
        min_trades: Minimum YES trades in window; CI = NULL below this.

    Returns:
        (ci_low, ci_high) as Decimal with 6dp, or (None, None).
    """
    if trades.empty:
        return None, None

    # Ensure timestamps are comparable
    t_open_ts = pd.Timestamp(t_open, tz="UTC") if t_open.tzinfo else pd.Timestamp(t_open).tz_localize("UTC")
    t_event_ts = pd.Timestamp(t_event, tz="UTC") if t_event.tzinfo else pd.Timestamp(t_event).tz_localize("UTC")

    ts_col = pd.to_datetime(trades["ts"], utc=True)
    mask = (ts_col >= t_open_ts) & (ts_col <= t_event_ts) & (trades["outcome_index"] == 1)
    window = trades[mask]

    if len(window) < min_trades:
        return None, None

    p_open_f = float(p_open)
    delta_total = float(p_resolve) - p_open_f
    if abs(delta_total) < _EPSILON:
        return None, None

    prices_arr = window["price"].astype(float).values
    weights_arr = window["notional_usdc"].astype(float).values
    n = len(prices_arr)

    rng = np.random.default_rng(seed)
    ils_boot = np.empty(B)

    for b in range(B):
        idx = rng.integers(0, n, size=n)
        w = weights_arr[idx]
        total_w = w.sum()
        if total_w == 0:
            ils_boot[b] = np.nan
            continue
        vwap = (prices_arr[idx] * w).sum() / total_w
        ils_boot[b] = (vwap - p_open_f) / delta_total

    valid = ils_boot[~np.isnan(ils_boot)]
    if len(valid) < int(B * 0.9):
        return None, None

    ci_low = Decimal(str(round(float(np.percentile(valid, 2.5)), 6)))
    ci_high = Decimal(str(round(float(np.percentile(valid, 97.5)), 6)))
    return ci_low, ci_high
