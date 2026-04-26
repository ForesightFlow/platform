"""Targeted backfill for the 8 documented potential-insider-trading cases.

Runs SubgraphCollector for each market (independent of volume threshold).
Runs ClobCollector if price_history < 60 points.
Idempotency: skips a market if trades exist AND market resolved >24h ago.
Writes JSONL to logs/documented_cases_backfill.jsonl and a status report.
Stops if total runtime > 4h.

Market IDs are stored as known prefixes (first 10 hex chars) and resolved
to full condition IDs via DB lookup at runtime.
"""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, text

from fflow.collectors.clob import ClobCollector
from fflow.collectors.subgraph import SubgraphCollector
from fflow.db import AsyncSessionLocal
from fflow.log import get_logger
from fflow.models import Market, Price, Trade

log = get_logger(__name__)

LOG_PATH = Path("logs/documented_cases_backfill.jsonl")
REPORT_PATH = Path("reports/DOCUMENTED_CASES_DATA_STATUS.md")
MAX_RUNTIME_SECONDS = 4 * 3600
MIN_PRICE_POINTS = 60

# Each entry has id_prefix (first 10 hex chars after 0x) to look up the full
# condition ID from the DB at runtime. label is human-readable.
CASES: list[dict] = [
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
        "name": "Maduro / Venezuela 2024-2026",
        "markets": [
            {"prefix": "0xbfa45527", "label": "Maduro in US custody by Jan 31"},
            {"prefix": "0x62b0cd59", "label": "US-Venezuela military by Dec 31"},
            {"prefix": "0x7f3c6b90", "label": "US invades Venezuela by Jan 31"},
        ],
    },
    {
        "case_id": "fficd-005",
        "name": "Bitcoin ETF SEC Approval January 2024",
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
        "name": "FTX / SBF Collapse 2022-2024",
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


def _append_log(entry: dict) -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")


async def _resolve_market_id(session, prefix: str) -> str | None:
    """Look up full condition ID by prefix match."""
    row = await session.execute(
        select(Market.id).where(Market.id.like(prefix + "%")).limit(1)
    )
    return row.scalar_one_or_none()


async def _get_market_info(session, market_id: str) -> dict:
    row = await session.execute(
        select(
            Market.question,
            Market.resolved_at,
            Market.resolution_outcome,
            Market.volume_total_usdc,
        ).where(Market.id == market_id)
    )
    r = row.first()
    return {
        "question": r[0],
        "resolved_at": r[1],
        "resolution_outcome": r[2],
        "volume_total_usdc": float(r[3]) if r[3] is not None else None,
    }


async def _count_trades(session, market_id: str) -> int:
    row = await session.execute(
        select(func.count()).select_from(Trade).where(Trade.market_id == market_id)
    )
    return row.scalar_one()


async def _count_prices(session, market_id: str) -> int:
    row = await session.execute(
        select(func.count()).select_from(Price).where(Price.market_id == market_id)
    )
    return row.scalar_one()


async def _count_wallets(session, market_id: str) -> int:
    row = await session.execute(
        text("SELECT COUNT(DISTINCT taker_address) FROM trades WHERE market_id = :mid"),
        {"mid": market_id},
    )
    return row.scalar_one()


def _is_stale(market_info: dict) -> bool:
    resolved_at = market_info.get("resolved_at")
    if resolved_at is None:
        return False
    return datetime.now(UTC) - resolved_at > timedelta(hours=24)


async def _run_subgraph(market_id: str) -> tuple[str, int, int]:
    collector = SubgraphCollector()
    try:
        result = await collector.run(market_id=market_id)
        return result.status, result.n_written, result.n_wallets
    except Exception as exc:
        msg = str(exc)
        if "bad indexers" in msg.lower():
            log.warning("subgraph_blocked_by_indexer", market=market_id)
            return "blocked-by-indexer", 0, 0
        log.error("subgraph_failed", market=market_id, error=msg)
        return "failed", 0, 0


async def _run_clob(market_id: str) -> tuple[str, int]:
    collector = ClobCollector()
    try:
        result = await collector.run(market_id=market_id)
        return result.status, result.n_written
    except Exception as exc:
        log.error("clob_failed", market=market_id, error=str(exc))
        return "failed", 0


async def _process_market(
    prefix: str,
    case_id: str,
    case_name: str,
    label: str,
) -> dict:
    t0 = time.monotonic()

    async with AsyncSessionLocal() as session:
        market_id = await _resolve_market_id(session, prefix)
        if market_id is None:
            log.warning("market_not_in_db", prefix=prefix, label=label)
            duration_ms = int((time.monotonic() - t0) * 1000)
            entry = {
                "ts": datetime.now(UTC).isoformat(),
                "prefix": prefix,
                "market_id": None,
                "case_id": case_id,
                "label": label,
                "status": "not-in-db",
                "trades_before": 0,
                "prices_before": 0,
                "wallets_before": 0,
                "trades_written": 0,
                "prices_written": 0,
                "wallets_written": 0,
                "duration_ms": duration_ms,
            }
            _append_log(entry)
            return entry

        market_info = await _get_market_info(session, market_id)
        trades_before = await _count_trades(session, market_id)
        prices_before = await _count_prices(session, market_id)
        wallets_before = await _count_wallets(session, market_id)

    # Idempotency: skip if trades already collected and market resolved >24h ago
    if trades_before > 0 and _is_stale(market_info):
        log.info("skip_idempotent", market=market_id, trades=trades_before)
        duration_ms = int((time.monotonic() - t0) * 1000)
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "prefix": prefix,
            "market_id": market_id,
            "case_id": case_id,
            "label": label,
            "status": "skipped-idempotent",
            "trades_before": trades_before,
            "prices_before": prices_before,
            "wallets_before": wallets_before,
            "trades_written": 0,
            "prices_written": 0,
            "wallets_written": 0,
            "duration_ms": duration_ms,
        }
        _append_log(entry)
        return entry

    log.info("subgraph_start", market=market_id, case=case_id, label=label)
    subgraph_status, trades_written, wallets_written = await _run_subgraph(market_id)

    prices_written = 0
    if prices_before < MIN_PRICE_POINTS:
        log.info("clob_start", market=market_id, prices_before=prices_before)
        _, prices_written = await _run_clob(market_id)

    overall_status = "ok" if subgraph_status == "success" else subgraph_status

    duration_ms = int((time.monotonic() - t0) * 1000)
    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "prefix": prefix,
        "market_id": market_id,
        "case_id": case_id,
        "label": label,
        "status": overall_status,
        "trades_before": trades_before,
        "prices_before": prices_before,
        "wallets_before": wallets_before,
        "trades_written": trades_written,
        "prices_written": prices_written,
        "wallets_written": wallets_written,
        "duration_ms": duration_ms,
    }
    _append_log(entry)
    log.info(
        "market_done",
        market=market_id,
        status=overall_status,
        trades_written=trades_written,
        prices_written=prices_written,
        duration_ms=duration_ms,
    )
    return entry


