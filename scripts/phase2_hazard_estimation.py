"""Phase 2 — Hazard estimation for deadline_resolved YES markets.

Samples 20 YES deadline markets per category (military_geopolitics,
regulatory_decision, corporate_disclosure), recovers T_event via Tier 3
web search, fits exponential hazard model λ̂ = 1/mean(τ), and writes
reports/TASK_03_HAZARD_ESTIMATION.md.

Usage:
    uv run python scripts/phase2_hazard_estimation.py --confirm

Cost cap: $20 per run; aborts if exceeded. Expected ~$5.40.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
from sqlalchemy import select, text

from fflow.db import AsyncSessionLocal
from fflow.models import Market, NewsTimestamp
from fflow.news.llm_match import llm_extract_date, reset_call_counter
from fflow.scoring.hazard_fit import HazardFit, fit_exponential

log = structlog.get_logger()

CATEGORIES = ["military_geopolitics", "regulatory_decision", "corporate_disclosure"]
SAMPLE_N = 20
COST_PER_CALL_EST = 0.09  # conservative estimate
COST_CAP = 20.0
MIN_CONFIDENCE = 0.70

# ── helpers ──────────────────────────────────────────────────────────────────


async def sample_eligible_markets(category: str, n: int) -> list[dict[str, Any]]:
    """Return up to n YES deadline markets with trade data, no existing T_event."""
    async with AsyncSessionLocal() as session:
        # Markets that are YES deadline, have timestamps,
        # and don't already have a NewsTimestamp recovery.
        # No trade/price data required — hazard model only needs T_open + T_event.
        rows = (
            await session.execute(
                text("""
                    SELECT m.id, m.question, m.description,
                           m.created_at_chain, m.resolved_at
                    FROM markets m
                    WHERE m.category_fflow = :cat
                      AND m.resolution_type = 'deadline_resolved'
                      AND m.resolution_outcome = 1
                      AND m.created_at_chain IS NOT NULL
                      AND m.resolved_at IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM news_timestamps nt WHERE nt.market_id = m.id
                      )
                    ORDER BY RANDOM()
                    LIMIT :lim
                """),
                {"cat": category, "lim": n},
            )
        ).fetchall()
    return [dict(r._mapping) for r in rows]


async def store_news_timestamp(
    market_id: str,
    t_event: datetime,
    tier: int,
    confidence: float,
    notes: str,
    sources: tuple[str, ...],
) -> None:
    async with AsyncSessionLocal() as session:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        publisher = ", ".join(sources[:3]) if sources else None
        now = datetime.now(UTC)
        stmt = (
            pg_insert(NewsTimestamp)
            .values(
                market_id=market_id,
                t_news=t_event,
                tier=tier,
                confidence=confidence,
                notes=notes,
                source_publisher=publisher,
                recovered_at=now,
            )
            .on_conflict_do_update(
                index_elements=["market_id"],
                set_={
                    "t_news": t_event,
                    "tier": tier,
                    "confidence": confidence,
                    "notes": notes,
                    "source_publisher": publisher,
                    "recovered_at": now,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()


# ── main ─────────────────────────────────────────────────────────────────────


async def run(confirm: bool, api_key: str) -> None:
    reset_call_counter()
    total_calls = 0
    results: dict[str, list[dict[str, Any]]] = {cat: [] for cat in CATEGORIES}
    low_confidence: list[dict[str, Any]] = []

    for category in CATEGORIES:
        log.info("phase2_sampling", category=category, n=SAMPLE_N)
        markets = await sample_eligible_markets(category, SAMPLE_N)
        log.info("phase2_sampled", category=category, found=len(markets))

        for mkt in markets:
            cost_so_far = total_calls * COST_PER_CALL_EST
            if cost_so_far >= COST_CAP:
                log.warning("phase2_cost_cap_reached", cost_est=cost_so_far)
                print(f"\n⚠ Cost cap ${COST_CAP} reached after {total_calls} calls. Stopping.")
                break

            if total_calls > 0 and total_calls % 10 == 0:
                print(f"  [cost monitor] ~${total_calls * COST_PER_CALL_EST:.2f} after {total_calls} calls")

            result = await llm_extract_date(
                question=mkt["question"],
                description=mkt.get("description"),
                api_key=api_key,
                confirmed=confirm,
                recovery_mode="t_event",
            )
            total_calls += 1

            if result is None:
                log.info("phase2_no_result", market_id=mkt["id"], question=mkt["question"][:60])
                continue

            if result.confidence < MIN_CONFIDENCE:
                log.info("phase2_low_confidence", market_id=mkt["id"],
                         confidence=result.confidence, question=mkt["question"][:60])
                low_confidence.append({
                    "market_id": mkt["id"],
                    "question": mkt["question"],
                    "t_event": result.t_news,
                    "confidence": result.confidence,
                    "notes": result.notes,
                })
                continue

            t_open = mkt["created_at_chain"]
            if t_open.tzinfo is None:
                t_open = t_open.replace(tzinfo=UTC)
            t_event = result.t_news
            tau_days = (t_event - t_open).total_seconds() / 86400

            if tau_days <= 0:
                log.warning("phase2_negative_tau", market_id=mkt["id"],
                            t_open=t_open.isoformat(), t_event=t_event.isoformat())
                continue

            results[category].append({
                "market_id": mkt["id"],
                "question": mkt["question"],
                "t_open": t_open,
                "t_event": t_event,
                "tau_days": tau_days,
                "confidence": result.confidence,
                "notes": result.notes,
                "sources": result.sources,
            })

            # Persist to DB
            await store_news_timestamp(
                market_id=mkt["id"],
                t_event=t_event,
                tier=3,
                confidence=result.confidence,
                notes=result.notes,
                sources=result.sources,
            )

            log.info("phase2_result", category=category, market_id=mkt["id"],
                     tau_days=round(tau_days, 2), confidence=result.confidence)

    # Fit hazard models
    fits: list[HazardFit] = []
    for category in CATEGORIES:
        tau_list = [r["tau_days"] for r in results[category]]
        if len(tau_list) < 3:
            log.warning("phase2_insufficient_data", category=category, n=len(tau_list))
            continue
        fit = fit_exponential(category, tau_list)
        fits.append(fit)
        log.info("phase2_fit", category=category, n=fit.n,
                 lambda_mle=round(fit.lambda_mle, 4),
                 half_life_days=round(fit.half_life_days, 1),
                 ks_pvalue=round(fit.ks_pvalue, 3))

    # Write report
    report_path = Path(__file__).parent.parent / "reports" / "TASK_03_HAZARD_ESTIMATION.md"
    write_report(report_path, fits, results, low_confidence, total_calls)
    print(f"\nReport written: {report_path}")
    print(f"Total LLM calls: {total_calls} | Estimated cost: ~${total_calls * COST_PER_CALL_EST:.2f}")


def write_report(
    path: Path,
    fits: list[HazardFit],
    results: dict[str, list[dict[str, Any]]],
    low_confidence: list[dict[str, Any]],
    total_calls: int,
) -> None:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Task 03 — Hazard Estimation Report",
        f"\nGenerated: {now}  ",
        f"Total Tier-3 calls: {total_calls} | Est. cost: ~${total_calls * COST_PER_CALL_EST:.2f}",
        "",
        "## Methodology",
        "",
        "For each category, 20 YES-resolved deadline markets were sampled randomly.",
        "T_event was recovered via Tier 3 (Claude + web search, `recovery_mode='t_event'`).",
        "τ = T_event − T_open in days. Exponential MLE: λ̂ = 1/mean(τ).",
        "KS test: pvalue < 0.05 → reject exponential (use λ as approximate).",
        "",
        "## Results by Category",
        "",
        "| Category | n | λ (events/day) | Half-life (days) | mean τ | p25 | p50 | p75 | KS stat | KS p |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    for fit in fits:
        lines.append(
            f"| {fit.category} | {fit.n} | {fit.lambda_mle:.4f} | {fit.half_life_days:.1f} "
            f"| {fit.mean_tau_days:.1f} | {fit.tau_p25:.1f} | {fit.tau_p50:.1f} "
            f"| {fit.tau_p75:.1f} | {fit.ks_statistic:.3f} | {fit.ks_pvalue:.3f} |"
        )

    lines += [
        "",
        "## Interpretation",
        "",
    ]
    for fit in fits:
        ks_note = "exponential fit adequate" if fit.ks_pvalue >= 0.05 else "REJECT exponential (p<0.05) — use λ as rough approximation only"
        lines.append(
            f"- **{fit.category}**: median event occurs {fit.tau_p50:.1f} days after market open; "
            f"half-life {fit.half_life_days:.1f} d. KS: {ks_note}."
        )

    lines += [
        "",
        "## Per-Market Detail",
        "",
    ]
    for category in CATEGORIES:
        lines.append(f"### {category}")
        lines.append("")
        lines.append("| Market (truncated) | T_open | T_event | τ (days) | conf | Sources |")
        lines.append("|---|---|---|---|---|---|")
        for r in sorted(results[category], key=lambda x: x["tau_days"]):
            q = r["question"][:60].replace("|", "/")
            t_open = r["t_open"].strftime("%Y-%m-%d")
            t_ev = r["t_event"].strftime("%Y-%m-%d")
            srcs = ", ".join(r["sources"][:3]) if r["sources"] else "—"
            lines.append(
                f"| {q} | {t_open} | {t_ev} | {r['tau_days']:.1f} | {r['confidence']:.2f} | {srcs} |"
            )
        lines.append("")

    if low_confidence:
        lines += [
            "## Low-Confidence Results (excluded from fit)",
            "",
            "| Market | T_event | conf | Notes |",
            "|---|---|---|---|",
        ]
        for r in low_confidence:
            q = r["question"][:60].replace("|", "/")
            t_ev = r["t_event"].strftime("%Y-%m-%d") if r.get("t_event") else "N/A"
            lines.append(f"| {q} | {t_ev} | {r['confidence']:.2f} | {r['notes'][:80]} |")

    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2 hazard estimation")
    parser.add_argument("--confirm", action="store_true",
                        help="Acknowledge per-call LLM cost (~$0.09/call)")
    args = parser.parse_args()

    if not args.confirm:
        print("Pass --confirm to acknowledge LLM cost (~$5.40 expected, $20 cap).")
        sys.exit(1)

    api_key = os.environ.get("FFLOW_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Set FFLOW_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.")
        sys.exit(1)

    asyncio.run(run(confirm=True, api_key=api_key))


if __name__ == "__main__":
    main()
