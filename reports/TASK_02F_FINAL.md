# Task 02F — Final Synthesis Report

**Generated:** 2026-04-27  
**Branch:** task02f/control-group-and-proxy-refinement  
**Status:** STOP — Phase 4 (LLM Tier 3) requires explicit user "go"

---

## Executive Summary

Task 02F tested the hypothesis that event_resolved prediction markets show elevated informed-trading signal (positive ILS) relative to a null distribution. Three phases of analysis converge on a **negative finding**: the proxy-based ILS (using `resolved_at − 24h` as T_news) cannot be distinguished from noise using the current methodology. The anomalous Epstein cluster (3 markets with ILS 0.55–0.93) is explained by formula edge effects and professional market-making, not by evidence of informed trading.

---

## Phase 1: Control Group Comparison

**Method:** 725 event_resolved markets (pilot) vs 683 unclassifiable markets (null distribution), both scored with `resolved_at − 24h` proxy.

| Group | N | Median ILS | %Positive |
|---|---|---|---|
| Pilot (event_resolved) | 725 | −0.084 | 15.2% |
| Control (unclassifiable) | 683 | −0.043 | **21.4%** |

**Result:** REVERSED SEPARATION. Control has significantly higher median and positive-rate than pilot. Mann-Whitney U p=0.000001, 95% CI on median difference = [−0.066, −0.023] (entirely negative).

**Explanation:** Unclassifiable markets include sports/esports (game ends = news event = resolution), behavioral prediction markets (Trump tweet counts, etc.), and short-window event markets. For these, `resolved_at` IS the news event, so `resolved_at − 24h` is a structurally better proxy. For event_resolved political/regulatory markets, actual news (election called, bill signed) typically precedes `resolved_at` by hours to days — the proxy window captures post-news price relaxation, not pre-news leakage.

**Implication:** The 15.2% positive rate in event_resolved markets is BELOW the null baseline (21.4%). No positive ILS signal is detectable with the current proxy.

---

## Phase 2: Proxy Sensitivity Analysis

**Method:** ILS recomputed for all pilot markets at 4 T_news offsets (resolved_at − 24h/6h/2h/1h). Spearman correlation between proxy pairs on 221 matched markets.

| Proxy | N | Median | %Positive | %|ILS|>1 |
|---|---|---|---|---|
| resolved_at − 24h | 725 | −0.084 | 15.2% | 13.9% |
| resolved_at − 6h | 592 | −0.134 | 11.0% | 19.3% |
| resolved_at − 2h | 316 | −0.332 | **0.0%** | 25.3% |
| resolved_at − 1h | 221 | −0.350 | **0.0%** | 27.1% |

Spearman correlations (n=221 matched): ρ(24h,6h)=0.763, ρ(24h,2h)=0.542, ρ(24h,1h)=0.542.

**Result:** Tighter proxies eliminate the positive fraction entirely and increase extreme negative values. Rankings are only moderately stable (ρ=0.542). The Epstein AOC market collapses from ILS=+0.933 at 24h to ILS=−4.241 at 6h.

**Implication:** There is no proxy offset in [1h, 24h] that reveals a robust positive ILS signal. Positive values at 24h are not confirmed by tighter proxies — they reflect the resolution window itself (24h window centered on formal administrative resolution), not news-induced price movement.

---

## Phase 3: Epstein Cluster Deep Dive

Three markets (AOC ILS=0.933, Sanders ILS=0.642, Barak ILS=0.553) were analyzed in depth.

### Price trajectory findings

| Market | p_open | p_news | Trajectory type |
|---|---|---|---|
| AOC | 0.940 | 0.996 | High-consensus from day 1; steady drift 94%→99.6% |
| Sanders | 0.910 | 0.968 | High-consensus from day 1; steady drift 91%→96.8% |
| Barak | 0.170 | 0.629 | Genuine price discovery; large Dec 20 crash (21.6%) + recovery |

**AOC/Sanders:** The high ILS is a formula edge effect. When p_open≥0.90, the denominator (p_resolve − p_open) ≤ 0.10, making the ratio very sensitive to small numerator changes. AOC's 5.6pp absolute price move (0.940→0.996) is tiny but produces ILS=0.933 because there was only 6pp of room left to 1.0. These markets were already highly confident from day 1 — not a signal of pre-news informed trading.

**Barak:** More substantive. Market opened at 17% YES (genuine uncertainty), moved to 63% by T_news. The Dec 20 crash (21.6%, 767 trades, $933 vol) followed immediately by Dec 21 recovery (52.9%, 852 trades, $9,332 vol) immediately before T_news is the most anomalous sequence in the dataset.

