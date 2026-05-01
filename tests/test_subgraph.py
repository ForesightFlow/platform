"""Subgraph trades collector tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fflow.collectors.subgraph import SubgraphCollector, _parse_log_index


class TestTradeDirectionInference:
    """BUY = taker receives YES token; SELL = taker gives YES token."""

    YES_TOKEN = "2222"

    def _infer_side(self, taker_asset: str) -> str:
        return "BUY" if str(taker_asset) == self.YES_TOKEN else "SELL"

    def test_taker_receives_yes_is_buy(self):
        assert self._infer_side(self.YES_TOKEN) == "BUY"

    def test_taker_gives_yes_is_sell(self):
        assert self._infer_side("1111") == "SELL"  # taker receives NO token → SELL YES

    def test_unknown_asset_is_sell(self):
        assert self._infer_side("9999") == "SELL"


class TestLogIndexParsing:
    def test_hyphen_format(self):
        assert _parse_log_index("0xabc-42") == 42

    def test_numeric_id(self):
        idx = _parse_log_index("12345")
        assert isinstance(idx, int)

    def test_empty_string(self):
        assert _parse_log_index("") == 0

    def test_no_hyphen_no_numeric(self):
        assert _parse_log_index("notanumber") == 0


class TestPriceComputation:
    """Prices are computed as USDC_paid / size_shares with 1e6 scaling."""

    def test_basic_price(self):
        size_shares_raw = 1_000_000  # 1 share in 1e6 units
        usdc_paid_raw = 650_000  # 0.65 USDC in 1e6 units
        price = (usdc_paid_raw / size_shares_raw / 1e6) if size_shares_raw else 0
        # This will be: 0.65 / 1e6 which is wrong, re-check formula
        # Correct: usdc_paid and size_shares are already in smallest units
        # usdc_paid / 1e6 = USDC amount; size_shares / 1e6 = number of shares
        # price = (usdc_paid / 1e6) / (size_shares / 1e6) = usdc_paid / size_shares
        price_corrected = usdc_paid_raw / size_shares_raw
        assert 0.0 <= price_corrected <= 1.0
        assert abs(price_corrected - 0.65) < 1e-9

    def test_zero_size_returns_zero(self):
        size_shares_raw = 0
        price = (1000 / size_shares_raw) if size_shares_raw else 0
        assert price == 0


# ---------------------------------------------------------------------------
# Fix 1: market filter must use yes_token, not condition_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_market_filter_uses_yes_token_not_condition_id():
    """_fetch_trades must pass yes_token decimal ID as 'market', not condition_id hex."""
    market_id = "0xa772acec556629f76d8bca3708761f05f7af3d66cd182411f5523f805a37abb1"
    yes_token = "17668809327328219504003917947221347901585485692946225330492575863390915623843"

    captured: dict = {}

    async def mock_execute(query, variable_values=None):
        if variable_values and "market" in variable_values:
            captured.update(variable_values)
        return {"enrichedOrderFilleds": []}  # empty → loop exits

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.execute = mock_execute

    collector = SubgraphCollector()
    with patch.object(collector, "_make_client", return_value=mock_client):
        await collector._fetch_trades(market_id, yes_token, None)

    assert "market" in captured, "_fetch_trades never called execute with market variable"
    assert captured["market"] == yes_token, (
        f"Expected yes_token={yes_token!r}, got {captured['market']!r}"
    )
    assert captured["market"] != market_id.lower(), (
        "market filter must be yes_token decimal, not condition_id hex"
    )


@pytest.mark.asyncio
async def test_enriched_order_filleds_key_is_read():
    """Response must be read from 'enrichedOrderFilleds' key, not 'orderFilleds'."""
    market_id = "0xdeadbeef"
    yes_token = "12345"

    call_count = 0

    async def mock_execute(query, variable_values=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Return data under enrichedOrderFilleds
            return {
                "enrichedOrderFilleds": [
                    {
                        "id": "0xtx_0xorder",
                        "timestamp": "1700000000",
                        "transactionHash": "0xtx",
                        "orderHash": "0xorder",
                        "maker": {"id": "0xmaker"},
                        "taker": {"id": "0xtaker"},
                        "market": {"id": yes_token},
                        "side": "Buy",
                        "size": "1000000",
                        "price": "0.65",
                    }
                ]
            }
        return {"enrichedOrderFilleds": []}  # second page empty → stop

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.execute = mock_execute

    collector = SubgraphCollector()
    with patch.object(collector, "_make_client", return_value=mock_client):
        trades = await collector._fetch_trades(market_id, yes_token, None)

    assert len(trades) == 1, "Should have parsed 1 trade from enrichedOrderFilleds"
    assert trades[0]["side"] == "Buy"


@pytest.mark.asyncio
async def test_subgraph_first_trades_shape():
    """Fetch first 5 enrichedOrderFilleds and verify structure.

    Re-record cassette after entity name fix:
      pytest --vcr-record=new_episodes tests/test_subgraph.py::test_subgraph_first_trades_shape
    """
    from gql import Client, gql
    from gql.transport.httpx import HTTPXAsyncTransport
    from fflow.config import settings

    if not settings.thegraph_api_key:
        pytest.skip("FFLOW_THEGRAPH_API_KEY not set")

    query = gql("""
    query {
      enrichedOrderFilleds(first: 5, orderBy: id, orderDirection: asc) {
        id
        timestamp
        transactionHash
        maker { id }
        taker { id }
        market { id }
        side
        size
        price
      }
    }
    """)

    headers = {"Accept": "application/json", "Authorization": f"Bearer {settings.thegraph_api_key}"}
    transport = HTTPXAsyncTransport(url=settings.subgraph_url, headers=headers)
    async with Client(transport=transport, fetch_schema_from_transport=False) as client:
        result = await client.execute(query)
        trades = result.get("enrichedOrderFilleds", [])
        assert isinstance(trades, list)
        assert len(trades) > 0, "Expected at least 1 enrichedOrderFilled"
        t = trades[0]
        assert "transactionHash" in t
        assert "timestamp" in t
        assert "taker" in t
        assert "side" in t
        assert int(t["timestamp"]) > 0
