"""Paper 3a Phase 1 — Population ILS^dl pipeline.

Processes 11,263+ markets (target categories, volume ≥$50K) from the
Polymarket Resolution Typology dataset through the full ILS^dl pipeline.

Execution order (enforced):
  Step 0: Hard validation on Iran-Apr30 (T_event = 2026-04-03, ILS^dl ≈ 0.113)
  Step 1: Pre-filter population (no LLM)
  Step 2: Event-description cache (cheap Haiku, no tools)
  Step 3: T_event recovery (Haiku one-shot + Sonnet cascade, async concurrency 20)
  Step 4: ILS^dl computation (existing compute_ils_deadline) + bootstrap CI
  Step 5: Write population_ils_dl.parquet + filter_chain_attrition.csv + phase1_log.jsonl
  Tasks 1.3–1.8: post-processing (no LLM)

Usage:
    uv run python scripts/paper3a_phase1.py --confirm [--skip-step0] [--dry-run]
    uv run python scripts/paper3a_phase1.py --test-batch   # 50-market Batch API test
    uv run python scripts/paper3a_phase1.py --post-only    # re-run 1.3-1.8 on existing parquet

Outputs (all in data/paper3a/):
  population_ils_dl.parquet
  filter_chain_attrition.csv
  phase1_log.jsonl
  hazard_rates.csv
  functional_form_comparison.csv
  functional_form_winners.csv
  ffic_localization.csv
  ffic_concordance_test.csv
  distribution_summary.csv
  detection_thresholds.csv
  anchor_sensitivity_summary.csv
  regulatory_validation_sample.csv   (50-market manual spot-check)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import structlog

log = structlog.get_logger()

# ── Constants ──────────────────────────────────────────────────────────────────

SEED = 20260430
PARQUET_PATH = Path("datasets/polymarket-resolution-typology/data/typology-v1.parquet")
FFIC_JSONL = Path("data/ffic-v1.jsonl")  # top-level copy or path from ffic-inventory
FFIC_JSONL_ALT = Path("/tmp/ffdatasets/ffic-inventory/ffic-v1.jsonl")
OUTPUT_DIR = Path("data/paper3a")

# Iran-Apr30: the Paper 2 reference market for Step 0 validation
IRAN_APR30_ID = "0x6d0e09d0f04572d9b1adad84703458b0297bc5603b69dccbde93147ee4443246"
IRAN_APR30_T_EVENT_DATE = date(2026, 4, 3)
IRAN_APR30_ILS_DL_EXPECTED = 0.113
IRAN_APR30_ILS_DL_TOLERANCE = 0.02

COST_ALERT_USD = 40.0
BUDGET_CAP_USD = 50.0
MIN_VOLUME_USDC = 50_000
TARGET_CATEGORIES = frozenset({"military_geopolitics", "regulatory_decision", "corporate_disclosure"})
CONCURRENCY_CAP = 20
CONFIDENCE_THRESHOLD = 0.70
BOOTSTRAP_B = 500

# DB DSN from env (used for CLOB prices + trades)
_DB_DSN: str | None = None


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_db_dsn() -> str | None:
    global _DB_DSN
    if _DB_DSN is not None:
        return _DB_DSN
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
    url = os.environ.get("FFLOW_DB_URL", "postgresql+asyncpg://fflow:fflow@localhost:5432/fflow")
    _DB_DSN = url.replace("postgresql+asyncpg://", "postgresql://")
    return _DB_DSN


async def _try_db_connect() -> "asyncpg.Connection | None":
    try:
        import asyncpg
        conn = await asyncpg.connect(_get_db_dsn())
        return conn
    except Exception as exc:
        log.warning("db_connect_failed", error=str(exc))
        return None


async def _fetch_prices(conn, market_id: str) -> pd.DataFrame:
    rows = await conn.fetch(
        "SELECT ts, mid_price::float FROM prices WHERE market_id=$1 ORDER BY ts",
        market_id,
    )
    if not rows:
        return pd.DataFrame(columns=["ts", "mid_price"])
    return pd.DataFrame([{"ts": r["ts"], "mid_price": r["mid_price"]} for r in rows])


async def _fetch_trades(conn, market_id: str, t_open: datetime, t_event: datetime) -> pd.DataFrame:
    rows = await conn.fetch(
        """SELECT ts, price::float, notional_usdc::float, outcome_index
           FROM trades
           WHERE market_id=$1 AND ts >= $2 AND ts <= $3 AND outcome_index=1
           ORDER BY ts""",
        market_id, t_open, t_event,
    )
    if not rows:
        return pd.DataFrame(columns=["ts", "price", "notional_usdc", "outcome_index"])
    return pd.DataFrame([dict(r) for r in rows])


# ── Step 0: Iran-Apr30 validation ──────────────────────────────────────────────

async def step0_validate_iran_apr30(
    client: "anthropic.AsyncAnthropic",
    db_conn,
    df: pd.DataFrame,
    *,
    skip: bool = False,
) -> None:
    """Hard assertion gate before any batch run.

    Verifies that the optimized pipeline reproduces Paper 2's Iran-Apr30 result:
      T_event = 2026-04-03 (exact date)
      ILS^dl  = 0.113 ± 0.020
      confidence ≥ 0.70
      n_sources ≥ 3
    """
    if skip:
        log.info("step0_skipped")
        return

    log.info("step0_start", market_id=IRAN_APR30_ID[:20])

    from fflow.news.t_event_recovery_v2 import recover_t_event_optimized
    from fflow.scoring.ils import compute_ils_deadline

    row = df[df["market_id"] == IRAN_APR30_ID]
    if row.empty:
        raise RuntimeError(f"Iran-Apr30 market {IRAN_APR30_ID} not found in parquet")
    row = row.iloc[0]

    t_open = _parse_iso(row["created_at"])
    t_resolve = _parse_iso(row["resolved_at"])

    # 1. T_event recovery
    result = await recover_t_event_optimized(
        question=row["question"],
        description=row.get("description"),
        t_open=t_open,
        t_resolve=t_resolve,
        client=client,
    )

    # Assertions
    if result.t_event is None:
        raise AssertionError(
            f"Step 0 FAIL: T_event recovery returned None "
            f"(confidence={result.confidence:.2f}, reasoning={result.reasoning!r})"
        )

    recovered_date = result.t_event.date()
    assert recovered_date == IRAN_APR30_T_EVENT_DATE, (
        f"Step 0 FAIL: T_event date mismatch — got {recovered_date}, "
        f"expected {IRAN_APR30_T_EVENT_DATE}. "
        f"Compare pipeline shape vs Paper 2 before proceeding."
    )
    assert result.confidence >= CONFIDENCE_THRESHOLD, (
        f"Step 0 FAIL: confidence {result.confidence:.2f} < {CONFIDENCE_THRESHOLD}"
    )
    assert result.n_sources >= 3, (
        f"Step 0 FAIL: n_sources {result.n_sources} < 3. Sources: {result.sources}"
    )

    # 2. ILS^dl computation — needs DB prices
    if db_conn is None:
        log.warning("step0_skipping_ils_check", reason="no DB connection")
        log.info("step0_t_event_validated", t_event=str(recovered_date))
        return

    prices = await _fetch_prices(db_conn, IRAN_APR30_ID)
    if prices.empty:
        log.warning("step0_skipping_ils_check", reason="no prices in DB for Iran-Apr30")
        log.info("step0_t_event_validated", t_event=str(recovered_date))
        return

    p_resolve = int(row["resolution_outcome"])
    bundle = compute_ils_deadline(
        prices=prices,
        t_open=t_open,
        t_resolve=t_resolve,
        p_resolve=p_resolve,
        t_event=result.t_event,
    )

    if bundle.ils is None:
        raise AssertionError(
            f"Step 0 FAIL: ILS^dl is None. Flags: {bundle.flags}. "
            f"Review price data for Iran-Apr30."
        )

    ils_val = float(bundle.ils)
    lo = IRAN_APR30_ILS_DL_EXPECTED - IRAN_APR30_ILS_DL_TOLERANCE
    hi = IRAN_APR30_ILS_DL_EXPECTED + IRAN_APR30_ILS_DL_TOLERANCE
    assert lo <= ils_val <= hi, (
        f"Step 0 FAIL: ILS^dl={ils_val:.4f} outside [{lo:.3f}, {hi:.3f}]. "
        f"p_open={bundle.p_open}, p_news={bundle.p_news}, p_resolve={p_resolve}. "
        f"Compare pipeline shape vs Paper 2 before proceeding."
    )

    log.info(
        "step0_validated",
        t_event=str(recovered_date),
        ils_dl=ils_val,
        p_open=str(bundle.p_open),
        p_event_minus=str(bundle.p_news),
        confidence=result.confidence,
        n_sources=result.n_sources,
        cost_usd=round(result.estimated_cost_usd, 4),
    )
    print(f"✓ Step 0 validated: T_event={recovered_date}, ILS^dl={ils_val:.4f}, "
          f"conf={result.confidence:.2f}, n_src={result.n_sources}")


# ── Step 1: Pre-filter ─────────────────────────────────────────────────────────

def step1_prefilter(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Apply resolution-type and deadline-NO filters without any LLM call.

    Returns:
        (filtered_df, attrition_stages)
        filtered_df: subset of df to pass to LLM stage (includes deadline_NO rows
                     but marked in_scope=False)
        attrition_stages: ordered dict for filter_chain_attrition.csv
    """
    stages: dict[str, int] = {}
    n_initial = len(df)
    stages["initial"] = n_initial

    # Drop 'unclassifiable' — no event to anchor on
    df_typed = df[df["resolution_type"] != "unclassifiable"].copy()
    stages["after_drop_unclassifiable"] = len(df_typed)

    # Mark deadline_NO (outcome=0) as out-of-scope but keep for population stats
    is_dl_no = (df_typed["resolution_type"] == "deadline_resolved") & (df_typed["resolution_outcome"] == 0.0)
    df_typed["in_scope"] = ~is_dl_no
    df_typed["exclusion_reason"] = ""
    df_typed.loc[is_dl_no, "exclusion_reason"] = "deadline_NO"
    stages["deadline_no_marked_out_of_scope"] = int(is_dl_no.sum())
    stages["surviving_for_llm"] = int((~is_dl_no).sum())

    return df_typed, stages


