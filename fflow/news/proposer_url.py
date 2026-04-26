"""Tier 1 T_news recovery: extract publish timestamp from the UMA proposer's evidence URL.

Strategy (in order):
  1. JSON-LD <script type="application/ld+json"> with datePublished
  2. OpenGraph <meta property="og:article:published_time">
  3. Twitter card <meta name="twitter:data1"> (publication date)
  4. <time datetime="..."> element with a parseable datetime
  5. <meta name="publish-date"> / "article:published_time" / "pubdate"

Confidence returned:
  0.95 — any timestamp found (same source, high reliability)
  None — no timestamp found

Denylist: skip fetch if URL matches any pattern in DENYLIST_PATTERNS.
"""

import json
import re
from datetime import UTC, datetime
from typing import NamedTuple
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

DENYLIST_PATTERNS: list[str] = [
    r"twitter\.com",
    r"x\.com",
    r"t\.co/",
    r"polymarket\.com",
]

_DENYLIST_RE = [re.compile(p) for p in DENYLIST_PATTERNS]
_USER_AGENT = "ForesightFlow-bot/1.0 (research; +https://github.com/ForesightFlow)"
_TIMEOUT = 10.0


class ProposerTimestamp(NamedTuple):
    t_news: datetime
    confidence: float
    source_url: str


def _is_denylisted(url: str) -> bool:
    return any(p.search(url) for p in _DENYLIST_RE)


def _parse_dt(value: str) -> datetime | None:
    """Parse an ISO-8601 or RFC-2822-ish string into an aware UTC datetime."""
    if not value:
        return None
    value = value.strip()
    # Try ISO 8601 variants
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M%z",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(value[:len(fmt) + 10], fmt)
            return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _extract_from_soup(soup: BeautifulSoup) -> datetime | None:
    # 1. JSON-LD
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, list):
            data = data[0] if data else {}
        for key in ("datePublished", "dateCreated", "dateModified"):
            val = data.get(key)
            if val:
                dt = _parse_dt(str(val))
                if dt:
                    return dt

    # 2. OpenGraph / meta tags
    og_props = (
        "article:published_time",
        "og:article:published_time",
        "pubdate",
        "publish-date",
        "date",
        "DC.date.issued",
    )
    for prop in og_props:
        tag = soup.find("meta", attrs={"property": prop}) or soup.find(
            "meta", attrs={"name": prop}
        )
        if tag:
            val = tag.get("content", "")
            dt = _parse_dt(str(val))
            if dt:
                return dt

    # 3. <time datetime="...">
    for tag in soup.find_all("time"):
        val = tag.get("datetime", "")
        dt = _parse_dt(str(val))
        if dt:
            return dt

    return None


async def fetch_proposer_timestamp(url: str) -> ProposerTimestamp | None:
    """Fetch the proposer evidence URL and extract the article publish datetime.

    Returns None if the URL is denylisted, unreachable, or no timestamp found.
    """
    if _is_denylisted(url):
        return None

    # Validate URL is HTTP/HTTPS
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None

    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except (httpx.HTTPError, Exception):
        return None

    soup = BeautifulSoup(html, "lxml")
    dt = _extract_from_soup(soup)
    if dt is None:
        return None

    return ProposerTimestamp(t_news=dt, confidence=0.95, source_url=url)