### Wallet findings

| Wallet | Markets | Vol ($) | First trade | Poly history | Profile |
|---|---|---|---|---|---|
| `0x4bfb41d5b357` | All 3 | 34,034 | Nov 19 (day 1) | 5,115 mkts since 2022 | Professional/market-maker |
| `0x44c1dfe43260` | All 3 | 6,640 | Dec 19 (2.9d before T_news) | 264 mkts since 2024 | Active trader |
| `0xe598435df0cd` | All 3 | 1,034 | Dec 20 | 277 mkts since 2025-11 | — |
| `0x4014e472d9ae` | All 3 | 680 | Dec 19 | 13 mkts, new Dec 2025 | New/possible sybil |

The dominant wallet (`0x4bfb41d5b357`) is active across 5,115 markets since 2022 — consistent with a professional market participant providing liquidity rather than taking informed directional bets. In AOC/Sanders, their positions were at near-maximum YES prices (0.985+) with minimal profit potential. In Barak, their avg buy price was ~0.457 with significant directional exposure.

**4 wallets appeared in all 3 Epstein markets.** None are newly created anonymous wallets. The dominant wallet is a known professional. This reduces the informed-trading inference strength.

---

## Synthesis: Why the Proxy-Based ILS Fails for Event_Resolved Markets

The core architectural finding, repeated across 3 phases:

```
Event_resolved markets:
  News event (bill signed, election called, verdict) → resolved_at delayed by hours/days

resolved_at − 24h proxy:
  T_news = 24 hours before formal administrative resolution
  → captures post-news price relaxation (downward drift back to stable)
  → NOT the pre-news informed trading window

Control (unclassifiable) markets:
  Resolution event IS the news event (game ends, count completes)
  resolved_at − 24h IS a valid T_news proxy
  → these markets correctly show higher positive ILS
```

The "reversed separation" (Phase 1) is not a data quality problem — it is the expected result when using a proxy that is structurally misaligned with the event type. The 15.2% pilot positive rate and the Epstein cluster high-ILS values are both artifacts of the proxy, not evidence of informed trading.

---

## Phase 4: Status (BLOCKED)

LLM Tier 3 on Barak specifically (to recover actual Epstein files release timestamp and recompute ILS). **Requires explicit user "go."**

Justification: The Dec 20 Barak price dislocation is anomalous and cannot be evaluated with the current proxy. The Epstein files were released by Judge Loretta Preska on Dec 23, 2025 — but advance notice / document availability could have preceded this. LLM Tier 3 would recover the actual article timestamp for `resolved_at − Xh` calibration.

Estimated cost: ~$1–2 for Barak only (1 market, 1 article search).

---

## Recommendations

1. **Do not use `resolved_at − Nh` as T_news for event_resolved markets.** The proxy systematically underperforms the null distribution regardless of offset (24h→1h all show ≤15% positive rate vs 21% control baseline).

2. **LLM Tier 3 is the necessary next step.** For event_resolved markets, the actual news timestamp must be recovered from external sources (GDELT, NewsAPI, LLM-assisted article retrieval). This is what Task 02 was originally scoped to deliver.

3. **Barak is the highest-value target.** The Dec 20 crash + recovery pattern, the moderate starting uncertainty (17%), and the meaningful wallet-level Barak position ($9,395 at ~0.457) make it the most economically plausible informed-trading candidate. AOC/Sanders should be deprioritized due to the p_open edge effect.

4. **Control group insight is actionable.** The unclassifiable markets with high positive ILS (sports/behavioral prediction markets, ILS up to 0.966) represent a separate research question: do these markets show early-mover advantage in the final 24h? These could be studied independently using the existing proxy.

---

## Files Produced

| File | Description |
|---|---|
| `reports/TASK_02F_CONTROL_COMPARISON.md` | Phase 1 — Mann-Whitney U, bootstrap CI, verdict |
| `reports/TASK_02F_PROXY_REFINEMENT.md` | Phase 2 — proxy sensitivity, Spearman correlations |
| `reports/TASK_02F_EPSTEIN_CASE_STUDY.md` | Phase 3 — price trajectories, wallet profiles |
| `reports/TASK_02F_FINAL.md` | This document — synthesis + Phase 4 gate |
| `scripts/build_control_group.py` | Phase 1 script |
| `scripts/proxy_refinement.py` | Phase 2 script |
| `scripts/epstein_phase3_query.py` | Phase 3 queries |
