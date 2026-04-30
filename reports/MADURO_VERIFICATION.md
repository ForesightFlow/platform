# MADURO / VENEZUELA FFIC fficd-004 VERIFICATION REPORT
**Date:** 2026-04-29  
**Supersedes:** `reports/MADURO_DATA_VERIFICATION.md`  
**Source of truth:** `datasets/polymarket-resolution-typology/data/typology-v1.parquet` (DB export, cutoff 2026-04-27, 911,237 markets)  
**External reference:** DOJ indictment of Gannon Van Dyke, April 23, 2026  
**Gamma API status:** Live API could not serve individual resolved markets by conditionId. Parquet is authoritative.

---

## VERDICT SUMMARY

> **No DB data corrections required.** All `resolution_outcome` values in the parquet are correct and consistent with DOJ ground truth. The user's premise that three fficd-004 markets are labeled NO is partially wrong: "Maduro in US custody" is already **YES** in our DB. The two remaining NO markets are factually correct NO resolutions. The main gap is that `fficd-004` does not yet exist in the codebase as a formal inventory.

---

## PART A — The 3 Markets You Listed

| # | Your claim | DB question | DB outcome | resolved_at | Volume |
|---|-----------|------------|-----------|-------------|--------|
| 1 | "labeled NO" | Maduro in U.S. custody by January 31? | **YES (1.0)** ✓ | 2026-01-07 01:00 UTC | $11,034,070 |
| 2 | "labeled NO" | US x Venezuela military engagement by December 31? | **NO (0.0)** ✓ | 2026-01-05 00:33 UTC | $51,073,021 |
| 3 | "labeled NO" | Will the U.S. invade Venezuela by January 31, 2026? | **NO (0.0)** ✓ | 2026-02-01 07:41 UTC | $8,368,551 |

**Market #1 correction to your premise:** "Maduro in US custody" has `resolution_outcome = 1.0` in our DB. No correction needed.

**Why Market #2 (engagement by Dec 31) is correctly NO:**
The deadline was December 31, 2025. The actual Venezuela operation occurred January 3, 2026 — three days after the deadline. Polymarket resolved NO per its rules. The market `resolved_at = 2026-01-05` (date market closed, not the event date). Correct.

**Why Market #3 (invade Venezuela) is correctly NO:**
Market description: *"military offensive intended to establish control over any portion of Venezuela."* The January 3 operation was a targeted capture, not an invasion establishing territorial control. Polymarket resolved NO per its criteria. Correct.

---

## PART B — DOJ Market Mapping

### DOJ indictment text (exact): 
> *"Polymarket resolved several Maduro- and Venezuela-related contracts to 'YES,' including the markets 'Maduro out by . . . January 31, 2026,' and 'US forces in Venezuela by . . . January 31, 2026.'"*

### Match 1 — "Maduro out by January 31, 2026"

| Field | Value |
|-------|-------|
| DB question | Maduro in U.S. custody by January 31? |
| market_id | `0xbfa45527ec959aacc36f7c312bd4f328171a7681ef1aeb3a7e34db5fb47d3f1d` |
| DB outcome | **YES (1.0)** |
| resolved_at | 2026-01-07T01:00:51Z |
| volume | $11,034,070 |
| category_fflow | military_geopolitics |

**Status:** Match confirmed. DOJ says YES; DB says YES. No discrepancy.

### Match 2 — "US forces in Venezuela by January 31, 2026"

The DOJ phrase does not exist verbatim in our DB. Two candidates examined:

| Candidate | market_id | DB outcome | Volume | Analysis |
|-----------|-----------|-----------|--------|---------|
| US forces in Venezuela **again** by January 31, 2026? | `0x3f8c674a…de3c` | NO (0.0) | $569,370 | "Again" = second incursion. No second op occurred → NO **correct** |
| US x Venezuela **military engagement** by January 31, 2026? | `0x92a5c555…13bd` | **YES (1.0)** | $931,284 | Different wording, same event |

**Assessment:** The DOJ is paraphrasing "US x Venezuela military engagement by January 31" as "US forces in Venezuela by January 31." These describe the same January 3 operation. The YES market exists and is correctly labeled. No "base" (non-*again*) "US forces in Venezuela by January 31" market exists in our DB — the monthly series ended at November 30, then switched to "…again…" variants starting January 2026. **No discrepancy.**

### Van Dyke's 4 Traded Markets (DOJ list)

| DOJ market name | DB best match | DB outcome | Volume | Van Dyke result |
|----------------|---------------|-----------|--------|-----------------|
| "U.S. Forces in Venezuela by January 31, 2026" | US x Venezuela military engagement by January 31, 2026? `0x92a5…` | **YES** | $931k | **Profit** |
| "Maduro out by January 31, 2026" | Maduro in U.S. custody by January 31? `0xbfa4…` | **YES** | $11.0M | **Profit** |
| "Will the U.S. invade Venezuela by January 31, 2026" | Will the U.S. invade Venezuela by January 31, 2026? `0x7f3c…` | **NO** | $8.4M | Likely **loss** (or hedged) |
| "Trump invokes War Powers against Venezuela by [date]" | Two markets: Jan 9 `0xdfaa…` / Jan 31 `0x79801a…` | **YES / YES** | $982k / $731k | **Profit** |

**Summary:** Van Dyke's YES positions in the "Maduro out," "US forces," and "War Powers" markets all resolved YES — these were his profitable trades. The "invade Venezuela" market resolved NO; he likely lost on that position or traded speculatively.

---

## PART C — Discrepancies Between DB and DOJ Ground Truth

