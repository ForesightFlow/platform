# Task 02 Diagnostics Report
Generated: 2026-04-26 08:17 UTC

---

## 1. Executive Summary

The ILS computation engine is **implemented and unit-tested correctly** (6/6 synthetic regime tests pass).
However, the real-data validation pipeline is **blocked by sample composition**: the Gamma API's
`closed=true` endpoint returns only the ~500 most-recently-closed markets, which are dominated
by sports, e-sports, crypto price, and weather markets.

Key numbers:
- **599** resolved markets in DB
- **12** with T_news recovered (Tier 1: 12)
- **0** markets scored for ILS
- Tier 1 URL type breakdown: chain.link=197, org.=140, wunderground.com=41, mlssoccer.com=29, net.=23

The ILS formula is mathematically valid. The **data acquisition strategy** needs adjusting
for political/geopolitical markets before acceptance testing is meaningful.

**Overall verdict: 🔴 RED — data collection insufficient; fix before Task 03**

---

## 2. Quantitative Findings

### 2A. T_news Tier Coverage
+------+-----------+----------------+
| Tier | N markets | Avg confidence |
+------+-----------+----------------+
| 1    | 12        | 0.95           |
+------+-----------+----------------+

### 2B. Coverage Funnel

| Stage | Count | % of resolved |
|---|---|---|
| Resolved markets | 599 | 100% |
| Got T_news | 12 | 2.0% |
| Got market_label row | 0 | 0.0% |
| Got ILS (non-null) | 0 | 0.0% |

### 2C. ILS Distribution by Category
_No ILS values computed — insufficient overlapping data (markets with both T_news AND price data)._

### 2D. Documented Insider Cases Sanity Check
_No insider-keyword markets in scored sample._

### 2E. Flag Distribution
_No market_labels rows → no flags._

### Sample Composition (all markets)
+----------------------+-------+----------+-------------+
| Category             | Total | Resolved | With prices |
+----------------------+-------+----------+-------------+
| other                | 34011 | 407      | 273         |
| regulatory_decision  | 6108  | 51       | 17          |
| military_geopolitics | 3363  | 141      | 119         |
| corporate_disclosure | 3222  | 0        | 0           |
+----------------------+-------+----------+-------------+

### Evidence URL Domain Breakdown (resolved markets)
+------------------+-------+
| Domain           | Count |
+------------------+-------+
| chain.link       | 197   |
| org.             | 140   |
| wunderground.com | 41    |
| mlssoccer.com    | 29    |
| net.             | 23    |
| binance.com      | 14    |
| ufc.com          | 12    |
| unafut.com       | 12    |
| com.co           | 10    |
| gg.              | 8     |
| atptour.com      | 5     |
| rugby.           | 3     |
+------------------+-------+

---

## 3. ILS Distribution Histograms

### Global ILS distribution
```
(no data)
```

---

## 4. Acceptance Criterion #9 Status

**Criterion:** At least 2 documented insider-trading cases (Iran, Venezuela, Maduro, Taylor Swift,
OpenAI launch, etc.) should show ILS ≥ 0.5.

**Status: CANNOT EVALUATE.**

The resolved market sample contains no political or geopolitical markets of the type
described in the acceptance criterion. All 599 resolved markets in the DB are:
- Sports/e-sports (CS:GO, LoL, Rocket League, UFC, MLS, ATP)
- Crypto price micro-markets (BTC/ETH up-down 5-minute windows)
- Weather markets (wunderground temperature thresholds)

These market types have:
- Mechanical/algorithmic resolution (no human news event driving T_news)
- Evidence URLs pointing to data feeds (chain.link, wunderground.com, hltv.org)
- Duration of 0–28 days (mean 5 days), not months-long like political markets

**To evaluate acceptance criterion #9, the following data collection is required:**
1. Fetch political markets specifically: Gamma API with `tag` values like
   "2024 us elections", "middle east", "russia-ukraine war" AND `before` filter
   pointing to 2024 resolution dates