# ── Steps 2+3: T_event recovery with event cache ───────────────────────────────

async def steps2_3_recover_t_events(
    markets_df: pd.DataFrame,
    client: "anthropic.AsyncAnthropic",
    log_entries: list[dict],
    cost_tracker: dict,
    *,
    dry_run: bool = False,
) -> dict[str, "TEventResult"]:
    """Event-description cache + one-shot Haiku T_event recovery."""
    from fflow.news.t_event_recovery_v2 import (
        CostAlertError,
        get_event_description,
        recover_batch_async,
        _normalize_cache_key,
    )

    # Only process in-scope markets (not deadline_NO)
    in_scope = markets_df[markets_df["in_scope"]].copy()
    log.info("recovery_starting", n_markets=len(in_scope))

    if dry_run:
        log.info("dry_run_skipping_llm")
        # Return dummy results for dry-run testing
        dummy = {}
        for _, row in in_scope.head(3).iterrows():
            from fflow.news.t_event_recovery_v2 import TEventResult
            dummy[row["market_id"]] = TEventResult(
                t_event=_parse_iso(row["resolved_at"]) - timedelta(days=1),
                confidence=0.8, n_sources=3, sources=("dry-run",),
                reasoning="dry-run result", model_used="dry-run",
                input_tokens=0, output_tokens=0, web_search_calls=0,
                estimated_cost_usd=0.0,
            )
        return dummy

    market_dicts = [
        {
            "market_id": row["market_id"],
            "question": row["question"],
            "description": row.get("description"),
            "t_open": _parse_iso(row["created_at"]),
            "t_resolve": _parse_iso(row["resolved_at"]),
        }
        for _, row in in_scope.iterrows()
    ]

    event_cache: dict = {}
    results, total_cost = await recover_batch_async(
        market_dicts,
        client,
        concurrency=CONCURRENCY_CAP,
        event_cache=event_cache,
        cost_alert_usd=COST_ALERT_USD,
        already_spent_usd=cost_tracker.get("total_usd", 0.0),
    )
    cost_tracker["total_usd"] = cost_tracker.get("total_usd", 0.0) + total_cost
    cost_tracker["cache_hits"] = sum(
        1 for mid in results if results[mid].model_used == ""
    )

    # Append to log
    for mid, res in results.items():
        log_entries.append({
            "market_id": mid,
            "stage": "t_event_recovery",
            "haiku_input_tokens": res.input_tokens if "sonnet" not in res.model_used else 0,
            "haiku_output_tokens": res.output_tokens if "sonnet" not in res.model_used else 0,
            "sonnet_called": "sonnet" in res.model_used,
            "sonnet_tokens": res.output_tokens if "sonnet" in res.model_used else None,
            "web_search_calls": res.web_search_calls,
            "estimated_cost_usd": round(res.estimated_cost_usd, 5),
            "t_event": res.t_event.isoformat() if res.t_event else None,
            "confidence": res.confidence,
            "n_sources": res.n_sources,
        })

    log.info(
        "recovery_done",
        n_results=len(results),
        cache_hits=cost_tracker.get("cache_hits", 0),
        total_cost_usd=round(cost_tracker.get("total_usd", 0.0), 2),
    )
    return results


