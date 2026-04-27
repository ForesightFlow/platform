"""Generate JSONL fixture for the ForesightFlow coordination experiment.

Phase 0:  ~50  markets — smoke test, manual review feasible
Phase 1A: ~2000 markets — full experiment run

baselineMidPrice: last CLOB mid_price strictly >24h before resolved_at.
If unavailable and --allow-trade-vwap: fall back to VWAP from trades >24h before resolved_at.
If neither: market is dropped.

Usage:
  uv run python scripts/make_foresightflow_fixture.py --phase 0 --output data/fixture_phase0.jsonl
  uv run python scripts/make_foresightflow_fixture.py --phase 1a --allow-trade-vwap \\
      --output data/fixture_phase1a.jsonl
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from fflow.db import AsyncSessionLocal

UTC = timezone.utc

# ─── Category mapping ────────────────────────────────────────────────────────

# Polymarket category_raw keywords → experiment 6-category label
_RAW_KEYWORDS: list[tuple[str, list[str]]] = [
    ("crypto",        ["bitcoin", "btc", "eth", "ethereum", "crypto", "defi", "sol", "solana",
                       "usdt", "usdc", "binance", "coinbase", "nft", "blockchain"]),
    ("sports",        ["nba", "nfl", "nhl", "mlb", "masters", "pga", "wimbledon", "ufc",
                       "cricket", "tennis", "soccer", "football", "basketball", "baseball",
                       "tournament", "championship", "superbowl", "super bowl", "world cup",
                       "formula 1", "f1", "ncaa", "premier league", "champions league",
                       "olympics", "olympic"]),
    ("entertainment", ["oscars", "grammy", "emmy", "bafta", "golden globe", "eurovision",
                       "mrbeast", "youtube", "netflix", "spotify", "box office", "billboard",
                       "taylor swift", "elon musk tweet", "tweet"]),
    ("geopolitics",   ["war", "military", "nato", "missile", "strike", "invasion", "troops",
                       "ukraine", "russia", "china", "taiwan", "iran", "israel", "hamas",
                       "hezbollah", "north korea", "sanctions", "ceasefire", "conflict"]),
    ("economics",     ["fed", "federal reserve", "interest rate", "inflation", "gdp", "cpi",
                       "recession", "earnings", "revenue", "merger", "acquisition", "ipo",
                       "stock", "nasdaq", "s&p", "dow jones", "unemployment"]),
    ("politics",      ["election", "president", "senate", "congress", "house", "vote", "poll",
                       "governor", "mayor", "parliament", "prime minister", "chancellor",
                       "referendum", "ballot", "campaign", "democrat", "republican",
                       "conservative", "labour", "liberal"]),
]

# fflow taxonomy → experiment label (fallback when category_raw doesn't match)
_FFLOW_MAP: dict[str, str] = {
    "military_geopolitics": "geopolitics",
    "regulatory_decision":  "politics",
    "corporate_disclosure": "economics",
}


def _map_category(category_fflow: str | None, category_raw: str | None, question: str) -> str:
    """Return one of: crypto | politics | sports | economics | geopolitics | entertainment."""
    # 1. keyword scan on category_raw + question (case-insensitive)
    haystack = " ".join(filter(None, [category_raw, question])).lower()
    for label, keywords in _RAW_KEYWORDS:
        if any(kw in haystack for kw in keywords):
            return label

    # 2. fflow taxonomy direct mapping
    if category_fflow and category_fflow in _FFLOW_MAP:
        return _FFLOW_MAP[category_fflow]

    # 3. fallback
    return "politics"


# ─── SQL helpers ─────────────────────────────────────────────────────────────

_CANDIDATE_SQL = """
SELECT
    m.id,
    m.question,
    m.category_fflow,
    m.category_raw,
    m.volume_total_usdc,
    m.resolved_at,
    m.resolution_outcome
FROM markets m
WHERE m.resolution_outcome IN (0, 1)
  AND m.volume_total_usdc >= :min_vol
  AND m.resolved_at >= :resolved_after
  AND m.resolved_at <= NOW()
  {category_filter}
ORDER BY m.volume_total_usdc DESC
"""

_CLOB_PRICE_SQL = """
SELECT mid_price, ts
FROM prices
WHERE market_id = :market_id
  AND ts < :cutoff
ORDER BY ts DESC
LIMIT 1
"""

_TRADE_VWAP_SQL = """
SELECT
    SUM(size_shares::numeric * price::numeric) / NULLIF(SUM(size_shares::numeric), 0) AS vwap,
    COUNT(*) AS n_trades
FROM trades
WHERE market_id = :market_id
  AND ts < :cutoff
