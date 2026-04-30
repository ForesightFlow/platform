"""Phase 2 of Task 02F: tighter T_news proxy exploration on pilot markets.

Computes ILS for each pilot market at 4 proxy offsets from resolved_at:
  24h, 6h, 2h, 1h

For each proxy:
  - Seeds news_timestamps into a temp column (doesn't overwrite existing)
  - Calls compute_ils directly (without persisting to market_labels)
  - Collects ILS distribution metrics

Epstein cluster market IDs are tracked separately.
"""

import asyncio
import statistics
from datetime import UTC, datetime, timedelta

import numpy as np
from scipy.stats import spearmanr
from sqlalchemy import text

from fflow.db import AsyncSessionLocal
from fflow.scoring.ils import compute_ils, PriceLookupError
from fflow.scoring.price_series import reconstruct_price_series

OFFSETS_HOURS = [24, 6, 2, 1]
MIN_VOLUME = 50_000.0

EPSTEIN_IDS = {
    "0xec60889422584c30517308290d07b8e78251b77795a49fa19f210f5b0ef42594",  # AOC
    "0x913caf5e4e8a31944ca4fa888f3e51abf1e1203137d9c1507e4c076322b0dd94",  # Sanders
    "0xfa1543cdef36d55ef9126aaab6015c7c7ed5aa6a2bb5be355f5cacc2302c7374",  # Barak
}


async def _compute_ils_for_offset(session, market_row: dict, offset_hours: int) -> float | None:
    """Compute ILS for a single market at a given T_news offset without persisting."""
    mid = market_row["id"]
    t_open = market_row["t_open"]
    t_resolve = market_row["resolved_at"]
    p_resolve = float(market_row["resolution_outcome"])

    t_news = t_resolve - timedelta(hours=offset_hours)
    if t_news < t_open:
        return None

    try:
        prices = await reconstruct_price_series(mid, session, granularity="1min")
    except Exception:
        return None

    if prices.empty:
        return None

    # Snap t_open to first trade if needed
    first_ts = prices["ts"].min()
    if hasattr(first_ts, "to_pydatetime"):
        first_ts = first_ts.to_pydatetime()
    if (first_ts - t_open).total_seconds() > 300:
        t_open = first_ts

    if t_news < t_open:
        return None

    try:
        bundle = compute_ils(
            prices=prices, t_open=t_open, t_news=t_news,
            t_resolve=t_resolve, p_resolve=p_resolve,
        )
        return float(bundle.ils) if bundle.ils is not None else None
    except PriceLookupError:
        return None


async def run() -> dict[int, list[float | None]]:
    """Return {offset_hours: [ils_or_None, ...]} for all pilot markets."""
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(text("""
            SELECT m.id, m.question, m.created_at_chain as t_open, m.resolved_at,
                   m.resolution_outcome, m.category_fflow
            FROM market_labels ml
            JOIN markets m ON m.id = ml.market_id
            WHERE m.resolution_type = 'event_resolved'
              AND ml.ils IS NOT NULL
            ORDER BY m.id
        """))).mappings().all()

    markets = [dict(r) for r in rows]
    print(f"Pilot markets: {len(markets)}")

    results: dict[int, list[float | None]] = {h: [] for h in OFFSETS_HOURS}

    for i, m in enumerate(markets):
        if (i + 1) % 100 == 0:
            ok_counts = {h: sum(1 for v in results[h] if v is not None) for h in OFFSETS_HOURS}
            print(f"  progress {i+1}/{len(markets)}: ok={ok_counts}")

        async with AsyncSessionLocal() as session:
            for h in OFFSETS_HOURS:
                val = await _compute_ils_for_offset(session, m, h)
                results[h].append(val)

    return markets, results


def _dist_summary(ils_list: list[float | None]) -> dict:
    vals = [v for v in ils_list if v is not None]
    if not vals:
        return {"n": 0}
    return {
        "n": len(vals),
        "median": statistics.median(vals),
        "mean": sum(vals) / len(vals),
        "pct_pos": 100 * sum(1 for v in vals if v > 0) / len(vals),
        "pct_extreme": 100 * sum(1 for v in vals if abs(v) > 1) / len(vals),
    }