async def _generate_report(results: list[dict]) -> None:
    status_icons = {
        "ok": "✅",
        "skipped-idempotent": "⏭️",
        "blocked-by-indexer": "🔴",
        "not-in-db": "❓",
        "failed": "❌",
    }

    lines = [
        "# Documented Cases Data Status",
        "",
        f"**Generated:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Markets processed:** {len(results)}",
        "",
        "---",
        "",
    ]

    by_case: dict[str, list[dict]] = {}
    for r in results:
        by_case.setdefault(r["case_id"], []).append(r)

    for case in CASES:
        cid = case["case_id"]
        case_results = by_case.get(cid, [])
        lines.append(f"## {cid.upper()} — {case['name']}")
        lines.append("")
        lines.append("| prefix | label | market_id | status | trades | prices | wallets | time |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in case_results:
            icon = status_icons.get(r["status"], "?")
            trades_total = r["trades_before"] + r["trades_written"]
            prices_total = r["prices_before"] + r["prices_written"]
            wallets_total = r["wallets_before"] + r["wallets_written"]
            mid = (r["market_id"] or "—")[:18] + "..." if r["market_id"] else "—"
            lines.append(
                f"| `{r['prefix']}` | {r['label']} | `{mid}` | {icon} {r['status']} "
                f"| {trades_total:,} | {prices_total:,} | {wallets_total:,} "
                f"| {r['duration_ms']/1000:.1f}s |"
            )
        if not case_results:
            lines.append("| — | — | — | not run | — | — | — | — |")
        lines.append("")

    status_counts: dict[str, int] = {}
    total_trades = sum(r["trades_before"] + r["trades_written"] for r in results)
    total_prices = sum(r["prices_before"] + r["prices_written"] for r in results)
    for r in results:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1

    lines += [
        "---",
        "",
        "## Summary",
        "",
    ]
    for status, count in sorted(status_counts.items()):
        icon = status_icons.get(status, "?")
        lines.append(f"- {icon} **{status}**: {count} markets")
    lines += [
        "",
        f"- Total trades in DB for these markets: {total_trades:,}",
        f"- Total price points in DB for these markets: {total_prices:,}",
    ]

    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n")
    print(f"\nReport written to {REPORT_PATH}")


async def main() -> None:
    all_markets = [(m["prefix"], c["case_id"], c["name"], m["label"]) for c in CASES for m in c["markets"]]
    print(f"Documented cases backfill — {len(all_markets)} markets across {len(CASES)} cases")
    print(f"Log: {LOG_PATH}  |  Max runtime: {MAX_RUNTIME_SECONDS/3600:.0f}h\n")

    wall_start = time.monotonic()
    results: list[dict] = []

    for i, (prefix, case_id, case_name, label) in enumerate(all_markets, 1):
        elapsed = time.monotonic() - wall_start
        if elapsed > MAX_RUNTIME_SECONDS:
            print(f"\nMax runtime reached ({elapsed/3600:.1f}h). Stopping.")
            break

        print(f"[{i}/{len(all_markets)}] {case_id} — {label[:55]}")
        result = await _process_market(prefix, case_id, case_name, label)
        results.append(result)

        elapsed_total = time.monotonic() - wall_start
        trades_total = result["trades_before"] + result["trades_written"]
        prices_total = result["prices_before"] + result["prices_written"]
        print(
            f"  → {result['status']} | trades:{trades_total:,} | prices:{prices_total:,} "
            f"| {result['duration_ms']/1000:.1f}s | elapsed:{elapsed_total/60:.1f}min"
        )

    await _generate_report(results)

    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    summary = " ".join(f"{s}={n}" for s, n in sorted(counts.items()))
    print(f"\nDone. {summary}")
    print(f"Total elapsed: {(time.monotonic()-wall_start)/60:.1f}min")


if __name__ == "__main__":
    asyncio.run(main())
