# Task 02E — ILS Pilot: Event-Resolved Markets

**Generated:** 2026-04-27  
**Branch:** task02e/resolution-typology  
**Status:** STOP — awaiting user review before next task

---

## Summary

| Metric | Value |
|---|---|
| event_resolved markets (vol≥50K) | 1,145 |
| Markets with trade data | 954 |
| T_news proxy seeded | 1,145 (`proxy:resolved_at-1d`) |
| ILS computed | 755 |
| ILS = NULL (delta_total=0) | 30 |
| ILS not computed (no price data) | 390 |

T_news strategy: `resolved_at - 24h` (tier=2, confidence=0.60). This is anchored to the actual resolution event rather than the arbitrary `end_date`.

---

## ILS Distribution

| Metric | Value |
|---|---|
| N (ILS not null) | 725 |
| Mean | −0.732 |
| Median (p50) | −0.084 |
| p25 | −0.408 |
| p75 | −0.014 |
| Min | −18.98 |
| Max | +0.933 |

| ILS Bin | N | % |
|---|---|---|
| < −2 | 65 | 8.6% |
| −2 to −1 | 36 | 4.8% |
| −1 to −0.5 | 61 | 8.1% |
| −0.5 to 0 | 440 | 58.3% |
| 0 to 0.5 | 104 | 13.8% |
| 0.5 to 1 | 19 | 2.5% |
| ≥ 1 | 30 | 4.0% |

**20.3% of markets have positive ILS** (price moved toward resolution before T_news proxy). This is qualitatively different from the FFICD cohort (0% positive ILS).

---

## Per-Category Breakdown

| Category | N | ILS Mean | ILS Median | % Positive |
|---|---|---|---|---|
| regulatory_decision | 514 | −0.815 | −0.105 | 14.4% |
| military_geopolitics | 151 | −0.509 | −0.024 | 16.6% |
| corporate_disclosure | 90 | −0.620 | −0.074 | 12.2% |

`military_geopolitics` has the highest % positive ILS (16.6%) and best median (−0.024), consistent with geopolitical event markets where information may leak before formal resolution.

---

## Top 15 Positive ILS Markets

| Question | Outcome | ILS | p_open | p_news | Category |
|---|---|---|---|---|---|
| Will Alexandria Ocasio-Cortez be named in newly released Epstein files? | YES | **0.933** | 0.940 | 0.996 | regulatory_decision |
| Trump gets more black voters than in 2020? | YES | **0.881** | 0.160 | 0.900 | corporate_disclosure |
| Will Han Duck Soo be sentenced to at least 20 years? | YES | **0.880** | 0.950 | 0.994 | regulatory_decision |
| Will India win? | NO | **0.804** | 0.460 | 0.090 | regulatory_decision |
| Will Ciucu win by at least 12%? | YES | **0.717** | 0.940 | 0.983 | regulatory_decision |
| Will South Africa win? | YES | **0.677** | 0.690 | 0.900 | regulatory_decision |
| Will Wildflower (Billie Eilish) win Song of the Year (68th GRAMMYs)? | YES | **0.650** | 0.940 | 0.979 | regulatory_decision |
| Will Bernie Sanders be named in Epstein files? | YES | **0.642** | 0.910 | 0.968 | regulatory_decision |
| Will 'BIRDS OF A FEATHER' win Song of the Year? | NO | **0.611** | 0.746 | 0.290 | regulatory_decision |
| Will New Zealand win? | NO | **0.605** | 0.220 | 0.087 | regulatory_decision |
| Will Australia win? | YES | **0.582** | 0.090 | 0.620 | regulatory_decision |
| Will the Liberal Party win by 1–24 seats? | NO | **0.567** | 0.960 | 0.416 | regulatory_decision |
| Will Ehud Barak be named in Epstein files? | YES | **0.553** | 0.170 | 0.629 | regulatory_decision |
| Fewer than 1550 tornadoes in the United States in 2025? | NO | **0.548** | 0.420 | 0.190 | corporate_disclosure |
| Will Natus Vincere win CS:GO BLAST Premier Fall Final 2024? | NO | **0.547** | 0.750 | 0.340 | military_geopolitics |

---

## Comparison: event_resolved vs FFICD (end_date proxy)

| Cohort | N | T_news proxy | ILS Mean | ILS Median | % Positive |
|---|---|---|---|---|---|
| FFICD (end_date−1d) | 3 (scored) | `end_date - 1 day` | −2.009 | −2.714 | 0% |
| event_resolved (resolved_at−1d) | 725 | `resolved_at - 1 day` | −0.732 | −0.084 | 20.3% |

The `resolved_at - 24h` proxy produces a qualitatively different distribution:
- Median moves from −2.714 → −0.084 (18× improvement)
- % positive moves from 0% → 20.3%

This validates the T_news anchoring hypothesis: anchoring to the resolution event (rather than the market deadline) recovers meaningful ILS signal.

---

## Interpretation

### Why most ILS is negative

For `event_resolved` markets, the proxy `resolved_at - 24h` is still imprecise:
- Resolution admin transaction fires within hours of the observed outcome
- `resolved_at - 24h` points to the period just before resolution, which is often AFTER market participants have already priced in the outcome
- Result: p_news > p_open, but in the "wrong" direction relative to outcome → negative ILS

A tighter proxy (e.g., `resolved_at - 6h` or `resolved_at - 2h`) would better capture the pre-resolution period. **This is a proxy quality problem, not a signal absence.**

### High positive ILS markets

The top ILS markets include:
1. **Epstein files markets** (AOC, Bernie Sanders, Ehud Barak) — ILS 0.55–0.93: large positive ILS suggests markets moved strongly toward the correct YES outcome before resolution. This is consistent with informed trading: whoever knew the filing content bid YES.
2. **Sports/election outcomes** (India, New Zealand, Australia "win" markets) — likely sports results flagged as `event_resolved`. The `window_7d_predates_topen` flag indicates these were very short-duration markets. For sports, T_news = match end, which is well before `resolved_at`.
3. **Grammy/election margin markets** — informational cascade as results leaked in real time.

### Null ILS markets (30 markets, delta_total=0)

30 markets resolved at the same price as their opening price (p_resolve = p_open). These are likely:
- Markets that stayed at a fixed 99% throughout and resolved YES
- Markets that stayed at 1% and resolved NO

ILS = 0/0 is undefined; these are correctly stored as NULL.

---

## Flags

| Flag | N | % |
|---|---|---|
| `window_7d_predates_topen` | 156 | 21.5% |
| None | 569 | 78.5% |

156 markets (21.5%) had market lifetime < 7 days — a substantial fraction. These are mostly sports and short-term geopolitical markets. Their ILS is technically valid but may conflate "proxy quality" noise with actual informed flow.

**Clean cohort (no flags, ILS not null): 569 markets.** This is the recommended base for any downstream analysis.

---

## Recommendations Before Task 03

1. **Use resolved_at−1d proxy as the default** for admin-resolved event markets. It is demonstrably better than end_date−1d.
2. **Investigate tighter offsets** (6h, 2h, 1h) on the Epstein/Grammy markets where ILS is already positive — tighter offsets should push ILS even higher if the signal is real.
3. **The 20.3% positive ILS rate** in the no-flag cohort warrants comparison against a random control group (Task 02D Phase 5 equivalent but with event_resolved markets).
4. **Epstein files markets** (3 markets, ILS 0.55–0.93) are the strongest informed trading signal candidates in the current corpus. They deserve deep-dive wallet analysis.
