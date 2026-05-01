"""UMA Optimistic Oracle collector tests."""

import pytest

from fflow.collectors.uma import _decode_ancillary, _extract_evidence_url, _price_to_outcome


class TestAncillaryDecoding:
    def test_hex_decode(self):
        # "hello world" in hex
        hex_val = "68656c6c6f20776f726c64"
        result = _decode_ancillary(hex_val)
        assert result == "hello world"

    def test_0x_prefix_stripped(self):
        hex_val = "0x68656c6c6f"
        result = _decode_ancillary(hex_val)
        assert result == "hello"

    def test_empty_returns_empty(self):
        assert _decode_ancillary("") == ""

    def test_invalid_hex_returns_raw(self):
        result = _decode_ancillary("not_hex_data")
        assert isinstance(result, str)


class TestEvidenceUrlExtraction:
    def test_extracts_non_polymarket_url(self):
        # Hex-encode a string containing a URL
        text = "q:Will X happen? res_data:p1:0,p2:1 https://reuters.com/article/xyz"
        hex_val = text.encode().hex()
        url = _extract_evidence_url(hex_val)
        assert url == "https://reuters.com/article/xyz"

    def test_skips_polymarket_url(self):
        text = "https://polymarket.com/event/xyz https://bbc.com/news/abc"
        hex_val = text.encode().hex()
        url = _extract_evidence_url(hex_val)
        assert url == "https://bbc.com/news/abc"

    def test_no_url_returns_none(self):
        text = "no urls here"
        hex_val = text.encode().hex()
        assert _extract_evidence_url(hex_val) is None


class TestPriceToOutcome:
    def test_yes_price(self):
        # 1e18 = YES (1.0 * 1e18)
        assert _price_to_outcome(str(10**18)) == 1

    def test_no_price(self):
        # 0 = NO
        assert _price_to_outcome("0") == 0

    def test_none_returns_none(self):
        assert _price_to_outcome(None) is None

    def test_half_rounds_to_yes(self):
        # 0.5 * 1e18 = borderline — should be YES (>= 0.5)
        assert _price_to_outcome(str(5 * 10**17)) == 1


@pytest.mark.vcr("uma_resolution.yaml")
@pytest.mark.asyncio
async def test_uma_resolution_for_known_market():
    """For a known resolved market, verify resolution data is recoverable.
    Record: pytest --vcr-record=new_episodes tests/test_uma.py::test_uma_resolution_for_known_market
    Cassette will be large; skip in CI if too slow.
    """
    pytest.skip("Requires VCR cassette — run with --vcr-record=new_episodes to generate")
