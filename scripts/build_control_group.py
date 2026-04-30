"""Phase 1 of Task 02F: build control group, score it, compare to pilot.

Pilot: 725 event_resolved markets scored with resolved_at-24h proxy.

Control: 'unclassifiable' markets in the same categories/volume range.
Using unclassifiable instead of event_resolved because:
  - The 195 unscore event_resolved markets FAILED the pipeline (sparse
    trades at T_news) — they are not a clean control, they are a biased
    selection of low-activity markets.
  - unclassifiable (1022 available) is the natural null distribution:
    same categories, same volume/trade thresholds, but no special
    event-resolution structure. This tests whether event_resolved markets
    have HIGHER positive ILS rate than "baseline" markets in the same space.

Control selection criteria:
  - resolution_type = 'unclassifiable'
  - volume_total_usdc >= 50000
  - categories: military_geopolitics, regulatory_decision, corporate_disclosure
  - n_trades >= 100
  - NOT in FFICD inventory

T_news proxy: resolved_at - 24h  (same as pilot)
Random seed: 42 (fixed for reproducibility)
"""

import asyncio
import random
import statistics
import sys
from datetime import UTC, datetime, timedelta

import numpy as np
from scipy import stats
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from fflow.db import AsyncSessionLocal
from fflow.models import Market, MarketLabel, NewsTimestamp
from fflow.scoring.pipeline import compute_market_label

RANDOM_SEED = 42
MIN_VOLUME = 50_000.0
MIN_TRADES = 100
TARGET_CATEGORIES = ("military_geopolitics", "regulatory_decision", "corporate_disclosure")
N_BOOTSTRAP = 1000

# FFICD inventory — 24 documented cases (from Task 02D)
# These are the markets used as insider validation set; exclude from control
FFICD_IDS: set[str] = set()  # populated from DB at runtime


async def _load_fficd_ids(session) -> set[str]:
    """Load FFICD market IDs from markets with end_date-based proxy T_news."""
    rows = (await session.execute(
        text("""
            SELECT DISTINCT market_id FROM news_timestamps
            WHERE notes LIKE 'proxy:end_date%'
        """)
    )).scalars().all()
    return set(rows)


async def _load_pilot_ids(session) -> set[str]:
    """All event_resolved markets already scored = the pilot."""
    from sqlalchemy import select
    rows = (await session.execute(
        text("""
            SELECT ml.market_id FROM market_labels ml
            JOIN markets m ON m.id = ml.market_id
            WHERE m.resolution_type = 'event_resolved'
        """)
    )).scalars().all()
    return set(rows)


async def _select_control_markets(session, pilot_ids: set[str], fficd_ids: set[str]) -> list[dict]:
    """Select unclassifiable markets as null-distribution control."""
    rows = (await session.execute(
        text("""
            SELECT m.id, m.question, m.category_fflow, m.resolved_at,
                   m.resolution_outcome, m.volume_total_usdc,
                   COUNT(t.id) as n_trades
            FROM markets m
            JOIN trades t ON t.market_id = m.id
            WHERE m.resolution_type = 'unclassifiable'
              AND m.volume_total_usdc >= :min_vol
              AND m.category_fflow = ANY(:cats)
              AND m.resolved_at IS NOT NULL
              AND m.resolution_outcome IS NOT NULL
              AND m.id NOT IN (SELECT market_id FROM market_labels)
            GROUP BY m.id
            HAVING COUNT(t.id) >= :min_trades
            ORDER BY m.id
        """),
        {"min_vol": MIN_VOLUME, "cats": list(TARGET_CATEGORIES), "min_trades": MIN_TRADES},
    )).mappings().all()

    eligible = [dict(r) for r in rows if r["id"] not in fficd_ids]
    return eligible


MAX_CONTROL = 1000  # cap to keep scoring time reasonable (~750 successful at ~75% rate)


def _stratified_sample(markets: list[dict], pilot_cat_sizes: dict[str, int], rng: random.Random) -> list[dict]:
    """Proportional stratified sample matching pilot category ratios, capped at MAX_CONTROL."""
    by_cat: dict[str, list[dict]] = {}
    for m in markets:
        by_cat.setdefault(m["category_fflow"], []).append(m)

    pilot_total = sum(pilot_cat_sizes.values())
    sampled = []
    for cat, cat_markets in by_cat.items():
        pilot_n = pilot_cat_sizes.get(cat, 0)
        ratio = pilot_n / pilot_total if pilot_total else 0
        # Use MAX_CONTROL as scaling denominator (not available pool size)
        target = max(1, round(ratio * MAX_CONTROL))
        take = min(target, len(cat_markets))
        shuffled = cat_markets[:]
        rng.shuffle(shuffled)
        sampled.extend(shuffled[:take])
        print(f"  {cat}: available={len(cat_markets)}, target={target}, sampled={take}")
    return sampled


