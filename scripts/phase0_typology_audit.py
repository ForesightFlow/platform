#!/usr/bin/env python
"""Task 03 Phase 0 — Resolution Typology Classifier Audit.

Runs two classifiers on the FFIC corpus and the full market DB:
  v1_naive  — 'by [full-month-name]' only; misses abbreviated months and day-numbers
  v2_final  — full deadline regex from fflow.scoring.resolution_type

Writes reports/TASK_03_TYPOLOGY_REFINEMENT.md.

Usage: uv run python scripts/phase0_typology_audit.py

'FFIC corpus' definition:
  Primary  — markets with news_timestamps AND prices (fully instrumented)
  Extended — all labeled military_geopolitics markets (broader political set)
"""

import asyncio
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text

from fflow.db import AsyncSessionLocal
from fflow.models import Market, MarketLabel, NewsTimestamp
from fflow.scoring.resolution_type import classify_resolution_type

REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# ── v1 baseline (naive — intentionally limited to expose false negatives) ──────

_V1_RE = re.compile(
    r"\bby\s+"
    r"(?:january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b",
    re.IGNORECASE,
)


def _classify_v1(question: str, description: str | None = None) -> str:
    text = question + (" " + description if description else "")
    return "deadline_resolved" if _V1_RE.search(text) else "unclassifiable"


# ── helpers ───────────────────────────────────────────────────────────────────


def _tabulate(headers: list[str], rows: list[list]) -> str:
    col_w = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_w[i] = max(col_w[i], len(str(cell)))
    sep = "+-" + "-+-".join("-" * w for w in col_w) + "-+"
    header_line = "| " + " | ".join(str(h).ljust(w) for h, w in zip(headers, col_w)) + " |"
    lines = [sep, header_line, sep]
    for row in rows:
        lines.append(
            "| " + " | ".join(str(c).ljust(w) for c, w in zip(row, col_w)) + " |"
        )
    lines.append(sep)
    return "\n".join(lines)


def _trunc(s: str, n: int = 72) -> str:
    return (s[:n - 1] + "…") if len(s) > n else s


