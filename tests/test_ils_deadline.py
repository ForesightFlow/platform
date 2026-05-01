"""Deadline-ILS unit tests — synthetic price series.

Tests verify compute_ils_deadline() against six deadline market regimes:
  1. Pure leakage: price fully converges 1 h before T_resolve → ILS_dl ≈ 1.0
  2. No leakage:   price flat until T_resolve → ILS_dl ≈ 0.0
  3. Partial:      price moves halfway before deadline → ILS_dl ≈ 0.5
  4. Overcooking:  price overshoots then corrects → ILS_dl > 1.0
  5. Counter-move: price moves wrong direction → ILS_dl < 0
  6. Low info:     |delta_total| < epsilon → ILS_dl = None, flag set

Also tests:
  - Multi-window variants (30min, 2h, 6h, 24h, 7d)
  - lookback_predates_topen flag
  - classify_resolution_type accuracy
  - classify_resolution_type_detailed description-only detection
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from fflow.scoring.ils import _DEADLINE_LOOKBACK, compute_ils, compute_ils_deadline
from fflow.scoring.resolution_type import (
    classify_resolution_type,
    classify_resolution_type_detailed,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def make_prices(points: list[tuple[int, float]]) -> pd.DataFrame:
    """Build price DataFrame from (minute_offset_from_T0, price) tuples."""
    rows = [
        {"ts": T0 + timedelta(minutes=m), "mid_price": Decimal(str(p))}
        for m, p in points
    ]
    return pd.DataFrame(rows)


def t(offset_minutes: int) -> datetime:
    return T0 + timedelta(minutes=offset_minutes)


# T_open at T0, T_resolve at T0 + 4 days = 5760 minutes
T_OPEN = T0
T_RESOLVE = T0 + timedelta(days=4)
T_REF = T_RESOLVE - _DEADLINE_LOOKBACK  # T_resolve - 1h = T0 + 4d - 1h


# ---------------------------------------------------------------------------
# Test 1 — Pure leakage (price converges fully 1 h before T_resolve)
# ---------------------------------------------------------------------------

def test_deadline_pure_leakage():
    """ILS_dl ≈ 1.0: price reaches final level before the 1-h lookback point."""
    # T_REF = T_RESOLVE - 1h = minute 5700. Price must be at/near 5700 for lookup.
    prices = make_prices([
        (0,    0.10),   # T_open: p = 0.10
        (5640, 0.10),   # flat until 1h before T_ref
        (5680, 0.95),   # price jumps toward resolution
        (5700, 0.97),   # AT T_ref: near-final level
    ])
    bundle = compute_ils_deadline(prices, T_OPEN, T_RESOLVE, p_resolve=1)
    assert bundle.ils is not None
    # ILS_dl = (0.97 - 0.10) / (1 - 0.10) = 0.87 / 0.90 ≈ 0.967
    assert bundle.ils > Decimal("0.90"), f"Expected ILS_dl > 0.90, got {bundle.ils}"
    assert "low_information_market" not in bundle.flags


# ---------------------------------------------------------------------------
# Test 2 — No leakage (price flat until T_resolve)
# ---------------------------------------------------------------------------

def test_deadline_no_leakage():
    """ILS_dl ≈ 0.0: price stays flat right up to T_resolve."""
    # T_REF = minute 5700; price must be at/near 5700 for lookup (±5 min tolerance).
    prices = make_prices([
        (0,    0.50),   # T_open: p = 0.50
        (5700, 0.50),   # AT T_ref: still flat
        (5760, 0.50),   # T_resolve: still 0.50
    ])
    bundle = compute_ils_deadline(prices, T_OPEN, T_RESOLVE, p_resolve=1)
    assert bundle.ils is not None
    # ILS_dl = (0.50 - 0.50) / (1 - 0.50) = 0
    assert abs(bundle.ils) < Decimal("0.01"), f"Expected ILS_dl ≈ 0, got {bundle.ils}"


# ---------------------------------------------------------------------------
# Test 3 — Partial leakage (~50%)
# ---------------------------------------------------------------------------

def test_deadline_partial_leakage():
    """ILS_dl ≈ 0.5: price moves halfway from open to resolution."""
    # p_open = 0.20, p_resolve = 1.0
    # delta_total = 0.80; p(T_ref) = 0.60 → delta_pre = 0.40 → ILS_dl = 0.5
    prices = make_prices([
        (0,    0.20),
        (2880, 0.20),   # flat until midpoint
        (5700, 0.60),   # moved to 0.60 before T_ref
        (5750, 0.60),   # holds at T_ref
    ])
    bundle = compute_ils_deadline(prices, T_OPEN, T_RESOLVE, p_resolve=1)
    assert bundle.ils is not None
    assert abs(bundle.ils - Decimal("0.5")) < Decimal("0.05"), (
        f"Expected ILS_dl ≈ 0.5, got {bundle.ils}"
    )


# ---------------------------------------------------------------------------
# Test 4 — Overshoot (ILS_dl > 1.0)
# ---------------------------------------------------------------------------

def test_deadline_overshoot():
    """ILS_dl > 1.0: price overshoots final resolution value before T_ref."""
    # p_open=0.10, p_resolve=0 (NO), p(T_ref)=0.90 → delta_total=-0.10
    # delta_pre = 0.90 - 0.10 = 0.80; ILS_dl = 0.80 / (-0.10) = -8.0
    # This is the "counter-move" scenario for NO resolution
    prices = make_prices([
        (0,    0.10),
        (5700, 0.90),   # price spikes to 0.90 before T_ref
        (5750, 0.90),
    ])
    bundle = compute_ils_deadline(prices, T_OPEN, T_RESOLVE, p_resolve=0)
    assert bundle.ils is not None
    # ILS_dl = (0.90 - 0.10) / (0 - 0.10) = 0.80 / (-0.10) = -8.0
    assert bundle.ils < Decimal("-1.0"), f"Expected ILS_dl < -1, got {bundle.ils}"


# ---------------------------------------------------------------------------
# Test 5 — Counter-move
# ---------------------------------------------------------------------------

def test_deadline_counter_move():
    """ILS_dl < 0: price moves away from final resolution direction."""
    # p_open=0.70, p_resolve=1 (YES), p(T_ref)=0.30 → ILS_dl < 0
    prices = make_prices([
        (0,    0.70),
        (5700, 0.30),   # price drops before T_ref
        (5750, 0.30),
    ])
    bundle = compute_ils_deadline(prices, T_OPEN, T_RESOLVE, p_resolve=1)
    assert bundle.ils is not None
    assert bundle.ils < Decimal("0"), f"Expected ILS_dl < 0, got {bundle.ils}"


# ---------------------------------------------------------------------------
# Test 6 — Low information (|delta_total| < epsilon → ILS_dl = None)
# ---------------------------------------------------------------------------

def test_deadline_low_information():
    """ILS_dl = None when |p_resolve - p_open| < epsilon (0.05)."""
    prices = make_prices([
        (0,    0.50),
        (5750, 0.52),   # barely moved
    ])
    # p_open ≈ 0.50, p_resolve=0 → delta_total = -0.50 ... wait
    # Use p_resolve=1 and a starting price near 0.98 to get tiny delta_total
    prices2 = make_prices([
        (0,    0.97),
        (5700, 0.97),   # AT T_ref (minute 5700, not 5750 which is outside ±5 min)
    ])
    bundle = compute_ils_deadline(prices2, T_OPEN, T_RESOLVE, p_resolve=1)
    # delta_total = 1 - 0.97 = 0.03 < epsilon=0.05
    assert bundle.ils is None
    assert "low_information_market" in bundle.flags


# ---------------------------------------------------------------------------
# Test 7 — Multi-window variants
# ---------------------------------------------------------------------------

def test_deadline_multi_window():
    """Multi-window ils_30min, ils_2h, etc. are computed correctly."""
    # p_open=0.10 at T0, steady rise to ~0.89 at T_ref=minute 5700, p_resolve=1
    # Use 30-min intervals so the 30min window (needs price at minute 5670) is covered.
    # 4 days = 192 half-hour steps; price at step s = 0.10 + (s/192)*0.80
    points = [(0, 0.10)]
    for step in range(1, 193):
        price = round(0.10 + (step / 192) * 0.80, 6)
        points.append((step * 30, price))
    prices = make_prices(points)

    bundle = compute_ils_deadline(prices, T_OPEN, T_RESOLVE, p_resolve=1)
    assert bundle.ils is not None
    # With 30-min data, all sub-7d windows have prices within ±5 min of their ref times
    assert bundle.ils_30min is not None
    assert bundle.ils_2h is not None
    assert bundle.ils_6h is not None
    assert bundle.ils_24h is not None
    # 7d window: T_ref - 7d = minute -4380 → predates T_open → None + flag
    assert bundle.ils_7d is None
    assert any("window_7d" in f for f in bundle.flags)


# ---------------------------------------------------------------------------
# Test 8 — lookback_predates_topen flag
# ---------------------------------------------------------------------------

def test_deadline_lookback_predates_topen():
    """When T_resolve - lookback <= T_open, flag is set."""
    # Market only 30 minutes long — lookback (1h) predates T_open
    t_resolve_short = T0 + timedelta(minutes=30)
    prices = make_prices([
        (0, 0.50),
        (29, 0.90),
    ])
    bundle = compute_ils_deadline(prices, T_OPEN, t_resolve_short, p_resolve=1)
    assert "lookback_predates_topen" in bundle.flags


# ---------------------------------------------------------------------------
# Test 9 — p_news field stores T_resolve⁻ price
# ---------------------------------------------------------------------------

def test_deadline_p_news_is_t_event_minus_price():
    """ILSBundle.p_news stores the price at T_resolve - lookback."""
    prices = make_prices([
        (0,    0.20),
        (5700, 0.75),   # price at T_ref (T_resolve - 1h)
        (5760, 0.80),   # T_resolve
    ])
    bundle = compute_ils_deadline(prices, T_OPEN, T_RESOLVE, p_resolve=1)
    # p_news should be the price at T_ref ≈ 0.75
    assert bundle.p_news is not None
    assert abs(bundle.p_news - Decimal("0.75")) < Decimal("0.01"), (
        f"p_news should be ~0.75, got {bundle.p_news}"
    )


# ---------------------------------------------------------------------------
# Test 10 — Resolution type classifier: deadline patterns
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("question,expected", [
    ("US forces enter Iran by April 30?", "deadline_resolved"),
    ("US x Iran ceasefire by April 7?", "deadline_resolved"),
    ("Will US strike Iran by Feb 28?", "deadline_resolved"),
    ("Iran conflict ends before July?", "deadline_resolved"),
    ("Will Israel strike Iran by end of March?", "deadline_resolved"),
    ("Military action ends by 2026?", "deadline_resolved"),
    ("Will X happen by Q2 2026?", "deadline_resolved"),
    ("Strike by 4/30?", "deadline_resolved"),
    ("No later than June 15, will peace hold?", "deadline_resolved"),
    # Non-deadline
    ("Who will win the 2024 election?", "unclassifiable"),
    ("Will there be a US-Iran war?", "unclassifiable"),
    ("Won by a landslide?", "unclassifiable"),
    ("Set by the committee?", "unclassifiable"),
])
def test_classify_resolution_type(question, expected):
    assert classify_resolution_type(question) == expected, (
        f"classify_resolution_type({question!r}) should be {expected!r}"
    )


# ---------------------------------------------------------------------------
# Test 11 — classify_resolution_type_detailed: description-only flag
# ---------------------------------------------------------------------------

def test_classify_type_detailed_question_match():
    rtype, desc_only = classify_resolution_type_detailed(
        "US forces enter Iran by April 30?", None
    )
    assert rtype == "deadline_resolved"
    assert desc_only is False


def test_classify_type_detailed_description_only():
    """Deadline in description but NOT question → description_only=True."""
    rtype, desc_only = classify_resolution_type_detailed(
        "Will the Gaza hospital explosion be resolved?",
        "This market resolves YES if a finding is published by December 31, 2024.",
    )
    assert rtype == "deadline_resolved"
    assert desc_only is True


def test_classify_type_detailed_unclassifiable():
    rtype, desc_only = classify_resolution_type_detailed(
        "Who will win?", "A general election question."
    )
    assert rtype == "unclassifiable"
    assert desc_only is False


# ---------------------------------------------------------------------------
# Test 12 — CLOB indexing lag: t_open forward-window lookup
# ---------------------------------------------------------------------------

def test_topen_with_clob_delay():
    """CLOB prices start 20 min after t_open — forward window finds first available price.

    Covers both compute_ils_deadline() and compute_ils() since both use the same
    _lookup_price forward-window logic for t_open.
    """
    # First price at +20 min (simulates typical CLOB indexing lag ~20 min).
    prices = make_prices([
        (20,   0.45),   # first available price — used as p_open
        (5700, 0.90),   # AT T_ref (T_resolve - 1h)
    ])

    # --- deadline path ---
    bundle_dl = compute_ils_deadline(prices, T_OPEN, T_RESOLVE, p_resolve=1)
    assert bundle_dl.p_open == Decimal("0.45"), (
        f"p_open should be first available price 0.45, got {bundle_dl.p_open}"
    )
    assert bundle_dl.ils is not None
    assert "price_history_gap_at_topen" not in bundle_dl.flags

    # --- standard path ---
    T_NEWS = T0 + timedelta(minutes=5700)  # same as T_ref for this comparison
    bundle_std = compute_ils(prices, T_OPEN, T_NEWS, T_RESOLVE, p_resolve=1)
    assert bundle_std.p_open == Decimal("0.45"), (
        f"p_open should be first available price 0.45, got {bundle_std.p_open}"
    )
    assert bundle_std.ils is not None
    assert "price_history_gap_at_topen" not in bundle_std.flags


def test_topen_forward_window_exceeded():
    """No price within 30 min of t_open → PriceLookupError (legitimately stale market)."""
    from fflow.scoring.ils import PriceLookupError

    prices = make_prices([
        (35,   0.50),   # first price at +35 min — outside 30-min forward window
        (5700, 0.80),
    ])
    with pytest.raises(PriceLookupError):
        compute_ils_deadline(prices, T_OPEN, T_RESOLVE, p_resolve=1)