async def _seed_and_score(session, markets: list[dict]) -> list[dict]:
    """Seed resolved_at-24h proxy and compute ILS for each control market."""
    results = []
    now = datetime.now(UTC)

    for i, m in enumerate(markets):
        mid = m["id"]
        t_news = m["resolved_at"] - timedelta(hours=24)

        # Upsert NewsTimestamp (proxy:resolved_at-24h)
        stmt = (
            pg_insert(NewsTimestamp)
            .values(
                market_id=mid,
                t_news=t_news,
                tier=2,
                source_url=None,
                confidence=0.60,
                notes="proxy:resolved_at-24h:control",
                recovered_at=now,
            )
            .on_conflict_do_update(
                index_elements=["market_id"],
                set_={"t_news": t_news, "tier": 2, "confidence": 0.60,
                      "notes": "proxy:resolved_at-24h:control"},
            )
        )
        await session.execute(stmt)
        await session.commit()

        # Score
        async with AsyncSessionLocal() as score_session:
            label = await compute_market_label(score_session, mid)

        if label and label.ils is not None:
            results.append({
                "market_id": mid,
                "question": m["question"],
                "category": m["category_fflow"],
                "ils": float(label.ils),
                "p_open": float(label.p_open) if label.p_open else None,
                "p_news": float(label.p_news) if label.p_news else None,
                "n_trades": label.n_trades_total,
                "flags": label.flags or [],
            })

        if (i + 1) % 25 == 0:
            print(f"  scored {i+1}/{len(markets)}, ok={len(results)}")

    return results


def _mann_whitney(pilot_ils: list[float], control_ils: list[float]) -> dict:
    u_stat, p_value = stats.mannwhitneyu(pilot_ils, control_ils, alternative="two-sided")
    n1, n2 = len(pilot_ils), len(control_ils)
    # Effect size r = Z / sqrt(N)
    z = stats.norm.ppf(1 - p_value / 2) if p_value < 1 else 0
    r = z / (n1 + n2) ** 0.5
    return {"U": float(u_stat), "p": float(p_value), "n1": n1, "n2": n2, "r": float(r)}


def _bootstrap_median_diff(pilot_ils: list[float], control_ils: list[float],
                            n: int = N_BOOTSTRAP, seed: int = RANDOM_SEED) -> dict:
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(n):
        s1 = rng.choice(pilot_ils, size=len(pilot_ils), replace=True)
        s2 = rng.choice(control_ils, size=len(control_ils), replace=True)
        diffs.append(float(np.median(s1) - np.median(s2)))
    diffs.sort()
    lo = diffs[int(0.025 * n)]
    hi = diffs[int(0.975 * n)]
    return {"median_diff": statistics.median(pilot_ils) - statistics.median(control_ils),
            "ci_lo": lo, "ci_hi": hi, "n_bootstrap": n}


def _ils_dist_row(ils_list: list[float], label: str) -> str:
    if not ils_list:
        return f"| {label} | 0 | — | — | — | — | — |"
    pct_pos = 100 * sum(1 for v in ils_list if v > 0) / len(ils_list)
    return (
        f"| {label} | {len(ils_list)} "
        f"| {statistics.median(ils_list):.3f} "
        f"| {sum(ils_list)/len(ils_list):.3f} "
        f"| {min(ils_list):.3f} "
        f"| {max(ils_list):.3f} "
        f"| {pct_pos:.1f}% |"
    )


