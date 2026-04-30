#!/usr/bin/env python3
"""
Task 02H Phase 3: Recover price + trade data for 2 unindexed FFIC markets.

Markets (both resolved YES):
  1. fficd-003 'US forces enter Iran by April 30' — $269M  (resolved 2026-04-09)
  2. fficd-003 'US-Iran ceasefire by April 7'      — $174M  (resolved 2026-04-11)

Approach:
  1. CLOB price history  → /prices-history (full 1-min candles, entire market life)
  2. Polymarket data-api → /trades (max 3000 most-recent trades per market)

The subgraph indexer failed for both markets (too large / indexer crash).
eth_getLogs on the CTF Exchange emits ~300 events/block across ALL markets;
downloading 82 GB to filter client-side is not practical.
The data-api gives the last ~3000 trades, covering the resolution window which
is the most analytically interesting period.
"""

import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy.dialects.postgresql import insert

sys.path.insert(0, str(Path(__file__).parent.parent))

from fflow.config import settings
from fflow.db import AsyncSessionLocal
from fflow.log import get_logger
from fflow.models import Market, Price, Trade, Wallet
from sqlalchemy import select, text

log = get_logger(__name__)

DATA_API = "https://data-api.polymarket.com"
CLOB_API = settings.clob_api_url  # https://clob.polymarket.com

MARKETS = [
    {
        "market_id": "0x6d0e09d0f04572d9b1adad84703458b0297bc5603b69dccbde93147ee4443246",
        "label": "US forces enter Iran by April 30",
        "created_at_ts": 1773851347,    # 2026-03-18T16:29:07 UTC
        "resolved_at_ts": 1775694501,   # 2026-04-09T00:28:21 UTC
    },
    {
        "market_id": "0x4c5701bcde0b8fb7d7f48c8e9d20245a6caa58c61a77f981fad98f2bfa0b1bc7",
        "label": "US x Iran ceasefire by April 7",
        "created_at_ts": 1774374725,    # 2026-03-24T17:52:05 UTC
        "resolved_at_ts": 1775867319,   # 2026-04-11T00:28:39 UTC
    },
]

# ---------------------------------------------------------------------------
# CLOB price history
# ---------------------------------------------------------------------------

_BATCH_SECONDS = 14 * 24 * 3600  # CLOB limits requests to ~15 days max


async def _get_yes_token(market_id: str) -> str:
    async with AsyncSessionLocal() as session:
        row = await session.execute(select(Market.raw_metadata).where(Market.id == market_id))
        meta = row.scalar_one()
        raw = meta.get("clobTokenIds", "[]")
        ids = json.loads(raw) if isinstance(raw, str) else raw
        return str(ids[1]) if len(ids) > 1 else ""


async def collect_clob_prices(
    client: httpx.AsyncClient,
    market_id: str,
    yes_token: str,
    label: str,
    start_ts: int = 0,
) -> int:
    """Fetch 1-min OHLCV from CLOB and upsert to prices table."""
    all_prices: list[dict] = []
    cursor = start_ts  # from market creation

    while True:
        batch_end = cursor + _BATCH_SECONDS
        resp = await client.get(
            f"{CLOB_API}/prices-history",
            params={"market": yes_token, "startTs": cursor, "endTs": batch_end, "fidelity": 1},
        )
        resp.raise_for_status()
        history = resp.json().get("history", [])
        if not history:
            break
        all_prices.extend(history)
        if len(history) < 2:
            break
        last_ts = history[-1]["t"]
        if last_ts <= cursor:
            break
        cursor = last_ts + 60

    if not all_prices:
        log.info("clob_no_prices", market=label)
        return 0

    seen_ts: set = set()
    rows = []
    for p in all_prices:
        ts = datetime.fromtimestamp(p["t"], tz=UTC).replace(second=0, microsecond=0)
        if ts in seen_ts:
            continue
        seen_ts.add(ts)
        rows.append({"market_id": market_id, "ts": ts, "mid_price": str(p["p"]),
                     "bid": None, "ask": None, "volume_minute": None})

    total = 0
    async with AsyncSessionLocal() as session:
        for i in range(0, len(rows), 1000):
            chunk = rows[i : i + 1000]
            stmt = (
                insert(Price)
                .values(chunk)
                .on_conflict_do_update(
                    index_elements=["market_id", "ts"],
                    set_={"mid_price": insert(Price).excluded.mid_price},
                )
            )
            await session.execute(stmt)
            total += len(chunk)
        await session.commit()

    log.info("clob_upserted", market=label, n=total)
    return total