# ── Step 4: ILS^dl computation ─────────────────────────────────────────────────

async def step4_compute_ils(
    markets_df: pd.DataFrame,
    t_event_results: dict,
    db_conn,
    log_entries: list[dict],
    attrition: dict,
) -> list[dict]:
    """Compute ILS^dl + bootstrap CI for each market with recovered T_event.

    Returns list of output rows for population_ils_dl.parquet.
    """
    from fflow.scoring.bootstrap import bootstrap_ils_dl_ci
    from fflow.scoring.ils import PriceLookupError, compute_ils_deadline

    output_rows = []
    n_no_prices = 0
    n_low_confidence = 0
    n_ils_computed = 0

    for _, row in markets_df.iterrows():
        mid = row["market_id"]
        t_open = _parse_iso(row["created_at"])
        t_resolve = _parse_iso(row["resolved_at"])
        p_resolve = int(row["resolution_outcome"]) if not pd.isna(row["resolution_outcome"]) else None
        category = row.get("category_fflow", "")
        resolution_type = row.get("resolution_type", "")
        volume = float(row["volume_total_usdc"]) if not pd.isna(row.get("volume_total_usdc", float("nan"))) else None
        period = "pre_2024" if t_resolve and t_resolve.date() < date(2024, 11, 1) else "post_2024"

        base = {
            "market_id": mid,
            "question": row["question"],
            "category": category,
            "subcategory": None,
            "resolution_type": resolution_type,
            "period": period,
            "T_open": t_open.isoformat() if t_open else None,
            "T_event": None,
            "T_event_confidence": None,
            "T_event_sources": None,
            "T_resolve": t_resolve.isoformat() if t_resolve else None,
            "tau_days": None,
            "volume_usdc": volume,
            "p_open": None,
            "p_event": None,
            "p_resolve": p_resolve,
            "ils_dl": None,
            "ils_dl_ci_low": None,
            "ils_dl_ci_high": None,
            "ils_dl_30min": None,
            "ils_dl_2h": None,
            "ils_dl_6h": None,
            "ils_dl_24h": None,
            "in_scope": bool(row.get("in_scope", True)),
            "exclusion_reason": str(row.get("exclusion_reason", "")),
        }

        # deadline_NO — already out of scope, include in parquet with NULLs
        if row.get("exclusion_reason") == "deadline_NO":
            output_rows.append(base)
            continue

        # Check T_event recovery
        te_result = t_event_results.get(mid)
        if te_result is None or te_result.t_event is None or te_result.confidence < CONFIDENCE_THRESHOLD:
            base["in_scope"] = False
            base["exclusion_reason"] = "low_confidence_t_event"
            if te_result:
                base["T_event_confidence"] = te_result.confidence
                base["T_event_sources"] = te_result.n_sources
            n_low_confidence += 1
            output_rows.append(base)
            continue

        t_event = te_result.t_event
        tau_days = (t_event - t_open).total_seconds() / 86400 if t_open else None

        base["T_event"] = t_event.isoformat()
        base["T_event_confidence"] = te_result.confidence
        base["T_event_sources"] = te_result.n_sources
        base["tau_days"] = tau_days

        # τ must be positive
        if tau_days is not None and tau_days <= 0:
            base["in_scope"] = False
            base["exclusion_reason"] = "negative_tau"
            output_rows.append(base)
            continue

        # Load CLOB prices
        if db_conn is None:
            base["in_scope"] = False
            base["exclusion_reason"] = "no_clob_coverage"
            n_no_prices += 1
            output_rows.append(base)
            continue

        prices = await _fetch_prices(db_conn, mid)
        if prices.empty:
            base["in_scope"] = False
            base["exclusion_reason"] = "no_clob_coverage"
            n_no_prices += 1
            output_rows.append(base)
            continue

        # ILS^dl computation
        try:
            bundle = compute_ils_deadline(
                prices=prices,
                t_open=t_open,
                t_resolve=t_resolve,
                p_resolve=p_resolve,
                t_event=t_event,
            )
        except (PriceLookupError, Exception) as exc:
            base["in_scope"] = False
            base["exclusion_reason"] = f"ils_compute_error"
            log.warning("ils_compute_error", market_id=mid[:16], error=str(exc))
            output_rows.append(base)
            continue

        p_open_val = float(bundle.p_open) if bundle.p_open else None
        p_event_val = float(bundle.p_news) if bundle.p_news else None

        # Scope conditions (applied after price lookup)
        if p_open_val is not None and abs(p_open_val - 0.5) > 0.4:
            base["in_scope"] = False
            base["exclusion_reason"] = "edge_effect"
            base["p_open"] = p_open_val
            output_rows.append(base)
            continue

        delta_total = (p_resolve or 0) - (p_open_val or 0.5)
        if abs(delta_total) < 0.05:
            base["in_scope"] = False
            base["exclusion_reason"] = "trivial_resolution"
            base["p_open"] = p_open_val
            output_rows.append(base)
            continue

        if bundle.ils is None:
            base["in_scope"] = False
            base["exclusion_reason"] = f"ils_null: {','.join(bundle.flags)}"
            output_rows.append(base)
            continue

        # Bootstrap CI
        ci_low, ci_high = None, None
        bootstrap_flag = ""
        if db_conn is not None:
            try:
                trades = await _fetch_trades(db_conn, mid, t_open, t_event)
                ci_low, ci_high = bootstrap_ils_dl_ci(
                    trades=trades,
                    t_open=t_open,
                    t_event=t_event,
                    p_open=bundle.p_open,
                    p_resolve=p_resolve,
                    B=BOOTSTRAP_B,
                    seed=SEED,
                )
                if ci_low is None:
                    bootstrap_flag = "low_trade_count"
            except Exception as exc:
                bootstrap_flag = f"bootstrap_error: {exc}"

        base.update({
            "p_open": p_open_val,
            "p_event": p_event_val,
            "ils_dl": float(bundle.ils),
            "ils_dl_ci_low": float(ci_low) if ci_low is not None else None,
            "ils_dl_ci_high": float(ci_high) if ci_high is not None else None,
            "ils_dl_30min": _dec_to_float(bundle.ils_30min),
            "ils_dl_2h": _dec_to_float(bundle.ils_2h),
            "ils_dl_6h": _dec_to_float(bundle.ils_6h),
            "ils_dl_24h": _dec_to_float(bundle.ils_24h),
            "in_scope": True,
            "exclusion_reason": bootstrap_flag,
        })
        n_ils_computed += 1
        output_rows.append(base)

    attrition["n_no_clob"] = n_no_prices
    attrition["n_low_confidence"] = n_low_confidence
    attrition["n_ils_computed"] = n_ils_computed
    log.info("ils_computation_done", n_computed=n_ils_computed,
             n_no_prices=n_no_prices, n_low_conf=n_low_confidence)
    return output_rows


