"""Backfill CLOB prices for all Paper 3a in-scope markets with T_event.

Reads population_ils_dl.parquet, finds markets that have T_event but no CLOB
coverage, then fetches 1-minute price history for each via the ClobCollector.

Progress is reported every 10 markets and saved to a checkpoint file so the
script can be resumed after interruption.

Usage:
    uv run python scripts/backfill_clob_phase3a.py
    uv run python scripts/backfill_clob_phase3a.py --concurrency 3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import structlog

log = structlog.get_logger()

PARQUET = Path("data/paper3a/population_ils_dl.parquet")
CHECKPOINT = Path("data/paper3a/clob_backfill_checkpoint.jsonl")
REPORT_EVERY = 10


def _load_checkpoint() -> set[str]:
    done: set[str] = set()
    if CHECKPOINT.exists():
        for line in CHECKPOINT.read_text().splitlines():
            try:
                done.add(json.loads(line)["market_id"])
            except Exception:
                pass
    return done


def _append_checkpoint(market_id: str, status: str, n_written: int) -> None:
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT, "a") as f:
        f.write(json.dumps({
            "market_id": market_id,
            "status": status,
            "n_written": n_written,
            "ts": datetime.now(timezone.utc).isoformat(),
        }) + "\n")


async def backfill_one(
    market_id: str,
    t_open: str,
    t_resolve: str,
    sem: asyncio.Semaphore,
) -> tuple[str, int]:
    """Fetch CLOB prices for one market. Returns (status, n_written)."""
    from fflow.collectors.clob import ClobCollector

    t_open_dt = datetime.fromisoformat(t_open.replace("Z", "+00:00")) if t_open else None
    t_resolve_dt = datetime.fromisoformat(t_resolve.replace("Z", "+00:00")) if t_resolve else None

    async with sem:
        try:
            result = await ClobCollector().run(
                market_id=market_id,
                start_ts=t_open_dt,
                end_ts=t_resolve_dt,
            )
            return result.status, result.n_written
        except Exception as exc:
            log.warning("clob_backfill_error", market_id=market_id[:20], error=str(exc))
            return "error", 0


async def main(concurrency: int = 5) -> None:
    if not PARQUET.exists():
        sys.exit(f"ERROR: {PARQUET} not found. Run paper3a_phase1.py first.")

    df = pd.read_parquet(PARQUET)

    # Target: markets that have T_event (checkpoint had a date)
    # We want all markets with T_event, regardless of exclusion_reason
    targets = df[df["T_event"].notna()][["market_id", "question", "T_open", "T_resolve"]].copy()
    log.info("targets_loaded", n=len(targets))

    done = _load_checkpoint()
    log.info("checkpoint_loaded", n_done=len(done))

    remaining = targets[~targets["market_id"].isin(done)].reset_index(drop=True)
    total = len(remaining)
    log.info("remaining", n=total)

    if total == 0:
        print("Nothing to backfill — all markets already in checkpoint.")
        return

    print(f"\n{'='*65}")
    print(f"CLOB Backfill: {total} markets (concurrency={concurrency})")
    print(f"{'='*65}\n")

    sem = asyncio.Semaphore(concurrency)
    completed = 0
    n_success = 0
    n_no_data = 0
    n_error = 0
    total_written = 0
    lock = asyncio.Lock()

    async def process_one(row: pd.Series) -> None:
        nonlocal completed, n_success, n_no_data, n_error, total_written

        status, n_written = await backfill_one(
            row["market_id"], row["T_open"], row["T_resolve"], sem
        )

        async with lock:
            _append_checkpoint(row["market_id"], status, n_written)
            completed += 1
            total_written += n_written
            if status == "success" and n_written > 0:
                n_success += 1
            elif status == "success" and n_written == 0:
                n_no_data += 1
            else:
                n_error += 1

            if completed % REPORT_EVERY == 0 or completed == total:
                pct = completed / total * 100
                print(
                    f"  [{completed:4d}/{total}  {pct:5.1f}%]  "
                    f"ok={n_success}  no_data={n_no_data}  err={n_error}  "
                    f"rows_written={total_written}",
                    flush=True,
                )
            else:
                icon = "✓" if n_written > 0 else ("∅" if status == "success" else "✗")
                q = str(row["question"])[:55]
                print(f"  {icon} {n_written:5d} rows  {q}", flush=True)

    tasks = [process_one(row) for _, row in remaining.iterrows()]
    await asyncio.gather(*tasks)

    print(f"\n{'='*65}")
    print(f"DONE")
    print(f"  Total markets:   {total}")
    print(f"  With data:       {n_success}")
    print(f"  No CLOB data:    {n_no_data}  (API has no history for these)")
    print(f"  Errors:          {n_error}")
    print(f"  Rows written:    {total_written}")
    print(f"\nNow re-run: uv run python scripts/paper3a_phase1.py --skip-step0 --skip-llm --resume --confirm")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(main(concurrency=args.concurrency))