# ---------------------------------------------------------------------------
# Data-api trade history (max ~3000 most-recent trades)
# ---------------------------------------------------------------------------

def _pseudo_log_index(tx_hash: str, proxy_wallet: str, size: float, price: float, ts: int) -> int:
    key = f"{tx_hash}:{proxy_wallet}:{size}:{price}:{ts}"
    return int(hashlib.md5(key.encode()).hexdigest(), 16) % (2 ** 31)


async def collect_data_api_trades(
    client: httpx.AsyncClient,
    market_id: str,
    label: str,
) -> int:
    """Fetch up to 3000 most-recent trades from data-api and upsert."""
    all_raw: list[dict] = []
    for offset in range(0, 3001, 1000):
        resp = await client.get(
            f"{DATA_API}/trades",
            params={"market": market_id, "limit": 1000, "offset": offset},
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or not data:
            break
        if isinstance(data, dict) and "error" in data:
            log.warning("data_api_error", market=label, offset=offset, error=data["error"])
            break
        all_raw.extend(data)
        if len(data) < 1000:
            break

    if not all_raw:
        return 0

    now = datetime.now(UTC)
    trade_rows: list[dict] = []
    wallet_set: dict[str, datetime] = {}

    for t in all_raw:
        tx_hash = t.get("transactionHash", "")
        proxy_wallet = (t.get("proxyWallet") or "").lower()
        size = float(t.get("size", 0))
        price = float(t.get("price", 0))
        timestamp = int(t.get("timestamp", 0))
        side = (t.get("side") or "BUY").upper()
        if side not in ("BUY", "SELL"):
            side = "BUY"

        ts = datetime.fromtimestamp(timestamp, tz=UTC)
        log_idx = _pseudo_log_index(tx_hash, proxy_wallet, size, price, timestamp)
        notional = size * price

        trade_rows.append({
            "market_id": market_id,
            "tx_hash": tx_hash,
            "log_index": log_idx,
            "ts": ts,
            "taker_address": proxy_wallet or "0x0000000000000000000000000000000000000000",
            "maker_address": None,
            "side": side,
            "outcome_index": 1,
            "size_shares": str(round(size, 6)),
            "price": str(round(price, 6)),
            "notional_usdc": str(round(notional, 6)),
            "raw_event": {"source": "data_api_polymarket", "tx_hash": tx_hash,
                          "proxy_wallet": proxy_wallet, "size": size, "price": price},
        })

        if proxy_wallet:
            if proxy_wallet not in wallet_set or wallet_set[proxy_wallet] > ts:
                wallet_set[proxy_wallet] = ts

    # upsert trades
    total = 0
    async with AsyncSessionLocal() as session:
        for i in range(0, len(trade_rows), 500):
            chunk = trade_rows[i : i + 500]
            stmt = insert(Trade).values(chunk).on_conflict_do_nothing(constraint="uq_trades_tx_log")
            await session.execute(stmt)
            total += len(chunk)
        await session.commit()

    # upsert wallets
    if wallet_set:
        wallet_rows = [
            {"address": a, "first_seen_polymarket_at": ts, "last_refreshed_at": now}
            for a, ts in wallet_set.items()
        ]
        async with AsyncSessionLocal() as session:
            for i in range(0, len(wallet_rows), 10_000):
                chunk = wallet_rows[i : i + 10_000]
                stmt = (
                    insert(Wallet)
                    .values(chunk)
                    .on_conflict_do_update(
                        index_elements=["address"],
                        set_={"first_seen_polymarket_at": insert(Wallet).excluded.first_seen_polymarket_at},
                        where=(
                            Wallet.first_seen_polymarket_at.is_(None)
                            | (Wallet.first_seen_polymarket_at > insert(Wallet).excluded.first_seen_polymarket_at)
                        ),
                    )
                )
                await session.execute(stmt)
            await session.commit()

    log.info("data_api_upserted", market=label, trades=total, wallets=len(wallet_set))
    return total


# ---------------------------------------------------------------------------
# Per-market orchestration
# ---------------------------------------------------------------------------

async def process_market(market: dict) -> dict:
    market_id = market["market_id"]
    label = market["label"]

    yes_token = await _get_yes_token(market_id)
    if not yes_token:
        raise RuntimeError(f"YES token not found for {market_id}")

    print(f"\n{'='*68}")
    print(f"  {label}")
    print(f"  market_id : {market_id}")
    print(f"  created   : {datetime.fromtimestamp(market['created_at_ts'], tz=UTC).isoformat()}")
    print(f"  resolved  : {datetime.fromtimestamp(market['resolved_at_ts'], tz=UTC).isoformat()}")

    started_at = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        row = await session.execute(
            text(
                "INSERT INTO data_collection_runs "
                "(collector, started_at, status, target, run_metadata) "
                "VALUES ('polygonscan_logs', :s, 'running', :t, CAST(:m AS jsonb)) "
                "RETURNING id"
            ),
            {
                "s": started_at,
                "t": market_id,
                "m": json.dumps({"label": label, "approach": "clob_prices+data_api_trades",
                                 "yes_token": yes_token}),
            },
        )
        await session.commit()
        run_id = row.scalar_one()

    status = "failed"
    n_prices = 0
    n_trades = 0
    error_msg = None

    try:
        async with httpx.AsyncClient(timeout=60.0, http2=True) as client:
            print(f"  Collecting CLOB price history...")
            n_prices = await collect_clob_prices(
                client, market_id, yes_token, label, start_ts=market["created_at_ts"]
            )
            print(f"  Collecting data-api trades (max 3000)...")
            n_trades = await collect_data_api_trades(client, market_id, label)

        print(f"  prices written : {n_prices:,}")
        print(f"  trades written : {n_trades:,}")
        status = "success"

    except Exception as exc:
        error_msg = str(exc)
        print(f"  ERROR: {error_msg}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        raise
    finally:
        finished_at = datetime.now(UTC)
        elapsed = (finished_at - started_at).total_seconds()
        print(f"  elapsed        : {elapsed:.1f}s  status={status}")
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    "UPDATE data_collection_runs SET "
                    "finished_at=:f, status=:s, n_records_written=:n, error_message=:e "
                    "WHERE id=:id"
                ),
                {"f": finished_at, "s": status, "n": n_prices + n_trades, "e": error_msg, "id": run_id},
            )
            await session.commit()

    return {
        "label": label,
        "market_id": market_id,
        "n_prices": n_prices,
        "n_trades": n_trades,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    print("Task 02H Phase 3 — CLOB prices + data-api trades recovery")
    print(f"Started : {datetime.now(UTC).isoformat()}")

    results = []
    for market in MARKETS:
        result = await process_market(market)
        results.append(result)

    print(f"\n{'='*68}")
    print("PHASE 3 SUMMARY")
    print(f"{'='*68}")
    for r in results:
        print(
            f"  {r['label'][:50]:50s}  "
            f"prices={r['n_prices']:>6,}  "
            f"trades={r['n_trades']:>5,}  "
            f"{r['status']}"
        )

    all_ok = all(r["status"] == "success" for r in results)
    print(f"\n  Overall: {'SUCCESS' if all_ok else 'PARTIAL'}")
    print(f"Finished: {datetime.now(UTC).isoformat()}")

    # Return results for report generation
    return results


if __name__ == "__main__":
    asyncio.run(main())
