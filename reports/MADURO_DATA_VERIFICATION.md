# MADURO / VENEZUELA DATA VERIFICATION
**Prepared:** 2026-04-29  
**Purpose:** Pre-submission data check for FFIC fficd-004 cluster  
**Data source:** `datasets/polymarket-resolution-typology/data/typology-v1.parquet` (direct DB export, cutoff 2026-04-27)  
**Gamma API cross-check:** Attempted; Gamma API does not support individual conditionId filtering for resolved markets — parquet is authoritative.

---

## 1. THE THREE MARKETS YOU LISTED — DB REALITY

> You stated: *"Three FFIC fficd-004 markets currently labeled with resolution_outcome=NO"*

| # | Question | market_id | DB outcome | resolved_at | Volume |
|---|----------|-----------|-----------|-------------|--------|
| 1 | Maduro in U.S. custody by January 31? | `0xbfa4...3f1d` | **1.0 (YES)** ✅ | 2026-01-07T01:00:51Z | $11,034,070 |
| 2 | US x Venezuela military engagement by December 31? | `0x62b0...45f` | **0.0 (NO)** | 2026-01-05T00:33:37Z | $51,073,021 |
| 3 | Will the U.S. invade Venezuela by January 31, 2026? | `0x7f3c...89d` | **0.0 (NO)** | 2026-02-01T07:41:52Z | $8,368,551 |

### Critical finding — Market #1

**Your claim is incorrect for market #1.** "Maduro in US custody" already has `resolution_outcome = 1.0` (YES) in our DB. It is not labeled NO. No correction needed for this market.

### Why Markets #2 and #3 resolved NO (and it is correct)

Market #2 "military engagement by December 31" resolved NO on **2026-01-05** — two days *after* the actual engagement, which occurred on **2026-01-03**. The deadline in the question was December 31, 2025. The operation missed the deadline by 3 days → NO resolution is factually correct per Polymarket's rules.

Market #3 "invade Venezuela by January 31" resolved NO on **2026-02-01** — the operation was characterised as a capture/special operation, not a military invasion in the Polymarket sense. NO is correct.

---

## 2. CRITICAL MISSING MARKET — NOT IN YOUR fficd-004 INVENTORY

There is a **$3.3M YES-resolved market** directly tied to the Jan 3 operation that is not in the three you listed:

| Question | market_id | DB outcome | resolved_at | Volume |
|----------|-----------|-----------|-------------|--------|
| US x Venezuela military engagement by January 15, 2026? | `0x3b4b...35a` | **1.0 (YES)** | 2026-01-03T10:30:45Z | $3,298,466 |

This market resolved YES *at the time of the operation* (Jan 3 at 10:30 UTC) and is the highest-volume YES market for the military engagement cluster. It should be included in fficd-004.

Two additional lower-volume YES engagement markets resolved on the same day:

| Question | market_id | outcome | resolved_at | Volume |
|----------|-----------|---------|-------------|--------|
| US x Venezuela military engagement by March 31, 2026? | `0x1444...` | YES | 2026-01-03T10:34:47Z | $1,444,954 |
| US x Venezuela military engagement by January 31, 2026? | `0x931...` | YES | 2026-01-03T10:31:53Z | $931,284 |

---

## 3. FULL fficd-004 CANDIDATE INVENTORY (substantive markets)

Markets with volume > $500k, directly relevant to the Jan 2026 Venezuela operation cluster, sorted by volume:

| Question | outcome | resolved_at | Volume | category_fflow |
|----------|---------|-------------|--------|----------------|
| US x Venezuela military engagement by December 31? | NO | 2026-01-05 | $51,073,021 | military_geopolitics |
| Maduro in U.S. custody by January 31? | **YES** | 2026-01-07 | $11,034,070 | military_geopolitics |
| Will the U.S. invade Venezuela by January 31, 2026? | NO | 2026-02-01 | $8,368,551 | military_geopolitics |
| US x Venezuela military engagement by November 30? | NO | 2025-12-01 | $9,188,344 | military_geopolitics |
| US x Venezuela military engagement by October 31? | NO | 2025-11-01 | $6,816,571 | military_geopolitics |
| US x Venezuela military engagement by December 15? | NO | 2025-12-16 | $3,803,403 | military_geopolitics |
| US x Venezuela military engagement by January 15, 2026? | **YES** | 2026-01-03 | $3,298,466 | military_geopolitics |
| Will the U.S. invade Venezuela by December 31, 2025? | NO | 2026-01-01 | $2,764,332 | military_geopolitics |
| Will the U.S. invade Venezuela by March 31, 2026? | NO | 2026-04-01 | $2,823,126 | military_geopolitics |
| Nicolás Maduro seen in public by January 5? | **YES** | 2026-01-04 | $1,588,800 | other |
| US x Venezuela military engagement by March 31, 2026? | **YES** | 2026-01-03 | $1,444,954 | military_geopolitics |
| Nicolás Maduro released from custody by January 9, 2026? | NO | 2026-01-10 | $1,439,202 | — |
| Another US strike on Venezuela on January 9? | NO | 2026-01-12 | $1,194,068 | — |
| US x Venezuela military engagement by January 31, 2026? | **YES** | 2026-01-03 | $931,284 | military_geopolitics |
| Trump invokes War Powers against Venezuela by January 9? | **YES** | 2026-01-06 | $982,231 | — |
| Trump invokes War Powers against Venezuela by January 31? | **YES** | 2026-01-06 | $731,648 | — |
| US x Venezuela military engagement by November 14? | NO | 2025-11-15 | $1,602,553 | military_geopolitics |
| US x Venezuela military engagement by November 7? | NO | 2025-11-08 | $1,504,728 | military_geopolitics |

---

## 4. OVERALL DB STATISTICS — ALL VENEZUELA/MADURO MARKETS

| Outcome | Count | Notes |
|---------|-------|-------|
| YES (1.0) | 120 | Includes many speech-bingo & Trump-says markets |
| NO (0.0) | 274 | Mostly deadline-miss and non-event markets |
| Unresolved | 84 | Includes DOJ trial outcome markets (open) |
| **Total** | **478** | All markets with "maduro" or "venezuela" in question/description |

### High-value unresolved markets (likely relevant for trial follow-on):

| Question | Volume |
|----------|--------|
| Will the US officially declare war on Venezuela by June 30, 2026? | $473,016 |
| Will Nicolás Maduro be sentenced to no prison time? | $367,835 |
| Nicolás Maduro released from custody by December 31, 2026? | $211,913 |
| Maduro guilty of all counts? | $101,892 |

---

## 5. GAMMA API CROSS-CHECK STATUS

Attempted four approaches:
1. `?conditionId={id}` — ignored by API (returns default page)
2. `?conditionIds={id1,id2}` — 422 Unprocessable Entity
3. `?closed=true&tag=geopolitics&limit=500` — these specific markets not in paginated results
4. `?closed=true&order=endDate&limit=500` — same

**Conclusion:** Gamma API does not efficiently serve individual closed markets by condition ID. The `typology-v1.parquet` (built directly from the `markets` table via `build_typology_dataset.py`) is the authoritative source for resolution outcomes. No discrepancy could be confirmed or denied via live API; DB data stands as ground truth.

---

## 6. SUMMARY OF REQUIRED ACTIONS (if you proceed to update paper)

1. **No correction needed for market #1** — "Maduro in US custody" is already YES in our DB. If your paper draft incorrectly states it as NO, that's a paper error, not a data error.
2. **Markets #2 and #3 (NO outcomes) are correct** — the Dec 31 deadline pre-dated the Jan 3 operation; "invasion" standard not met.
3. **Add market `0x3b4b...35a`** ("US x Venezuela military engagement by January 15") to fficd-004 — it's the key $3.3M YES market resolving exactly at the time of the operation.
4. **fficd-004 case ID does not yet exist in codebase** — the fixture_phase05.jsonl and FFIC target lists contain no Venezuela markets; this cluster has not been formally ingested into the FFIC pipeline.
