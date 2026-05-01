"""End-to-end backfill validation script.

Runs the full pipeline on a small sample (≤20 markets, last 90 days)
across all three ForesightFlow categories, then prints a summary report.

Usage: uv run python scripts/backfill_sample.py
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, ".")

from fflow.collectors.clob import ClobCollector
from fflow.collectors.gamma import GammaCollector
from fflow.collectors.polygonscan import PolygonscanCollector
from fflow.collectors.subgraph import SubgraphCollector
from fflow.collectors.uma import UmaCollector
from fflow.log import configure_logging, get_logger
from fflow.taxonomy.classifier import classify_batch

configure_logging("INFO", False)
log = get_logger("backfill_sample")

CATEGORIES = ["politics", "geopolitics", "regulation"]
SINCE = datetime.now(UTC) - timedelta(days=90)
MAX_MARKETS = 20
MAX_WALLETS = 20


async def main() -> None:
    print("=" * 60)
    print("ForesightFlow — Sample Backfill Validation")
    print(f"Since: {SINCE.date()}")
    print("=" * 60)

    # 1. Gamma
    print("\n[1/6] Collecting market metadata (Gamma)...")
    gamma_result = await GammaCollector().run(since=SINCE, categories=CATEGORIES)
    print(f"      → {gamma_result.n_written} markets ingested, status={gamma_result.status}")
    if gamma_result.status == "failed":
        print(f"      ERROR: {gamma_result.error}")
        return

    # Fetch market IDs from DB
    from sqlalchemy import select, text
    from fflow.db import AsyncSessionLocal
    from fflow.models import Market, Trade, Wallet

    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(Market.id, Market.question, Market.resolved_at)
            .order_by(Market.created_at_chain.desc())
            .limit(MAX_MARKETS)
        )
        markets = rows.all()

    print(f"      Working with {len(markets)} markets for subsequent steps")

    # 2. CLOB prices
    print("\n[2/6] Collecting price history (CLOB)...")
    clob_total = 0
    for mid, question, _ in markets:
        try:
            r = await ClobCollector().run(market_id=mid, start_ts=SINCE)
            clob_total += r.n_written
            print(f"      {mid[:16]}... → {r.n_written} prices")
        except Exception as e:
            print(f"      {mid[:16]}... ERROR: {e}")

    # 3. Subgraph trades
    print("\n[3/6] Collecting trade log (subgraph)...")
    trade_total = 0
    for mid, question, _ in markets:
        try:
            r = await SubgraphCollector().run(market_id=mid, from_ts=SINCE)
            trade_total += r.n_written
            print(f"      {mid[:16]}... → {r.n_written} trades")
        except Exception as e:
            print(f"      {mid[:16]}... ERROR: {e}")

    # 4. UMA resolution
    print("\n[4/6] Collecting UMA resolution data...")
    uma_total = 0
    resolved_mids = [mid for mid, _, resolved_at in markets if resolved_at is not None]
    unresolved_mids = [mid for mid, _, resolved_at in markets if resolved_at is None]
    for mid in unresolved_mids[:5]:  # limit to avoid long UMA subgraph scan
        try:
            r = await UmaCollector().run(market_id=mid)
            uma_total += r.n_written
            print(f"      {mid[:16]}... → {r.n_written} resolved")
        except Exception as e:
            print(f"      {mid[:16]}... ERROR: {e}")

    # 5. Polygonscan wallets
    print("\n[5/6] Collecting wallet data (Polygonscan)...")
    async with AsyncSessionLocal() as session:
        from sqlalchemy import func
        top_wallets_q = await session.execute(
            select(Trade.taker_address, func.count().label("n"))
            .group_by(Trade.taker_address)
            .order_by(func.count().desc())
            .limit(MAX_WALLETS)
        )
        top_wallets = [r[0] for r in top_wallets_q.all()]

    poly_total = 0
    collector = PolygonscanCollector()
    for addr in top_wallets:
        try:
            r = await collector.run(wallet=addr)
            poly_total += r.n_written
            print(f"      {addr[:16]}... → {r.n_written} updated")
        except Exception as e:
            print(f"      {addr[:16]}... ERROR: {e}")

    # 6. Taxonomy
    print("\n[6/6] Running taxonomy classifier...")
    n_classified = await classify_batch(limit=1000)
    print(f"      → {n_classified} markets classified")

    # Summary report
    print("\n" + "=" * 60)
    print("SUMMARY REPORT")
    print("=" * 60)
    async with AsyncSessionLocal() as session:
        markets_count = (await session.execute(text("SELECT COUNT(*) FROM markets"))).scalar()
        prices_count = (await session.execute(text("SELECT COUNT(*) FROM prices"))).scalar()
        trades_count = (await session.execute(text("SELECT COUNT(*) FROM trades"))).scalar()
        wallets_count = (await session.execute(text("SELECT COUNT(*) FROM wallets"))).scalar()
        resolved_count = (
            await session.execute(
                text("SELECT COUNT(*) FROM markets WHERE resolved_at IS NOT NULL")
            )
        ).scalar()
        cat_rows = await session.execute(
            text("SELECT category_fflow, COUNT(*) FROM markets GROUP BY 1 ORDER BY 2 DESC")
        )
        cats = cat_rows.all()

    print(f"Markets:      {markets_count}")
    print(f"Prices:       {prices_count}")
    print(f"Trades:       {trades_count}")
    print(f"Wallets:      {wallets_count}")
    print(f"Resolved:     {resolved_count}")
    print("\nCategory breakdown:")
    for cat, count in cats:
        print(f"  {cat or 'NULL':30s} {count}")

    print("\nAcceptance criteria:")
    ok = True
    checks = [
        ("markets >= 10", markets_count >= 10),
        ("prices >= 5000", prices_count >= 5000),
        ("trades >= 100", trades_count >= 100),
        ("wallets >= 20", wallets_count >= 20),
        ("resolved >= 1", resolved_count >= 1),
    ]
    for label, passed in checks:
        status = "✓" if passed else "✗"
        print(f"  [{status}] {label}")
        if not passed:
            ok = False

    print()
    if ok:
        print("All acceptance criteria met.")
    else:
        print("Some criteria not met — check collector errors above.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
