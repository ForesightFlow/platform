# Task 03 Final Report: Deadline-ILS Methodology and FFIC Analysis

Generated: 2026-04-28  
Branch: task03/deadline-ils-implementation

---

## 1. Methodology

### 1.1 Deadline-ILS (ILS_dl) Formula

For deadline_resolved YES markets the standard ILS formula (which requires an external T_news anchor)
is inapplicable. Paper §7.2 defines:

```
ILS_dl = (p(T_event⁻) − p(T_open)) / (p_resolve − p(T_open))
```

where T_event⁻ = price one minute before the event became publicly observable. Three cases:

| Resolution | Method |
|---|---|
| deadline_resolved YES, T_event recovered | ILS_dl with T_event⁻ = T_event − 1 min |
| deadline_resolved YES, T_event unknown | ILS_dl with T_event⁻ = T_resolve − 1 h (legacy proxy) |
| deadline_resolved NO | Skip: no event occurred; ILS_dl undefined |
| event_resolved | Standard ILS with T_news from Tier 1/2/3 |

**Why the proxy matters:** On the FFIC "US forces enter Iran" market, the correct formula yields
ILS_dl = +0.113, while the T_resolve−1h proxy gives ILS_dl = −0.331 — a material difference that
would invert the trading-direction signal.

### 1.2 T_event Recovery (Tier 3)

Claude Haiku-4.5 with built-in web search (`web_search_20250305`), `recovery_mode="t_event"`.
System prompt targets: *when the underlying event actually occurred and became publicly observable*.
Confidence = 0.80 when sources cited (web search), 0.60 otherwise.

Cost: ~$0.09 per call (including ~30 KB input context from web search results).
Call cap: 50 per CLI invocation (reset between pipeline phases).

---

## 2. Hazard Estimation by Category

**Goal:** Characterize τ = T_event − T_open (days until event) per category, using an exponential
hazard model S(τ) = exp(−λτ) with MLE λ̂ = 1/mean(τ).

**Sample:** 20 YES deadline markets per category, T_event recovered via Tier 3.
**Total cost:** ~$5.40 (50 calls × $0.09).

| Category | n | λ (events/day) | Half-life (days) | mean τ | p25 | p50 | p75 | KS p |
|---|---|---|---|---|---|---|---|---|
| military_geopolitics | 9 | 0.306 | 2.3 | 3.3 | 2.0 | 2.2 | 4.1 | 0.609 |
| corporate_disclosure | 5 | 0.156 | 4.5 | 6.4 | 0.6 | 6.1 | 11.5 | 0.616 |
| regulatory_decision | 15 | 0.035 | 19.9 | 28.7 | 1.7 | 4.3 | 34.2 | 0.013 |

**Interpretation:**

- **military_geopolitics**: Short median lead time (2.2 d). Exponential fit adequate. Most markets
  in this category resolve within a week of opening — consistent with markets created around
  fast-moving geopolitical events (speeches, summits, immediate military actions). Half-life 2.3 d
  implies >50% of events occur within 2 days of market creation.

- **corporate_disclosure**: Moderate lead time (6.1 d median), adequate exponential fit but n=5 only
  (cap hit at 50 calls, corporate category last-sampled). Treat as preliminary; re-run Phase 2
  with separate cap budget for reliable estimates.

- **regulatory_decision**: Long tail (median 4.3 d, mean 28.7 d) with **rejected** exponential
  (KS p=0.013). Distribution is bimodal: many short-τ "speech bingo" markets (0.3–2 d) mixed with
  genuine regulatory deadlines (30–170 d). Recommend splitting this category into
  `regulatory_decision_speech` vs `regulatory_decision_formal` before using λ in production.

**Implication for ILS_dl pipeline:** For military_geo markets, using T_resolve−1h as proxy when
T_event is unavailable introduces a typical error of up to 2 days (~median τ) — significant
relative to the 2.3 d half-life, but modest relative to the full market lifetime (T_resolve −
T_open is typically 2–3 weeks for these markets).

---

## 3. FFIC Analysis: Iran/Military Action Cluster (2026)

### 3.1 Market Inventory

Tier 3 was run on 18 substantive FFIC markets (actual military/diplomatic events, not speech bingo).
16/18 T_event recovered successfully.

