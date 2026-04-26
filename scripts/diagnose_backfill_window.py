"""Backfill window diagnostic.

Investigates:
  A. Why resolved_at is only set for the last 2 hours (599 markets).
  B. Whether Gamma API supports date-range pagination for historical resolved markets.
  C. What's in raw_metadata['closedTime'] and how that relates to resolved_at.
  D. Whether Gamma tags are informative enough to filter for news-based markets.

Usage:
    uv run python scripts/diagnose_backfill_window.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fflow.config import settings
from fflow.log import configure_logging

configure_logging(log_level="WARNING")

SEP = "─" * 70
GAMMA_URL = settings.gamma_api_url


def _hdr(title: str) -> None:
    print(f"\n{SEP}\n{title}\n{SEP}")


async def get(url: str, params: dict | None = None) -> dict | list:
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, params=params or {})
    print(f"  GET {r.url}")
    print(f"  HTTP {r.status_code}  content-length≈{len(r.content)} bytes")
    return r.json()


# ─────────────────────────────────────────────────────────────────────────────
# A. Why resolved_at is limited to last 2 hours
# ─────────────────────────────────────────────────────────────────────────────

async def section_a_resolved_source() -> None:
    _hdr("A. Source of resolved_at in DB")
    from fflow.db import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as session:
        # How many resolved markets, and what fraction have closedTime in raw_metadata?
        r = await session.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE resolved_at IS NOT NULL)                          AS resolved_total,
                COUNT(*) FILTER (WHERE resolved_at IS NOT NULL
                    AND (raw_metadata->>'closedTime') IS NOT NULL)                       AS resolved_with_closed_time,
                COUNT(*) FILTER (WHERE resolved_at IS NOT NULL
                    AND (raw_metadata->>'closedTime') IS NULL)                           AS resolved_no_closed_time,
                COUNT(*) FILTER (WHERE resolved_at IS NULL
                    AND (raw_metadata->>'closedTime') IS NOT NULL)                       AS unresolved_but_has_closed_time,
                COUNT(*) FILTER (WHERE raw_metadata->>'closedTime' IS NOT NULL)          AS total_with_closed_time,
                COUNT(*) FILTER (WHERE (raw_metadata->>'active')::bool = false)         AS inactive_markets,
                COUNT(*) FILTER (WHERE (raw_metadata->>'closed')::bool = true)          AS closed_markets
            FROM markets
        """))
        row = r.fetchone()
        print(f"  resolved_at IS NOT NULL                        : {row[0]}")
        print(f"  resolved_at + closedTime in raw_metadata       : {row[1]}")
        print(f"  resolved_at but NO closedTime                  : {row[2]}")
        print(f"  closedTime present but resolved_at IS NULL     : {row[3]}  ← backfill potential")
        print(f"  total markets with closedTime in raw_metadata  : {row[4]}")
        print(f"  markets where active=false                     : {row[5]}")
        print(f"  markets where closed=true                      : {row[6]}")

        # Show sample where closedTime exists but resolved_at is null
        r2 = await session.execute(text("""
            SELECT id, question,
                   raw_metadata->>'closedTime'  AS closed_time,
                   raw_metadata->>'endDate'     AS end_date,
                   raw_metadata->>'active'      AS active,
                   raw_metadata->>'closed'      AS closed_flag,
                   category_fflow
            FROM markets
            WHERE (raw_metadata->>'closedTime') IS NOT NULL
              AND resolved_at IS NULL
            ORDER BY (raw_metadata->>'closedTime') DESC
            LIMIT 10
        """))
        rows = r2.fetchall()
        print(f"\n  Sample 'closedTime but no resolved_at' (newest first):")
        for row in rows:
            print(f"    [{row.closed_time}] [{row.category_fflow}] {row.question[:70]}")

        # UMA runs in DCR
        r3 = await session.execute(text("""
            SELECT started_at, finished_at, status, n_records_written, left(error_message, 100)
            FROM data_collection_runs
            WHERE collector = 'uma'
            ORDER BY started_at DESC LIMIT 5
        """))
        uma_rows = r3.fetchall()
        print(f"\n  UMA collector runs:")
        if uma_rows:
            for row in uma_rows:
                print(f"    {row}")
        else:
            print("    (no UMA runs recorded)")


# ─────────────────────────────────────────────────────────────────────────────
# B. Gamma code audit — what parameters are used
# ─────────────────────────────────────────────────────────────────────────────