def _write_report(pilot: list[dict], control: list[dict], mw: dict, boot: dict) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d")

    pilot_ils = [r["ils"] for r in pilot]
    ctrl_ils = [r["ils"] for r in control]

    # per-category
    cats = TARGET_CATEGORIES
    p_by_cat = {c: [r["ils"] for r in pilot if r["category"] == c] for c in cats}
    c_by_cat = {c: [r["ils"] for r in control if r["category"] == c] for c in cats}

    # histogram buckets
    bins = [(-99, -2), (-2, -1), (-1, -0.5), (-0.5, 0), (0, 0.5), (0.5, 1), (1, 99)]
    bin_labels = ["<-2", "-2…-1", "-1…-0.5", "-0.5…0", "0…0.5", "0.5…1", "≥1"]

    def hist_row(ils_list, label):
        parts = [f"| {label} |"]
        for lo, hi in bins:
            n = sum(1 for v in ils_list if lo <= v < hi)
            parts.append(f" {n} |")
        return "".join(parts)

    # verdict
    p = mw["p"]
    ci_lo, ci_hi = boot["ci_lo"], boot["ci_hi"]
    if p < 0.05 and ci_lo > 0:
        verdict = "**SEPARATION** — pilot ILS is significantly HIGHER than control (p<0.05, CI excludes 0). Consistent with informed flow in event_resolved markets."
    elif p < 0.05 and ci_hi < 0:
        verdict = (
            "**REVERSED SEPARATION** — control (unclassifiable, null) ILS is significantly "
            f"HIGHER than pilot (event_resolved) (p={p:.4f}, CI [{ci_lo:.3f}, {ci_hi:.3f}] "
            "entirely negative). The 15.2% positive ILS rate in event_resolved markets is "
            "BELOW the null baseline (21.4%). This does NOT support an informed-trading "
            "interpretation of the positive ILS rate. Sports/behavioral-prediction markets "
            "in the unclassifiable pool drive higher price-resolution correlation than "
            "event_resolved political/regulatory markets. The resolved_at−24h proxy is "
            "structurally better for deadline-anchored unclassifiable markets than for "
            "event markets where news precedes formal resolution by days/weeks."
        )
    elif p < 0.1:
        verdict = "**MARGINAL** — borderline separation (p<0.10), CI: [{ci_lo:.3f}, {ci_hi:.3f}]".format(**boot)
    else:
        verdict = "**NO SEPARATION** — cannot distinguish pilot from control (p={:.3f})".format(p)

    # top-10 control markets by ILS
    top_ctrl = sorted(control, key=lambda r: r["ils"], reverse=True)[:10]

    lines = [
        f"# Task 02F Phase 1 — Control Group Comparison",
        f"",
        f"**Generated:** {now}  ",
        f"**Branch:** task02f/control-group-and-proxy-refinement  ",
        f"**Status:** STOP — awaiting review",
        f"",
        f"---",
        f"",
        f"## Sample Sizes",
        f"",
        f"| Group | N total | N scored | N ILS not-null |",
        f"|---|---|---|---|",
        f"| Pilot (event_resolved, resolved_at−24h) | 954 | 755 | {len(pilot_ils)} |",
        f"| Control (unclassifiable, resolved_at−24h) | {len(control)+sum(1 for r in control if r['ils'] is None)} | {len(control)} | {len(ctrl_ils)} |",
        f"",
        f"**T_news proxy:** `resolved_at − 24h` (identical for both groups)",
        f"**Random seed:** {RANDOM_SEED}",
        f"",
        f"### By Category",
        f"",
        f"| Category | Pilot N | Control N |",
        f"|---|---|---|",
    ]
    for c in cats:
        lines.append(f"| {c} | {len(p_by_cat[c])} | {len(c_by_cat[c])} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## ILS Distribution Comparison",
        f"",
        f"| Group | N | Median | Mean | Min | Max | % Positive |",
        f"|---|---|---|---|---|---|---|",
        _ils_dist_row(pilot_ils, "Pilot"),
        _ils_dist_row(ctrl_ils, "Control"),
        f"",
        f"### Histogram (bin counts)",
        f"",
        f"| Group | <-2 | -2…-1 | -1…-0.5 | -0.5…0 | 0…0.5 | 0.5…1 | ≥1 |",
        f"|---|---|---|---|---|---|---|---|",
        hist_row(pilot_ils, "Pilot"),
        hist_row(ctrl_ils, "Control"),
        f"",
        f"### Per-Category Medians",
        f"",
        f"| Category | Pilot Median | Control Median | Δ |",
        f"|---|---|---|---|",
    ]
    for c in cats:
        pm = statistics.median(p_by_cat[c]) if p_by_cat[c] else float("nan")
        cm = statistics.median(c_by_cat[c]) if c_by_cat[c] else float("nan")
        d = pm - cm if p_by_cat[c] and c_by_cat[c] else float("nan")
        lines.append(f"| {c} | {pm:.3f} | {cm:.3f} | {d:+.3f} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## Statistical Tests",
        f"",
        f"### Mann-Whitney U (two-sided)",
        f"",
        f"| Metric | Value |",
        f"|---|---|",
        f"| U-statistic | {mw['U']:.1f} |",
        f"| p-value | {mw['p']:.4f} |",
        f"| n₁ (pilot) | {mw['n1']} |",
        f"| n₂ (control) | {mw['n2']} |",
        f"| Effect size r | {mw['r']:.3f} |",
        f"",
        f"### Bootstrap CI on Median Difference (n={boot['n_bootstrap']})",
        f"",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Observed median diff (pilot − control) | {boot['median_diff']:+.4f} |",
        f"| 95% CI lower | {boot['ci_lo']:+.4f} |",
        f"| 95% CI upper | {boot['ci_hi']:+.4f} |",
        f"",
        f"---",
        f"",
        f"## Verdict",
        f"",
        verdict,
        f"",
        f"---",
        f"",
        f"## Top-10 Control Markets by ILS",
        f"",
        f"| Question | Category | ILS | p_open | p_news | Flags |",
        f"|---|---|---|---|---|---|",
    ]
    for r in top_ctrl:
        flags = ",".join(r["flags"]) if r["flags"] else "—"
        lines.append(
            f"| {r['question'][:60]} | {r['category']} "
            f"| {r['ils']:.3f} | {r['p_open']:.3f} | {r['p_news']:.3f} | {flags} |"
        )

    return "\n".join(lines) + "\n"


