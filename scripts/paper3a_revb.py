"""Paper 3a Phase B — Revision computations (reviewer response).

Runs tasks B1–B8 in dependency order:
  B7 → B6 → B5 → B2 → B3 → B8 → B4 → B1

Outputs go to data/paper3a/revision1/.
LLM calls (B1, B4) use OpenAI mini; budget hard cap $30.

Usage:
    uv run python scripts/paper3a_revb.py [--skip-llm] [--only B2]
    --skip-llm   run all pure-computation tasks; skip B1+B4
    --only Bx    run only the named task (comma-separated, e.g. --only B2,B3)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import structlog
from scipy.stats import expon, exponweib, kstest, lognorm, skew

sys.path.insert(0, str(Path(__file__).parent.parent))

log = structlog.get_logger()

SEED = 20260430
rng = np.random.default_rng(SEED)
BOOTSTRAP_B = 1000
LLM_COST_CAP_USD = 30.0

ROOT = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "data" / "paper3a" / "revision1"
POP_PARQUET = ROOT / "data" / "paper3a" / "population_ils_dl.parquet"
CHECKPOINT = ROOT / "data" / "paper3a" / "t_event_checkpoint.jsonl"
HAZARD_CSV = ROOT / "data" / "paper3a" / "hazard_rates.csv"
FUNC_CSV = ROOT / "data" / "paper3a" / "functional_form_comparison.csv"
ANCHOR_CSV = ROOT / "data" / "paper3a" / "anchor_sensitivity_summary.csv"
TYPOLOGY_PARQUET = ROOT / "datasets" / "polymarket-resolution-typology" / "data" / "typology-v1.parquet"
FFIC_JSONL = Path("/tmp/ffdatasets/ffic-inventory/ffic-dataset/data/ffic-v1.jsonl")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ── helpers ────────────────────────────────────────────────────────────────────

def _bucket(row) -> str:
    sub = str(row.get("subcategory") or "")
    if "announcement" in sub:
        return "regulatory_announcement"
    if "formal" in sub:
        return "regulatory_formal"
    return "other"


def _load_pop() -> pd.DataFrame:
    return pq.read_table(POP_PARQUET).to_pandas()


def _write_csv(df: pd.DataFrame, name: str) -> None:
    p = OUTPUT_DIR / name
    df.to_csv(p, index=False)
    log.info("csv_written", path=str(p), n=len(df))


def _write_json(obj: dict, name: str) -> None:
    p = OUTPUT_DIR / name
    p.write_text(json.dumps(obj, indent=2, default=str))
    log.info("json_written", path=str(p))


# ── B7: anchor sensitivity recomputed on 88-market sample ─────────────────────

def run_b7(pop: pd.DataFrame) -> pd.DataFrame:
    """Recompute anchor_sensitivity_summary.csv with explicit 88-market denominator."""
    print("\n── B7: anchor sensitivity (88-market denominator) ──")
    ils = pop[pop["in_scope"] & pop["ils_dl"].notna()].copy()
    assert len(ils) == 88, f"Expected 88 ILS markets, got {len(ils)}"

    def anchor_robust(row):
        vals = [row["ils_dl"], row.get("ils_dl_30min"), row.get("ils_dl_2h"),
                row.get("ils_dl_6h"), row.get("ils_dl_24h")]
        vals = [v for v in vals if v is not None and not pd.isna(v)]
        if len(vals) < 2:
            return True, ""
        signs = {1 if v >= 0 else -1 for v in vals}
        spread = max(vals) - min(vals)
        if len(signs) > 1:
            return False, "sign_flip"
        if spread > 0.3:
            return False, f"spread_{spread:.2f}"
        return True, ""

    results = ils.apply(anchor_robust, axis=1)
    ils = ils.copy()
    ils["anchor_robust"] = [r[0] for r in results]
    ils["anchor_failure_reason"] = [r[1] for r in results]

    rows = []
    for cat, cell in ils.groupby("category"):
        n_total = len(cell)
        n_robust = int(cell["anchor_robust"].sum())
        pct = round(100 * n_robust / n_total, 1) if n_total else None
        paired = cell[["ils_dl", "ils_dl_24h"]].dropna()
        spearman = (float(paired["ils_dl"].rank().corr(paired["ils_dl_24h"].rank()))
                    if len(paired) >= 5 else None)
        rows.append({
            "category": cat, "n_total": n_total,
            "n_anchor_robust": n_robust, "pct_anchor_robust": pct,
            "spearman_24h_to_event": round(spearman, 4) if spearman else None,
        })
    df = pd.DataFrame(rows)
    _write_csv(df, "anchor_sensitivity_summary.csv")
    print(df.to_string())
    # Also expose anchor_robust flags on ils for downstream use
    return ils[["market_id", "anchor_robust", "anchor_failure_reason"]].copy()


# ── B6: FFIC T_event ground-truth comparison ───────────────────────────────────

def run_b6() -> None:
    """Single-row verification: Bitcoin ETF fficd-005 known date = 2024-01-10."""
    print("\n── B6: FFIC T_event ground-truth check ──")
    KNOWN = {"fficd-005": {"known_date": "2024-01-10",
                           "market_id_prefix": "0xb36886bb"}}

    # Find in checkpoint
    records = [json.loads(l) for l in CHECKPOINT.read_text().splitlines() if l.strip()]
    ck = {r["market_id"]: r for r in records}

    pop = _load_pop()
    rows = []
    for case_id, meta in KNOWN.items():
        pfx = meta["market_id_prefix"]
        matches = pop[pop["market_id"].str.startswith(pfx)]
        if matches.empty:
            log.warning("ffic_b6_market_not_in_pop", prefix=pfx)
            continue
        mid = matches.iloc[0]["market_id"]
        rec = ck.get(mid)
        if rec is None:
            log.warning("ffic_b6_not_in_checkpoint", market_id=mid[:16])
            continue

        llm_date = rec.get("t_event", "")[:10]  # YYYY-MM-DD
        known = meta["known_date"]
        try:
            delta_days = abs((datetime.fromisoformat(llm_date) -
                              datetime.fromisoformat(known)).days)
        except Exception:
            delta_days = None

        rows.append({
            "case_id": case_id,
            "known_date": known,
            "llm_recovered_date": llm_date,
            "exact_match": llm_date == known,
            "within_24h": delta_days is not None and delta_days <= 1,
            "source_match": False,  # no ground-truth sources to compare
            "provider": rec.get("provider", "unknown"),
            "confidence": rec.get("confidence"),
            "delta_days": delta_days,
        })

    df = pd.DataFrame(rows)
    _write_csv(df, "ffic_tevent_verification.csv")
    print(df.to_string())


# ── B5: parametric bootstrap KS ───────────────────────────────────────────────

def run_b5(pop: pd.DataFrame) -> None:
    """Add ks_pvalue_bootstrap to functional_form_comparison.csv."""
    print("\n── B5: parametric bootstrap KS ──")
    ils = pop[pop["in_scope"] & pop["ils_dl"].notna() & pop["tau_days"].notna()].copy()
    ils["bucket"] = ils.apply(_bucket, axis=1)

    dist_map = {
        "exponential": (expon, 1),
        "weibull": (exponweib, 2),
        "lognormal": (lognorm, 2),
    }

    fc = pd.read_csv(FUNC_CSV)
    boot_pvals: list[float | None] = []

    for _, row in fc.iterrows():
        cat = row["category"]
        sub = row["subcategory"]
        period = row["period"]
        dist_name = row["distribution"]

        mask = (ils["category"] == cat) & (ils["period"] == period)
        if sub and not pd.isna(sub):
            mask &= ils["subcategory"].fillna("") == sub
        cell_taus = ils.loc[mask, "tau_days"].astype(float).values
        n = len(cell_taus)

        if n < 5:
            boot_pvals.append(None)
            continue

        dist_obj, _ = dist_map[dist_name]
        try:
            params = dist_obj.fit(cell_taus, floc=0)
            ks_obs, _ = kstest(cell_taus, dist_obj.cdf, args=params)

            count_extreme = 0
            for _ in range(999):
                sample = dist_obj.rvs(*params, size=n,
                                      random_state=rng.integers(1 << 31))
                params_b = dist_obj.fit(sample, floc=0)
                ks_b, _ = kstest(sample, dist_obj.cdf, args=params_b)
                if ks_b >= ks_obs:
                    count_extreme += 1

            boot_p = (1 + count_extreme) / (999 + 1)
            boot_pvals.append(round(boot_p, 4))
        except Exception as exc:
            log.warning("b5_fit_error", dist=dist_name, error=str(exc))
            boot_pvals.append(None)

    fc["ks_pvalue_bootstrap"] = boot_pvals
    _write_csv(fc, "functional_form_comparison.csv")
    print(fc[["category", "subcategory", "period", "distribution",
              "ks_pvalue", "ks_pvalue_bootstrap"]].to_string())


# ── B2: hazard-adjusted ILS^dl ─────────────────────────────────────────────────
#
# METHODOLOGY NOTE (all-event_resolved finding):
# All 88 ILS^dl markets are resolution_type=event_resolved. The spec formula
# is designed for deadline markets (price declines as D approaches without event).
# We apply it with D = T_resolve (market closing date), which is T_event + median
# 0.94 days for our sample. The adjustment reduces the absolute value of negative
# ILS^dl values (positive shift), correctly representing the fraction of pre-event
# drift attributable to residual deadline-decay expectation.
#
# Exponential hazard model used for all cells (lower AIC than Weibull for the
# single fitted cell; Weibull k estimates are near 1 for most cells indicating
# near-memoryless behavior). Lambda is fitted per (category×period) cell if n≥5,
# else global lambda from full 88-market tau_days set.

def _exp_survival(t: float, lam: float) -> float:
    return math.exp(-lam * max(t, 0.0))


def _expected_decay_price(p_open: float, tau_elapsed: float,
                          tau_total: float, lam: float) -> float:
    """Spec formula with exponential survival (k=1 Weibull)."""
    tau_remaining = max(tau_total - tau_elapsed, 0.0)
    S_total = _exp_survival(tau_total, lam)
    S_remaining = _exp_survival(tau_remaining, lam)
    denom = 1.0 - S_total
    if denom < 1e-9:
        return p_open
    raw = p_open * (S_remaining - S_total) / denom
    return max(0.0, min(1.0, raw))


def run_b2(pop: pd.DataFrame) -> pd.DataFrame:
    """Compute expected_decay_price and ils_dl_adj; write updated parquet."""
    print("\n── B2: hazard-adjusted ILS^dl ──")
    ils_mask = pop["in_scope"] & pop["ils_dl"].notna()
    ils = pop[ils_mask].copy()

    # Fit exponential lambda per (category × subcategory × period) cell
    ils["bucket"] = ils.apply(_bucket, axis=1)
    cell_lambda: dict[tuple, float] = {}
    global_lam = 1.0 / ils["tau_days"].mean()

    for keys, cell in ils.groupby(["category", "subcategory", "period"], dropna=False):
        taus = cell["tau_days"].dropna().astype(float).values
        if len(taus) >= 5:
            lam_fit = 1.0 / taus.mean()
        else:
            lam_fit = global_lam
        cell_lambda[keys] = lam_fit

    # Parse datetime columns
    for col in ["T_open", "T_event", "T_resolve"]:
        pop[col + "_dt"] = pd.to_datetime(pop[col], utc=True, errors="coerce")

    decay_prices, ils_adj_vals = [], []
    method_flags = []

    for idx, row in pop.iterrows():
        if not (row.get("in_scope") and pd.notna(row.get("ils_dl"))):
            decay_prices.append(None)
            ils_adj_vals.append(None)
            method_flags.append(None)
            continue

        p_open = float(row["p_open"])
        p_event = float(row["p_event"])
        p_resolve = float(row["p_resolve"])
        tau_elapsed = float(row["tau_days"])  # T_event - T_open

        t_open = row["T_open_dt"]
        t_resolve = row["T_resolve_dt"]
        if pd.isna(t_open) or pd.isna(t_resolve):
            decay_prices.append(None)
            ils_adj_vals.append(None)
            method_flags.append("missing_timestamps")
            continue

        tau_total = (t_resolve - t_open).total_seconds() / 86400.0

        cat = row.get("category", "")
        sub = row.get("subcategory") or ""
        period = row.get("period", "")
        lam = cell_lambda.get((cat, sub if sub else None, period),
               cell_lambda.get((cat, sub, period), global_lam))

        edp = _expected_decay_price(p_open, tau_elapsed, tau_total, lam)
        denom = p_resolve - p_open
        if abs(denom) < 1e-6:
            adj = None
            method_flags.append("trivial_resolution")
        else:
            adj = (p_event - edp) / denom
            method_flags.append("exp_hazard")

        decay_prices.append(edp)
        ils_adj_vals.append(adj)

    pop["expected_decay_price"] = decay_prices
    pop["ils_dl_adj"] = ils_adj_vals
    pop["b2_method"] = method_flags

    # Drop temp columns before saving
    pop_save = pop.drop(columns=["T_open_dt", "T_event_dt", "T_resolve_dt"],
                        errors="ignore")
    pop_save.to_parquet(POP_PARQUET, index=False)
    log.info("parquet_updated", cols_added=["expected_decay_price", "ils_dl_adj"])

    # Report shift
    in_scope_ils = pop[pop["in_scope"] & pop["ils_dl"].notna()].copy()
    raw_med = in_scope_ils["ils_dl"].median()
    adj_med = in_scope_ils["ils_dl_adj"].dropna().median()
    print(f"  Raw median ILS^dl:  {raw_med:.4f}")
    print(f"  Adj median ILS^dl:  {adj_med:.4f}")
    print(f"  Shift (adj - raw):  {adj_med - raw_med:+.4f}")
    print(f"  n_adj_computed: {in_scope_ils['ils_dl_adj'].notna().sum()}")

    # hazard_adjusted_summary.csv
    rows = []
    for bucket_name in ["regulatory_announcement", "regulatory_formal", "other"]:
        for period in ["pre_2024", "post_2024"]:
            cell = in_scope_ils[
                (in_scope_ils.apply(_bucket, axis=1) == bucket_name) &
                (in_scope_ils["period"] == period)
            ]
            n = len(cell)
            if n < 3:
                continue
            raw_vals = cell["ils_dl"].astype(float).values
            adj_vals = cell["ils_dl_adj"].dropna().astype(float).values

            def _stats(vals, prefix):
                return {
                    f"{prefix}_n": len(vals),
                    f"{prefix}_mean": round(np.mean(vals), 4),
                    f"{prefix}_median": round(np.median(vals), 4),
                    f"{prefix}_std": round(np.std(vals), 4),
                    f"{prefix}_p10": round(np.percentile(vals, 10), 4),
                    f"{prefix}_p25": round(np.percentile(vals, 25), 4),
                    f"{prefix}_p50": round(np.percentile(vals, 50), 4),
                    f"{prefix}_p75": round(np.percentile(vals, 75), 4),
                    f"{prefix}_p90": round(np.percentile(vals, 90), 4),
                }

            row = {"bucket": bucket_name, "period": period, "n": n}
            row.update(_stats(raw_vals, "raw"))
            if len(adj_vals) >= 3:
                row.update(_stats(adj_vals, "adj"))
            rows.append(row)

    summary_df = pd.DataFrame(rows)
    _write_csv(summary_df, "hazard_adjusted_summary.csv")
    print(summary_df[["bucket", "period", "n",
                       "raw_median", "adj_median"]].to_string())
    return pop


# ── B3: bootstrap CIs on medians ──────────────────────────────────────────────

def run_b3(pop: pd.DataFrame) -> None:
    """Bootstrap CIs on median ILS^dl (raw and adj) and fraction positive."""
    print("\n── B3: median bootstrap CIs ──")
    ils = pop[pop["in_scope"] & pop["ils_dl"].notna()].copy()
    ils["bucket"] = ils.apply(_bucket, axis=1)

    rows = []
    for bucket_name in ["regulatory_announcement", "regulatory_formal", "other"]:
        for period in ["pre_2024", "post_2024"]:
            cell = ils[
                (ils["bucket"] == bucket_name) & (ils["period"] == period)
            ]
            n = len(cell)
            if n < 3:
                continue
            raw = cell["ils_dl"].astype(float).values
            adj = cell["ils_dl_adj"].dropna().astype(float).values

            def _bootstrap_median(vals, B=BOOTSTRAP_B):
                meds = [np.median(rng.choice(vals, size=len(vals), replace=True))
                        for _ in range(B)]
                return (round(float(np.percentile(meds, 2.5)), 4),
                        round(float(np.percentile(meds, 97.5)), 4))

            def _bootstrap_frac_pos(vals, B=BOOTSTRAP_B):
                fracs = [np.mean(rng.choice(vals, size=len(vals), replace=True) > 0)
                         for _ in range(B)]
                return (round(float(np.mean(vals) > 0), 4),
                        round(float(np.percentile(fracs, 2.5)), 4),
                        round(float(np.percentile(fracs, 97.5)), 4))

            raw_ci = _bootstrap_median(raw)
            adj_ci = _bootstrap_median(adj) if len(adj) >= 3 else (None, None)
            frac, fci_lo, fci_hi = _bootstrap_frac_pos(raw)

            rows.append({
                "bucket": bucket_name, "period": period, "n": n,
                "median_raw": round(float(np.median(raw)), 4),
                "ci_low_raw": raw_ci[0], "ci_high_raw": raw_ci[1],
                "median_adj": round(float(np.median(adj)), 4) if len(adj) >= 3 else None,
                "ci_low_adj": adj_ci[0], "ci_high_adj": adj_ci[1],
                "frac_positive": frac,
                "frac_pos_ci_low": fci_lo, "frac_pos_ci_high": fci_hi,
            })

    df = pd.DataFrame(rows)
    _write_csv(df, "median_bootstrap_cis.csv")
    print(df.to_string())


# ── B8: three-sample reporting ─────────────────────────────────────────────────

def run_b8(pop: pd.DataFrame, anchor_flags: pd.DataFrame) -> None:
    """Recompute distribution_summary and detection_thresholds for anchor_robust subset."""
    print("\n── B8: three-sample reporting (anchor_robust subset) ──")

    pop = pop.merge(anchor_flags[["market_id", "anchor_robust"]], on="market_id", how="left")
    ils = pop[pop["in_scope"] & pop["ils_dl"].notna()].copy()
    ils["bucket"] = ils.apply(_bucket, axis=1)
    ils_robust = ils[ils["anchor_robust"] == True].copy()
    print(f"  Anchor-robust subset: {len(ils_robust)}/88")

    quantiles_map = {"p10": 10, "p50": 50, "p90": 90, "p95": 95, "p99": 99}

    def _dist_rows(subset, scope_label):
        rows = []
        for bkt in ["regulatory_announcement", "regulatory_formal", "other"]:
            for period in ["pre_2024", "post_2024"]:
                cell = subset[(subset["bucket"] == bkt) & (subset["period"] == period)]
                n = len(cell)
                if n < 2:
                    continue
                vals = cell["ils_dl"].astype(float).values
                row = {
                    "sample_scope": scope_label, "bucket": bkt, "period": period, "n": n,
                    "mean": round(float(np.mean(vals)), 4),
                    "median": round(float(np.median(vals)), 4),
                    "std": round(float(np.std(vals)), 4),
                    "skewness": round(float(skew(vals)), 4),
                }
                for label, q in quantiles_map.items():
                    row[label] = round(float(np.percentile(vals, q)), 4)
                rows.append(row)
        return rows

    all_rows = _dist_rows(ils, "computed") + _dist_rows(ils_robust, "anchor_robust")
    df = pd.DataFrame(all_rows)
    _write_csv(df, "distribution_summary_v3.csv")

    # Detection thresholds
    thresh_rows = []
    for scope_label, subset in [("computed", ils), ("anchor_robust", ils_robust)]:
        for bkt in ["regulatory_announcement", "regulatory_formal", "other"]:
            for period in ["pre_2024", "post_2024"]:
                cell = subset[(subset["bucket"] == bkt) & (subset["period"] == period)]
                n = len(cell)
                if n < 2:
                    continue
                vals = cell["ils_dl"].astype(float).values
                row = {"sample_scope": scope_label, "bucket": bkt, "period": period, "n": n}
                for thr_name, thr_pctile in [("top_10", 90), ("top_5", 95), ("top_1", 99)]:
                    row[f"{thr_name}_threshold"] = round(float(np.percentile(vals, thr_pctile)), 4)
                thresh_rows.append(row)
    thr_df = pd.DataFrame(thresh_rows)
    _write_csv(thr_df, "detection_thresholds_v3.csv")
    print(f"  distribution_summary_v3: {len(df)} rows")
    print(df[["sample_scope", "bucket", "period", "n", "median"]].to_string())


# ── B4: tail market review (LLM classification) ───────────────────────────────

_B4_SYSTEM = """\
You classify Polymarket prediction market price patterns for a financial \
research paper. Output JSON only: {"classification": "...", "confidence": 0.0, \
"brief_reasoning": "..."}"""

_B4_PROMPT = """\
Classify the pre-event price behavior of this Polymarket prediction market.