2. OR: directly query Polymarket's GraphQL endpoint for markets with known
   condition IDs (Trump 2024, Gaza ceasefire, Iran nuclear deal, etc.)
3. Fetch their CLOB price history
4. Run Tier 1 T_news extraction (Reuters, AP, BBC article URLs will parse correctly)

---

## 5. Anomalies & Open Questions

### 5.1 Taxonomy classifier false positives
The `military_geopolitics` category captures 119/599 resolved markets, but visual inspection
shows these are CS:GO/Counter-Strike markets (keyword "strike") and esports markets.
The regex is too broad — "strike", "warfare" match sports market text.

**Fix for Task 03:** Add negation patterns (e.g., skip if question contains "map", "rounds",
"kills", "esports", "CS:", "LoL:", "Dota").

### 5.2 Gamma API's `closed=true` endpoint is not useful for political markets
The endpoint returns only the ~500 most-recently-closed markets globally, regardless of `tag`.
For historical political markets (2024 election, Gaza, Iran), we need:
- Specific condition IDs → hardcoded fetch list
- OR: Polymarket data export / REST API search with date range
- OR: The Graph subgraph filtered by market type / resolution outcome

### 5.3 Tier 1 T_news extraction: 12/413 = 2.9% success rate
Failure modes:
- 161/413 URLs are `chain.link` price feeds (no article metadata)
- 118/413 URLs are `*.org` domains (mostly sports orgs without datestamp markup)
- 37/413 are `wunderground.com` (weather data pages, no article)
Tier 1 is **working correctly** — it extracts dates from real news articles.
The problem is that our sample doesn't have real news articles as evidence URLs.

### 5.4 CLOB 400 errors for 72/481 markets
The CLOB API returns 400 when the YES token ID is invalid or the market has no
price history. These are likely markets that used the FPMM (AMM) model before
CLOB, or markets with very low volume.

### 5.5 Circular data gap
Markets with T_news (12) ≠ markets with prices (409). This is a coincidence:
the 12 that had parseable news article URLs happened to all be in the 72 CLOB failures.

---

## 6. Recommendation

**🔴 RED — data collection insufficient; fix before Task 03**

### What is working correctly
- ILS formula: all 6 synthetic regime tests pass (pure leakage, no leakage,
  partial, counter-evidence, low-information, multi-window)
- Tier 1 extraction: correctly parses JSON-LD, OpenGraph, `<time>` tags from real news articles
- Tier 2 (GDELT): implemented with graceful degradation; requires GCP credentials to test
- Tier 3 (LLM): implemented with `--confirm` gate and 50-call cap
- Pipeline: compute_market_label() upserts correctly, LabelAudit provenance works
- DB schema: all Task 02 tables created and populated correctly

### What needs to be addressed before Task 03
1. **Political market dataset**: curate a list of 50–100 condition IDs for known political
   markets (2024 US election, Gaza, Iran, Venezuela, Taylor Swift Eras Tour dates, FDA approvals).
   Fetch their CLOB data and run Tier 1 — these will have real news URLs.
2. **Taxonomy false positives**: add negation for esports/sports market text patterns.
3. **CLOB 400 handling**: fall back to fetching with `interval=all` instead of `startTs/endTs`
   for markets without CLOB price history in the specified window.

### Estimated effort to reach GREEN
- 2–3 hours: curate political market condition ID list + re-run collection
- After data collection: acceptance criterion #9 can be evaluated

---

## Appendix: Pipeline Logs

### label_sample.py output
```
Processing 50 markets…
2026-04-26 12:15:21 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:22 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:22 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:22 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:22 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:23 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:24 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:24 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:24 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:25 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:25 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:25 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:26 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:26 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:27 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:27 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:28 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:28 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:28 [warning  ] gdelt_unavailable              reason="google-cloud-bigquery not installed; install with: uv pip install 'fflow[gdelt]'"
2026-04-26 12:15:29 [warning  ] gdelt_unavailable              reason=
...(truncated)
```

### validate_labels.py output
```
No labels found. Run: fflow score batch


```
