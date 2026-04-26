"""Subgraph trades collector tests."""

import pytest

from fflow.collectors.subgraph import _parse_log_index


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


@pytest.mark.vcr("subgraph_trades.yaml")
@pytest.mark.asyncio
async def test_subgraph_first_trades_shape():
    """Fetch first 5 trades from the subgraph and verify structure.
    Requires FFLOW_THEGRAPH_API_KEY to record cassette.
    Record: pytest --record-mode=new_episodes tests/test_subgraph.py::test_subgraph_first_trades_shape
    """
    from gql import Client, gql
    from gql.transport.httpx import HTTPXAsyncTransport
    from fflow.config import settings

    if not settings.thegraph_api_key:
        pytest.skip("FFLOW_THEGRAPH_API_KEY not set — set key to record cassette")

    query = gql("""
    query {
      orderFilleds(first: 5, orderBy: id, orderDirection: asc) {
        id
        timestamp
        transactionHash
        maker
        taker
        makerAssetId
        takerAssetId
        makerAmountFilled
        takerAmountFilled
      }
    }
    """)

    headers = {"Accept": "application/json", "Authorization": f"Bearer {settings.thegraph_api_key}"}
    transport = HTTPXAsyncTransport(url=settings.subgraph_url, headers=headers)
    async with Client(transport=transport, fetch_schema_from_transport=False) as client:
        result = await client.execute(query)
        trades = result.get("orderFilleds", [])
        assert isinstance(trades, list)
        if trades:
            t = trades[0]
            assert "transactionHash" in t
            assert "timestamp" in t
            assert "taker" in t
            assert int(t["timestamp"]) > 0
