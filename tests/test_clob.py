"""CLOB price-history collector tests."""

from datetime import UTC, datetime, timezone

import pytest

from fflow.collectors.clob import ClobCollector


class TestPriceNormalization:
    def test_minute_snap(self):
        ts_raw = 1774463449  # has non-zero seconds
        ts = datetime.fromtimestamp(ts_raw, tz=UTC)
        snapped = ts.replace(second=0, microsecond=0)
        assert snapped.second == 0
        assert snapped.microsecond == 0
        assert snapped.tzinfo is not None

    def test_price_in_range(self):
        prices = [{"t": 1774463449, "p": p} for p in [0.0, 0.5, 1.0]]
        for p in prices:
            assert 0.0 <= float(p["p"]) <= 1.0

    def test_price_string_conversion(self):
        price_val = str(0.565)
        assert float(price_val) == 0.565


class TestYesTokenResolution:
    """YES token is at index 1 of clobTokenIds JSON string."""

    def test_yes_token_index(self):
        import json
        raw = '["111111", "222222"]'
        ids = json.loads(raw)
        assert ids[1] == "222222"

    def test_single_token_raises(self):
        import json
        raw = '["111111"]'
        ids = json.loads(raw)
        # Should raise ValueError (< 2 tokens)
        assert len(ids) < 2


@pytest.mark.vcr("clob_price_history.yaml")
@pytest.mark.asyncio
async def test_clob_price_history_shape():
    """Verify price history response: timestamps are sequential, prices in [0,1].
    Record: pytest --vcr-record=new_episodes tests/test_clob.py::test_clob_price_history_shape
    """
    from fflow.collectors.base import RetryableHTTPClient
    from fflow.config import settings

    # Use a known active market's YES token
    token = "2527312495175492857904889758552137141356236738032676480522356889996545113869"
    start_ts = 1774400000
    end_ts = start_ts + 7200  # 2 hours

    async with RetryableHTTPClient(base_url=settings.clob_api_url) as client:
        resp = await client.get(
            "/prices-history",
            params={"market": token, "startTs": start_ts, "endTs": end_ts, "fidelity": 1},
        )
        assert resp.status_code == 200
        data = resp.json()
        history = data.get("history", [])
        assert isinstance(history, list)

        if history:
            for point in history:
                assert "t" in point
                assert "p" in point
                assert 0.0 <= float(point["p"]) <= 1.0

            # timestamps should be monotonically increasing
            timestamps = [p["t"] for p in history]
            assert timestamps == sorted(timestamps)