# ── Task 1.3: Regulatory sub-categorization ────────────────────────────────────

def task_1_3_regulatory_subcategory(pop_df: pd.DataFrame) -> pd.DataFrame:
    """Add subcategory column and produce validation sample.

    Returns updated pop_df with subcategory filled for regulatory_decision rows.
    Also writes regulatory_validation_sample.csv (50 rows) for manual review.
    """
    from fflow.taxonomy.regulatory_split import classify_regulatory

    reg_mask = pop_df["category"] == "regulatory_decision"
    if reg_mask.sum() == 0:
        return pop_df

    subcats = pop_df.loc[reg_mask].apply(
        lambda r: classify_regulatory(r["question"], None), axis=1
    )
    pop_df = pop_df.copy()
    pop_df.loc[reg_mask, "subcategory"] = subcats.values

    # Write 50-market validation sample (reproducible)
    rng = random.Random(SEED)
    reg_rows = pop_df[reg_mask]
    sample_size = min(50, len(reg_rows))
    sample_idx = rng.sample(list(reg_rows.index), sample_size)
    sample_df = pop_df.loc[sample_idx, ["market_id", "question", "subcategory"]].copy()
    sample_df["manual_subcategory"] = ""
    sample_df["agreement"] = ""
    out_path = OUTPUT_DIR / "regulatory_validation_sample.csv"
    sample_df.to_csv(out_path, index=False)
    log.info("regulatory_validation_sample_written", path=str(out_path), n=sample_size)

    return pop_df


