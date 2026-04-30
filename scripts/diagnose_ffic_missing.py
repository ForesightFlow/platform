"""Phase 1: Diagnose trade-history gaps for all 24 FFIC markets.

For each market:
  - Resolve prefix → full market_id + metadata
  - Current trades count in DB
  - subgraph_trades collector run history (n_runs, last status, last n_written)
  - Diagnosis: never_run | ran_returned_zero | ran_indexer_failed | partial | ok
  - Recommendation: rerun_subgraph | try_rpc_direct | investigate_further | ok

Writes reports/TASK_02H_FFIC_DIAGNOSTICS.md.
"""

import asyncio
import pathlib
from datetime import UTC, datetime

from sqlalchemy import text

from fflow.db import AsyncSessionLocal

FFIC_CASES = [
    {
        "case_id": "fficd-001",
        "name": "2024 US Presidential Election",
        "markets": [
            {"prefix": "0xdd22472e", "label": "Trump wins"},
            {"prefix": "0xc6485bb7", "label": "Harris wins"},
            {"prefix": "0x55c55189", "label": "Other Republican wins"},
            {"prefix": "0x230144e3", "label": "Michelle Obama wins"},
        ],
    },
    {
        "case_id": "fficd-002",
        "name": "October 2024 Iran Strike on Israel",
        "markets": [
            {"prefix": "0xc1b6d712", "label": "Iran strike today"},
            {"prefix": "0x93727420", "label": "Another strike by Friday"},
            {"prefix": "0xc8312853", "label": "Iran strike by Nov 8"},
        ],
    },
    {
        "case_id": "fficd-003",
        "name": "2026 US-Iran Military Conflict Cluster",
        "markets": [
            {"prefix": "0x6d0e09d0", "label": "US forces enter Iran by Apr 30"},
            {"prefix": "0x4c5701bc", "label": "US-Iran ceasefire by Apr 7"},
            {"prefix": "0xd4bbf7f6", "label": "Khamenei out by Feb 28"},
            {"prefix": "0x9823d715", "label": "Israel-Hezbollah ceasefire by Apr 18"},
            {"prefix": "0x3488f31e", "label": "US strikes Iran by Feb 28"},
            {"prefix": "0x70909f0b", "label": "Khamenei out by Mar 31"},
        ],
    },
    {
        "case_id": "fficd-004",
        "name": "Maduro / Venezuela 2024–2026",
        "markets": [
            {"prefix": "0xbfa45527", "label": "Maduro in US custody by Jan 31"},
            {"prefix": "0x62b0cd59", "label": "US-Venezuela military by Dec 31"},
            {"prefix": "0x7f3c6b90", "label": "US invades Venezuela by Jan 31"},
        ],
    },
    {
        "case_id": "fficd-005",
        "name": "Bitcoin ETF SEC Approval Jan 2024",
        "markets": [
            {"prefix": "0xb36886bb", "label": "Bitcoin ETF approved by Jan 15"},
        ],
    },
    {
        "case_id": "fficd-006",
        "name": "Google Year in Search 2025",
        "markets": [
            {"prefix": "0x54361608", "label": "Gene Hackman #1 Passings"},
            {"prefix": "0x45126353", "label": "Ismail Haniyeh #1 Passings"},
            {"prefix": "0x26477123", "label": "Zendaya #1 Actors"},
        ],
    },
    {
        "case_id": "fficd-007",
        "name": "FTX / SBF Collapse 2022–2024",
        "markets": [
            {"prefix": "0xf4078ddd", "label": "Biden pardons SBF"},
            {"prefix": "0x2b8608c1", "label": "SBF sentenced to 50+ years"},
            {"prefix": "0x02c8326d", "label": "FTX no payouts in 2024"},
        ],
    },
    {
        "case_id": "fficd-008",
        "name": "Romanian Presidential Election 2024",
        "markets": [
            {"prefix": "0x9872fe47", "label": "Ciuca wins Romanian election"},
        ],
    },
]


