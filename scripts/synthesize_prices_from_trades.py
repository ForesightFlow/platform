"""Synthesize 1-minute VWAP prices from trades for Paper 3a markets.

For each target market with T_event but missing/sparse CLOB prices,
computes per-minute VWAP from YES-outcome trades and upserts into prices table.

Only inserts rows for minutes not already covered by CLOB prices.

Usage:
    uv run python scripts/synthesize_prices_from_trades.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import asyncpg
import pandas as pd
import structlog

log = structlog.get_logger()

DB_DSN = "postgresql://fflow:fflow@localhost:5432/fflow"
PARQUET = Path("data/paper3a/population_ils_dl.parquet")
REPORT_EVERY = 25


async def synthesize_one(
    conn: asyncpg.Connection,
    market_id: str,
) -> tuple[int, int]:
    """Returns (n_inserted, n_trades)."""
    # Fetch all YES trades
    rows = await conn.fetch(
        """SELECT date_trunc('minute', ts) AS ts_min,
                  SUM(price * notional_usdc) / NULLIF(SUM(notional_usdc), 0) AS vwap,
                  COUNT(*) AS n_trades
           FROM trades
           WHERE market_id = $1 AND outcome_index = 1
           GROUP BY ts_min
           ORDER BY ts_min""",
        market_id,
    )
    if not rows:
        return 0, 0

    n_trades = sum(r["n_trades"] for r in rows)

    # Get existing price timestamps to avoid overwriting CLOB data
    existing_ts = set(
        row["ts"] for row in await conn.fetch(
            "SELECT ts FROM prices WHERE market_id = $1", market_id
        )
    )

    # Build records to insert (skip minutes already covered)
    to_insert = []
    for r in rows:
        ts_min = r["ts_min"]
        if ts_min in existing_ts or r["vwap"] is None:
            continue
        to_insert.append((market_id, ts_min, r["vwap"]))

    if not to_insert:
        return 0, n_trades

    await conn.executemany(
        """INSERT INTO prices (market_id, ts, mid_price)
           VALUES ($1, $2, $3)
           ON CONFLICT (market_id, ts) DO NOTHING""",
        to_insert,
    )
    return len(to_insert), n_trades


async def main() -> None:
    if not PARQUET.exists():
        sys.exit(f"ERROR: {PARQUET} not found.")

    df = pd.read_parquet(PARQUET)
    targets = df[df["T_event"].notna()]["market_id"].tolist()
    print(f"Target markets: {len(targets)}")

    conn = await asyncpg.connect(DB_DSN)

    # Filter to those that have trades
    rows = await conn.fetch(
        "SELECT DISTINCT market_id FROM trades WHERE market_id = ANY($1) AND outcome_index = 1",
        targets,
    )
    with_trades = [r["market_id"] for r in rows]
    print(f"Have trades: {len(with_trades)}")

    total_inserted = 0
    completed = 0

    for market_id in with_trades:
        n_inserted, n_trades = await synthesize_one(conn, market_id)
        total_inserted += n_inserted
        completed += 1
        if completed % REPORT_EVERY == 0 or completed == len(with_trades):
            print(
                f"  [{completed:3d}/{len(with_trades)}]  "
                f"rows_inserted={total_inserted}  last: {n_inserted} from {n_trades} trades",
                flush=True,
            )

    await conn.close()

    print(f"\nDone. Total price rows inserted: {total_inserted}")
    print(f"Now re-run: uv run python scripts/paper3a_phase1.py --skip-step0 --skip-llm --resume --confirm")


if __name__ == "__main__":
    asyncio.run(main())
