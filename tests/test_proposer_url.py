"""Tests for Tier 1 T_news extraction from proposer evidence URLs.

Uses local HTML fixtures to avoid network calls.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

FIXTURES = Path(__file__).parent / "fixtures"


def _soup(filename: str) -> BeautifulSoup:
    return BeautifulSoup((FIXTURES / filename).read_text(), "lxml")


# ---------------------------------------------------------------------------
# Unit tests for _extract_from_soup (no HTTP)
# ---------------------------------------------------------------------------

def test_extract_jsonld_date():
    from fflow.news.proposer_url import _extract_from_soup

    soup = _soup("article_jsonld.html")
    dt = _extract_from_soup(soup)

    assert dt is not None
    assert dt.year == 2024
    assert dt.month == 3
    assert dt.day == 15
    assert dt.tzinfo is not None


def test_extract_opengraph_date():
    from fflow.news.proposer_url import _extract_from_soup

    soup = _soup("article_opengraph.html")
    dt = _extract_from_soup(soup)

    assert dt is not None
    assert dt.year == 2024
    assert dt.month == 7
    assert dt.day == 4


def test_extract_time_tag():
    from fflow.news.proposer_url import _extract_from_soup

    soup = _soup("article_time_tag.html")
    dt = _extract_from_soup(soup)

    assert dt is not None
    assert dt.year == 2024
    assert dt.month == 11
    assert dt.day == 20


def test_extract_no_date_returns_none():
    from fflow.news.proposer_url import _extract_from_soup

    soup = _soup("article_no_date.html")
    dt = _extract_from_soup(soup)

    assert dt is None


# ---------------------------------------------------------------------------
# Denylist
# ---------------------------------------------------------------------------

def test_denylist_twitter():
    from fflow.news.proposer_url import _is_denylisted

    assert _is_denylisted("https://twitter.com/user/status/123")
    assert _is_denylisted("https://x.com/user/status/456")
    assert not _is_denylisted("https://reuters.com/article/foo")


def test_denylist_polymarket():
    from fflow.news.proposer_url import _is_denylisted

    assert _is_denylisted("https://polymarket.com/event/foo")


# ---------------------------------------------------------------------------
# fetch_proposer_timestamp integration (httpx mock)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_returns_none_for_denylisted():
    from fflow.news.proposer_url import fetch_proposer_timestamp

    result = await fetch_proposer_timestamp("https://twitter.com/user/status/123")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_returns_none_for_non_http():
    from fflow.news.proposer_url import fetch_proposer_timestamp

    result = await fetch_proposer_timestamp("ftp://example.com/file.html")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_extracts_date_from_fixture(monkeypatch):
    """Monkeypatch httpx.AsyncClient to serve local fixture HTML."""
    import httpx
    from unittest.mock import AsyncMock, MagicMock

    html = (FIXTURES / "article_jsonld.html").read_text()
    url = "https://example-news.com/iran-deal"

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.text = html

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    monkeypatch.setattr(
        "fflow.news.proposer_url.httpx.AsyncClient",
        lambda **kw: mock_client,
    )

    from fflow.news.proposer_url import fetch_proposer_timestamp
    result = await fetch_proposer_timestamp(url)

    assert result is not None
    assert result.t_news.year == 2024
    assert result.confidence == 0.95
    assert result.source_url == url