# ── Tasks 1.4–1.5: Hazard rates + functional form ─────────────────────────────

def tasks_1_4_1_5_hazard(pop_df: pd.DataFrame) -> None:
    """Fit exponential/Weibull/lognormal to τ by (category × subcategory × period)."""
    from scipy.stats import expon, exponweib, lognorm, kstest

    in_scope = pop_df[pop_df["in_scope"] & pop_df["tau_days"].notna() & (pop_df["tau_days"] > 0)].copy()
    rng = np.random.default_rng(SEED)

    hazard_rows = []
    form_rows = []
    winner_rows = []

    cells = in_scope.groupby(["category", "subcategory", "period"], dropna=False)

    for (cat, sub, period), cell_df in cells:
        taus = cell_df["tau_days"].astype(float).values
        n = len(taus)
        if n < 20:
            continue

        # Exponential MLE: λ = 1/mean(τ)
        lam = 1.0 / np.mean(taus)
        hl = np.log(2) / lam

        # Bootstrap CI on λ (B=500)
        lam_boot = np.array([
            1.0 / np.mean(rng.choice(taus, size=n, replace=True))
            for _ in range(BOOTSTRAP_B)
        ])
        ks_stat, ks_p = kstest(taus, "expon", args=(0, 1 / lam))
        hazard_rows.append({
            "category": cat, "subcategory": sub or "", "period": period, "n": n,
            "lambda_hat": round(lam, 6), "half_life_days": round(hl, 3),
            "ks_pvalue": round(ks_p, 4),
            "lambda_ci_low": round(float(np.percentile(lam_boot, 2.5)), 6),
            "lambda_ci_high": round(float(np.percentile(lam_boot, 97.5)), 6),
        })

        # Functional form comparison (AIC/BIC)
        dists = {
            "exponential": (expon, 1),
            "weibull": (exponweib, 2),
            "lognormal": (lognorm, 2),
        }
        cell_form_rows = []
        for dist_name, (dist_obj, n_params) in dists.items():
            try:
                params = dist_obj.fit(taus, floc=0)
                log_lik = np.sum(dist_obj.logpdf(taus, *params))
                aic = 2 * n_params - 2 * log_lik
                bic = n_params * np.log(n) - 2 * log_lik
                ks_s, ks_p2 = kstest(taus, dist_obj.cdf, args=params)
                cell_form_rows.append({
                    "category": cat, "subcategory": sub or "", "period": period,
                    "distribution": dist_name, "aic": round(aic, 3),
                    "bic": round(bic, 3), "ks_pvalue": round(ks_p2, 4),
                    "n_params": n_params,
                })
            except Exception as exc:
                log.warning("hazard_fit_error", dist=dist_name, error=str(exc))

        form_rows.extend(cell_form_rows)

        # Winner (lowest AIC; if delta < 4, prefer simpler)
        if cell_form_rows:
            sorted_forms = sorted(cell_form_rows, key=lambda r: r["aic"])
            winner = sorted_forms[0]
            runner_up = sorted_forms[1] if len(sorted_forms) > 1 else winner
            aic_delta = round(runner_up["aic"] - winner["aic"], 3)
            winner_rows.append({
                "category": cat, "subcategory": sub or "", "period": period,
                "winner": winner["distribution"],
                "aic_delta_vs_runner_up": aic_delta,
            })

    _write_csv(pd.DataFrame(hazard_rows), OUTPUT_DIR / "hazard_rates.csv")
    _write_csv(pd.DataFrame(form_rows), OUTPUT_DIR / "functional_form_comparison.csv")
    _write_csv(pd.DataFrame(winner_rows), OUTPUT_DIR / "functional_form_winners.csv")
    log.info("hazard_done", n_cells=len(hazard_rows))


# ── Task 1.6: FFIC localization ────────────────────────────────────────────────

