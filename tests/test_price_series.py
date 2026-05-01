"""Tests for fflow.scoring.price_series — all use synthetic data, no live DB."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from fflow.scoring.price_series import get_price_at, reconstruct_price_series

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ts(minutes_offset: int = 0) -> datetime:
    base = datetime(2024, 11, 5, 10, 0, 0, tzinfo=UTC)
    return base + timedelta(minutes=minutes_offset)


def _mock_session(clob_rows=None, trade_rows=None):
    """Return an AsyncSession mock whose execute() returns the given rows."""
    session = MagicMock()

    def make_execute_result(rows):
        result = MagicMock()
        result.fetchall.return_value = rows or []
        result.fetchone.return_value = rows[0] if rows else None
        return result

    call_count = 0
    clob = clob_rows or []
    trades = trade_rows or []

    async def _execute(stmt, params=None):
        nonlocal call_count
        sql = str(stmt) if hasattr(stmt, '__str__') else ""
        if "prices" in sql and "trades" not in sql:
            return make_execute_result(clob)
        return make_execute_result(trades)

    session.execute = _execute
    return session


# ─── reconstruct_price_series ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_clob_preferred_when_available():
    clob = [(_ts(0), "0.5"), (_ts(1), "0.6"), (_ts(2), "0.7")]
    session = _mock_session(clob_rows=clob)
    df = await reconstruct_price_series("0xabc", session)
    assert not df.empty
    assert df["source"].iloc[0] == "clob"
    assert len(df) == 3


@pytest.mark.asyncio
async def test_trade_vwap_fallback_when_no_clob():
    # No CLOB rows → should fall back to trades
    trade_rows = [
        (_ts(0), Decimal("1.20"), Decimal("2.00")),   # notional=1.20, shares=2.00 → vwap=0.60
        (_ts(1), Decimal("0.90"), Decimal("1.00")),   # vwap=0.90
        (_ts(3), Decimal("0.70"), Decimal("1.00")),   # gap at minute 2, forward-filled
    ]
    session = _mock_session(clob_rows=[], trade_rows=trade_rows)
    df = await reconstruct_price_series("0xabc", session)
    assert not df.empty
    assert df["source"].iloc[0] == "trade_vwap"
    # minute 2 should be forward-filled from minute 1 (vwap=0.90)
    ts_min2 = _ts(2)
    row = df[df["ts"] == pd.Timestamp(ts_min2)]
    assert not row.empty
    assert abs(float(row["mid_price"].iloc[0]) - 0.90) < 1e-6


@pytest.mark.asyncio
async def test_single_trade_per_minute():
    trade_rows = [(_ts(0), Decimal("0.50"), Decimal("1.00"))]
    session = _mock_session(clob_rows=[], trade_rows=trade_rows)
    df = await reconstruct_price_series("0xabc", session)
    assert len(df) == 1
    assert abs(float(df["mid_price"].iloc[0]) - 0.50) < 1e-6


@pytest.mark.asyncio
async def test_vwap_correct_with_multiple_trades():
    # Two buckets: first has 2 trades totalling notional=1.50, shares=3.00 → VWAP=0.50
    trade_rows = [
        (_ts(0), Decimal("1.50"), Decimal("3.00")),
        (_ts(1), Decimal("0.80"), Decimal("2.00")),  # vwap=0.40
    ]
    session = _mock_session(clob_rows=[], trade_rows=trade_rows)
    df = await reconstruct_price_series("0xabc", session)
    assert abs(float(df[df["ts"] == pd.Timestamp(_ts(0))]["mid_price"].iloc[0]) - 0.50) < 1e-6
    assert abs(float(df[df["ts"] == pd.Timestamp(_ts(1))]["mid_price"].iloc[0]) - 0.40) < 1e-6


@pytest.mark.asyncio
async def test_empty_returns_empty_dataframe():
    session = _mock_session(clob_rows=[], trade_rows=[])
    df = await reconstruct_price_series("0xabc", session)
    assert df.empty


@pytest.mark.asyncio
async def test_gap_forward_filled():
    # Gap between minute 0 and minute 5 — minutes 1-4 should be forward-filled
    trade_rows = [
        (_ts(0), Decimal("0.30"), Decimal("1.00")),
        (_ts(5), Decimal("0.70"), Decimal("1.00")),
    ]
    session = _mock_session(clob_rows=[], trade_rows=trade_rows)
    df = await reconstruct_price_series("0xabc", session)
    assert len(df) == 6  # 0..5 inclusive
    # Minutes 1-4 forward-filled from minute 0 (0.30)
    for m in [1, 2, 3, 4]:
        row = df[df["ts"] == pd.Timestamp(_ts(m))]
        assert not row.empty, f"minute {m} missing"
        assert abs(float(row["mid_price"].iloc[0]) - 0.30) < 1e-6


# ─── get_price_at ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_price_at_clob_hit():
    clob_row = ("0.650000", _ts(0))
    session = MagicMock()

    async def _execute(stmt, params=None):
        result = MagicMock()
        sql = str(stmt)
        if "prices" in sql:
            result.fetchone.return_value = clob_row
        else:
            result.fetchone.return_value = None
        return result

    session.execute = _execute
    price, source = await get_price_at("0xabc", _ts(0), session)
    assert source == "clob"
    assert price == Decimal("0.650000")


@pytest.mark.asyncio
async def test_get_price_at_trade_vwap_fallback():
    session = MagicMock()

    async def _execute(stmt, params=None):
        result = MagicMock()
        sql = str(stmt)
        if "prices" in sql:
            result.fetchone.return_value = None
        else:
            result.fetchone.return_value = (Decimal("0.42"),)
        return result

    session.execute = _execute
    price, source = await get_price_at("0xabc", _ts(0), session)
    assert source == "trade_vwap"
    assert price == Decimal("0.42")


@pytest.mark.asyncio
async def test_get_price_at_not_found():
    session = MagicMock()

    async def _execute(stmt, params=None):
        result = MagicMock()
        result.fetchone.return_value = None
        return result

    session.execute = _execute
    price, source = await get_price_at("0xabc", _ts(0), session)
    assert price is None
    assert source == "not_found"