async def diagnose_market(session, prefix: str, label: str, case_id: str) -> dict:
    result = {
        "prefix": prefix,
        "label": label,
        "case_id": case_id,
        "market_id": None,
        "question": None,
        "volume_usdc": None,
        "created_at": None,
        "closed_at": None,
        "resolved_at": None,
        "resolution_type": None,
        "n_trades_db": 0,
        "n_runs": 0,
        "last_status": None,
        "last_n_written": None,
        "all_statuses": [],
        "diagnosis": None,
        "recommendation": None,
    }

    # Resolve prefix → market
    row = (await session.execute(
        text("SELECT id, question, volume_total_usdc, created_at_chain, "
             "end_date, resolved_at, resolution_type "
             "FROM markets WHERE id LIKE :p LIMIT 1"),
        {"p": prefix + "%"},
    )).mappings().first()

    if row is None:
        result["diagnosis"] = "not_in_db"
        result["recommendation"] = "check_gamma_collection"
        return result

    mid = row["id"]
    result["market_id"] = mid
    result["question"] = row["question"]
    result["volume_usdc"] = float(row["volume_total_usdc"] or 0)
    result["created_at"] = row["created_at_chain"]
    result["closed_at"] = row["end_date"]
    result["resolved_at"] = row["resolved_at"]
    result["resolution_type"] = row["resolution_type"]

    # Current trades count
    result["n_trades_db"] = (await session.execute(
        text("SELECT COUNT(*) FROM trades WHERE market_id = :mid"), {"mid": mid}
    )).scalar() or 0

    # Collector run history
    runs = (await session.execute(
        text("SELECT status, n_records_written, started_at "
             "FROM data_collection_runs "
             "WHERE collector = 'subgraph_trades' AND target = :mid "
             "ORDER BY started_at DESC"),
        {"mid": mid},
    )).mappings().all()

    result["n_runs"] = len(runs)
    if runs:
        result["last_status"] = runs[0]["status"]
        result["last_n_written"] = runs[0]["n_records_written"]
        result["all_statuses"] = [r["status"] for r in runs]

    # Diagnose
    n = result["n_trades_db"]
    nr = result["n_runs"]

    if nr == 0:
        if n > 0:
            result["diagnosis"] = "partial"  # trades exist but no run record
            result["recommendation"] = "rerun_subgraph"
        else:
            result["diagnosis"] = "never_run"
            result["recommendation"] = "rerun_subgraph"
    else:
        last_written = result["last_n_written"] or 0
        any_success = any(s == "success" for s in result["all_statuses"])
        any_failed = any(s == "failed" for s in result["all_statuses"])

        vol = result["volume_usdc"] or 0
        if n == 0 and any_success and last_written == 0:
            if vol >= 1_000_000:
                result["diagnosis"] = "ran_indexer_failed"
                result["recommendation"] = "try_rpc_direct"
            else:
                result["diagnosis"] = "ran_returned_zero"
                result["recommendation"] = "rerun_subgraph"
        elif n == 0 and any_failed:
            # Runs failed — high-volume markets likely exceed indexer capacity
            if vol >= 50_000_000:
                result["diagnosis"] = "ran_indexer_failed"
                result["recommendation"] = "try_rpc_direct"
            else:
                result["diagnosis"] = "ran_indexer_failed"
                result["recommendation"] = "rerun_subgraph"
        elif n > 0 and n < 100:
            result["diagnosis"] = "partial"
            result["recommendation"] = "rerun_subgraph"
        elif n >= 100:
            result["diagnosis"] = "ok"
            result["recommendation"] = "ok"
        else:
            result["diagnosis"] = "investigate_further"
            result["recommendation"] = "investigate_further"

    return result


