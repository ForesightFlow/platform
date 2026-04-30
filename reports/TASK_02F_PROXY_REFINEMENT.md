# Task 02F Phase 2 — Proxy Refinement

**Generated:** 2026-04-27  
**Branch:** task02f/control-group-and-proxy-refinement

---

## Distribution Metrics by Proxy

| Proxy | N | Median | Mean | % Positive | % |ILS|>1 |
|---|---|---|---|---|---|
| resolved_at−24h | 725 | -0.084 | -0.732 | 15.2% | 13.9% |
| resolved_at−6h | 592 | -0.134 | -1.018 | 11.0% | 19.3% |
| resolved_at−2h | 316 | -0.332 | -1.605 | 0.0% | 25.3% |
| resolved_at−1h | 221 | -0.350 | -1.877 | 0.0% | 27.1% |

---

## Proxy Correlations (Spearman, n=221 matched markets)

| Pair | Spearman ρ |
|---|---|
| ILS_24h vs ILS_6h | 0.763 |
| ILS_24h vs ILS_2h | 0.542 |
| ILS_24h vs ILS_1h | 0.542 |

Monotone trend analysis (n=221 matched markets):
- ILS increases as proxy tightens (24h→1h): 14 markets (6.3%)
- ILS decreases as proxy tightens (24h→1h): 143 markets (64.7%)

---

## Epstein Cluster — ILS Across Proxies

| Market | 24h | 6h | 2h | 1h | Trend |
|---|---|---|---|---|---|
| Will Bernie Sanders be named in newly released Eps… | 0.642 | 0.922 | -10.001 | -10.056 | — |
| Will Alexandria Ocasio-Cortez be named in newly re… | 0.933 | -4.241 | -15.537 | -15.534 | — |
| Will Ehud Barak be named in newly released Epstein… | 0.553 | 0.299 | -0.176 | -0.192 | — |

---

## Interpretation

**Moderate proxy sensitivity** (ρ₂₄h,₁h=0.542). Rankings partially consistent across offsets, but individual market ILS values shift. Tighter proxies recover additional signal for some markets.
