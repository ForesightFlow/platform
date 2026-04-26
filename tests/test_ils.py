"""ILS computation tests — synthetic price series (test-first, TDD).

These six tests define the contract for compute_ils() and must pass
before any backfill is run. They exercise the six regimes from paper Figure 2.

Price series format: list of (offset_minutes_from_t_open, price) tuples.
t_open = epoch 0, t_news = some offset, t_resolve = later offset.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

T0 = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)


def make_prices(points: list[tuple[int, float]]) -> pd.DataFrame:
    """Build a price DataFrame from (minute_offset, price) pairs."""
    rows = [
        {"ts": T0 + timedelta(minutes=m), "mid_price": Decimal(str(p))}
        for m, p in points
    ]
    return pd.DataFrame(rows)


def t(offset_minutes: int) -> datetime:
    return T0 + timedelta(minutes=offset_minutes)


# ---------------------------------------------------------------------------
# Test 1 — Pure leakage
# Price drifts from 0.15 → 0.95 before t_news, then stays flat through t_resolve=1.0
# Expected: ILS ≈ 1.0 (within 0.05)
# ---------------------------------------------------------------------------

def test_pure_leakage():
    from fflow.scoring.ils import compute_ils

    # Drift 0.15 → 0.99 before t_news: ILS = (0.99-0.15)/(1.0-0.15) = 0.84/0.85 ≈ 0.988
    prices = make_prices(
        [(i, 0.15 + 0.84 * i / 480) for i in range(0, 481)]  # 0→480 min: 0.15→0.99
        + [(i, 0.99) for i in range(481, 721)]                # 481→720 min: flat
    )
    bundle = compute_ils(
        prices=prices,
        t_open=t(0),
        t_news=t(480),
        t_resolve=t(720),
        p_resolve=1,
    )
    assert bundle.ils is not None
    assert abs(bundle.ils - Decimal("1.0")) <= Decimal("0.05"), f"ILS={bundle.ils}"
    assert "low_information_market" not in bundle.flags


# ---------------------------------------------------------------------------
# Test 2 — No leakage
# Price flat at 0.15 until t_news, then jumps to 0.99 by t_resolve.
# Expected: ILS ≈ 0.0
# ---------------------------------------------------------------------------

def test_no_leakage():
    from fflow.scoring.ils import compute_ils

    prices = make_prices(
        [(i, 0.15) for i in range(0, 481)]   # flat pre-news
        + [(i, 0.99) for i in range(481, 721)]  # jump post-news
    )
    bundle = compute_ils(
        prices=prices,
        t_open=t(0),
        t_news=t(480),
        t_resolve=t(720),
        p_resolve=1,
    )
    assert bundle.ils is not None
    assert abs(bundle.ils - Decimal("0.0")) <= Decimal("0.05"), f"ILS={bundle.ils}"


# ---------------------------------------------------------------------------
# Test 3 — Partial leakage
# Linear drift 0.15→0.55 pre-news, jump 0.55→0.99 post-news.
# Expected: ILS ∈ [0.45, 0.55]
# ---------------------------------------------------------------------------

def test_partial_leakage():
    from fflow.scoring.ils import compute_ils

    prices = make_prices(
        [(i, 0.15 + 0.40 * i / 480) for i in range(0, 481)]  # 0.15→0.55
        + [(i, 0.99) for i in range(481, 721)]
    )
    bundle = compute_ils(
        prices=prices,
        t_open=t(0),
        t_news=t(480),
        t_resolve=t(720),
        p_resolve=1,
    )
    assert bundle.ils is not None
    assert Decimal("0.45") <= bundle.ils <= Decimal("0.55"), f"ILS={bundle.ils}"


# ---------------------------------------------------------------------------
# Test 4 — Counter-evidence
# Price drifts DOWN from 0.30→0.20 before news, then jumps to 0.99.
# Expected: ILS < 0 (pre-news drift is against the eventual outcome)
# ---------------------------------------------------------------------------

def test_counter_evidence():
    from fflow.scoring.ils import compute_ils

    prices = make_prices(
        [(i, 0.30 - 0.10 * i / 480) for i in range(0, 481)]  # 0.30→0.20
        + [(i, 0.99) for i in range(481, 721)]
    )
    bundle = compute_ils(
        prices=prices,
        t_open=t(0),
        t_news=t(480),
        t_resolve=t(720),
        p_resolve=1,
    )
    assert bundle.ils is not None
    assert bundle.ils < Decimal("0"), f"ILS={bundle.ils} should be negative"


# ---------------------------------------------------------------------------
# Test 5 — Low-information market
# Price flat at 0.50 throughout. Total move is tiny (resolves YES = 1.0 but
# p_open ≈ 0.50 → delta_total = 0.50 which is fine, but let's make it resolve
# barely different from open to trigger the epsilon filter).
# Construct: p_open=0.52, p_resolve=1 but delta_total=0.48 > 0.05, so ILS is defined.
# For NULL ILS we need |delta_total| < epsilon: make p_open=0.98, p_resolve=1 (delta=0.02).
# Expected: ils is None, flag 'low_information_market'
# ---------------------------------------------------------------------------

def test_low_information_market():
    from fflow.scoring.ils import compute_ils

    # p_open = 0.98, p_resolve = 1.0 → delta_total = 0.02 < epsilon=0.05
    prices = make_prices(
        [(i, 0.98) for i in range(0, 481)]
        + [(i, 0.99) for i in range(481, 721)]
    )
    bundle = compute_ils(
        prices=prices,
        t_open=t(0),
        t_news=t(480),
        t_resolve=t(720),
        p_resolve=1,
    )
    assert bundle.ils is None, f"Expected None ILS but got {bundle.ils}"
    assert "low_information_market" in bundle.flags


# ---------------------------------------------------------------------------
# Test 6 — Multi-window correctness
# Pre-news drift is concentrated entirely in the last 30 minutes before t_news.
# Before that: flat at 0.15. Then 30-min ramp to 0.80. Resolves at 1.
#
# Expected:
#   ILS_30min ≈ ILS_full (all drift happened in 30-min window)
#   ILS_24h ≈ ILS_full   (24h window contains the full pre-news period)
#   ILS_2h includes the drift: ILS_2h ≈ ILS_full
#   ILS_6h same: ≈ ILS_full
#   The key assertion: ILS_30min is defined and close to ILS
# ---------------------------------------------------------------------------

def test_multiwindow_correctness():
    from fflow.scoring.ils import compute_ils

    # t_open=0, t_news=480, t_resolve=720
    # Flat 0.15 until minute 450, then ramp 0.15→0.80 over 30 minutes
    flat = [(i, 0.15) for i in range(0, 451)]
    ramp = [(450 + i, 0.15 + 0.65 * i / 30) for i in range(1, 31)]  # min 451..480
    post = [(i, 0.80) for i in range(481, 721)]
    prices = make_prices(flat + ramp + post)

    bundle = compute_ils(
        prices=prices,
        t_open=t(0),
        t_news=t(480),
        t_resolve=t(720),
        p_resolve=1,
    )

    assert bundle.ils is not None
    assert bundle.ils_30min is not None, "ILS_30min should be defined"

    # ILS_30min: window starts at t_news - 30min = t(450), price there ≈ 0.15
    # so ILS_30min ≈ ILS (all pre-news drift is inside this window)
    assert abs(bundle.ils_30min - bundle.ils) <= Decimal("0.10"), (
        f"ILS_30min={bundle.ils_30min} should ≈ ILS={bundle.ils}"
    )

    # ILS_2h window predates t_news by 2h = 120 min → starts at t(360), price=0.15
    # so ILS_2h ≈ ILS as well (drift is the same from that reference point)
    if bundle.ils_2h is not None:
        assert bundle.ils_2h > Decimal("0"), "ILS_2h should be positive"

    # flags: no low_information_market
    assert "low_information_market" not in bundle.flags