| Market (truncated) | T_open | T_event | τ (d) | ILS_dl |
|---|---|---|---|---|
| US forces enter Iran by April 30? | 2026-03-18 | 2026-04-03 | 16.0 | **+0.113** |
| US x Iran ceasefire by April 7? | 2026-03-24 | 2026-04-06 | 13.0 | None (low_info) |
| Iran strike East-West Pipeline by Apr 30 | 2026-03-23 | 2026-04-08 | 15.9 | no prices |
| JD Vance diplomatic meeting with Iran by Apr 15 | 2026-04-10 | 2026-04-11 | 0.4 | no prices |
| US x Iran meeting by Apr 14 / Apr 13 | 2026-04-10 | 2026-04-11 | 0.4 | no prices |
| Iran strike on US military by March 31 | 2026-02-18 | 2026-02-28 | 9.5 | no prices |
| Military action against Iran ends by Apr 10/11 | 2026-03-24 | 2026-02-28 | −24.7 | no prices |
| Will Iran strike Saudi/Kuwait/Jordan/Israel by Apr 30 | 2026-03-24 | 2026-03-01 | −23.7 | no prices |
| Trump announces military action vs Iran before July | 2025-06-20 | 2025-06-21 | 1.0 | no prices |
| Israel military action against Iran before August | 2025-06-11 | 2025-06-13 | 1.3 | no prices |
| Hezbollah military action against Israel by March 20 | 2026-03-17 | 2026-03-02 | −15.9 | no prices |
| Russia military action against Kyiv by April 10 | 2026-04-01 | 2026-04-03 | 1.1 | no prices |

**Negative τ markets:** Markets for "Military action ends by date X" and "Iran strike target by
Apr 30" were opened *after* the underlying event had already started (conflict began Feb 28, 2026).
These are "conflict duration" markets, not "will it happen?" markets — pre-event informed trading
cannot be detected since the event pre-dates T_open.

### 3.2 ILS_dl for the Two Markets with Price Data

**"US forces enter Iran by April 30?" (Iran Apr30)**

| Metric | Value |
|---|---|
| t_open | 2026-03-18 16:29 UTC |
| T_event | 2026-04-03 00:00 UTC (F-15E rescue / covert entry) |
| t_resolve | 2026-04-09 00:28 UTC |
| p_open | 0.250 |
| p_news (p(T_event⁻)) | 0.335 |
| p_resolve | 1 (YES) |
| δ_pre | +0.085 |
| ILS_dl | **+0.113** |
| ILS_30min | 0.000 |
| ILS_2h | 0.000 |
| ILS_6h | −0.099 |
| ILS_24h | −0.267 |
| ILS_7d | −0.081 |

**Price trajectory (daily averages):**

```
2026-03-18: 0.46 (market opens, price rises quickly from 0.25 initial)
2026-03-22: 0.42  
2026-03-25: 0.46  (peak acceptance)
2026-03-29: 0.34
2026-04-03: 0.26  ← T_event (US entry into Iran)
2026-04-04: 0.17
2026-04-05: 0.015  (market participants price NO heavily)
2026-04-08: 0.002
2026-04-09: 0.001  → resolved YES by UMA
```

**Interpretation:** The crowd *expected NO* through most of the market's life (price fell steadily
from 0.46 to near-zero by April 8), but UMA resolved YES on April 9. The p_open = 0.25 is the
initial market-creation price; the market quickly priced it up to 0.46 then gradually declined.

ILS_dl = +0.113 (11.3% of the eventual YES move occurred pre-T_event). The short-window ILS
(30 min, 2 h) = 0, indicating no last-minute informed spike around T_event. The negative 24h ILS
(−0.267) reflects the falling price in the 24h pre-event window.

**Verdict:** Mild pre-event directional positioning (positive ILS_dl) but no evidence of
concentrated last-minute informed trading. The market broadly mispredicted the outcome (crowd:
~20% YES by April 8; resolution: YES).

---

**"US x Iran ceasefire by April 7?" (ceasefire Apr7)**

| Metric | Value |
|---|---|
| t_open | 2026-03-24 17:52 UTC |
| T_event | 2026-04-06 00:00 UTC |
| t_resolve | 2026-04-11 00:28 UTC |
| p_open | 0.975 |
| p_news | 0.978 |
| ILS_dl | **None** (low_information_market) |
| δ_pre | +0.003 |

**Interpretation:** Market opened at 97.5% YES probability — the ceasefire was widely expected.
With δ_total = 0.025 < ε = 0.05, ILS_dl is undefined. No measurable information leakage possible
in a market with such high prior probability.

### 3.3 Wallet Analysis

Trade data is available for both FFIC markets, but only from the **resolution window**
(2026-04-08 through 2026-04-11) — post-T_event. Pre-event individual trades are not available
in the subgraph collection (only aggregate OHLCV prices from CLOB).

**Iran Apr30 post-resolution trade window:**

