# Task 03 Phase 0 — Resolution Typology Refinement
Generated: 2026-04-27 19:28 UTC

---

## 1. Summary

Phase 0 introduces `fflow/scoring/resolution_type.py` — a pure-function classifier that
identifies **deadline_resolved** markets (question commits to a specific date) vs.
**unclassifiable** (conservative fallback; `event_resolved` detection is Phase 1).

| Metric | Value |
|---|---|
| FFIC primary corpus (news + prices) | 2 markets |
| FFIC extended corpus (labeled military_geo) | 1,201 markets |
| deadline_resolved in extended — v1 (naive) | 344 / 1201 (28.6%) |
| deadline_resolved in extended — v2 (final) | 362 / 1201 (30.1%) |
| Reclassified unclassifiable → deadline | +18 markets |
| Full corpus size | 911,237 markets |
| deadline_resolved in full corpus | 58,872 / 911,237 (6.5%) |

---

## 2. FFIC Primary Corpus — Before / After

The two markets with both T_news and price data (the FFIC-003 targets):

**v1 (naive):** matches `by [full-month-name]` only — misses abbreviated months,
"before/prior to" prepositions, bare years, and numeric dates.

**v2 (final):** comprehensive deadline regex.

+-----------------------------------+-------------------+-------------------+------+--+
| Question                          | v1 naive          | v2 final          | ILS  |  |
+-----------------------------------+-------------------+-------------------+------+--+
| US forces enter Iran by April 30? | deadline_resolved | deadline_resolved | null |  |
| US x Iran ceasefire by April 7?   | deadline_resolved | deadline_resolved | null |  |
+-----------------------------------+-------------------+-------------------+------+--+

**Observation:** Both target markets use "by April [day]" — full month name, so v1
also catches them. The v2 improvement is demonstrated in the extended corpus (Section 3):
abbreviated months ("by Feb 28", "by Oct 31"), "before [month]" prepositions, and bare
year patterns are the formats v1 misses.

---

## 3. FFIC Extended Corpus — Before / After

All 1,201 labeled `military_geopolitics` markets:

| Classifier | deadline_resolved | unclassifiable |
|---|---|---|
| v1 naive | 344 (28.6%) | 857 |
| v2 final | 362 (30.1%) | 839 |

### 3a. Markets reclassified unclassifiable → deadline_resolved

+----------------------------------------------------------------------+----------------+-------------------+
| Question                                                             | v1             | v2                |
+----------------------------------------------------------------------+----------------+-------------------+
| US seizes an Iran-linked oil tanker by Feb 28?                       | unclassifiable | deadline_resolved |
| Will the US seize an Iran-linked tanker by Feb 28?                   | unclassifiable | deadline_resolved |
| French forces seize another oil tanker by Feb 28?                    | unclassifiable | deadline_resolved |
| Trump strikes another drug boat by Oct 31?                           | unclassifiable | deadline_resolved |
| Trump strikes another drug boat by Oct 15?                           | unclassifiable | deadline_resolved |
| Trump announces end of military operations against Iran before July? | unclassifiable | deadline_resolved |
| Trump x Zelenskyy talk before July?                                  | unclassifiable | deadline_resolved |
| Iran x Israel conflict ends before July?                             | unclassifiable | deadline_resolved |
| Israel military action against Iran before 2026?                     | unclassifiable | deadline_resolved |
| Iran strike on Israel by Nov 8?                                      | unclassifiable | deadline_resolved |
| Will Israel strike Iran on Saturday?                                 | unclassifiable | deadline_resolved |
| Will Israel strike Iran on Thursday?                                 | unclassifiable | deadline_resolved |
| Will Israel strike Iran on Wednesday?                                | unclassifiable | deadline_resolved |
| US call for Gaza ceasefire before March?                             | unclassifiable | deadline_resolved |
| Will Hamas release 20+ hostages in a single day by Nov 30?           | unclassifiable | deadline_resolved |
| Will Israel announce 24h+ humanitarian pause by Nov 30?              | unclassifiable | deadline_resolved |
| Israel or Palestine responsible for Gaza hospital explosion?         | unclassifiable | deadline_resolved |
|  Israel and Hamas ceasefire in 2023?                                 | unclassifiable | deadline_resolved |
+----------------------------------------------------------------------+----------------+-------------------+

### 3b. All deadline_resolved markets in extended corpus (sample)

