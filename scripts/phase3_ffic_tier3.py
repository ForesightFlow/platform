"""Phase 3 — Tier 3 T_event recovery for FFIC (Iran/military) cluster.

Targets ~15 substantive deadline-YES markets about actual geopolitical events
(military strikes, diplomatic meetings, ceasefire/conflict resolution).

Already processed: US forces enter Iran (Apr30), US×Iran ceasefire (Apr7),
John Oliver "Iran" episode — excluded.

Usage:
    uv run python scripts/phase3_ffic_tier3.py --confirm
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
from sqlalchemy import select

from fflow.db import AsyncSessionLocal
from fflow.models import Market, NewsTimestamp
from fflow.news.llm_match import llm_extract_date, reset_call_counter

log = structlog.get_logger()

# Substantive FFIC markets: actual military/diplomatic events (not speech bingo)
# Grouped by event cluster for cross-market analysis
FFIC_TARGETS = [
    # --- US-Iran military engagement cluster (2026-03 to 2026-04) ---
    "0xb2a02ec1302923548722a92a0d21a0c440915ad15c429b5a61e825b4b1c82047",  # Military action against Iran ends by April 11
    "0x8d050a7e7b301544e0c5ae7160bfaf6602a28f8a09cd7d34b185fd7dd0f3299a",  # Military action against Iran ends by April 10
    "0x1d26da1a9cc0d92d79d44419493ff14bd05f813fddfbb2cd035e1d6fbbceaaab",  # Iran strike on US military by March 31
    "0x60b784f62abc35e1337c88945807f3aca380959efecc5ef7c94b0479a35c4f9a",  # Iran strike on Saudi Arabia by Apr 30 (Apr7 open)
    # --- Iran regional strikes cluster (2026-03-24 opens) ---
    "0xb32a8f9d6a33d17afda204649706b6a6e2684f5b4a983b3713da55b51fbe44af",  # Iran strike Kuwait by Apr 30
    "0xeeb11ad524bcd010152f83cc48717e3d815e1cc7c4ba30a6393c512480fc3110",  # Iran strike Israel by Apr 30
    "0x35063394dd3c69b7879e8e07b35d4bd5e6b41e7fbbc30916aac96a00b719c076",  # Iran strike Jordan by Apr 30
    "0x8c6884ff1f49b7069530aae4772ddaac03a3cc16f80d79a38629050822e93249",  # Iran strike Saudi Arabia by Apr 30 (Mar24 open)
    "0x076515957ef9ff4fea74bed263b110a79271abbce3c36fbd2e395ff13182a5cb",  # Iran strike East-West Pipeline by Apr 30
    # --- US-Iran diplomacy cluster (April 2026) ---
    "0x7a07d0fbd168d0395d14bda2e975aa4e3ca446bf790aacf45ea973bb6d38661e",  # JD Vance diplomatic meeting with Iran by Apr 15
    "0x605b4e400519c8313326b3079d74910d2fa1e68417e28532abb2f88543b334c6",  # US x Iran meeting by Apr 14
    "0xdba42146f7ee38014812a2b16bf5714b26284d4bb96d440064a389dfcccf6394",  # US x Iran meeting by Apr 13
    # --- Earlier Iran events (2025) ---
    "0xeff458dac9abcf69cdb56a41c445738058a829b281992d5fe3388f0b3936211d",  # Trump announces military action against Iran before July
    "0x65e2de7aa9d97d3c1fa818321dcba2ead3a44c42a94f29df4b008d1cddb6fa46",  # Israel military action against Iran before August
    # --- Iran response to Israel (2024) ---
    "0x1ece049871ed71da5cc344a1117c6e5095d23ac33b1844e3ee4c9ab4741c3bf3",  # Iran response to Israel by Sunday
    "0x142f700ff49206ba1cbb23d45a7dfafb8203630aa49a926a00c3e97f4ce8c228",  # Iran response to Israel by April 19
    # --- Hezbollah / Russia (collateral cluster) ---
    "0x9dd08ad49749189bbc3ae7b2d2c8711a9ddddec183cc1d8d563e0813510c62a0",  # Hezbollah military action against Israel by March 20
    "0xe0aec59af764e5a24e698626e631c8831ab76a21c51f9a23323f75508c28c43c",  # Russia military action against Kyiv by April 10
]

COST_PER_CALL_EST = 0.09


async def run(confirm: bool, api_key: str) -> None:
    reset_call_counter()
    total_calls = 0
    results = []

    async with AsyncSessionLocal() as session:
        for market_id in FFIC_TARGETS:
            # Check if already processed
            existing = (
                await session.execute(
                    select(NewsTimestamp).where(NewsTimestamp.market_id == market_id)
                )
            ).scalar_one_or_none()
            if existing is not None:
                log.info("phase3_skip_existing", market_id=market_id)
                continue

            mkt = await session.get(Market, market_id)
            if mkt is None:
                log.warning("phase3_market_not_found", market_id=market_id)
                continue

            log.info("phase3_processing", market_id=market_id[:16], question=mkt.question[:70])

            result = await llm_extract_date(
                question=mkt.question,
                description=mkt.description,
                api_key=api_key,
                confirmed=confirm,
                recovery_mode="t_event",
            )
            total_calls += 1

            if result is None:
                log.info("phase3_no_result", market_id=market_id[:16])
                results.append({"market_id": market_id, "question": mkt.question,
                                 "t_event": None, "confidence": 0, "sources": ()})
                continue

            # Store to DB
            from datetime import UTC
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            publisher = ", ".join(result.sources[:3]) if result.sources else None
            now = datetime.now(UTC)
            stmt = (
                pg_insert(NewsTimestamp)
                .values(
                    market_id=market_id,
                    t_news=result.t_news,
                    tier=3,
                    confidence=result.confidence,
                    notes=result.notes,
                    source_publisher=publisher,
                    recovered_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["market_id"],
                    set_={
                        "t_news": result.t_news,
                        "tier": 3,
                        "confidence": result.confidence,
                        "notes": result.notes,
                        "source_publisher": publisher,
                        "recovered_at": now,
                    },
                )
            )
            await session.execute(stmt)
            await session.commit()

            t_open = mkt.created_at_chain
            if t_open and t_open.tzinfo is None:
                t_open = t_open.replace(tzinfo=UTC)
            tau = (result.t_news - t_open).total_seconds() / 86400 if t_open else None

            results.append({
                "market_id": market_id,
                "question": mkt.question,
                "t_open": t_open,
                "t_event": result.t_news,
                "tau_days": tau,
                "confidence": result.confidence,
                "sources": result.sources,
                "notes": result.notes,
            })
            log.info("phase3_stored", market_id=market_id[:16],
                     t_event=result.t_news.strftime("%Y-%m-%d"),
                     tau_days=round(tau, 2) if tau else None,
                     confidence=result.confidence)

    # Print summary table
    print(f"\n{'='*80}")
    print(f"Phase 3 complete: {total_calls} calls | ~${total_calls * COST_PER_CALL_EST:.2f}")
    print(f"{'='*80}")
    print(f"{'Question':<55} {'T_event':^12} {'τ(d)':^7} {'conf':^5}")
    print("-" * 80)
    for r in results:
        q = r["question"][:54]
        t = r["t_event"].strftime("%Y-%m-%d") if r.get("t_event") else "UNKNOWN"
        tau = f"{r['tau_days']:.1f}" if r.get("tau_days") is not None else "—"
        conf = f"{r['confidence']:.2f}" if r.get("confidence") else "—"
        print(f"{q:<55} {t:^12} {tau:^7} {conf:^5}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 3 FFIC Tier 3 batch")
    parser.add_argument("--confirm", action="store_true",
                        help="Acknowledge per-call LLM cost")
    args = parser.parse_args()
    if not args.confirm:
        print(f"Pass --confirm (≤{len(FFIC_TARGETS)} calls × ~$0.09 each).")
        sys.exit(1)
    api_key = os.environ.get("FFLOW_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Set FFLOW_ANTHROPIC_API_KEY.")
        sys.exit(1)
    asyncio.run(run(confirm=True, api_key=api_key))


if __name__ == "__main__":
    main()
