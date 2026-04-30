# Task 02h Phase 2 — Subgraph Backfill Results

**Generated:** 2026-04-27  
**Branch:** task02h/ffic-trade-backfill

Phase 2 ran the subgraph collector for all 10 `never_run` FFIC markets.
All 10 succeeded. Two bugs were discovered and fixed en route.

---

## Results

| Case | Label | Vol ($) | Trades collected | Status |
|---|---|---|---|---|
| fficd-003 | Khamenei out by Feb 28 | 131,114,971 | **113,472** | ✓ success |
| fficd-003 | Israel-Hezbollah ceasefire by Apr 18 | 98,599,882 | **11,035** | ✓ success |
| fficd-003 | US strikes Iran by Feb 28 | 89,652,867 | **109,072** | ✓ success |
| fficd-003 | Khamenei out by Mar 31 | 63,238,698 | **89,267** | ✓ success |
| fficd-004 | Maduro in US custody by Jan 31 | 11,034,070 | **3,350** | ✓ success |
| fficd-004 | US-Venezuela military by Dec 31 | 51,073,021 | **60,785** | ✓ success |
| fficd-004 | US invades Venezuela by Jan 31 | 8,368,551 | **17,776** | ✓ success |
| fficd-005 | Bitcoin ETF approved by Jan 15 | 12,622,418 | **7,515** | ✓ success |
| fficd-006 | Gene Hackman #1 Passings | 2,952,428 | **453** | ✓ success |
| fficd-007 | Biden pardons SBF | 8,209,071 | **13,787** | ✓ success |

**Total new trades collected: 446,512**

All four fficd-003 borderline markets ($63–131M) were handled successfully by the
subgraph — unlike fficd-003's two previously-attempted markets ($174M, $269M) which
failed with the indexer. The $63–131M range is at the upper edge of indexer capacity;
all four returned large trade counts (11K–113K) rather than zero.

---

## Bugs Fixed

### 1. Wrong subgraph entity — `orderFilleds` vs `enrichedOrderFilleds`

The `master` branch `subgraph.py` used `orderFilleds` in the GQL query. The configured
subgraph (`81Dm16JjuFSrqz813HysXoUPvzTwE7fsfPk2RTf66nyC`) exposes `enrichedOrderFilleds`
with a different field schema. The fix was already present on `task02d+` branches but not
merged to master. Cherry-picked commit `263faac` onto this branch.

### 2. PostgreSQL 32,767 parameter limit in wallet upsert

For markets with > 10,922 unique wallets, the single-batch wallet INSERT exceeded
asyncpg's 32,767 argument limit (3 columns × rows). Fixed by chunking wallet rows at
10,000 per batch (matching the existing 500-row chunk used for trades).

Affected markets: Khamenei Feb28 (21,425 wallets), US-strikes Iran (20,193),
Khamenei Mar31 (19,494), Venezuela Dec31 (10,113).

---

## Remaining Phase 3 Targets (ran_indexer_failed, unchanged)

The 6 markets with confirmed indexer failures still have 0 trades:

| Case | Label | Vol ($) | n_runs | Status |
|---|---|---|---|---|
| fficd-001 | Trump wins | 1,531,479,285 | 4 | indexer_failed |
| fficd-001 | Harris wins | 1,037,039,118 | 1 | indexer_failed |
| fficd-001 | Other Republican wins | 241,655,100 | 1 | indexer_failed |
| fficd-001 | Michelle Obama wins | 153,382,276 | 1 | indexer_failed |
| fficd-003 | US forces enter Iran by Apr 30 | 269,049,107 | 2 | indexer_failed |
| fficd-003 | US-Iran ceasefire by Apr 7 | 173,696,184 | 1 | indexer_failed |

These require Polygonscan logs API (Option 3B) or direct Polygon JSON-RPC (Option 3A).
The US election markets ($153M–$1.5B) are the primary Phase 3 targets.

---

## Updated FFIC Counts

| Status | Before Phase 2 | After Phase 2 |
|---|---|---|
| ok (≥ 100 trades in DB) | 8 | **18** |
| never_run → now ok | 0 | +10 |
| ran_indexer_failed | 6 | 6 (unchanged) |
| **Total with trade data** | **8** | **18** |