async def section_b_gamma_code_audit() -> None:
    _hdr("B. gamma.py code audit — relevant query parameters")
    code_path = ROOT / "fflow" / "collectors" / "gamma.py"
    src = code_path.read_text()

    # Extract _paginate method
    start = src.find("async def _paginate")
    end = src.find("\n    async def ", start + 1)
    if end == -1:
        end = src.find("\n\ndef ", start + 1)
    print(src[start:end])

    print("\n  KEY OBSERVATIONS:")
    if "closed" in src:
        closed_idx = [i for i in range(len(src)) if src[i:i+6] == "closed"]
        for idx in closed_idx:
            ctx = src[max(0, idx-30):idx+60]
            print(f"    'closed' found: ...{ctx}...")
    else:
        print("    'closed' parameter: NOT used → fetches active markets only")

    if "end_date" in src.lower():
        print("    'end_date' filter: FOUND")
    else:
        print("    'end_date' filter: NOT used")

    if "start_date" in src.lower():
        print("    'start_date' filter: FOUND")
    else:
        print("    'start_date' filter: NOT used")


# ─────────────────────────────────────────────────────────────────────────────
# C. Gamma API — does it support historical date-range queries?
# ─────────────────────────────────────────────────────────────────────────────

async def section_c_gamma_date_range() -> None:
    _hdr("C. Gamma API — date-range queries for historical resolved markets")

    # Test 1: closed=true without date filter (what does it return?)
    print("  Test 1: closed=true, no date filter, limit=5")
    data = await get(f"{GAMMA_URL}/markets", {
        "closed": "true",
        "limit": 5,
        "order": "closedTime",
        "ascending": "false",
    })
    markets = data if isinstance(data, list) else data.get("markets", [])
    print(f"  → {len(markets)} markets")
    for m in markets[:3]:
        print(f"    [{m.get('closedTime', '?')}] {m.get('question', '?')[:70]}")

    # Test 2: closed=true with end_date_min/end_date_max for August 2024 (US election season)
    print("\n  Test 2: closed=true + end_date_min=2024-08-01 + end_date_max=2024-08-31")
    data2 = await get(f"{GAMMA_URL}/markets", {
        "closed": "true",
        "end_date_min": "2024-08-01",
        "end_date_max": "2024-08-31",
        "limit": 10,
        "order": "endDate",
        "ascending": "false",
    })
    markets2 = data2 if isinstance(data2, list) else data2.get("markets", [])
    print(f"  → {len(markets2)} markets for Aug 2024 (end_date)")
    for m in markets2[:5]:
        print(f"    [{m.get('closedTime','?')}] [{m.get('tags','?')}] {m.get('question','?')[:70]}")

    # Test 3: closed=true with start_date filter (using createdAt window Aug 2024)
    print("\n  Test 3: closed=true + start_date_min=2024-08-01 + start_date_max=2024-08-31")
    data3 = await get(f"{GAMMA_URL}/markets", {
        "closed": "true",
        "start_date_min": "2024-08-01",
        "start_date_max": "2024-08-31",
        "limit": 10,
    })
    markets3 = data3 if isinstance(data3, list) else data3.get("markets", [])
    print(f"  → {len(markets3)} markets for Aug 2024 (start_date)")
    for m in markets3[:5]:
        print(f"    [{m.get('closedTime','?')}] {m.get('question','?')[:70]}")

    # Test 4: closed=true + closed_time_min/max
    print("\n  Test 4: closed=true + closed_time_min=2024-08-01 + closed_time_max=2024-08-31")
    data4 = await get(f"{GAMMA_URL}/markets", {
        "closed": "true",
        "closed_time_min": "2024-08-01",
        "closed_time_max": "2024-08-31",
        "limit": 10,
    })
    markets4 = data4 if isinstance(data4, list) else data4.get("markets", [])
    print(f"  → {len(markets4)} markets for Aug 2024 (closed_time)")
    for m in markets4[:5]:
        print(f"    [{m.get('closedTime','?')}] {m.get('question','?')[:70]}")

    # Test 5: volume ordering — does sorting by volume reveal high-signal markets?
    print("\n  Test 5: closed=true + order=volume + limit=10 (high-volume historical)")
    data5 = await get(f"{GAMMA_URL}/markets", {
        "closed": "true",
        "limit": 10,
        "order": "volume",
        "ascending": "false",
    })
    markets5 = data5 if isinstance(data5, list) else data5.get("markets", [])
    print(f"  → {len(markets5)} markets by volume desc")
    for m in markets5[:5]:
        print(f"    vol=${float(m.get('volume', 0) or 0):,.0f}  [{m.get('closedTime','?')[:10]}]  {m.get('question','?')[:60]}")


# ─────────────────────────────────────────────────────────────────────────────
# D. Search for Iran strike market (Feb 2026 insider case)
# ─────────────────────────────────────────────────────────────────────────────

