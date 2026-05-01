"""Polygonscan wallet collector tests."""

import pytest

from fflow.collectors.polygonscan import _compute_funding_sources


class TestFundingSources:
    def _make_transfer(self, from_addr: str, to_addr: str, value: int) -> dict:
        return {"from": from_addr, "to": to_addr, "value": str(value)}

    def test_only_incoming_counted(self):
        wallet = "0xabc"
        txs = [
            self._make_transfer("0xsender1", "0xabc", 1_000_000),  # incoming
            self._make_transfer("0xabc", "0xother", 500_000),  # outgoing — excluded
        ]
        sources = _compute_funding_sources(wallet, txs)
        assert len(sources) == 1
        assert sources[0]["counterparty"] == "0xsender1"

    def test_aggregates_by_sender(self):
        wallet = "0xabc"
        txs = [
            self._make_transfer("0xsender1", "0xabc", 1_000_000),
            self._make_transfer("0xsender1", "0xabc", 2_000_000),
            self._make_transfer("0xsender2", "0xabc", 500_000),
        ]
        sources = _compute_funding_sources(wallet, txs)
        by_addr = {s["counterparty"]: s for s in sources}
        assert by_addr["0xsender1"]["n_transfers"] == 2
        assert abs(by_addr["0xsender1"]["total_usdc"] - 3.0) < 1e-6

    def test_top_10_limit(self):
        wallet = "0xabc"
        txs = [
            self._make_transfer(f"0xsender{i}", "0xabc", 1_000_000)
            for i in range(15)
        ]
        sources = _compute_funding_sources(wallet, txs)
        assert len(sources) <= 10

    def test_sorted_by_total_desc(self):
        wallet = "0xabc"
        txs = [
            self._make_transfer("0xsmall", "0xabc", 100_000),
            self._make_transfer("0xbig", "0xabc", 10_000_000),
        ]
        sources = _compute_funding_sources(wallet, txs)
        assert sources[0]["counterparty"] == "0xbig"

    def test_case_insensitive_address(self):
        wallet = "0xABC"
        txs = [self._make_transfer("0xSENDER", "0xabc", 1_000_000)]
        sources = _compute_funding_sources(wallet, txs)
        assert len(sources) == 1

    def test_empty_returns_empty(self):
        assert _compute_funding_sources("0xabc", []) == []


@pytest.mark.vcr("polygonscan_wallet.yaml")
@pytest.mark.asyncio
async def test_polygonscan_known_wallet():
    """For a known wallet, verify first_seen_chain_at and funding_sources.
    Record: pytest --vcr-record=new_episodes tests/test_polygonscan.py::test_polygonscan_known_wallet
    """
    pytest.skip("Requires API key + VCR cassette — run with --vcr-record=new_episodes to generate")
