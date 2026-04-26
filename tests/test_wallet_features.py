"""Tests for wallet_features.compute_wallet_features.

Uses MagicMock session to avoid PostgreSQL-specific types in SQLite.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

T_NEWS = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
MARKET_ID = "0x" + "a" * 64


def _mock_session(rows: list) -> MagicMock:
    """Build a mock AsyncSession whose execute() returns the given rows."""
    result = MagicMock()
    result.one.return_value = rows[0] if rows else SimpleNamespace(n=0, vol=0, max_jump=0)
    result.all.return_value = rows
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _row(address: str, notional: float, first_ts: datetime):
    return SimpleNamespace(
        taker_address=address,
        notional=Decimal(str(notional)),
        first_trade_ts=first_ts,
    )


# ---------------------------------------------------------------------------
# HHI tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hhi_single_dominant_wallet():
    """One wallet holds 100% of pre-news volume → HHI = 1.0"""
    from fflow.scoring.wallet_features import compute_wallet_features

    rows = [_row("0xWALLET_A", 1000.0, T_NEWS - timedelta(hours=1))]
    session = _mock_session(rows)

    result = await compute_wallet_features(session, MARKET_ID, T_NEWS, p_resolve=1)

    assert result["wallet_hhi_top10"] is not None
    assert abs(result["wallet_hhi_top10"] - Decimal("1.0")) < Decimal("0.001")


@pytest.mark.asyncio
async def test_hhi_equal_wallets():
    """Four equal wallets → HHI = 0.25"""
    from fflow.scoring.wallet_features import compute_wallet_features

    rows = [
        _row(f"0xWALLET_{i:02d}", 250.0, T_NEWS - timedelta(minutes=30 + i))
        for i in range(4)
    ]
    session = _mock_session(rows)

    result = await compute_wallet_features(session, MARKET_ID, T_NEWS, p_resolve=1)

    assert result["wallet_hhi_top10"] is not None
    assert abs(result["wallet_hhi_top10"] - Decimal("0.25")) < Decimal("0.01")


@pytest.mark.asyncio
async def test_time_to_news_ordering():
    """time_to_news_top10 is sorted by notional descending (DB ORDER BY)."""
    from fflow.scoring.wallet_features import compute_wallet_features

    rows = [
        _row("0xBIG", 900.0, T_NEWS - timedelta(minutes=120)),
        _row("0xSMALL", 100.0, T_NEWS - timedelta(minutes=10)),
    ]
    session = _mock_session(rows)

    result = await compute_wallet_features(session, MARKET_ID, T_NEWS, p_resolve=1)

    top = result["time_to_news_top10"]
    assert top is not None
    assert len(top) == 2
    assert top[0]["address"] == "0xBIG"
    assert top[0]["notional_usdc"] > top[1]["notional_usdc"]
    # BIG entered 120 min before news, SMALL entered 10 min before
    assert top[0]["minutes_before_news"] > top[1]["minutes_before_news"]


@pytest.mark.asyncio
async def test_no_trades_returns_none():
    """Empty result → None for both metrics."""
    from fflow.scoring.wallet_features import compute_wallet_features

    result_mock = MagicMock()
    result_mock.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=result_mock)

    result = await compute_wallet_features(session, MARKET_ID, T_NEWS, p_resolve=1)

    assert result["wallet_hhi_top10"] is None
    assert result["time_to_news_top10"] is None


@pytest.mark.asyncio
async def test_truncates_to_top10():
    """Only top 10 wallets are included in the result."""
    from fflow.scoring.wallet_features import compute_wallet_features

    rows = [
        _row(f"0xWALLET_{i:02d}", float(100 - i), T_NEWS - timedelta(minutes=i + 1))
        for i in range(15)
    ]
    session = _mock_session(rows)

    result = await compute_wallet_features(session, MARKET_ID, T_NEWS, p_resolve=1)

    assert result["time_to_news_top10"] is not None
    assert len(result["time_to_news_top10"]) == 10