async def section_d_iran_search() -> None:
    _hdr("D. Searching for geopolitical markets (Iran/elections)")

    # Attempt text search if the API supports it
    print("  Test 1: text search with q=iran")
    data = await get(f"{GAMMA_URL}/markets", {
        "q": "iran",
        "closed": "true",
        "limit": 10,
    })
    markets = data if isinstance(data, list) else data.get("markets", [])
    print(f"  → {len(markets)} results")
    for m in markets[:5]:
        print(f"    [{m.get('closedTime','?')[:10]}] {m.get('question','?')[:70]}")

    # Try tag-based search
    print("\n  Test 2: tag=iran + closed=true")
    data2 = await get(f"{GAMMA_URL}/markets", {
        "tag": "iran",
        "closed": "true",
        "limit": 10,
    })
    markets2 = data2 if isinstance(data2, list) else data2.get("markets", [])
    print(f"  → {len(markets2)} results for tag=iran")
    for m in markets2[:5]:
        print(f"    [{m.get('closedTime','?')[:10]}] {m.get('question','?')[:70]}")

    # Try tag=politics + date range
    print("\n  Test 3: tag=politics + closed=true + limit=10 (any date)")
    data3 = await get(f"{GAMMA_URL}/markets", {
        "tag": "politics",
        "closed": "true",
        "limit": 10,
        "order": "volume",
        "ascending": "false",
    })
    markets3 = data3 if isinstance(data3, list) else data3.get("markets", [])
    print(f"  → {len(markets3)} results for tag=politics+closed")
    for m in markets3[:5]:
        vol = float(m.get('volume', 0) or 0)
        print(f"    vol=${vol:,.0f}  [{m.get('closedTime','?')[:10]}] {m.get('question','?')[:70]}")

    # Try events endpoint (events have categories)
    print("\n  Test 4: /events endpoint (category=politics)")
    data4 = await get(f"{GAMMA_URL}/events", {
        "closed": "true",
        "tag": "politics",
        "limit": 10,
        "order": "volume",
        "ascending": "false",
    })
    events = data4 if isinstance(data4, list) else data4.get("events", [])
    print(f"  → {len(events)} events for category=politics+closed")
    for e in events[:5]:
        print(f"    [{e.get('closedTime','?')[:10] if isinstance(e, dict) else '?'}] {str(e)[:100]}")


# ─────────────────────────────────────────────────────────────────────────────
# E. Tags assessment — are Gamma tags informative?
# ─────────────────────────────────────────────────────────────────────────────

async def section_e_tags_assessment() -> None:
    _hdr("E. Tags assessment — are Gamma tags informative?")
    from fflow.db import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as session:
        # Show distribution of tags from raw_metadata
        r = await session.execute(text("""
            SELECT
                tag_val,
                COUNT(*) AS n,
                COUNT(*) FILTER (WHERE category_fflow = 'military_geopolitics') AS geopolitical,
                COUNT(*) FILTER (WHERE category_fflow = 'politics_us') AS politics_us
            FROM markets,
                 jsonb_array_elements_text(
                     CASE jsonb_typeof(raw_metadata->'tags')
                         WHEN 'array' THEN raw_metadata->'tags'
                         ELSE '[]'::jsonb
                     END
                 ) AS tag_val
            GROUP BY tag_val
            ORDER BY n DESC
            LIMIT 30
        """))
        tag_rows = r.fetchall()
        print(f"  Top 30 tags (from raw_metadata.tags array):")
        if tag_rows:
            for row in tag_rows:
                print(f"    {row.tag_val:40s}  n={row.n:5d}  geo={row.geopolitical}  pol={row.politics_us}")
        else:
            print("    → No array tags found. Trying slug/string field...")

        # Many Polymarket markets store tags as a single string or in events
        r2 = await session.execute(text("""
            SELECT
                raw_metadata->>'tags' AS tags_raw,
                category_fflow,
                question
            FROM markets
            WHERE raw_metadata->>'tags' IS NOT NULL
              AND raw_metadata->>'tags' != 'null'
              AND raw_metadata->>'tags' != '[]'
            ORDER BY random()
            LIMIT 10
        """))
        sample_tags = r2.fetchall()
        print(f"\n  Sample 10 markets with non-empty tags:")
        for row in sample_tags:
            print(f"    tags={str(row.tags_raw)[:50]}  cat={row.category_fflow}  q={row.question[:50]}")

        # 30 random pairs for geopolitical markets
        r3 = await session.execute(text("""
            SELECT
                raw_metadata->>'tags' AS tags_raw,
                raw_metadata#>'{events,0,tag}' AS event_tag,
                category_fflow,
                question,
                raw_metadata->>'closedTime' AS closed_time
            FROM markets
            WHERE category_fflow IN ('military_geopolitics', 'politics_us', 'politics_intl', 'geopolitics')
            ORDER BY random()
            LIMIT 30
        """))
        geo_sample = r3.fetchall()
        print(f"\n  30 random geopolitical/political markets — (tags, question):")
        for row in geo_sample:
            tags = row.tags_raw or row.event_tag or "(no tag)"
            print(f"    [{str(tags)[:30]}] {row.question[:65]}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    await section_a_resolved_source()
    await section_b_gamma_code_audit()
    await section_c_gamma_date_range()
    await section_d_iran_search()
    await section_e_tags_assessment()
    print(f"\n{SEP}\nDone. See findings above.\n{SEP}")


if __name__ == "__main__":
    asyncio.run(main())