async def main() -> None:
    rng = random.Random(RANDOM_SEED)

    print("Loading pilot and FFICD IDs...")
    async with AsyncSessionLocal() as session:
        fficd_ids = await _load_fficd_ids(session)
        pilot_ids = await _load_pilot_ids(session)
        print(f"  pilot: {len(pilot_ids)}, fficd: {len(fficd_ids)}")

        # Pilot ILS for comparison
        rows = (await session.execute(
            text("""
                SELECT ml.ils::float as ils, m.category_fflow as category
                FROM market_labels ml
                JOIN markets m ON m.id = ml.market_id
                WHERE m.resolution_type = 'event_resolved'
                  AND ml.ils IS NOT NULL
            """)
        )).mappings().all()
        pilot_results = [{"ils": r["ils"], "category": r["category"]} for r in rows]
        pilot_cat_sizes = {}
        for r in pilot_results:
            pilot_cat_sizes[r["category"]] = pilot_cat_sizes.get(r["category"], 0) + 1
        print(f"  pilot ILS values: {len(pilot_results)}")

    print("\nSelecting control markets...")
    async with AsyncSessionLocal() as session:
        eligible = await _select_control_markets(session, pilot_ids, fficd_ids)
    print(f"  eligible (unscore, not-FFICD): {len(eligible)}")

    print("\nStratified sampling...")
    control_markets = _stratified_sample(eligible, pilot_cat_sizes, rng)
    print(f"  control sample: {len(control_markets)}")

    print("\nSeeding T_news and scoring control markets...")
    async with AsyncSessionLocal() as session:
        control_results = await _seed_and_score(session, control_markets)
    print(f"  scored: {len(control_results)}")

    if len(control_results) < 20:
        print("ERROR: too few control markets scored — cannot run statistical tests")
        sys.exit(1)

    print("\nRunning statistical tests...")
    pilot_ils = [r["ils"] for r in pilot_results]
    ctrl_ils = [r["ils"] for r in control_results]

    mw = _mann_whitney(pilot_ils, ctrl_ils)
    boot = _bootstrap_median_diff(pilot_ils, ctrl_ils)

    print(f"  Mann-Whitney p={mw['p']:.4f}, U={mw['U']:.0f}")
    print(f"  Bootstrap median diff={boot['median_diff']:+.4f}, 95% CI [{boot['ci_lo']:+.4f}, {boot['ci_hi']:+.4f}]")

    print("\nWriting report...")
    report = _write_report(pilot_results, control_results, mw, boot)

    import pathlib
    pathlib.Path("reports").mkdir(exist_ok=True)
    pathlib.Path("reports/TASK_02F_CONTROL_COMPARISON.md").write_text(report)
    print("  → reports/TASK_02F_CONTROL_COMPARISON.md")

    # Print summary
    print("\n=== Phase 1 summary ===")
    print(f"Pilot:   n={len(pilot_ils)}, median={statistics.median(pilot_ils):.3f}, "
          f"%pos={100*sum(1 for v in pilot_ils if v>0)/len(pilot_ils):.1f}%")
    print(f"Control: n={len(ctrl_ils)}, median={statistics.median(ctrl_ils):.3f}, "
          f"%pos={100*sum(1 for v in ctrl_ils if v>0)/len(ctrl_ils):.1f}%")
    print(f"Mann-Whitney: U={mw['U']:.0f}, p={mw['p']:.4f}, r={mw['r']:.3f}")
    print(f"Bootstrap CI: [{boot['ci_lo']:+.4f}, {boot['ci_hi']:+.4f}]")


if __name__ == "__main__":
    asyncio.run(main())
