#!/usr/bin/env python
"""Sanity checks on the market_labels distribution.

Usage:
    uv run python scripts/validate_labels.py

Checks:
  - ILS ∈ [-1, 2]  (allows counter-evidence and >1 outliers)
  - Fraction of low_information_market flags
  - ILS distribution summary (p5, p25, p50, p75, p95)
  - Count by resolution outcome (0 vs 1)
  - Count with null ILS
"""

import asyncio
import sys
from decimal import Decimal

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from fflow.db import AsyncSessionLocal
from fflow.models import MarketLabel
from sqlalchemy import func, select


async def validate():
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(MarketLabel))).scalars().all()

    if not rows:
        print("No labels found. Run: fflow score batch")
        return

    n = len(rows)
    ils_vals = [float(r.ils) for r in rows if r.ils is not None]
    n_null = n - len(ils_vals)
    n_low_info = sum(1 for r in rows if "low_information_market" in (r.flags or []))

    print(f"Total labels:         {n}")
    print(f"ILS defined:          {len(ils_vals)} ({100*len(ils_vals)/n:.1f}%)")
    print(f"ILS null:             {n_null}")
    print(f"low_information_market: {n_low_info} ({100*n_low_info/n:.1f}%)")

    if ils_vals:
        sorted_vals = sorted(ils_vals)
        def percentile(p):
            idx = int(len(sorted_vals) * p / 100)
            return sorted_vals[min(idx, len(sorted_vals)-1)]

        print(f"\nILS distribution:")
        print(f"  min   = {sorted_vals[0]:.4f}")
        print(f"  p5    = {percentile(5):.4f}")
        print(f"  p25   = {percentile(25):.4f}")
        print(f"  p50   = {percentile(50):.4f}")
        print(f"  p75   = {percentile(75):.4f}")
        print(f"  p95   = {percentile(95):.4f}")
        print(f"  max   = {sorted_vals[-1]:.4f}")

        out_of_range = [v for v in ils_vals if v < -1 or v > 2]
        if out_of_range:
            print(f"\nWARNING: {len(out_of_range)} ILS values outside [-1, 2]")
        else:
            print(f"\nOK: all ILS values in [-1, 2]")

    # By outcome
    by_outcome = {}
    for r in rows:
        k = r.p_resolve
        by_outcome[k] = by_outcome.get(k, 0) + 1
    print(f"\nBy resolution:")
    for k, v in sorted(by_outcome.items()):
        print(f"  p_resolve={k}: {v}")

    # Tier distribution
    async with AsyncSessionLocal() as session:
        from fflow.models import NewsTimestamp
        tier_rows = (
            await session.execute(
                select(NewsTimestamp.tier, func.count().label("n"))
                .group_by(NewsTimestamp.tier)
                .order_by(NewsTimestamp.tier)
            )
        ).all()

    print(f"\nNewsTimestamp tier distribution:")
    for r in tier_rows:
        print(f"  tier {r.tier}: {r.n}")


if __name__ == "__main__":
    asyncio.run(validate())