async def run():
    async with AsyncSessionLocal() as session:
        all_results = []
        for case in FFIC_CASES:
            for mkt in case["markets"]:
                r = await diagnose_market(session, mkt["prefix"], mkt["label"], case["case_id"])
                r["case_name"] = case["name"]
                all_results.append(r)
                print(
                    f"  {r['case_id']} {r['label'][:35]:35s}: "
                    f"trades={r['n_trades_db']:5d}  n_runs={r['n_runs']}  "
                    f"vol=${r['volume_usdc']:>15,.0f}  "
                    f"diag={r['diagnosis']}"
                )

    # ── Summary counts ────────────────────────────────────────────────────────
    diag_counts: dict[str, int] = {}
    rec_counts: dict[str, int] = {}
    for r in all_results:
        diag_counts[r["diagnosis"]] = diag_counts.get(r["diagnosis"], 0) + 1
        rec_counts[r["recommendation"]] = rec_counts.get(r["recommendation"], 0) + 1

    print(f"\nDiagnosis summary: {diag_counts}")
    print(f"Recommendation summary: {rec_counts}")

    # ── Write report ──────────────────────────────────────────────────────────
    now = datetime.now(UTC).strftime("%Y-%m-%d")
    lines = [
        "# Task 02h — FFIC Trade-History Diagnostics",
        "",
        f"**Generated:** {now}  ",
        "**Branch:** task02h/ffic-trade-backfill",
        "",
        "Per-market diagnosis of missing trade history for all 24 FFIC markets.",
        "",
        "---",
        "",
        "## Diagnostic Table",
        "",
        "| Case | Label | Market ID | Vol ($) | Trades in DB | n_runs | Last status | n_written | Diagnosis | Recommendation |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    for r in all_results:
        mid_str = (r["market_id"][:16] + "…") if r["market_id"] else "NOT_IN_DB"
        vol_str = f"{r['volume_usdc']:,.0f}" if r["volume_usdc"] is not None else "—"
        last_s = r["last_status"] or "—"
        last_w = str(r["last_n_written"]) if r["last_n_written"] is not None else "—"
        lines.append(
            f"| {r['case_id']} | {r['label']} | `{mid_str}` "
            f"| {vol_str} | {r['n_trades_db']:,} "
            f"| {r['n_runs']} | {last_s} | {last_w} "
            f"| {r['diagnosis']} | {r['recommendation']} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Diagnosis Definitions",
        "",
        "| Diagnosis | Meaning |",
        "|---|---|",
        "| `ok` | ≥ 100 trades in DB, no action needed |",
        "| `never_run` | subgraph collector has never been run for this market |",
        "| `ran_returned_zero` | collector ran successfully but returned 0 trades (low-volume or subgraph gap) |",
        "| `ran_indexer_failed` | collector ran but returned 0 despite high volume — likely The Graph indexer capacity limit |",
        "| `partial` | < 100 trades in DB, re-run needed |",
        "| `not_in_db` | market not present in markets table at all |",
        "| `investigate_further` | ambiguous state requiring manual review |",
        "",
        "## Recommendation Definitions",
        "",
        "| Recommendation | Action |",
        "|---|---|",
        "| `ok` | No action |",
        "| `rerun_subgraph` | `fflow collect subgraph --market <id> --max-pages 200` |",
        "| `try_rpc_direct` | Direct Polygon JSON-RPC or Polygonscan logs endpoint (Phase 3) |",
        "| `check_gamma_collection` | Market not in DB — re-run gamma collector first |",
        "| `investigate_further` | Manual review required |",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Diagnosis | Count |",
        "|---|---|",
    ]
    for diag, cnt in sorted(diag_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| {diag} | {cnt} |")

    lines += [
        "",
        "| Recommendation | Count |",
        "|---|---|",
    ]
    for rec, cnt in sorted(rec_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| {rec} | {cnt} |")

    # Group A (high-volume, indexer-failed) — flagged for Phase 3
    group_a = [r for r in all_results if r["recommendation"] == "try_rpc_direct"]
    group_b = [r for r in all_results if r["recommendation"] == "rerun_subgraph"]

    lines += [
        "",
        "---",
        "",
        "## Phase 2 Target List (rerun_subgraph)",
        "",
        "| Case | Label | Market ID | Vol ($) | Trades in DB |",
        "|---|---|---|---|---|",
    ]
    for r in group_b:
        mid_str = r["market_id"] if r["market_id"] else "NOT_IN_DB"
        lines.append(
            f"| {r['case_id']} | {r['label']} | `{mid_str}` "
            f"| {r['volume_usdc']:,.0f} | {r['n_trades_db']:,} |"
        )

    if group_a:
        lines += [
            "",
            "## Phase 3 Target List (try_rpc_direct — Group A)",
            "",
            "| Case | Label | Market ID | Vol ($) |",
            "|---|---|---|---|",
        ]
        for r in group_a:
            mid_str = r["market_id"] if r["market_id"] else "NOT_IN_DB"
            lines.append(
                f"| {r['case_id']} | {r['label']} | `{mid_str}` "
                f"| {r['volume_usdc']:,.0f} |"
            )

    pathlib.Path("reports").mkdir(exist_ok=True)
    pathlib.Path("reports/TASK_02H_FFIC_DIAGNOSTICS.md").write_text("\n".join(lines) + "\n")
    print("\n→ reports/TASK_02H_FFIC_DIAGNOSTICS.md")


if __name__ == "__main__":
    asyncio.run(run())