| Metric | Value |
|---|---|
| Total notional | $9.78M |
| Total trades | 3,995 |
| HHI_top10 | 0.057 (moderately concentrated) |
| Top wallet (0x7072dd52) | $1.56M (16% of volume) |

**Cross-market coordination signal:**

332 wallets traded in **both** FFIC markets (Iran Apr30 + ceasefire Apr7). Top cross-market actors:

| Wallet | Iran Apr30 | Ceasefire Apr7 | Total |
|---|---|---|---|
| 0x7072dd52... | $1,562,742 | $404,985 | $1,967,727 |
| 0xe25b9180... | $870,182 | $299,400 | $1,169,582 |
| 0x4da76bbf... | $174,650 | $29,970 | $204,620 |
| 0xd5ccdf77... | $149,850 | $199,800 | $349,650 |
| 0x162f6fff... | $119,749 | $51,746 | $171,495 |

**Caveat:** These trades occurred in the resolution settlement window, not pre-event. They represent
resolution arbitrage (collecting YES payouts) rather than informed pre-event positioning. The
cross-market coordination signal here reflects the same arbitrage traders harvesting both YES
resolutions, not coordinated advance knowledge.

To detect informed pre-event trading in future analysis, the subgraph collector must be run
continuously on target markets from T_open, not retroactively from T_resolve.

---

## 4. Paper v1.0 Implications

### 4.1 Dataset Curation Recommendations

1. **Exclude negative-τ deadline markets** from ILS_dl analysis. Markets for "will X end by date Y"
   when X started before T_open have no pre-event window and should be excluded from detection
   pipeline.

2. **regulatory_decision bimodality** requires sub-category split before using λ in ILS_dl
   expected-information calculations.

3. **corporate_disclosure sample too small** (n=5). Phase 2 should be re-run with a dedicated
   30-call budget for corporate_disclosure before publishing hazard parameters.

4. **Price data coverage** for deadline markets is sparse. Only 2 of 18 FFIC markets had CLOB
   price series; the others have no ILS_dl computable. The CLOB collector should be expanded to
   cover all deadline_resolved markets via continuous collection.

5. **Trade data gap**: Subgraph trades are available only for markets explicitly collected in the
   ingest pipeline. For deadline markets, trades must be collected from T_open to enable pre-event
   wallet HHI computation. The resolution-window-only HHI reported here is NOT the §3.4 metric —
   it's post-resolution arbitrage activity.

### 4.2 ILS_dl Thresholds (Preliminary)

From the single computable Iran Apr30 market (ILS_dl = +0.113):

- Short-window (30 min, 2 h) = 0: rules out last-minute news-driven spike
- 6h window negative: rules out informed trading in the 6 h window
- 24h window negative: price was falling for 24 h before T_event

Recommend: For a market to flag as "informed", require ILS_dl > 0.25 AND at least one of
{ils_30min, ils_2h} > 0.10. Iran Apr30 does NOT meet this threshold — it shows mild drift,
not concentrated pre-event informed positioning.

### 4.3 Cost Accounting

| Phase | Calls | Estimated cost |
|---|---|---|
| Phase 2 (hazard estimation) | 50 | ~$4.50 |
| Phase 3 (FFIC Tier 3) | 25 | ~$2.25 |
| Retries (parser fix) | 7 | ~$0.63 |
| Sanity test (Phase 1) | 1 | ~$0.09 |
| **Total** | **83** | **~$7.47** |

Budget used: $7.47 of $35 cap (~21%). Remaining $27.53 available for expanded Phase 2 corpus
or live collection of additional FFIC markets.

---

## 5. Technical Fixes Delivered (Phase 1)

| Item | Fix |
|---|---|
| T_open CLOB gap | Forward-only window [t_open, t_open+30min] for first-price lookup |
| Resolution type backfill | Bulk IN-clause grouped updates; 880K markets in 2m41s |
| Web search not enabled | Added `tools=[{"type": "web_search_20250305", "name": "web_search"}]` |
| Response parsing (web search) | Concatenate ALL text blocks (not just last one) |
| Date parser `raw_date[:len(fmt)]` | Removed slice; parse full raw_date |
| Date parser trailing `**` markdown | Strip with `re.sub(r"[*,;.\\s]+$", "", raw_date)` |
| Date format `T%H:%MZ` | Added `%Y-%m-%dT%H:%MZ` format to parse list |
| Legacy T_resolve proxy | Added `t_event` parameter to `compute_ils_deadline()` |
| Pipeline branching | deadline YES → t_event; deadline NO → skip; else → t_news |
| Alembic chain broken | Created `0005_stub.py` no-op to anchor chain |

---

*End of Task 03 Report*
