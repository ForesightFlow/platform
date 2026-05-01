#!/usr/bin/env python
"""End-to-end pipeline: Tier 1 T_news → ILS scoring for a batch of markets.

Usage:
    uv run python scripts/label_sample.py [--limit N] [--dry-run]

Steps per market:
  1. Try Tier 1 (proposer URL). If success → save NewsTimestamp.
  2. If Tier 1 fails, try Tier 2 (GDELT). If success → save NewsTimestamp.
  3. compute_market_label() → MarketLabel.

Prints a summary table at the end.
"""

import asyncio
import sys
from datetime import UTC, datetime

import typer

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from fflow.config import settings
from fflow.db import AsyncSessionLocal
from fflow.models import Market, NewsTimestamp
from fflow.news.gdelt import search_gdelt
from fflow.news.proposer_url import fetch_proposer_timestamp
from fflow.scoring.pipeline import compute_market_label
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert


async def _upsert_news(session, market_id: str, tier: int, t_news, confidence, **kwargs):
    stmt = (
        pg_insert(NewsTimestamp)
        .values(
            market_id=market_id,
            t_news=t_news,
            tier=tier,
            confidence=confidence,
            recovered_at=datetime.now(UTC),
            **kwargs,
        )
        .on_conflict_do_update(
            index_elements=["market_id"],
            set_={"t_news": t_news, "tier": tier, "confidence": confidence},
        )
    )
    await session.execute(stmt)
    await session.commit()


async def label_sample(limit: int = 50, dry_run: bool = False):
    results = []

    async with AsyncSessionLocal() as session:
        markets = (
            await session.execute(
                select(Market)
                .where(Market.resolution_outcome.isnot(None))
                .where(Market.created_at_chain.isnot(None))
                .where(Market.resolved_at.isnot(None))
                .limit(limit)
            )
        ).scalars().all()

    print(f"Processing {len(markets)} markets…")

    for mkt in markets:
        tier_used = None
        t_news = None

        # Check existing NewsTimestamp
        async with AsyncSessionLocal() as session:
            existing = await session.get(NewsTimestamp, mkt.id)

        if existing:
            tier_used = existing.tier
            t_news = existing.t_news
        else:
            # Tier 1
            if mkt.resolution_evidence_url:
                result = await fetch_proposer_timestamp(mkt.resolution_evidence_url)
                if result:
                    tier_used = 1
                    t_news = result.t_news
                    if not dry_run:
                        async with AsyncSessionLocal() as session:
                            await _upsert_news(
                                session, mkt.id, 1, t_news, result.confidence,
                                source_url=result.source_url,
                            )

            # Tier 2 fallback
            if t_news is None:
                gdelt_result = await search_gdelt(
                    question=mkt.question,
                    t_resolve=mkt.resolved_at or datetime.now(UTC),
                    t_open=mkt.created_at_chain,
                )
                if gdelt_result:
                    tier_used = 2
                    t_news = gdelt_result.t_news
                    if not dry_run:
                        async with AsyncSessionLocal() as session:
                            await _upsert_news(
                                session, mkt.id, 2, t_news, gdelt_result.confidence,
                                source_url=gdelt_result.source_url,
                                source_publisher=gdelt_result.source_publisher,
                                query_keywords=gdelt_result.query_keywords,
                            )

        if t_news is None:
            results.append((mkt.id[:12], "—", "no t_news", None))
            continue

        # Score
        async with AsyncSessionLocal() as session:
            label = await compute_market_label(session, mkt.id, dry_run=dry_run)

        ils_str = str(label.ils) if label and label.ils is not None else "null"
        flags_str = ",".join(label.flags) if label else "prerequisite_failed"
        results.append((mkt.id[:12], f"tier{tier_used}", ils_str, flags_str))

    # Summary
    print(f"\n{'ID':>14}  {'Tier':<6}  {'ILS':>10}  Flags")
    print("-" * 60)
    for row in results:
        print(f"{row[0]:>14}  {row[1]:<6}  {str(row[2]):>10}  {row[3] or ''}")

    n_scored = sum(1 for r in results if r[2] not in (None, "null", "no t_news"))
    print(f"\nTotal: {len(results)} markets, {n_scored} scored")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(label_sample(limit=args.limit, dry_run=args.dry_run))