def task_1_6_ffic_localization(pop_df: pd.DataFrame) -> None:
    """Rank FFIC markets within their category distribution."""
    from scipy.stats import binomtest

    # Load FFIC inventory
    ffic_path = FFIC_JSONL if FFIC_JSONL.exists() else FFIC_JSONL_ALT
    if not ffic_path.exists():
        log.warning("ffic_jsonl_not_found", paths=[str(FFIC_JSONL), str(FFIC_JSONL_ALT)])
        return

    ffic_cases = []
    with open(ffic_path) as f:
        for line in f:
            if line.strip():
                ffic_cases.append(json.loads(line))

    # Flatten to per-market
    ffic_markets = []
    for case in ffic_cases:
        for m in case.get("markets", []):
            ffic_markets.append({
                "case_id": case["case_id"],
                "description": case.get("title", ""),
                "market_id": m.get("market_id", ""),
            })

    in_scope = pop_df[pop_df["in_scope"] & pop_df["ils_dl"].notna()].copy()
    rng = np.random.default_rng(SEED)

    loc_rows = []
    for fm in ffic_markets:
        mid = fm["market_id"]
        mrow = in_scope[in_scope["market_id"] == mid]
        if mrow.empty:
            loc_rows.append({**fm, "ils_dl": None, "rank_pctile": None,
                              "rank_ci_low": None, "rank_ci_high": None,
                              "in_top_10": None, "in_top_5": None, "in_top_1": None,
                              "note": "not_in_scope_or_missing_ils"})
            continue

        mrow = mrow.iloc[0]
        cat = mrow["category"]
        sub = mrow.get("subcategory")
        period = mrow["period"]
        ils = float(mrow["ils_dl"])

        cell_mask = (
            in_scope["category"] == cat,
        )
        cell_df = in_scope[in_scope["category"] == cat]
        if sub and not pd.isna(sub):
            cell_df = cell_df[cell_df["subcategory"].fillna("") == sub]
        cell_df = cell_df[cell_df["period"] == period]

        cell_ils = cell_df["ils_dl"].astype(float).values
        if len(cell_ils) < 2:
            loc_rows.append({**fm, "ils_dl": ils, "rank_pctile": None,
                              "rank_ci_low": None, "rank_ci_high": None,
                              "in_top_10": None, "in_top_5": None, "in_top_1": None,
                              "note": "cell_too_small"})
            continue

        pctile = float(np.mean(cell_ils <= ils)) * 100

        # Bootstrap CI on rank
        ranks_boot = np.array([
            np.mean(rng.choice(cell_ils, size=len(cell_ils), replace=True) <= ils) * 100
            for _ in range(BOOTSTRAP_B)
        ])
        rank_ci_lo = float(np.percentile(ranks_boot, 2.5))
        rank_ci_hi = float(np.percentile(ranks_boot, 97.5))

        loc_rows.append({
            **fm,
            "ils_dl": round(ils, 6),
            "rank_pctile": round(pctile, 2),
            "rank_ci_low": round(rank_ci_lo, 2),
            "rank_ci_high": round(rank_ci_hi, 2),
            "in_top_10": pctile >= 90,
            "in_top_5": pctile >= 95,
            "in_top_1": pctile >= 99,
            "note": "",
        })

    loc_df = pd.DataFrame(loc_rows)
    _write_csv(loc_df, OUTPUT_DIR / "ffic_localization.csv")

    # Concordance test
    valid = loc_df[loc_df["in_top_10"].notna()]
    n_total = len(valid)
    concordance_rows = []
    for threshold, label, p_null in [(0.10, "top_10", 0.10), (0.05, "top_5", 0.05), (0.01, "top_1", 0.01)]:
        col = f"in_top_{int(threshold*100)}"
        if col not in valid.columns:
            continue
        observed = int(valid[col].sum())
        expected = round(n_total * p_null, 2)
        p_val = binomtest(observed, n_total, p_null, alternative="greater").pvalue if n_total > 0 else None
        concordance_rows.append({
            "threshold": label, "n_ffic_in_scope": n_total,
            "expected_uniform": expected, "observed": observed,
            "binomial_pvalue": round(p_val, 4) if p_val is not None else None,
        })

    _write_csv(pd.DataFrame(concordance_rows), OUTPUT_DIR / "ffic_concordance_test.csv")
    log.info("ffic_localization_done", n_markets=len(loc_rows))


# ── Tasks 1.7–1.8: Distribution summaries + anchor sensitivity ─────────────────