**None.** All four Van Dyke markets match DOJ resolution claims:
- "Maduro out" → YES ✓  
- "US forces" → YES ✓ (matched to "military engagement by January 31")  
- "War Powers" → YES ✓  
- "Invade Venezuela" → NO (Van Dyke traded it; it resolved NO per its criteria)

---

## PART D — Markets That Should Be in fficd-004 Inventory

The user's original 3-market list is **not the right scope for fficd-004**. The correct inventory is the full cluster of markets with insider-relevant resolution in the January 2026 Venezuela operation window.

### Core YES markets (Van Dyke's cluster, all resolve Jan 3–7)

| Role | Question | market_id | Outcome | resolved_at | Volume | resolution_type |
|------|----------|-----------|---------|-------------|--------|-----------------|
| PRIMARY | Maduro in U.S. custody by January 31? | `0xbfa45527ec959aacc36f7c312bd4f328171a7681ef1aeb3a7e34db5fb47d3f1d` | YES | 2026-01-07T01:00:51Z | $11,034,070 | unclassifiable |
| PRIMARY | US x Venezuela military engagement by January 15, 2026? | `0x3b4b3c1b3c57646192cc82d219b984ba8ce3f659277e114d08066bfd9bfb935a` | YES | 2026-01-03T10:30:45Z | $3,298,466 | unclassifiable |
| CORE | US x Venezuela military engagement by January 31, 2026? | `0x92a5c5555d26f52758609c2da6a684a96fd54265abfb1d3c247d57335b6e13bd` | YES | 2026-01-03T10:31:53Z | $931,284 | unclassifiable |
| CORE | Trump invokes War Powers against Venezuela by January 9? | `0xdfaaf716c433747ae71bae5e78dfd4fdd0250d9cc348302376ae5baad52ca647` | YES | 2026-01-06T18:10:57Z | $982,231 | unclassifiable |
| CORE | Trump invokes War Powers against Venezuela by January 31? | `0x79801a0feefbc4c35df8f35d33583eef8ff2bd7a514c619929ac62e23c2cf93d` | YES | 2026-01-06T18:10:57Z | $731,648 | unclassifiable |
| SECONDARY | US x Venezuela military engagement by March 31, 2026? | `0x3ad10b05e536a030e250fa6f19e5ffc95133d87d34c084f8cd2075e129332cab` | YES | 2026-01-03T10:34:47Z | $1,444,954 | unclassifiable |
| SECONDARY | Nicolás Maduro seen in public by January 5? | `0xe377cc3f81cabf05e05be23be9be14a889c34f35eb38e6d166da4448d4b7850c` | YES | 2026-01-04T03:40:35Z | $1,588,800 | deadline_resolved |

### Context NO markets (deadline-miss or standard-not-met)

| Role | Question | market_id | Outcome | resolved_at | Volume |
|------|----------|-----------|---------|-------------|--------|
| CONTEXT / VanDyke-traded | Will the U.S. invade Venezuela by January 31, 2026? | `0x7f3c6b9029a1a4a932509c147a2cc0762e1116b7a4568cde472908b29dd4889d` | NO | 2026-02-01T07:41:52Z | $8,368,551 |
| CONTEXT (deadline-miss, largest) | US x Venezuela military engagement by December 31? | `0x62b0cd598091a179147acbd4616400f804acfdff6f76f029944b481b37cbd45f` | NO | 2026-01-05T00:33:37Z | $51,073,021 |
| CONTEXT | US x Venezuela military engagement by November 30? | `0xbea5d5174cb5355eaf0f8cee780e67d0b22a6ff614ef7ec82cc2fe6ce8f4b111` | NO | 2025-12-01T07:18:48Z | $9,188,344 |
| CONTEXT | US forces in Venezuela again by January 31, 2026? | `0x3f8c674a155ca643341200af3bc4dfc61a825f0c2de3d384df0707f11321de9c` | NO | 2026-02-01T07:58:44Z | $569,370 |

### Open markets (trial / custody follow-on, not fficd-004 but worth tracking)

| Question | market_id | Status | Volume |
|----------|-----------|--------|--------|
| Will Nicolás Maduro be sentenced to no prison time? | `0x67…` | OPEN | $367,835 |
| Nicolás Maduro released from custody by December 31, 2026? | `0x75158a…` | OPEN | $211,913 |
| Maduro guilty of all counts? | (in DB) | OPEN | $101,892 |
| Will the US officially declare war on Venezuela by June 30, 2026? | (in DB) | OPEN | $473,016 |

---

## PART E — Recommended Corrections

### DB corrections: NONE

All `resolution_outcome` values are correct. No `UPDATE` statements required.

### fficd-004 inventory: CREATE (additive)

`fficd-004` does not yet exist in the codebase. Required additions:
- **`data/fficd-004-inventory.jsonl`** — 11 core market records (7 YES + 4 NO context)
- Optionally add Venezuela cluster to `scripts/phase4_ffic_tier4.py` for ILS/T_event computation

### typology-v1 dataset: NO REBUILD

`MANIFEST.json` SHA-256 hashes remain valid. CHANGELOG unchanged. No version bump.

---

## OVERALL CLUSTER STATS (full 478-market Venezuela/Maduro universe)

| Outcome | Count | Notes |
|---------|-------|-------|
| YES (1.0) | 120 | Includes speech-bingo, Trump-says markets; 7 in core fficd-004 cluster |
| NO (0.0) | 274 | Deadline-miss, non-event, standard-not-met |
| Unresolved / OPEN | 84 | Includes DOJ trial follow-on markets |
| **Total** | **478** | |