"""

_TRADE_COUNT_SQL = """
SELECT COUNT(*) FROM trades WHERE market_id = :market_id
"""


async def _get_baseline_clob(session, market_id: str, cutoff: datetime) -> float | None:
    r = await session.execute(
        text(_CLOB_PRICE_SQL), {"market_id": market_id, "cutoff": cutoff}
    )
    row = r.fetchone()
    return float(row[0]) if row else None


async def _get_baseline_vwap(session, market_id: str, cutoff: datetime) -> tuple[float | None, int]:
    r = await session.execute(
        text(_TRADE_VWAP_SQL), {"market_id": market_id, "cutoff": cutoff}
    )
    row = r.fetchone()
    if row and row[0] is not None:
        return float(row[0]), int(row[1])
    return None, 0


async def _get_trade_count(session, market_id: str) -> int:
    r = await session.execute(text(_TRADE_COUNT_SQL), {"market_id": market_id})
    return r.scalar() or 0


# ─── Main ─────────────────────────────────────────────────────────────────────

async def generate(
    phase: str,
    resolved_after: datetime,
    min_vol: float,
    categories: list[str] | None,
    limit: int,
    allow_trade_vwap: bool,
    output_path: str,
) -> None:
    category_filter = ""
    if categories:
        placeholders = ", ".join(f"'{c}'" for c in categories)
        category_filter = f"AND m.category_fflow IN ({placeholders})"

    sql = text(_CANDIDATE_SQL.format(category_filter=category_filter))

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            sql,
            {
                "min_vol": min_vol,
                "resolved_after": resolved_after,
            },
        )
        candidates = result.fetchall()

    print(f"Candidates: {len(candidates)}", file=sys.stderr)

    written = 0
    dropped_no_price = 0
    dropped_no_trades = 0
    scanned = 0

    import os
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True) if os.path.dirname(output_path) else None

    with open(output_path, "w") as fh:
        async with AsyncSessionLocal() as session:
            for row in candidates:
                if written >= limit:
                    break

                scanned += 1
                if scanned % 500 == 0:
                    print(
                        f"  scanned={scanned} written={written} "
                        f"dropped_no_price={dropped_no_price} dropped_no_trades={dropped_no_trades}",
                        file=sys.stderr,
                    )

                market_id, question, cat_fflow, cat_raw, volume, resolved_at, outcome = row
                if resolved_at is None:
                    continue

                cutoff = resolved_at - timedelta(hours=24)

                # baselineMidPrice: CLOB first
                baseline_price = await _get_baseline_clob(session, market_id, cutoff)
                baseline_source = "clob"

                if baseline_price is None:
                    if not allow_trade_vwap:
                        dropped_no_price += 1
                        continue
                    # trade VWAP fallback
                    baseline_price, vwap_n = await _get_baseline_vwap(session, market_id, cutoff)
                    baseline_source = "trade_vwap"
                    if baseline_price is None:
                        dropped_no_price += 1
                        continue

                trade_count = await _get_trade_count(session, market_id)
                if trade_count == 0:
                    dropped_no_trades += 1
                    continue

                exp_category = _map_category(cat_fflow, cat_raw, question)

                record = {
                    "marketId":        market_id,
                    "question":        question,
                    "category":        exp_category,
                    "categoryFflow":   cat_fflow,
                    "resolutionOutcome": outcome,
                    "resolvedAt":      resolved_at.isoformat(),
                    "baselineDate":    cutoff.isoformat(),
                    "baselineMidPrice": round(baseline_price, 6),
                    "baselineSource":  baseline_source,
                    "volumeUsdc":      float(volume),
                    "tradeCount":      trade_count,
                    "ilsScore":        None,
                }
                fh.write(json.dumps(record) + "\n")
                written += 1

    print(
        f"Written: {written} | dropped_no_price: {dropped_no_price} "
        f"| dropped_no_trades: {dropped_no_trades}",
        file=sys.stderr,
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--phase", choices=["0", "1a"], default="0",
                   help="Phase 0 = 50 markets, 1a = up to 2000 (default: 0)")
    p.add_argument("--resolved-after", default="2024-01-01",
                   help="ISO date, include markets resolved on or after this date (default: 2024-01-01)")
    p.add_argument("--min-vol", type=float, default=50_000,
                   help="Minimum volume_total_usdc (default: 50000)")
    p.add_argument("--categories", default=None,
                   help="Comma-separated fflow categories to include, e.g. "
                        "military_geopolitics,regulatory_decision (default: all)")
    p.add_argument("--limit", type=int, default=None,
                   help="Hard cap on output rows (default: 50 for phase 0, 2000 for phase 1a)")
    p.add_argument("--allow-trade-vwap", action="store_true",
                   help="When CLOB price is absent, fall back to trade VWAP >24h before resolution")
    p.add_argument("--output", default=None,
                   help="Output JSONL path (default: data/fixture_phase<N>.jsonl)")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    resolved_after = datetime.fromisoformat(args.resolved_after).replace(tzinfo=UTC)
    categories = [c.strip() for c in args.categories.split(",")] if args.categories else None

    phase_limits = {"0": 50, "1a": 2000}
    limit = args.limit if args.limit is not None else phase_limits[args.phase]

    output = args.output or f"data/fixture_phase{args.phase}.jsonl"

    asyncio.run(
        generate(
            phase=args.phase,
            resolved_after=resolved_after,
            min_vol=args.min_vol,
            categories=categories,
            limit=limit,
            allow_trade_vwap=args.allow_trade_vwap,
            output_path=output,
        )
    )


if __name__ == "__main__":
    main()