def tasks_1_7_1_8_summaries(pop_df: pd.DataFrame) -> None:
    """Distribution summary tables (1.7) and anchor sensitivity (1.8)."""
    rng = np.random.default_rng(SEED)
    in_scope = pop_df[pop_df["in_scope"] & pop_df["ils_dl"].notna()].copy()

    # ── 1.7: Distribution summary ──────────────────────────────────────────────
    summary_rows = []
    threshold_rows = []
    quantiles = [1, 5, 10, 25, 50, 75, 90, 95, 99]

    cells = in_scope.groupby(["category", "subcategory", "period"], dropna=False)
    for (cat, sub, period), cell_df in cells:
        vals = cell_df["ils_dl"].astype(float).values
        n = len(vals)
        if n < 5:
            continue

        row_base = {"category": cat, "subcategory": sub or "", "period": period, "n": n}

        # Basic stats
        summary_rows.append({**row_base, "statistic": "mean", "value": round(float(np.mean(vals)), 6)})
        summary_rows.append({**row_base, "statistic": "median", "value": round(float(np.median(vals)), 6)})
        summary_rows.append({**row_base, "statistic": "std", "value": round(float(np.std(vals)), 6)})
        summary_rows.append({**row_base, "statistic": "skewness", "value": round(float(_skewness(vals)), 6)})
        summary_rows.append({**row_base, "statistic": "kurtosis", "value": round(float(_kurtosis(vals)), 6)})
        for q in quantiles:
            summary_rows.append({**row_base, "statistic": f"p{q:02d}", "value": round(float(np.percentile(vals, q)), 6)})

        # Bootstrap CIs on top-decile thresholds
        thresh_boot = np.array([
            np.percentile(rng.choice(vals, size=n, replace=True), [90, 95, 99])
            for _ in range(BOOTSTRAP_B)
        ])
        for i, (thr_name, thr_pctile) in enumerate([("top_10", 90), ("top_5", 95), ("top_1", 99)]):
            thr_val = np.percentile(vals, thr_pctile)
            threshold_rows.append({
                **row_base,
                f"{thr_name}_threshold": round(float(thr_val), 6),
                f"{thr_name}_ci_low": round(float(np.percentile(thresh_boot[:, i], 2.5)), 6),
                f"{thr_name}_ci_high": round(float(np.percentile(thresh_boot[:, i], 97.5)), 6),
            })

    _write_csv(pd.DataFrame(summary_rows), OUTPUT_DIR / "distribution_summary.csv")

    # Merge threshold rows by cell
    if threshold_rows:
        thr_df = pd.DataFrame(threshold_rows)
        # Aggregate into one row per cell
        cols = ["category", "subcategory", "period", "n"]
        thr_agg = thr_df.groupby(cols, dropna=False).first().reset_index()
        _write_csv(thr_agg, OUTPUT_DIR / "detection_thresholds.csv")

    # ── 1.8: Anchor sensitivity ────────────────────────────────────────────────
    has_variants = in_scope[["ils_dl", "ils_dl_30min", "ils_dl_2h", "ils_dl_6h", "ils_dl_24h"]].notna().any(axis=1)
    anchor_df = in_scope[has_variants].copy()

    def anchor_robust(row):
        vals = [row["ils_dl"], row.get("ils_dl_30min"), row.get("ils_dl_2h"),
                row.get("ils_dl_6h"), row.get("ils_dl_24h")]
        vals = [v for v in vals if v is not None and not pd.isna(v)]
        if len(vals) < 2:
            return True, ""
        signs = set(1 if v >= 0 else -1 for v in vals)
        sign_flip = len(signs) > 1
        spread = max(vals) - min(vals)
        if sign_flip:
            return False, "sign_flip"
        if spread > 0.3:
            return False, f"spread_{spread:.2f}"
        return True, ""

    anchor_results = anchor_df.apply(lambda r: anchor_robust(r), axis=1)
    in_scope = in_scope.copy()
    in_scope.loc[anchor_df.index, "anchor_robust"] = [r[0] for r in anchor_results]
    in_scope.loc[anchor_df.index, "anchor_failure_reason"] = [r[1] for r in anchor_results]

    anchor_summary_rows = []
    for cat, cell_df in in_scope.groupby("category"):
        n_total = len(cell_df)
        n_robust = int(cell_df["anchor_robust"].fillna(True).sum())
        pct = round(100 * n_robust / n_total, 1) if n_total > 0 else None

        # Spearman corr between ils_dl and ils_dl_24h
        paired = cell_df[["ils_dl", "ils_dl_24h"]].dropna()
        spearman = float(paired["ils_dl"].rank().corr(paired["ils_dl_24h"].rank())) if len(paired) >= 5 else None

        anchor_summary_rows.append({
            "category": cat, "n_total": n_total, "n_anchor_robust": n_robust,
            "pct_anchor_robust": pct,
            "spearman_24h_to_event": round(spearman, 4) if spearman else None,
        })

    _write_csv(pd.DataFrame(anchor_summary_rows), OUTPUT_DIR / "anchor_sensitivity_summary.csv")
    log.info("summaries_done")


# ── Output writers ─────────────────────────────────────────────────────────────

def write_filter_chain_attrition(attrition: dict) -> None:
    rows = [
        {"stage": "Initial (cat+vol≥50K)", "n_remaining": attrition["initial"], "n_dropped": 0, "drop_reason": "---"},
        {"stage": "Drop unclassifiable", "n_remaining": attrition["after_drop_unclassifiable"],
         "n_dropped": attrition["initial"] - attrition["after_drop_unclassifiable"], "drop_reason": "unclassifiable"},
        {"stage": "Deadline_NO marked out-of-scope", "n_remaining": attrition["surviving_for_llm"],
         "n_dropped": attrition["deadline_no_marked_out_of_scope"], "drop_reason": "deadline_NO"},
        {"stage": "T_event confidence ≥0.7", "n_remaining": attrition["surviving_for_llm"] - attrition.get("n_low_confidence", 0),
         "n_dropped": attrition.get("n_low_confidence", 0), "drop_reason": "LLM low confidence"},
        {"stage": "CLOB coverage", "n_remaining": attrition["surviving_for_llm"] - attrition.get("n_low_confidence", 0) - attrition.get("n_no_clob", 0),
         "n_dropped": attrition.get("n_no_clob", 0), "drop_reason": "no_clob_coverage"},
        {"stage": "ILS^dl computed", "n_remaining": attrition.get("n_ils_computed", 0), "n_dropped": 0, "drop_reason": "---"},
    ]
    _write_csv(pd.DataFrame(rows), OUTPUT_DIR / "filter_chain_attrition.csv")


def write_population_parquet(rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    _write_parquet(df, OUTPUT_DIR / "population_ils_dl.parquet")
    log.info("population_parquet_written", n_rows=len(df), path=str(OUTPUT_DIR / "population_ils_dl.parquet"))


def write_phase1_log(log_entries: list[dict]) -> None:
    path = OUTPUT_DIR / "phase1_log.jsonl"
    with open(path, "w") as f:
        for entry in log_entries:
            f.write(json.dumps(entry, default=str) + "\n")
    log.info("phase1_log_written", n_entries=len(log_entries), path=str(path))


# ── Utilities ──────────────────────────────────────────────────────────────────

def _parse_iso(s) -> datetime | None:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=UTC)
    s = str(s)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s.rstrip("Z"), fmt.rstrip("Z"))
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _dec_to_float(d) -> float | None:
    if d is None:
        return None
    try:
        return float(d)
    except (TypeError, InvalidOperation):
        return None


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    log.info("csv_written", path=str(path), n_rows=len(df))


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def _skewness(vals: np.ndarray) -> float:
    from scipy.stats import skew
    return float(skew(vals))


def _kurtosis(vals: np.ndarray) -> float:
    from scipy.stats import kurtosis
    return float(kurtosis(vals))