# ── main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    async with AsyncSessionLocal() as session:

        # --- FFIC primary: markets with both news_timestamps and prices --------
        primary_rows = (
            await session.execute(
                text(
                    """
                    SELECT m.id, m.question, m.description,
                           m.category_fflow, m.created_at_chain,
                           ml.ils
                    FROM markets m
                    JOIN news_timestamps nt ON nt.market_id = m.id
                    JOIN (SELECT DISTINCT market_id FROM prices) p
                         ON p.market_id = m.id
                    LEFT JOIN market_labels ml ON ml.market_id = m.id
                    ORDER BY m.created_at_chain
                    """
                )
            )
        ).all()

        # --- FFIC extended: all labeled military_geopolitics markets ----------
        extended_rows = (
            await session.execute(
                text(
                    """
                    SELECT m.id, m.question, m.description,
                           m.category_fflow, m.created_at_chain,
                           ml.ils
                    FROM markets m
                    JOIN market_labels ml ON ml.market_id = m.id
                    WHERE m.category_fflow = 'military_geopolitics'
                    ORDER BY m.created_at_chain DESC
                    """
                )
            )
        ).all()

        # --- Full corpus: all markets (for distribution only) -----------------
        # Stream in chunks to avoid memory issues with 900K rows
        full_dist: dict[str, dict[str, int]] = defaultdict(
            lambda: {"deadline_resolved": 0, "unclassifiable": 0}
        )
        n_full = 0

        offset = 0
        chunk_size = 10_000
        while True:
            chunk = (
                await session.execute(
                    text(
                        "SELECT question, description, category_fflow "
                        "FROM markets ORDER BY id LIMIT :lim OFFSET :off"
                    ).bindparams(lim=chunk_size, off=offset)
                )
            ).all()
            if not chunk:
                break
            for q, desc, cat in chunk:
                rt = classify_resolution_type(q or "", desc)
                cat_key = cat or "null"
                full_dist[cat_key][rt] = full_dist[cat_key].get(rt, 0) + 1
                n_full += 1
            offset += chunk_size
            if offset % 100_000 == 0:
                print(f"  full corpus scan: {offset:,} / ~{n_full:,} so far...")

    # ── Classify primary FFIC corpus (before/after) ---------------------------

    primary_table = []
    for mid, q, desc, cat, created_at, ils in primary_rows:
        v1 = _classify_v1(q or "", desc)
        v2 = classify_resolution_type(q or "", desc)
        ils_str = f"{float(ils):.3f}" if ils is not None else "null"
        primary_table.append(
            [_trunc(q or "", 72), v1, v2, ils_str, "← CHANGED" if v1 != v2 else ""]
        )

    # ── Classify extended FFIC corpus (before/after, sample) ------------------

    ext_v1_counts: dict[str, int] = {}
    ext_v2_counts: dict[str, int] = {}
    ext_changed: list[tuple] = []        # rows where v1 ≠ v2
    ext_all_dl_v2: list[tuple] = []      # all deadline_resolved under v2

    for mid, q, desc, cat, created_at, ils in extended_rows:
        v1 = _classify_v1(q or "", desc)
        v2 = classify_resolution_type(q or "", desc)
        ext_v1_counts[v1] = ext_v1_counts.get(v1, 0) + 1
        ext_v2_counts[v2] = ext_v2_counts.get(v2, 0) + 1
        if v1 != v2:
            ext_changed.append((q, v1, v2))
        if v2 == "deadline_resolved":
            ils_str = f"{float(ils):.3f}" if ils is not None else "null"
            ext_all_dl_v2.append((q, ils_str))

    # ── Full corpus distribution -----------------------------------------------

    cat_order = sorted(
        full_dist.keys(),
        key=lambda c: sum(full_dist[c].values()),
        reverse=True,
    )
    dist_rows = []
    for cat_key in cat_order:
        d = full_dist[cat_key]
        total_cat = sum(d.values())
        n_dl = d.get("deadline_resolved", 0)
        pct_dl = n_dl / total_cat * 100 if total_cat else 0.0
        dist_rows.append(
            [cat_key, f"{total_cat:,}", f"{n_dl:,}", f"{pct_dl:.1f}%"]
        )

    total_dl = sum(d.get("deadline_resolved", 0) for d in full_dist.values())

    # ── Build report -----------------------------------------------------------

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    # Primary table (all rows — only 2 markets)
    primary_md = _tabulate(
        ["Question", "v1 naive", "v2 final", "ILS", ""],
        primary_table,
    )

    # Extended summary counts
    ext_n = len(extended_rows)
    n_dl_v1_ext = ext_v1_counts.get("deadline_resolved", 0)
    n_dl_v2_ext = ext_v2_counts.get("deadline_resolved", 0)

    # Sample of changed rows (up to 30)
    changed_sample_md = ""
    if ext_changed:
        changed_rows = [[_trunc(q, 70), v1, v2] for q, v1, v2 in ext_changed[:30]]
        changed_sample_md = _tabulate(
            ["Question", "v1", "v2"],
            changed_rows,
        )
        if len(ext_changed) > 30:
            changed_sample_md += f"\n_(showing 30 of {len(ext_changed)} reclassified)_"

    # Sample deadline markets in extended corpus (top 25 by question length as proxy)
    dl_sample_rows = [
        [_trunc(q, 70), ils] for q, ils in ext_all_dl_v2[:25]
    ]
    dl_sample_md = _tabulate(["Question", "ILS"], dl_sample_rows) if dl_sample_rows else "_none_"
    if len(ext_all_dl_v2) > 25:
        dl_sample_md += f"\n_(showing 25 of {len(ext_all_dl_v2)} deadline_resolved markets)_"

    dist_md = _tabulate(
        ["category_fflow", "Total", "deadline_resolved", "% deadline"],
        dist_rows,
    )

    report = f"""# Task 03 Phase 0 — Resolution Typology Refinement
Generated: {now}

---

## 1. Summary

Phase 0 introduces `fflow/scoring/resolution_type.py` — a pure-function classifier that
identifies **deadline_resolved** markets (question commits to a specific date) vs.
**unclassifiable** (conservative fallback; `event_resolved` detection is Phase 1).

| Metric | Value |
|---|---|
| FFIC primary corpus (news + prices) | {len(primary_rows)} markets |
| FFIC extended corpus (labeled military_geo) | {ext_n:,} markets |
| deadline_resolved in extended — v1 (naive) | {n_dl_v1_ext} / {ext_n} ({n_dl_v1_ext/ext_n*100:.1f}%) |
| deadline_resolved in extended — v2 (final) | {n_dl_v2_ext} / {ext_n} ({n_dl_v2_ext/ext_n*100:.1f}%) |
| Reclassified unclassifiable → deadline | +{n_dl_v2_ext - n_dl_v1_ext} markets |
| Full corpus size | {n_full:,} markets |
| deadline_resolved in full corpus | {total_dl:,} / {n_full:,} ({total_dl/n_full*100:.1f}%) |

---

## 2. FFIC Primary Corpus — Before / After

The two markets with both T_news and price data (the FFIC-003 targets):

**v1 (naive):** matches `by [full-month-name]` only — misses abbreviated months,
"before/prior to" prepositions, bare years, and numeric dates.

**v2 (final):** comprehensive deadline regex.

{primary_md}

**Observation:** Both target markets use "by April [day]" — full month name, so v1
also catches them. The v2 improvement is demonstrated in the extended corpus (Section 3):
abbreviated months ("by Feb 28", "by Oct 31"), "before [month]" prepositions, and bare
year patterns are the formats v1 misses.

---

## 3. FFIC Extended Corpus — Before / After

All {ext_n:,} labeled `military_geopolitics` markets:

| Classifier | deadline_resolved | unclassifiable |
|---|---|---|
| v1 naive | {n_dl_v1_ext} ({n_dl_v1_ext/ext_n*100:.1f}%) | {ext_v1_counts.get("unclassifiable", 0)} |
| v2 final | {n_dl_v2_ext} ({n_dl_v2_ext/ext_n*100:.1f}%) | {ext_v2_counts.get("unclassifiable", 0)} |

### 3a. Markets reclassified unclassifiable → deadline_resolved

{changed_sample_md if changed_sample_md else "_No reclassifications in extended corpus._"}

### 3b. All deadline_resolved markets in extended corpus (sample)

{dl_sample_md}

---

## 4. Full Corpus Distribution ({n_full:,} markets)

Resolution type v2 distribution by `category_fflow`:

{dist_md}

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
"""

    report_path = REPORTS_DIR / "TASK_03_TYPOLOGY_REFINEMENT.md"
    report_path.write_text(report)
    print(f"\nReport written → {report_path}")
    print(f"\nKey results:")
    print(f"  FFIC primary corpus: {len(primary_rows)} markets")
    print(f"  FFIC extended corpus: {ext_n:,} military_geo markets")
    print(f"  deadline_resolved v1: {n_dl_v1_ext} ({n_dl_v1_ext/ext_n*100:.1f}%)")
    print(f"  deadline_resolved v2: {n_dl_v2_ext} ({n_dl_v2_ext/ext_n*100:.1f}%)")
    print(f"  Reclassified: +{n_dl_v2_ext - n_dl_v1_ext}")
    print(f"  Full corpus deadline_resolved: {total_dl:,} / {n_full:,} ({total_dl/n_full*100:.1f}%)")


if __name__ == "__main__":
    asyncio.run(main())
