"""Tier 2 T_news recovery: GDELT BigQuery keyword search.

Gracefully degrades when GCP credentials are not configured — prints a
human-readable message and returns None rather than raising a traceback.

Usage:
    result = await search_gdelt(question="Will Maduro resign?", t_resolve=...)
    if result is None:
        # GCP not available or no match
        ...
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

import structlog

log = structlog.get_logger()

_GDELT_TABLE = "gdelt-bq.gdeltv2.gkg"
_CONFIDENCE = 0.70
_WINDOW_BEFORE_RESOLVE = timedelta(days=30)
_MAX_RESULTS = 5

_import_warned = False  # fire gdelt_unavailable only once per process

# NLTK stopwords (English) — loaded lazily
_STOPWORDS: set[str] | None = None


def _get_stopwords() -> set[str]:
    global _STOPWORDS
    if _STOPWORDS is None:
        try:
            from nltk.corpus import stopwords

            _STOPWORDS = set(stopwords.words("english"))
        except Exception:
            _STOPWORDS = {
                "the", "a", "an", "in", "on", "at", "to", "for", "of",
                "and", "or", "is", "are", "was", "will", "be", "by", "with",
                "that", "this", "it", "from", "as", "do", "did", "does",
            }
    return _STOPWORDS


def _extract_keywords(question: str, top_n: int = 5) -> list[str]:
    """Pull the top-N non-stopword tokens from the market question."""
    stopwords = _get_stopwords()
    tokens = re.findall(r"\b[a-zA-Z]{3,}\b", question)
    seen: list[str] = []
    for tok in tokens:
        lower = tok.lower()
        if lower not in stopwords and lower not in seen:
            seen.append(lower)
        if len(seen) >= top_n:
            break
    return seen


def _build_query(keywords: list[str], t_start: datetime, t_end: datetime) -> str:
    kw_list = ", ".join(f"'{k.upper()}'" for k in keywords)
    start_str = t_start.strftime("%Y%m%d%H%M%S")
    end_str = t_end.strftime("%Y%m%d%H%M%S")
    return f"""
SELECT DATE, SourceCommonName, DocumentIdentifier, V2Themes
FROM `{_GDELT_TABLE}`
WHERE DATE BETWEEN {start_str} AND {end_str}
  AND (
    {' OR '.join(f"THEMES LIKE '%{k.upper()}%'" for k in keywords)}
  )
ORDER BY DATE ASC
LIMIT {_MAX_RESULTS}
"""


class GdeltResult(NamedTuple):
    t_news: datetime
    confidence: float
    source_url: str
    source_publisher: str
    query_keywords: list[str]


async def search_gdelt(
    question: str,
    t_resolve: datetime,
    t_open: datetime | None = None,
    dry_run: bool = False,
) -> GdeltResult | None:
    """Search GDELT BigQuery for the earliest relevant news article.

    Returns None if:
      - google-cloud-bigquery is not installed
      - GCP credentials are not configured
      - No matching article found

    When dry_run=True, prints the query that would run and returns None.
    """
    global _import_warned
    try:
        from google.cloud import bigquery  # type: ignore
        from google.api_core.exceptions import GoogleAPICallError  # type: ignore
    except ImportError:
        if not _import_warned:
            _import_warned = True
            log.warning(
                "gdelt_unavailable",
                reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'",
            )
        return None

    keywords = _extract_keywords(question)
    if not keywords:
        log.warning("gdelt_no_keywords", question=question)
        return None

    t_end = t_resolve
    t_start = (t_open or (t_resolve - _WINDOW_BEFORE_RESOLVE)).replace(tzinfo=UTC) if (
        t_open is None
    ) else t_open

    query = _build_query(keywords, t_start, t_end)

    if dry_run:
        print(f"[GDELT dry-run] keywords={keywords}")
        print(f"[GDELT dry-run] window={t_start.date()} → {t_end.date()}")
        print(f"[GDELT dry-run] estimated rows scanned: ~millions (standard GDELT scan)")
        print(query)
        return None

    try:
        client = bigquery.Client()
    except Exception as exc:
        log.warning(
            "gdelt_gcp_auth_failed",
            reason=str(exc),
            hint="Run: gcloud auth application-default login",
        )
        return None

    try:
        job = client.query(query)
        rows = list(job.result())
    except GoogleAPICallError as exc:
        log.warning("gdelt_query_failed", error=str(exc))
        return None

    if not rows:
        log.info("gdelt_no_results", keywords=keywords)
        return None

    first = rows[0]
    raw_date = str(first.DATE)
    try:
        dt = datetime.strptime(raw_date, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        dt = datetime.strptime(raw_date[:8], "%Y%m%d").replace(tzinfo=UTC)

    return GdeltResult(
        t_news=dt,
        confidence=_CONFIDENCE,
        source_url=str(first.DocumentIdentifier),
        source_publisher=str(first.SourceCommonName),
        query_keywords=keywords,
    )