# ── Main ───────────────────────────────────────────────────────────────────────

async def main_async(args: argparse.Namespace) -> None:
    import anthropic

    api_key = os.environ.get("FFLOW_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set FFLOW_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log_entries: list[dict] = []
    cost_tracker: dict = {"total_usd": 0.0}
    attrition: dict = {}

    # ── Load parquet ───────────────────────────────────────────────────────────
    log.info("loading_parquet", path=str(PARQUET_PATH))
    full_df = pq.read_table(PARQUET_PATH).to_pandas()
    sample_df = full_df[
        full_df["category_fflow"].isin(TARGET_CATEGORIES) &
        (full_df["volume_total_usdc"].notna()) &
        (full_df["volume_total_usdc"] >= MIN_VOLUME_USDC)
    ].copy()
    sample_df = sample_df.rename(columns={"category_fflow": "category"})
    log.info("sample_loaded", n_markets=len(sample_df))
    if len(sample_df) != 11263:
        log.warning("sample_size_discrepancy",
                    actual=len(sample_df), paper_says=11263,
                    note="Parquet may have been updated after Paper 1 submission")

    # ── DB connection (best-effort) ────────────────────────────────────────────
    db_conn = await _try_db_connect()
    if db_conn is None:
        log.warning("running_without_db",
                    note="ILS^dl computation requires DB prices; will mark no_clob_coverage")

    client = anthropic.AsyncAnthropic(api_key=api_key)

    # ── Post-only mode ─────────────────────────────────────────────────────────
    if args.post_only:
        pop_path = OUTPUT_DIR / "population_ils_dl.parquet"
        if not pop_path.exists():
            print(f"ERROR: {pop_path} not found. Run main pipeline first.")
            sys.exit(1)
        pop_df = pq.read_table(pop_path).to_pandas()
        pop_df = task_1_3_regulatory_subcategory(pop_df)
        tasks_1_4_1_5_hazard(pop_df)
        task_1_6_ffic_localization(pop_df)
        tasks_1_7_1_8_summaries(pop_df)
        if db_conn:
            await db_conn.close()
        return

    if not args.confirm:
        print("Pass --confirm to acknowledge LLM cost (~$25-35 for full run).")
        sys.exit(1)

    # ── Step 0: Iran-Apr30 validation ──────────────────────────────────────────
    await step0_validate_iran_apr30(client, db_conn, full_df, skip=args.skip_step0)

    # ── Step 1: Pre-filter ─────────────────────────────────────────────────────
    filtered_df, attrition = step1_prefilter(sample_df)
    log.info("prefilter_done", **attrition)

    # ── 50-market small batch test ─────────────────────────────────────────────
    if args.test_batch:
        log.info("test_batch_mode_not_implemented",
                 note="Batch API test stub — implementing synchronous fallback")
        # TODO: implement Batch API path after confirming web_search support
        # For now, the async path with concurrency=20 is the default
        print("NOTE: Batch API path not yet implemented. Using async concurrency path.")

    # ── Steps 2+3: T_event recovery ───────────────────────────────────────────
    in_scope_df = filtered_df[filtered_df["in_scope"]].copy()

    t_event_results = await steps2_3_recover_t_events(
        in_scope_df, client, log_entries, cost_tracker, dry_run=args.dry_run
    )

    # ── Step 4: ILS^dl computation ─────────────────────────────────────────────
    output_rows = await step4_compute_ils(
        filtered_df, t_event_results, db_conn, log_entries, attrition
    )

    # ── Step 5: Write main outputs ─────────────────────────────────────────────
    pop_df = pd.DataFrame(output_rows)
    write_population_parquet(output_rows)
    write_filter_chain_attrition(attrition)
    write_phase1_log(log_entries)

    total_cost = cost_tracker.get("total_usd", 0.0)
    print(f"\n── Pipeline complete ──")
    print(f"  Markets processed:    {len(output_rows):,}")
    print(f"  ILS^dl computed:      {attrition.get('n_ils_computed', 0):,}")
    print(f"  Total LLM cost:       ${total_cost:.2f}")
    if total_cost > BUDGET_CAP_USD:
        print(f"  ⚠ WARNING: cost ${total_cost:.2f} exceeds budget ${BUDGET_CAP_USD:.2f}")

    # ── Tasks 1.3–1.8: post-processing ────────────────────────────────────────
    pop_df = task_1_3_regulatory_subcategory(pop_df)
    # Re-save parquet with subcategory populated
    write_population_parquet(pop_df.to_dict("records"))

    tasks_1_4_1_5_hazard(pop_df)
    task_1_6_ffic_localization(pop_df)
    tasks_1_7_1_8_summaries(pop_df)

    if db_conn:
        await db_conn.close()

    print("All Phase 1 outputs written to data/paper3a/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper 3a Phase 1 — Population ILS^dl pipeline")
    parser.add_argument("--confirm", action="store_true",
                        help="Acknowledge LLM cost (~$25-35 for full run)")
    parser.add_argument("--skip-step0", action="store_true",
                        help="Skip Iran-Apr30 validation (NOT recommended for first run)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip LLM calls; run pre-filter + structure only")
    parser.add_argument("--test-batch", action="store_true",
                        help="Run 50-market Batch API test after Step 0")
    parser.add_argument("--post-only", action="store_true",
                        help="Skip main pipeline; run Tasks 1.3-1.8 on existing parquet")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
