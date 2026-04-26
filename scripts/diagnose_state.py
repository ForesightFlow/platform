"""State diagnostic: read-only survey of DB + conditional reruns.

Phase 1 — read-only (7 sections)
Phase 2 — safe reruns where data is missing (subgraph / polygonscan / Tier 1)
Phase 3 — post-rerun state snapshot

Output: reports/STATE_ASSESSMENT.md + console summary.

Usage:
    uv run python scripts/diagnose_state.py [--no-rerun]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path

# ── ensure project root on path ───────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fflow.db import AsyncSessionLocal
from fflow.log import configure_logging, get_logger

configure_logging(log_level="WARNING")  # silence collectors during diagnostics
log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _q(session, sql: str, *params):
    from sqlalchemy import text
    result = await session.execute(text(sql), list(params) if params else {})
    return result


async def _scalar(session, sql: str, params: dict | None = None):
    from sqlalchemy import text
    result = await session.execute(text(sql), params or {})
    row = result.fetchone()
    return row[0] if row else None


async def _rows(session, sql: str, params: dict | None = None):
    from sqlalchemy import text
    result = await session.execute(text(sql), params or {})
    return result.fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — Markets inventory
# ─────────────────────────────────────────────────────────────────────────────

async def section1_markets(session) -> dict:
    total = await _scalar(session, "SELECT COUNT(*) FROM markets")
    resolved = await _scalar(
        session, "SELECT COUNT(*) FROM markets WHERE resolved_at IS NOT NULL"
    )
    with_outcome = await _scalar(
        session,
        "SELECT COUNT(*) FROM markets WHERE resolution_outcome IS NOT NULL",
    )
    with_evidence = await _scalar(
        session,
        "SELECT COUNT(*) FROM markets WHERE resolution_evidence_url IS NOT NULL",
    )
    by_category = await _rows(
        session,
        """
        SELECT
            COALESCE(category_fflow, '(uncategorised)') AS cat,
            COUNT(*) AS n,
            COUNT(*) FILTER (WHERE resolved_at IS NOT NULL) AS resolved
        FROM markets
        GROUP BY cat ORDER BY n DESC LIMIT 20
        """,
    )
    # top categories among resolved
    resolved_by_cat = await _rows(
        session,
        """
        SELECT
            COALESCE(category_fflow, '(uncategorised)') AS cat,
            COUNT(*) AS n
        FROM markets
        WHERE resolved_at IS NOT NULL
        GROUP BY cat ORDER BY n DESC LIMIT 20
        """,
    )
    # oldest and newest resolved_at
    ts_range = await _rows(
        session,
        "SELECT MIN(resolved_at), MAX(resolved_at) FROM markets WHERE resolved_at IS NOT NULL",
    )
    # sample of resolved market questions
    sample_q = await _rows(
        session,
        """
        SELECT question, category_fflow, resolved_at::date
        FROM markets
        WHERE resolved_at IS NOT NULL
        ORDER BY resolved_at DESC
        LIMIT 10
        """,
    )

    return {
        "total": total,
        "resolved": resolved,
        "with_outcome": with_outcome,
        "with_evidence_url": with_evidence,
        "by_category": by_category,
        "resolved_by_cat": resolved_by_cat,
        "ts_range": ts_range,
        "sample_questions": sample_q,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — Trades
# ─────────────────────────────────────────────────────────────────────────────

async def section2_trades(session) -> dict:
    total_trades = await _scalar(session, "SELECT COUNT(*) FROM trades")
    markets_with_trades = await _scalar(
        session, "SELECT COUNT(DISTINCT market_id) FROM trades"
    )
    # How many resolved markets have at least 1 trade?
    resolved_with_trades = await _scalar(
        session,
        """
        SELECT COUNT(DISTINCT m.id)
        FROM markets m
        JOIN trades t ON t.market_id = m.id
        WHERE m.resolved_at IS NOT NULL
        """,
    )
    resolved_without_trades = await _scalar(
        session,
        """
        SELECT COUNT(*)
        FROM markets m
        WHERE m.resolved_at IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM trades t WHERE t.market_id = m.id)
        """,
    )
    # top markets by trade count
    top_markets = await _rows(
        session,
        """
        SELECT market_id, COUNT(*) AS n, MIN(ts) AS first_ts, MAX(ts) AS last_ts
        FROM trades
        GROUP BY market_id
        ORDER BY n DESC LIMIT 10
        """,
    )
    # last data_collection_runs for subgraph
    last_runs = await _rows(
        session,
        """
        SELECT target, started_at, finished_at, status, n_records_written, error_message
        FROM data_collection_runs
        WHERE collector = 'subgraph_trades'
        ORDER BY started_at DESC LIMIT 10
        """,
    )
    return {
        "total_trades": total_trades,
        "markets_with_trades": markets_with_trades,
        "resolved_with_trades": resolved_with_trades,
        "resolved_without_trades": resolved_without_trades,
        "top_markets": top_markets,
        "last_runs": last_runs,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section 3 — Prices
# ─────────────────────────────────────────────────────────────────────────────

async def section3_prices(session) -> dict:
    total_prices = await _scalar(session, "SELECT COUNT(*) FROM prices")
    markets_with_prices = await _scalar(
        session, "SELECT COUNT(DISTINCT market_id) FROM prices"
    )
    resolved_with_prices = await _scalar(
        session,
        """
        SELECT COUNT(DISTINCT m.id)
        FROM markets m
        JOIN prices p ON p.market_id = m.id
        WHERE m.resolved_at IS NOT NULL
        """,
    )
    resolved_without_prices = await _scalar(
        session,
        """
        SELECT COUNT(*)
        FROM markets m
        WHERE m.resolved_at IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM prices p WHERE p.market_id = m.id)
        """,
    )
    last_runs = await _rows(
        session,
        """
        SELECT target, started_at, finished_at, status, n_records_written, error_message
        FROM data_collection_runs
        WHERE collector = 'clob_prices'
        ORDER BY started_at DESC LIMIT 5
        """,
    )
    # markets with prices but no trades
    prices_no_trades = await _scalar(
        session,
        """
        SELECT COUNT(DISTINCT p.market_id)
        FROM prices p
        WHERE NOT EXISTS (SELECT 1 FROM trades t WHERE t.market_id = p.market_id)
        """,
    )
    return {
        "total_prices": total_prices,
        "markets_with_prices": markets_with_prices,
        "resolved_with_prices": resolved_with_prices,
        "resolved_without_prices": resolved_without_prices,
        "prices_no_trades": prices_no_trades,
        "last_runs": last_runs,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section 4 — Evidence URLs & T_news
# ─────────────────────────────────────────────────────────────────────────────

async def section4_tnews(session) -> dict:
    total_nt = await _scalar(session, "SELECT COUNT(*) FROM news_timestamps")
    by_tier = await _rows(
        session,
        "SELECT tier, COUNT(*) AS n FROM news_timestamps GROUP BY tier ORDER BY tier",
    )
    with_evidence = await _scalar(
        session,
        "SELECT COUNT(*) FROM markets WHERE resolution_evidence_url IS NOT NULL",
    )
    evidence_domains = await _rows(
        session,
        r"""
        SELECT
            substring(resolution_evidence_url FROM 'https?://([^/]+)') AS domain,
            COUNT(*) AS n
        FROM markets
        WHERE resolution_evidence_url IS NOT NULL
        GROUP BY domain ORDER BY n DESC LIMIT 15
        """,
    )
    # resolved markets with evidence URL but no T_news
    evidence_no_tnews = await _scalar(
        session,
        """
        SELECT COUNT(*)
        FROM markets m
        WHERE m.resolved_at IS NOT NULL
          AND m.resolution_evidence_url IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM news_timestamps n WHERE n.market_id = m.id)
        """,
    )
    # sample Tier 1 results
    tier1_sample = await _rows(
        session,
        """
        SELECT nt.market_id, nt.t_news, nt.source_url, nt.confidence, m.question
        FROM news_timestamps nt
        JOIN markets m ON m.id = nt.market_id
        WHERE nt.tier = 1
        ORDER BY nt.recovered_at DESC LIMIT 10
        """,
    )
    # last tier1 CLI runs
    last_runs = await _rows(
        session,
        """
        SELECT target, started_at, status, n_records_written, error_message
        FROM data_collection_runs
        WHERE collector = 'news_tier1'
        ORDER BY started_at DESC LIMIT 5
        """,
    )
    return {
        "total_nt": total_nt,
        "by_tier": by_tier,
        "with_evidence_url": with_evidence,
        "evidence_domains": evidence_domains,
        "evidence_no_tnews": evidence_no_tnews,
        "tier1_sample": tier1_sample,
        "last_runs": last_runs,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section 5 — Wallets
# ─────────────────────────────────────────────────────────────────────────────

async def section5_wallets(session) -> dict:
    total_wallets = await _scalar(session, "SELECT COUNT(*) FROM wallets")
    with_chain_data = await _scalar(
        session,
        "SELECT COUNT(*) FROM wallets WHERE first_seen_chain_at IS NOT NULL",
    )
    with_funding = await _scalar(
        session,
        "SELECT COUNT(*) FROM wallets WHERE funding_sources IS NOT NULL AND funding_sources != '[]'::jsonb",
    )
    stale_30d = await _scalar(
        session,
        """
        SELECT COUNT(*) FROM wallets
        WHERE last_refreshed_at < NOW() - INTERVAL '30 days'
           OR first_seen_chain_at IS NULL
        """,
    )
    last_runs = await _rows(
        session,
        """
        SELECT target, started_at, status, n_records_written, error_message
        FROM data_collection_runs
        WHERE collector = 'polygonscan'
        ORDER BY started_at DESC LIMIT 5
        """,
    )
    return {
        "total_wallets": total_wallets,
        "with_chain_data": with_chain_data,
        "with_funding": with_funding,
        "stale_30d": stale_30d,
        "last_runs": last_runs,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section 6 — Gamma collection audit
# ─────────────────────────────────────────────────────────────────────────────

async def section6_gamma_audit(session) -> dict:
    last_runs = await _rows(
        session,
        """
        SELECT started_at, finished_at, status, n_records_written,
               left(error_message, 200) AS error_message
        FROM data_collection_runs
        WHERE collector = 'gamma'
        ORDER BY started_at DESC LIMIT 5
        """,
    )
    # category distribution — shows what Gamma actually returned
    cat_dist = await _rows(
        session,
        """
        SELECT
            COALESCE(category_fflow, '(uncategorised)') AS cat,
            COUNT(*) AS n,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
        FROM markets
        GROUP BY cat ORDER BY n DESC
        """,
    )
    # last_refreshed_at distribution — did Gamma recently run?
    refresh_buckets = await _rows(
        session,
        """
        SELECT
            CASE
                WHEN last_refreshed_at > NOW() - INTERVAL '1 day' THEN '<1d ago'
                WHEN last_refreshed_at > NOW() - INTERVAL '7 days' THEN '1-7d ago'
                WHEN last_refreshed_at > NOW() - INTERVAL '30 days' THEN '7-30d ago'
                ELSE '>30d ago'
            END AS bucket,
            COUNT(*) AS n
        FROM markets
        GROUP BY bucket ORDER BY MIN(last_refreshed_at) DESC
        """,
    )
    # what categories does gamma's raw tag look like?
    raw_cat_sample = await _rows(
        session,
        """
        SELECT category_raw, COUNT(*) AS n
        FROM markets
        GROUP BY category_raw ORDER BY n DESC LIMIT 20
        """,
    )
    # political / geopolitical count
    political = await _scalar(
        session,
        """
        SELECT COUNT(*) FROM markets
        WHERE category_fflow IN ('politics_us', 'politics_intl', 'geopolitics', 'military_geopolitics')
        """,
    )
    return {
        "last_runs": last_runs,
        "cat_dist": cat_dist,
        "refresh_buckets": refresh_buckets,
        "raw_cat_sample": raw_cat_sample,
        "political_count": political,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section 7 — Labels & ILS
# ─────────────────────────────────────────────────────────────────────────────

async def section7_labels(session) -> dict:
    total_labels = await _scalar(session, "SELECT COUNT(*) FROM market_labels")
    with_ils = await _scalar(
        session, "SELECT COUNT(*) FROM market_labels WHERE ils IS NOT NULL"
    )
    flags_dist = await _rows(
        session,
        """
        SELECT flag, COUNT(*) AS n
        FROM market_labels, unnest(flags) AS flag
        GROUP BY flag ORDER BY n DESC
        """,
    )
    sample = await _rows(
        session,
        """
        SELECT market_id, ils, flags, computed_at
        FROM market_labels
        ORDER BY computed_at DESC LIMIT 10
        """,
    )
    return {
        "total_labels": total_labels,
        "with_ils": with_ils,
        "flags_dist": flags_dist,
        "sample": sample,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Hypothesis evaluation
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_hypotheses(s1, s2, s3, s4, s5, s6) -> dict[str, bool]:
    resolved = s1["resolved"] or 0
    political = s6["political_count"] or 0
    total = s1["total"] or 1

    h1 = political < max(50, resolved * 0.15)  # <15% political/geopolitical

    h2 = (s2["resolved_with_trades"] or 0) == 0 or (
        (s2["resolved_without_trades"] or 0) > resolved * 0.5
    )

    h3 = (s5["stale_30d"] or 0) > (s5["total_wallets"] or 0) * 0.8 or (
        (s5["with_chain_data"] or 0) == 0
    )

    evidence_no_tnews = s4["evidence_no_tnews"] or 0
    h4 = evidence_no_tnews > 0

    # H5: markets have prices AND T_news but ILS still null (price gap around T_news)
    # we approximate: resolved_with_prices > 0 but total_nt == 0
    h5 = (s3["resolved_with_prices"] or 0) > 0 and (s4["total_nt"] or 0) == 0

    return {"H1": h1, "H2": h2, "H3": h3, "H4": h4, "H5": h5}


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — Conditional reruns
# ─────────────────────────────────────────────────────────────────────────────

async def phase2_rerun_subgraph(session, limit: int = 20) -> str:
    """Run subgraph for resolved markets that have prices but no trades."""
    from fflow.collectors.subgraph import SubgraphCollector

    market_ids = await _rows(
        session,
        """
        SELECT DISTINCT p.market_id
        FROM prices p
        JOIN markets m ON m.id = p.market_id
        WHERE m.resolved_at IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM trades t WHERE t.market_id = p.market_id)
        ORDER BY p.market_id
        LIMIT :limit
        """,
        {"limit": limit},
    )

    if not market_ids:
        return "subgraph: no candidate markets found"

    collector = SubgraphCollector()
    results = []
    for (mid,) in market_ids:
        try:
            r = await collector.run(market_id=mid)
            results.append(f"  {mid[:20]}… → {r.status} ({r.n_written} trades)")
        except Exception as exc:  # noqa: BLE001
            results.append(f"  {mid[:20]}… → ERROR: {exc}")

    return f"subgraph reruns ({len(market_ids)} markets):\n" + "\n".join(results)


async def phase2_rerun_polygonscan(session) -> str:
    """Run polygonscan for all stale wallets (no chain data)."""
    from fflow.collectors.polygonscan import PolygonscanCollector

    collector = PolygonscanCollector()
    try:
        r = await collector.run(all_stale=True, max_age_days=30)
        return f"polygonscan: {r.status}, {r.n_written} wallets enriched"
    except Exception as exc:  # noqa: BLE001
        return f"polygonscan: ERROR {exc}"


async def phase2_rerun_tier1(session) -> str:
    """Run Tier 1 T_news recovery for resolved markets with evidence URL but no T_news."""
    from fflow.news.proposer_url import fetch_proposer_timestamp as fetch_proposer_tnews

    candidate_rows = await _rows(
        session,
        """
        SELECT m.id, m.question, m.resolution_evidence_url, m.resolved_at
        FROM markets m
        WHERE m.resolved_at IS NOT NULL
          AND m.resolution_evidence_url IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM news_timestamps n WHERE n.market_id = m.id)
        ORDER BY m.resolved_at DESC
        LIMIT 30
        """,
    )

    if not candidate_rows:
        return "tier1: no candidates"

    from fflow.models import NewsTimestamp
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    now = datetime.now(UTC)
    written = 0
    skipped = 0
    errors = 0
    log_lines: list[str] = []

    for mid, question, url, resolved_at in candidate_rows:
        try:
            result = await fetch_proposer_tnews(url)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            log_lines.append(f"  {mid[:20]}… ERR {exc}")
            continue

        if result is None:
            skipped += 1
            log_lines.append(f"  {mid[:20]}… SKIP (no date in {url[:60]})")
            continue

        stmt = (
            pg_insert(NewsTimestamp)
            .values(
                market_id=mid,
                t_news=result.t_news,
                tier=1,
                source_url=url,
                confidence=str(result.confidence),
                recovered_at=now,
            )
            .on_conflict_do_update(
                index_elements=["market_id"],
                set_={"t_news": pg_insert(NewsTimestamp).excluded.t_news,
                      "tier": pg_insert(NewsTimestamp).excluded.tier,
                      "confidence": pg_insert(NewsTimestamp).excluded.confidence,
                      "recovered_at": pg_insert(NewsTimestamp).excluded.recovered_at},
            )
        )
        await session.execute(stmt)
        written += 1
        log_lines.append(f"  {mid[:20]}… OK {result.t_news.date()} conf={result.confidence}")

    await session.commit()
    summary = f"tier1: {len(candidate_rows)} tried, {written} written, {skipped} skipped, {errors} errors"
    return summary + "\n" + "\n".join(log_lines[:30])


# ─────────────────────────────────────────────────────────────────────────────
# Report rendering
# ─────────────────────────────────────────────────────────────────────────────

_MAX_CELL = 120  # truncate long cells so one bad column doesn't balloon the report


def _cell(v) -> str:
    s = str(v) if v is not None else ""
    return s if len(s) <= _MAX_CELL else s[:_MAX_CELL - 1] + "…"


def _table(rows, headers: list[str]) -> str:
    if not rows:
        return "(none)"
    cells = [[_cell(r[i]) for i in range(len(headers))] for r in rows]
    widths = [max(len(str(h)), max((len(c[i]) for c in cells), default=0))
               for i, h in enumerate(headers)]
    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    head = "| " + " | ".join(str(h).ljust(w) for h, w in zip(headers, widths)) + " |"
    body = "\n".join(
        "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(row)) + " |"
        for row in cells
    )
    return f"{head}\n{sep}\n{body}"


def render_report(
    s1, s2, s3, s4, s5, s6, s7, hypotheses: dict[str, bool],
    phase2_log: list[str],
    s2b=None, s3b=None, s4b=None, s5b=None,
) -> str:
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    verdict_emoji = "🟢" if hypotheses.get("H2") is False and hypotheses.get("H4") is False else "🔴"

    lines: list[str] = [
        f"# STATE_ASSESSMENT — {ts}",
        "",
        f"**Verdict:** {verdict_emoji}  (H1={hypotheses['H1']} H2={hypotheses['H2']} "
        f"H3={hypotheses['H3']} H4={hypotheses['H4']} H5={hypotheses['H5']})",
        "",
    ]

    # ── Section 1 ────────────────────────────────────────────────────────────
    lines += [
        "## 1. Markets Inventory",
        "",
        f"- Total markets: **{s1['total']}**",
        f"- Resolved: **{s1['resolved']}**  (with outcome: {s1['with_outcome']}, with evidence URL: {s1['with_evidence_url']})",
        "",
        "**Resolved_at range:**",
    ]
    if s1["ts_range"] and s1["ts_range"][0][0]:
        lines.append(f"  {s1['ts_range'][0][0]} → {s1['ts_range'][0][1]}")
    lines += [
        "",
        "**Category distribution (resolved):**",
        "",
        _table(s1["resolved_by_cat"], ["category_fflow", "n_resolved"]),
        "",
        "**Sample questions (10 most recently resolved):**",
        "",
    ]
    for q, cat, dt in (s1["sample_questions"] or []):
        lines.append(f"- [{dt}] `{cat}` — {q[:100]}")
    lines.append("")

    # ── Section 2 ────────────────────────────────────────────────────────────
    lines += [
        "## 2. Trades",
        "",
        f"- Total trade rows: **{s2['total_trades']}**",
        f"- Markets with trades: {s2['markets_with_trades']}",
        f"- Resolved markets WITH trades: {s2['resolved_with_trades']}",
        f"- Resolved markets WITHOUT trades: **{s2['resolved_without_trades']}**",
        "",
        "**Top markets by trade count:**",
        "",
        _table(s2["top_markets"], ["market_id", "n_trades", "first_ts", "last_ts"]),
        "",
        "**Last subgraph collection runs:**",
        "",
        _table(s2["last_runs"],
               ["target", "started_at", "finished_at", "status", "n_written", "error"]),
        "",
    ]

    # ── Section 3 ────────────────────────────────────────────────────────────
    lines += [
        "## 3. Prices",
        "",
        f"- Total price rows: **{s3['total_prices']}**",
        f"- Markets with prices: {s3['markets_with_prices']}",
        f"- Resolved markets WITH prices: {s3['resolved_with_prices']}",
        f"- Resolved markets WITHOUT prices: {s3['resolved_without_prices']}",
        f"- Markets with prices but NO trades: **{s3['prices_no_trades']}**",
        "",
        "**Last CLOB collection runs:**",
        "",
        _table(s3["last_runs"], ["target", "started_at", "finished_at", "status", "n_written", "error"]),
        "",
    ]

    # ── Section 4 ────────────────────────────────────────────────────────────
    lines += [
        "## 4. Evidence URLs & T_news",
        "",
        f"- Markets with resolution_evidence_url: {s4['with_evidence_url']}",
        f"- T_news records (all tiers): **{s4['total_nt']}**",
        f"- Markets with evidence URL but NO T_news: **{s4['evidence_no_tnews']}**",
        "",
        "**T_news by tier:**",
        "",
        _table(s4["by_tier"], ["tier", "n"]),
        "",
        "**Evidence URL domains (top 15):**",
        "",
        _table(s4["evidence_domains"], ["domain", "n"]),
        "",
        "**Tier 1 sample:**",
        "",
        _table(s4["tier1_sample"],
               ["market_id", "t_news", "source_url", "confidence", "question"]),
        "",
    ]

    # ── Section 5 ────────────────────────────────────────────────────────────
    lines += [
        "## 5. Wallets",
        "",
        f"- Total wallets: **{s5['total_wallets']}**",
        f"- With chain data (first_seen_chain_at): {s5['with_chain_data']}",
        f"- With funding sources: {s5['with_funding']}",
        f"- Stale / missing chain data: **{s5['stale_30d']}**",
        "",
        "**Last Polygonscan runs:**",
        "",
        _table(s5["last_runs"], ["target", "started_at", "status", "n_written", "error"]),
        "",
    ]

    # ── Section 6 ────────────────────────────────────────────────────────────
    lines += [
        "## 6. Gamma Collection Audit",
        "",
        "**Last Gamma runs:**",
        "",
        _table(s6["last_runs"],
               ["started_at", "finished_at", "status", "n_written", "error"]),
        "",
        f"- Political/geopolitical markets in DB: **{s6['political_count']}**",
        "",
        "**Category distribution (all markets):**",
        "",
        _table(s6["cat_dist"], ["category_fflow", "n", "pct%"]),
        "",
        "**Top raw category_raw values:**",
        "",
        _table(s6["raw_cat_sample"], ["category_raw", "n"]),
        "",
        "**Market freshness (last_refreshed_at):**",
        "",
        _table(s6["refresh_buckets"], ["bucket", "n"]),
        "",
    ]

    # ── Section 7 ────────────────────────────────────────────────────────────
    lines += [
        "## 7. Labels & ILS",
        "",
        f"- Total market_labels: **{s7['total_labels']}**",
        f"- Labels with ILS value: **{s7['with_ils']}**",
        "",
        "**Flag distribution:**",
        "",
        _table(s7["flags_dist"], ["flag", "n"]),
        "",
    ]

    # ── Hypotheses ────────────────────────────────────────────────────────────
    h_desc = {
        "H1": "Market sample bias — <15% political/geopolitical (Gamma API limitation for closed=true)",
        "H2": "Trades missing — subgraph not yet run for resolved markets",
        "H3": "Wallets missing chain data — polygonscan not yet run",
        "H4": "T_news gap — resolved markets have evidence URL but Tier 1 not run",
        "H5": "ILS blocked — price history exists + T_news exists but no overlap window",
    }
    lines += ["## Root Cause Hypotheses", ""]
    for h, val in hypotheses.items():
        flag = "TRUE 🔴" if val else "false ✅"
        lines.append(f"- **{h}** [{flag}]: {h_desc[h]}")
    lines.append("")

    # ── Phase 2 log ───────────────────────────────────────────────────────────
    if phase2_log:
        lines += ["## Phase 2 — Rerun Log", ""]
        lines += ["```"]
        lines += phase2_log
        lines += ["```", ""]

    # ── Post-rerun snapshot ───────────────────────────────────────────────────
    if s2b or s3b or s4b or s5b:
        lines += ["## Phase 3 — Post-Rerun State", ""]
        if s2b:
            lines += [
                f"- Trades: {s2b['total_trades']} total, "
                f"{s2b['resolved_with_trades']} resolved markets covered, "
                f"{s2b['resolved_without_trades']} still missing",
                "",
            ]
        if s3b:
            lines += [
                f"- Prices: {s3b['total_prices']} rows, {s3b['markets_with_prices']} markets",
                "",
            ]
        if s4b:
            lines += [
                f"- T_news: {s4b['total_nt']} total, {s4b['evidence_no_tnews']} still missing",
                "",
            ]
        if s5b:
            lines += [
                f"- Wallets: {s5b['total_wallets']} total, "
                f"{s5b['with_chain_data']} with chain data, "
                f"{s5b['stale_30d']} still stale",
                "",
            ]

    lines += ["---", f"*Generated by scripts/diagnose_state.py at {ts}*"]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main(run_reruns: bool = True) -> None:
    print("▶ Phase 1: collecting DB state…")
    async with AsyncSessionLocal() as session:
        s1 = await section1_markets(session)
        s2 = await section2_trades(session)
        s3 = await section3_prices(session)
        s4 = await section4_tnews(session)
        s5 = await section5_wallets(session)
        s6 = await section6_gamma_audit(session)
        s7 = await section7_labels(session)

    hypotheses = evaluate_hypotheses(s1, s2, s3, s4, s5, s6)
    print(f"   Hypotheses: {hypotheses}")

    phase2_log: list[str] = []
    s2b = s3b = s4b = s5b = None

    if run_reruns:
        print("▶ Phase 2: conditional reruns…")
        async with AsyncSessionLocal() as session:
            if hypotheses["H2"]:
                print("   H2=TRUE → running subgraph collector…")
                msg = await phase2_rerun_subgraph(session)
                phase2_log.append(msg)
                print(f"   {msg[:120]}")
            else:
                phase2_log.append("subgraph: skipped (H2=FALSE, trades present)")

            if hypotheses["H3"] and (s5["total_wallets"] or 0) > 0:
                print("   H3=TRUE → running polygonscan collector…")
                msg = await phase2_rerun_polygonscan(session)
                phase2_log.append(msg)
                print(f"   {msg[:120]}")
            else:
                phase2_log.append("polygonscan: skipped (H3=FALSE or no wallets)")

            if hypotheses["H4"] and not hypotheses["H1"]:
                print("   H4=TRUE, H1=FALSE → running Tier 1 T_news recovery…")
                msg = await phase2_rerun_tier1(session)
                phase2_log.append(msg)
                print(f"   {msg[:120]}")
            elif hypotheses["H4"] and hypotheses["H1"]:
                phase2_log.append(
                    "tier1: skipped (H4=TRUE but H1=TRUE — sample is biased; "
                    "fix market selection first)"
                )
            else:
                phase2_log.append("tier1: skipped (H4=FALSE, all evidence URLs already processed)")

        print("▶ Phase 3: post-rerun state…")
        async with AsyncSessionLocal() as session:
            s2b = await section2_trades(session)
            s3b = await section3_prices(session)
            s4b = await section4_tnews(session)
            s5b = await section5_wallets(session)
    else:
        phase2_log.append("(reruns skipped via --no-rerun flag)")

    report = render_report(
        s1, s2, s3, s4, s5, s6, s7, hypotheses, phase2_log,
        s2b=s2b, s3b=s3b, s4b=s4b, s5b=s5b,
    )

    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "STATE_ASSESSMENT.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"\n✓ Report written → {out_path}")
    print("\n" + "=" * 70)
    print(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-rerun", dest="run_reruns", action="store_false",
        help="Skip Phase 2 reruns, only produce read-only diagnostic",
    )
    args = parser.parse_args()
    asyncio.run(main(run_reruns=args.run_reruns))