Question: {question}
Opening price (p_open): {p_open:.3f}
Pre-event price at T_event^- (p_event): {p_event:.3f}
Resolution outcome (p_resolve): {p_resolve:.0f}  (1=YES, 0=NO)
Days from open to event (tau): {tau_days:.1f}
Raw ILS^dl: {ils_dl:.4f}  (fraction of total move that was pre-event)
Hazard-adjusted ILS^dl: {ils_dl_adj}

Choose ONE classification:
- plausible_leakage: price moved sharply toward outcome before event, \
consistent with informed flow
- rational_decay: price change consistent with mechanical deadline decay \
(deadline approached without event, then sudden resolution)
- anchor_fragile: market lacks a clear discrete event; pre-event price \
reflects multiple anchors; ILS^dl unstable across time windows
- ambiguous: cannot determine from price-trajectory shape alone
- other: explain in brief_reasoning

Output JSON only."""


async def _classify_one_haiku(client, question: str, row_data: dict) -> dict:
    """Classify using Anthropic Haiku (sequential-friendly, no rate limit issues)."""
    prompt = _B4_PROMPT.format(**row_data)
    for attempt in range(3):
        try:
            msg = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                system=_B4_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            text = msg.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())
        except Exception as exc:
            if attempt == 2:
                log.warning("b4_classify_failed", error=str(exc))
                return {"classification": "error", "confidence": 0.0,
                        "brief_reasoning": str(exc)[:120]}
            await asyncio.sleep(1.5 ** attempt)
    return {"classification": "error", "confidence": 0.0, "brief_reasoning": "max_retries"}


async def run_b4_async(pop: pd.DataFrame, anthropic_key: str) -> None:
    import anthropic as _anthropic
    print("\n── B4: tail market review (Haiku classification) ──")
    ils = pop[pop["in_scope"] & pop["ils_dl"].notna()].copy()
    ils["bucket"] = ils.apply(_bucket, axis=1)
    top10 = ils.nlargest(10, "ils_dl")
    bot10 = ils.nsmallest(10, "ils_dl")
    tail20 = pd.concat([top10, bot10]).drop_duplicates("market_id")
    tail20 = tail20.sort_values("ils_dl", ascending=False).reset_index(drop=True)

    client = _anthropic.AsyncAnthropic(api_key=anthropic_key)
    # Sequential to stay well within rate limits
    results = []
    for _, row in tail20.iterrows():
        adj_str = f"{row['ils_dl_adj']:.4f}" if pd.notna(row.get("ils_dl_adj")) else "n/a"
        row_data = {
            "question": row["question"],
            "p_open": float(row["p_open"]),
            "p_event": float(row["p_event"]),
            "p_resolve": float(row["p_resolve"]),
            "tau_days": float(row["tau_days"]),
            "ils_dl": float(row["ils_dl"]),
            "ils_dl_adj": adj_str,
        }
        result = await _classify_one_haiku(client, row["question"], row_data)
        results.append(result)
        await asyncio.sleep(0.3)  # avoid burst rate limit

    out_rows = []
    for i, (_, row) in enumerate(tail20.iterrows()):
        r = results[i]
        out_rows.append({
            "rank": i + 1,
            "market_id": row["market_id"][:20],
            "question": row["question"],
            "bucket": row["bucket"],
            "period": row["period"],
            "p_open": round(float(row["p_open"]), 4),
            "p_event": round(float(row["p_event"]), 4),
            "p_resolve": int(row["p_resolve"]),
            "ils_dl_raw": round(float(row["ils_dl"]), 4),
            "ils_dl_adj": round(float(row["ils_dl_adj"]), 4) if pd.notna(row.get("ils_dl_adj")) else None,
            "tau_days": round(float(row["tau_days"]), 2),
            "volume_usdc": row.get("volume_usdc"),
            "diagnostic_flag": r.get("classification", "error"),
            "llm_confidence": r.get("confidence"),
            "llm_reasoning": r.get("brief_reasoning", ""),
        })

    df = pd.DataFrame(out_rows)
    _write_csv(df, "tail_market_review.csv")
    print(df[["rank", "diagnostic_flag", "ils_dl_raw", "ils_dl_adj",
              "bucket", "question"]].to_string())
    cost_est = len(tail20) * 0.0005
    print(f"  Estimated cost: ~${cost_est:.3f}")


# ── B1: T_event second-pass validation (OpenAI mini, 50 markets) ──────────────

async def run_b1_async(pop: pd.DataFrame, anthropic_key: str) -> None:
    import anthropic as _anthropic
    from fflow.news.t_event_recovery_v2 import recover_t_event_one_shot, TEventResult

    print("\n── B1: T_event second-pass validation (50 markets, Haiku+web) ──")
    client = _anthropic.AsyncAnthropic(api_key=anthropic_key)

    # Load checkpoint for pass-1 data
    records = [json.loads(l) for l in CHECKPOINT.read_text().splitlines() if l.strip()]
    ck = {r["market_id"]: r for r in records}

    # Accepted recovery set: 442 markets with T_event and confidence >= 0.7
    accepted = pop[pop["T_event"].notna() & (pop["T_event_confidence"].fillna(0) >= 0.7)].copy()
    assert len(accepted) == 442, f"Expected 442, got {len(accepted)}"
    accepted["bucket"] = accepted.apply(_bucket, axis=1)

    # Stratified sample: 12 announcement, 18 formal, 20 other
    strat = {"regulatory_announcement": 12, "regulatory_formal": 18, "other": 20}
    parts = []
    for bkt, n in strat.items():
        pool = accepted[accepted["bucket"] == bkt]
        parts.append(pool.sample(n=min(n, len(pool)), random_state=SEED))
    sample50 = pd.concat(parts).reset_index(drop=True)
    print(f"  Sample: {len(sample50)} markets  "
          f"(ann={strat['regulatory_announcement']}, "
          f"formal={strat['regulatory_formal']}, other={strat['other']})")

    # Load typology for descriptions
    typo = pq.read_table(TYPOLOGY_PARQUET).to_pandas()
    typo_idx = typo.set_index("market_id")

    def _parse_dt(s):
        if not s or (isinstance(s, float) and pd.isna(s)):
            return None
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except Exception:
            return None

    # Sequential with small delay: 50 × ~0.03/call = ~$1.50, ~5 min
    results = []
    sem = asyncio.Semaphore(4)

    async def _one(row):
        async with sem:
            mid = row["market_id"]
            desc_row = typo_idx.loc[mid] if mid in typo_idx.index else None
            desc = str(desc_row["description"]) if desc_row is not None else ""
            try:
                result = await recover_t_event_one_shot(
                    question=row["question"],
                    description=desc,
                    t_open=_parse_dt(row.get("T_open")),
                    t_resolve=_parse_dt(row.get("T_resolve")),
                    client=client,
                )
                return result
            except Exception as exc:
                log.warning("b1_recovery_failed", market_id=mid[:16], error=str(exc))
                return exc

    tasks = [_one(row) for _, row in sample50.iterrows()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Build output rows
    val_rows = []
    disagree_rows = []
    total_cost = 0.0

    for i, (_, row) in enumerate(sample50.iterrows()):
        mid = row["market_id"]
        result = results[i]
        pass1 = ck.get(mid, {})

        pass1_date = pass1.get("t_event", "")[:10] if pass1.get("t_event") else None
        pass1_conf = pass1.get("confidence")
        pass1_prov = pass1.get("provider", "anthropic_haiku")
        pass1_sources = pass1.get("sources", [])

        if isinstance(result, Exception):
            log.warning("b1_recovery_failed", market_id=mid[:16], error=str(result))
            pass2_date = None
            pass2_conf = None
            pass2_sources = []
        else:
            total_cost += getattr(result, "estimated_cost_usd", 0.0)
            pass2_date = result.t_event.strftime("%Y-%m-%d") if result.t_event else None
            pass2_conf = result.confidence
            pass2_sources = list(result.sources or [])

        # Agreement metrics
        def _to_dt(s):
            try:
                return datetime.fromisoformat(s) if s else None
            except Exception:
                return None

        dt1 = _to_dt(pass1_date)
        dt2 = _to_dt(pass2_date)

        exact = (pass1_date == pass2_date) if (pass1_date and pass2_date) else None
        if dt1 and dt2:
            delta_h = abs((dt1 - dt2).total_seconds()) / 3600
            w24h = delta_h <= 24
            w6h = delta_h <= 6
        else:
            delta_h = None
            w24h = None
            w6h = None

        # Source overlap: any URL in both?
        p1_urls = {str(s) for s in pass1_sources}
        p2_urls = {str(s) for s in pass2_sources}
        src_overlap = bool(p1_urls & p2_urls) if (p1_urls and p2_urls) else False

        # Disagreement severity
        if pass1_date and pass2_date and not exact:
            delta_days = abs((datetime.fromisoformat(pass1_date) -
                              datetime.fromisoformat(pass2_date)).days)
            severity = "minor" if delta_days <= 7 else "major"
        else:
            severity = None

        val_rows.append({
            "market_id": mid,
            "question": row["question"][:120],
            "sub_bucket": row["bucket"],
            "pass1_provider": pass1_prov,
            "pass1_date": pass1_date,
            "pass1_confidence": pass1_conf,
            "pass2_provider": "anthropic_haiku",
            "pass2_date": pass2_date,
            "pass2_confidence": pass2_conf,
            "exact_match": exact,
            "within_24h": w24h,
            "within_6h": w6h,
            "source_overlap": src_overlap,
            "disagreement_severity": severity,
        })

        if not exact and (pass1_date or pass2_date):
            disagree_rows.append({
                "market_id": mid,
                "question": row["question"][:120],
                "pass1_date": pass1_date,
                "pass1_sources": "; ".join(list(pass1_sources)[:3]),
                "pass2_date": pass2_date,
                "pass2_sources": "; ".join(pass2_sources[:3]),
                "severity_class": severity or "unknown",
            })

    val_df = pd.DataFrame(val_rows)
    _write_csv(val_df, "tevent_validation.csv")

    if disagree_rows:
        dis_df = pd.DataFrame(disagree_rows)
        _write_csv(dis_df, "tevent_disagreements.csv")
    else:
        # Write empty file so path always exists
        pd.DataFrame(columns=["market_id", "question", "pass1_date",
                               "pass1_sources", "pass2_date",
                               "pass2_sources", "severity_class"]).to_csv(
            OUTPUT_DIR / "tevent_disagreements.csv", index=False)

    # Summary JSON
    def _rate(col):
        valid = val_df[col].dropna()
        return round(float(valid.mean()), 4) if len(valid) else None

    by_bucket = {}
    for bkt in ["regulatory_announcement", "regulatory_formal", "other"]:
        sub = val_df[val_df["sub_bucket"] == bkt]
        by_bucket[bkt] = {
            "n": len(sub),
            "exact_match_rate": _rate_col(sub, "exact_match"),
            "within_24h_rate": _rate_col(sub, "within_24h"),
            "within_6h_rate": _rate_col(sub, "within_6h"),
            "source_overlap_rate": _rate_col(sub, "source_overlap"),
        }

    summary = {
        "n_total": len(val_df),
        "overall": {
            "exact_match_rate": _rate("exact_match"),
            "within_24h_rate": _rate("within_24h"),
            "within_6h_rate": _rate("within_6h"),
            "source_overlap_rate": _rate("source_overlap"),
        },
        "by_bucket": by_bucket,
        "n_disagreements": len(disagree_rows),
        "n_minor_disagreements": sum(1 for r in disagree_rows if r["severity_class"] == "minor"),
        "n_major_disagreements": sum(1 for r in disagree_rows if r["severity_class"] == "major"),
        "estimated_cost_usd": round(total_cost, 4),
    }
    _write_json(summary, "tevent_validation_summary.json")
    print(json.dumps(summary, indent=2))


def _rate_col(df: pd.DataFrame, col: str) -> float | None:
    valid = df[col].dropna()
    return round(float(valid.mean()), 4) if len(valid) else None


# ── Main ───────────────────────────────────────────────────────────────────────

async def main_async(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    anthropic_key = (os.environ.get("FFLOW_ANTHROPIC_API_KEY") or
                     os.environ.get("ANTHROPIC_API_KEY", ""))
    if not anthropic_key and not args.skip_llm:
        print("WARNING: ANTHROPIC_API_KEY not set — B1 and B4 will be skipped")
        args.skip_llm = True

    only = set(args.only.split(",")) if args.only else None

    def _run(name):
        return only is None or name in only

    pop = _load_pop()

    # B7 — anchor sensitivity (must go first; anchor_flags used in B8)
    anchor_flags = pd.DataFrame()
    if _run("B7"):
        anchor_flags = run_b7(pop)

    # B6 — FFIC T_event check
    if _run("B6"):
        run_b6()

    # B5 — parametric bootstrap KS
    if _run("B5"):
        run_b5(pop)

    # B2 — hazard-adjusted ILS (updates parquet; reload pop after)
    if _run("B2"):
        pop = run_b2(pop)
    else:
        # Reload in case B2 was run previously
        pop = _load_pop()

    # B3 — median bootstrap CIs
    if _run("B3"):
        run_b3(pop)

    # B8 — three-sample reporting
    if _run("B8"):
        if anchor_flags.empty:
            # Recompute if B7 was skipped
            anchor_flags = run_b7(pop)
        run_b8(pop, anchor_flags)

    # B4 — tail market review (Haiku classification, ~$0.001)
    if _run("B4") and not args.skip_llm:
        await run_b4_async(pop, anthropic_key)

    # B1 — T_event second pass (Haiku+web, ~$1.50)
    if _run("B1") and not args.skip_llm:
        await run_b1_async(pop, anthropic_key)

    print(f"\n── All done. Outputs in {OUTPUT_DIR} ──")


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper 3a revision B computations")
    parser.add_argument("--skip-llm", action="store_true",
                        help="Skip B1 and B4 (LLM calls)")
    parser.add_argument("--only", type=str, default="",
                        help="Comma-separated task list, e.g. --only B2,B3")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