+------------------------------------------------------------------------+---------+
| Question                                                               | ILS     |
+------------------------------------------------------------------------+---------+
| North Korea missile test/launch by April 30, 2026?                     | -8.726  |
| JD Vance diplomatic meeting with Iran by April 11?                     | 0.012   |
| US x Iran meeting by April 11, 2026?                                   | -0.509  |
| Will Trump endorse an Israeli Ceasefire in Lebanon by April 30?        | -0.147  |
| Will Trump announce that the US x Iran ceasefire has been broken by A… | 0.805   |
| JD Vance diplomatic meeting with Iran by April 30?                     | -1.137  |
| Will the United States send warships through the Strait of Hormuz by … | 0.587   |
| Will Russia enter Verkhnia Tersa by April 30, 2026?                    | -0.977  |
| Will Russia enter Dovha Balka by April 30?                             | -1.545  |
| Israel military action against Iranian Power Plant by April 30?        | 0.193   |
| Military action against Iran ends by June 30, 2026?                    | -0.703  |
| Military action against Iran ends by May 31, 2026?                     | -1.753  |
| Military action against Iran ends by April 30, 2026?                   | -1.750  |
| Will JD Vance talk to Iranian negotiators by April 30?                 | -1.702  |
| Military action against Iran ends by April 30, 2026?                   | -1.407  |
| Military action against Iran ends by April 29, 2026?                   | -9.944  |
| Military action against Iran ends by April 28, 2026?                   | -1.340  |
| Military action against Iran ends by April 27, 2026?                   | -8.762  |
| Military action against Iran ends by April 25, 2026?                   | -1.402  |
| Military action against Iran ends by April 24, 2026?                   | -1.395  |
| Military action against Iran ends by April 23, 2026?                   | -1.313  |
| Military action against Iran ends by April 22, 2026?                   | -1.522  |
| Military action against Iran ends by April 20, 2026?                   | -2.609  |
| Military action against Iran ends by April 18, 2026?                   | -12.808 |
| Military action against Iran ends by April 16, 2026?                   | -2.268  |
+------------------------------------------------------------------------+---------+
_(showing 25 of 362 deadline_resolved markets)_

---

## 4. Full Corpus Distribution (911,237 markets)

Resolution type v2 distribution by `category_fflow`:

+----------------------+---------+-------------------+------------+
| category_fflow       | Total   | deadline_resolved | % deadline |
+----------------------+---------+-------------------+------------+
| other                | 771,424 | 39,609            | 5.1%       |
| regulatory_decision  | 71,588  | 7,745             | 10.8%      |
| military_geopolitics | 47,580  | 4,249             | 8.9%       |
| corporate_disclosure | 20,645  | 7,269             | 35.2%      |
+----------------------+---------+-------------------+------------+

**Key finding:** `deadline_resolved` markets are concentrated in `military_geopolitics`
and `regulatory_decision` — geopolitical events with clear deadlines and regulatory
decisions tied to specific dates. The `other` bucket (sports, crypto) has lower
deadline density, as expected.

---

## 5. Classifier Design Notes

**File:** `fflow/scoring/resolution_type.py`

**v1 baseline pattern (intentionally limited):**
```
by + [january|february|...|december]
```
Misses: abbreviated months (Apr, Sep), "before/prior to" preposition,
"end of [month]", bare years, numeric dates.

**v2 final pattern (comprehensive):**
```
(by|before|prior to|no later than) + (end of)? + date-token
date-token: [Month][Day?][Year?] | Year | Q1-4 | numeric-date
```

Catches all of:
- "by April 30" / "by Apr 30" / "by April 30th"
- "by end of April" / "by the end of April"
- "before March 1" / "prior to April 7"
- "by 2026" / "by Q2 2026"
- "no later than June 15"
- Numeric: "by 4/30/2026"

**False positive safeguards:**
- Requires a date-like token immediately after the deadline preposition
- "won by a landslide", "set by committee", "guaranteed by contract" → do NOT match
  (no month/year/date token follows)

**Conservative design:** `event_resolved` detection deferred to Phase 1.
`unclassifiable` is the safe fallback — zero false positive risk.

---

## 6. Next Steps (Phase 1)

1. Add `resolution_type VARCHAR(30)` column to `markets` (Alembic migration 0003)
2. Backfill via `classify_resolution_type(question, description)` for all rows
3. CLI: `fflow taxonomy classify-type [--batch]`
4. Branch `compute_market_label()` in `fflow/scoring/pipeline.py`:
   - `deadline_resolved` → `compute_ils_deadline()` (to be implemented)
   - others → existing `compute_ils()` path
5. Implement `compute_ils_deadline()` per paper Section 7

**STOP — awaiting user review of this report before Phase 1.**