def write_report(markets: list[dict], results: dict[int, list[float | None]]) -> None:
    now = datetime.now(UTC).strftime("%Y-%m-%d")

    # Align results: only markets with all 4 offsets non-null
    n = len(markets)
    aligned = [
        {h: results[h][i] for h in OFFSETS_HOURS}
        for i in range(n)
        if all(results[h][i] is not None for h in OFFSETS_HOURS)
    ]
    aligned_ids = [
        markets[i]["id"]
        for i in range(n)
        if all(results[h][i] is not None for h in OFFSETS_HOURS)
    ]
    print(f"Markets with all 4 proxy values: {len(aligned)}")

    # Spearman correlations between proxies
    def get_col(h):
        return [row[h] for row in aligned]

    corr_24_1 = spearmanr(get_col(24), get_col(1)).statistic if aligned else float("nan")
    corr_24_2 = spearmanr(get_col(24), get_col(2)).statistic if aligned else float("nan")
    corr_24_6 = spearmanr(get_col(24), get_col(6)).statistic if aligned else float("nan")

    # Epstein cluster values
    epstein_rows = [(markets[i], {h: results[h][i] for h in OFFSETS_HOURS})
                    for i in range(n) if markets[i]["id"] in EPSTEIN_IDS]

    # Monotone trend: for each aligned market, does ILS increase as offset decreases?
    # (tighter proxy = should show higher ILS if signal is real)
    n_monotone_inc = sum(
        1 for row in aligned
        if row[24] <= row[6] <= row[2] <= row[1]
    )
    n_monotone_dec = sum(
        1 for row in aligned
        if row[24] >= row[6] >= row[2] >= row[1]
    )

    lines = [
        f"# Task 02F Phase 2 — Proxy Refinement",
        f"",
        f"**Generated:** {now}  ",
        f"**Branch:** task02f/control-group-and-proxy-refinement",
        f"",
        f"---",
        f"",
        f"## Distribution Metrics by Proxy",
        f"",
        f"| Proxy | N | Median | Mean | % Positive | % |ILS|>1 |",
        f"|---|---|---|---|---|---|",
    ]
    for h in OFFSETS_HOURS:
        s = _dist_summary(results[h])
        if s["n"] == 0:
            lines.append(f"| resolved_at−{h}h | 0 | — | — | — | — |")
        else:
            lines.append(
                f"| resolved_at−{h}h | {s['n']} "
                f"| {s['median']:.3f} "
                f"| {s['mean']:.3f} "
                f"| {s['pct_pos']:.1f}% "
                f"| {s['pct_extreme']:.1f}% |"
            )

    lines += [
        f"",
        f"---",
        f"",
        f"## Proxy Correlations (Spearman, n={len(aligned)} matched markets)",
        f"",
        f"| Pair | Spearman ρ |",
        f"|---|---|",
        f"| ILS_24h vs ILS_6h | {corr_24_6:.3f} |",
        f"| ILS_24h vs ILS_2h | {corr_24_2:.3f} |",
        f"| ILS_24h vs ILS_1h | {corr_24_1:.3f} |",
        f"",
    ]

    if aligned:
        lines += [
            f"Monotone trend analysis (n={len(aligned)} matched markets):",
            f"- ILS increases as proxy tightens (24h→1h): {n_monotone_inc} markets ({100*n_monotone_inc/len(aligned):.1f}%)",
            f"- ILS decreases as proxy tightens (24h→1h): {n_monotone_dec} markets ({100*n_monotone_dec/len(aligned):.1f}%)",
        ]

    lines += [
        f"",
        f"---",
        f"",
        f"## Epstein Cluster — ILS Across Proxies",
        f"",
        f"| Market | 24h | 6h | 2h | 1h | Trend |",
        f"|---|---|---|---|---|---|",
    ]
    for mkt, vals in epstein_rows:
        trend = "↑" if all(vals.get(h) is not None for h in OFFSETS_HOURS) and (
            vals[1] > vals[6] > vals[24] or vals[1] > vals[24]
        ) else "—"
        v_str = " | ".join(
            f"{vals[h]:.3f}" if vals[h] is not None else "N/A"
            for h in OFFSETS_HOURS
        )
        q = mkt["question"][:50]
        lines.append(f"| {q}… | {v_str} | {trend} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## Interpretation",
        f"",
    ]

    # Determine robustness interpretation
    if corr_24_1 > 0.7:
        interp = (
            "**ILS is robust to proxy choice** (ρ₂₄h,₁h={:.3f} > 0.7). "
            "Market rankings are stable across proxy offsets. Signal quality "
            "does not depend on the 24h vs 1h choice."
        ).format(corr_24_1)
    elif corr_24_1 > 0.4:
        interp = (
            "**Moderate proxy sensitivity** (ρ₂₄h,₁h={:.3f}). Rankings partially "
            "consistent across offsets, but individual market ILS values shift. "
            "Tighter proxies recover additional signal for some markets."
        ).format(corr_24_1)
    else:
        interp = (
            "**ILS is highly proxy-sensitive** (ρ₂₄h,₁h={:.3f} < 0.4). Large "
            "fraction of apparent signal is an artifact of proxy choice. "
            "Robust conclusions require proper article-derived T_news."
        ).format(corr_24_1)
    lines.append(interp)

    pathlib.Path("reports").mkdir(exist_ok=True)
    pathlib.Path("reports/TASK_02F_PROXY_REFINEMENT.md").write_text("\n".join(lines) + "\n")
    print("→ reports/TASK_02F_PROXY_REFINEMENT.md")


if __name__ == "__main__":
    import json, pathlib
    cache = pathlib.Path("/tmp/proxy_cache.json")
    if cache.exists():
        print("Loading from cache...")
        data = json.loads(cache.read_text())
        markets = data["markets"]
        results = {int(k): v for k, v in data["results"].items()}
    else:
        markets, results = asyncio.run(run())
        cache.write_text(json.dumps({"markets": markets, "results": {str(k): v for k, v in results.items()}}, default=str))
        print(f"Saved cache to {cache}")
    write_report(markets, results)
    print("\n=== Proxy summary ===")
    for h in OFFSETS_HOURS:
        s = _dist_summary(results[h])
        print(f"  {h}h: n={s.get('n',0)}, median={s.get('median',float('nan')):.3f}, "
              f"%pos={s.get('pct_pos',0):.1f}%")
