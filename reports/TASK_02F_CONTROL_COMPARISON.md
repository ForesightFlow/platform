# Task 02F Phase 1 — Control Group Comparison

**Generated:** 2026-04-27  
**Branch:** task02f/control-group-and-proxy-refinement  
**Status:** STOP — awaiting review

---

## Design Note: Why unclassifiable as control

The 195 event_resolved markets NOT already in `market_labels` proved to be the markets that FAILED the scoring pipeline (sparse trades at T_news) — a biased selection. Using them as control would compare "active event markets" vs. "low-activity event markets," conflating signal with data quality.

**Control group = unclassifiable markets in same categories/volume.** This is the natural null distribution: same categories, same volume/trade thresholds, no special event-resolution structure. The question becomes: do event_resolved markets have HIGHER positive ILS than baseline unclassifiable markets?

---

## Sample Sizes

| Group | N total | N scored | N ILS not-null |
|---|---|---|---|
| Pilot (event_resolved, resolved_at−24h) | 954 | 755 | 725 |
| Control (unclassifiable, resolved_at−24h) | 1,000 sampled | 683 | 683 |

**T_news proxy:** `resolved_at − 24h` (identical for both groups)  
**Random seed:** 42

### By Category

| Category | Pilot N | Control N |
|---|---|---|
| military_geopolitics | 145 | 93 |
| regulatory_decision | 497 | 490 |
| corporate_disclosure | 83 | 100 |

---

## ILS Distribution Comparison

| Group | N | Median | Mean | Min | Max | % Positive |
|---|---|---|---|---|---|---|
| Pilot (event_resolved) | 725 | −0.084 | −0.732 | −18.980 | +0.933 | 15.2% |
| Control (unclassifiable) | 683 | −0.043 | −0.551 | −18.978 | +0.966 | **21.4%** |

### Histogram (bin counts)

| Group | <−2 | −2…−1 | −1…−0.5 | −0.5…0 | 0…0.5 | 0.5…1 | ≥1 |
|---|---|---|---|---|---|---|---|
| Pilot | 65 | 36 | 61 | 440 | 104 | 19 | 0 |
| Control | 52 | 24 | 35 | 402 | 150 | 20 | 0 |

### Per-Category Breakdown

| Category | Pilot Median | Pilot %pos | Control Median | Control %pos | Δ Median |
|---|---|---|---|---|---|
| military_geopolitics | −0.024 | 17.2% | −0.046 | **30.1%** | +0.022 (pilot higher) |
| regulatory_decision | −0.105 | 14.9% | −0.036 | **20.0%** | −0.069 (control higher) |
| corporate_disclosure | −0.074 | 13.3% | −0.092 | **20.0%** | +0.018 (pilot higher) |

---

## Statistical Tests

### Mann-Whitney U (two-sided)

| Metric | Value |
|---|---|
| U-statistic | 209,893 |
| p-value | **0.000001** |
| n₁ (pilot) | 725 |
| n₂ (control) | 683 |
| Effect size r | 0.132 (small-moderate) |

### Bootstrap CI on Median Difference (pilot − control, n=1000)

| Metric | Value |
|---|---|
| Observed median diff | **−0.0416** |
| 95% CI lower | −0.0659 |
| 95% CI upper | −0.0229 |

CI entirely negative — pilot median is significantly BELOW control median.

---

## Verdict

**REVERSED SEPARATION** — the control group (unclassifiable, null distribution) has significantly HIGHER median ILS than the pilot (event_resolved) (p=0.000001, 95% CI [−0.066, −0.023] entirely negative).

The pilot's 15.2% positive ILS rate is BELOW the null baseline of 21.4%. This finding **does not support** the hypothesis that event_resolved markets show elevated informed-trading signal via the resolved_at−24h proxy.

### Interpretation

The unclassifiable control group includes:
1. **Sports/esports result markets** (Counter-Strike, LoL, cricket): score becomes observable in the final minutes/hours before game ends → prices converge rapidly → high positive ILS near resolved_at−24h
2. **Behavioral prediction markets** (Trump tweet counts, Elon post counts, "Will Trump say X?"): outcome observable in real time as the measurement period ends → systematic price convergence
3. **Short-window event markets** ("Will Iranian agent be charged by April 30?", ILS=0.966): these are arguably more event-like than their `unclassifiable` classification suggests

The `resolved_at−24h` proxy is architecturally better for these unclassifiable markets because the resolution event IS the news event (game ends, count completes). For event_resolved political/regulatory markets, the actual news (election called, bill signed) typically precedes `resolved_at` by hours to days → the 24h window captures post-news price relaxation, not pre-news leakage.

### Implication for research direction

The positive ILS signal in event_resolved markets requires a **better T_news anchor** — not resolved_at, but the actual news event timestamp (election call, vote result, announcement). This is exactly what LLM Tier 3 or GDELT would provide. Without it, the proxy-based ILS cannot be distinguished from the null.

---

## Top-10 Control Markets by ILS

| Question | Category | ILS | p_open | p_news | Flags |
|---|---|---|---|---|---|
| Will an Iranian agent be charged in the US by April 30? | military_geopolitics | **0.966** | 0.240 | 0.974 | — |
| Will Elon Musk's net worth be less than $640b on March 31? | regulatory_decision | **0.922** | 0.900 | 0.070 | — |
| Will Trump announce that the US x Iran ceasefire has been broken? | military_geopolitics | **0.805** | 0.230 | 0.850 | — |
| Will Donald Trump post 80-99 Truth Social posts (Feb)? | regulatory_decision | **0.780** | 0.980 | 0.216 | — |
| Will Trump say "China" during the State of the Union address? | military_geopolitics | **0.755** | 0.090 | 0.022 | — |
| Will Trump say "Big Beautiful Bill" during his 4th of July rally? | regulatory_decision | **0.734** | 0.640 | 0.170 | — |
| Will Donald Trump post 80-99 Truth Social posts (Feb v2)? | regulatory_decision | **0.708** | 0.930 | 0.272 | — |
| Will Trump say "Mars" during Las Vegas rally on October 24? | regulatory_decision | 0.687 | 0.480 | 0.150 | window_7d |
| Will Kanye release 'Vultures' Vol. 1 by Feb 9? | corporate_disclosure | **0.674** | 0.570 | 0.860 | — |
| Will Elon Musk post 90-114 tweets from March 30 to April 1? | regulatory_decision | 0.652 | 0.740 | 0.910 | window_7d |

Note: "Iranian agent charged" (ILS=0.966) and "Iran ceasefire broken" (ILS=0.805) are arguably event-driven markets misclassified as unclassifiable — their presence reinforces that the classifier needs improvement.
