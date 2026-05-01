"""Gamma collector tests."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fflow.collectors.gamma import GammaCollector, _gamma_outcome, _parse_dt


# ---------------------------------------------------------------------------
# Unit tests — field mapping
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_iso_z(self):
        dt = _parse_dt("2025-05-02T15:03:10.397014Z")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.year == 2025

    def test_none(self):
        assert _parse_dt(None) is None

    def test_iso_offset(self):
        dt = _parse_dt("2024-01-15T00:00:00+00:00")
        assert dt is not None


class TestFieldMapping:
    """Verify that raw Gamma API response maps to the expected DB row shape."""

    def _make_raw(self) -> dict:
        return {
            "conditionId": "0xabc123",
            "question": "Will X happen?",
            "description": "Details here.",
            "createdAt": "2025-01-01T00:00:00Z",
            "endDate": "2025-06-01T00:00:00Z",
            "volume": "12345.67",
            "liquidity": "999.0",
            "slug": "will-x-happen",
            "clobTokenIds": json.dumps(["1111", "2222"]),
            "events": [{"title": "Geopolitics: Will X happen?"}],
        }

    def test_condition_id_used_as_pk(self):
        raw = self._make_raw()
        assert raw["conditionId"] == "0xabc123"

    def test_clob_token_ids_parseable(self):
        raw = self._make_raw()
        ids = json.loads(raw["clobTokenIds"])
        assert ids[1] == "2222"  # YES token at index 1

    def test_event_title_as_category_raw(self):
        raw = self._make_raw()
        event_title = (raw.get("events") or [{}])[0].get("title", "")
        assert "Geopolitics" in event_title

    def test_category_fflow_starts_null(self):
        # The Gamma collector never sets category_fflow; taxonomy classifier does
        collector = GammaCollector()
        assert collector.name == "gamma"


# ---------------------------------------------------------------------------
# Fix 2: resolved_at from closedTime
# ---------------------------------------------------------------------------

class TestResolvedAtFromClosedTime:
    """_upsert_markets must map closedTime → resolved_at."""

    def _make_closed_market(self) -> dict:
        return {
            "conditionId": "0xdead1234",
            "question": "Will Y happen?",
            "closedTime": "2024-11-06T23:59:00Z",
            "endDate": "2024-11-06T00:00:00Z",
            "outcomePrices": '["1","0"]',
            "volume": "100000.0",
            "liquidity": "5000.0",
            "slug": "will-y-happen",
            "clobTokenIds": json.dumps(["9999", "8888"]),
            "events": [{"title": "US Elections 2024"}],
        }

    def test_resolved_at_extracted(self):
        m = self._make_closed_market()
        dt = _parse_dt(m.get("closedTime"))
        assert dt is not None
        assert dt.year == 2024
        assert dt.month == 11
        assert dt.day == 6

    def test_resolved_at_is_none_when_no_closed_time(self):
        m = self._make_closed_market()
        del m["closedTime"]
        assert _parse_dt(m.get("closedTime")) is None


# ---------------------------------------------------------------------------
# Fix 2: _gamma_outcome
# ---------------------------------------------------------------------------

class TestGammaOutcome:
    """outcomePrices["1","0"] = YES won (1); ["0","1"] = NO won (0); else None."""

    def test_yes_outcome(self):
        assert _gamma_outcome({"outcomePrices": '["1","0"]'}) == 1

    def test_no_outcome(self):
        assert _gamma_outcome({"outcomePrices": '["0","1"]'}) == 0

    def test_partial_price_is_none(self):
        assert _gamma_outcome({"outcomePrices": '["0.5","0.5"]'}) is None

    def test_missing_field_is_none(self):
        assert _gamma_outcome({}) is None

    def test_list_format(self):
        # outcomePrices may already be a list (not a string)
        assert _gamma_outcome({"outcomePrices": ["1", "0"]}) == 1
        assert _gamma_outcome({"outcomePrices": ["0", "1"]}) == 0

    def test_float_string_tolerance(self):
        # "1.0" and "0.0" should also work
        assert _gamma_outcome({"outcomePrices": '["1.0","0.0"]'}) == 1
        assert _gamma_outcome({"outcomePrices": '["0.0","1.0"]'}) == 0


# ---------------------------------------------------------------------------
# Integration tests (VCR cassettes)
# ---------------------------------------------------------------------------

@pytest.mark.vcr("gamma_single_market.yaml")
@pytest.mark.asyncio
async def test_gamma_fetch_single_market():
    """Fetch one well-known market and verify field mapping.
    Record cassette with: pytest --vcr-record=new_episodes tests/test_gamma.py::test_gamma_fetch_single_market
    """
    from fflow.collectors.gamma import RetryableHTTPClient
    from fflow.config import settings

    async with RetryableHTTPClient(base_url=settings.gamma_api_url) as client:
        resp = await client.get(
            "/markets",
            params={"limit": 1, "tag": "politics"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        market = data[0]
        assert "conditionId" in market
        assert market["conditionId"].startswith("0x")
        assert "question" in market
        clob_ids = json.loads(market.get("clobTokenIds", "[]"))
        assert len(clob_ids) == 2
