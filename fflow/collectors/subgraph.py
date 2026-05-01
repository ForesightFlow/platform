"""Polymarket subgraph collector — full trade log via The Graph GraphQL."""

from datetime import UTC, datetime

from gql import Client, gql
from gql.transport.httpx import HTTPXAsyncTransport
from sqlalchemy.dialects.postgresql import insert

from fflow.collectors.base import BaseCollector, CollectorResult
from fflow.config import settings
from fflow.db import AsyncSessionLocal
from fflow.log import get_logger
from fflow.models import Trade, Wallet

log = get_logger(__name__)

_PAGE_SIZE = 1000

# API note (verified 2026-04-26): The Polymarket subgraph exposes `enrichedOrderFilleds`
# (not `orderFilleds`). market.id is the YES token decimal ID. size is raw int (divide by
# 1e6 for shares). price is already a 0-1 decimal. side is "Buy"/"Sell" relative to the token.
_TRADES_QUERY = gql("""
query Trades($market: String!, $lastId: String!, $first: Int!) {
  enrichedOrderFilleds(
    where: { market: $market, id_gt: $lastId }
    first: $first
    orderBy: id
    orderDirection: asc
  ) {
    id
    timestamp
    transactionHash
    orderHash
    maker { id }
    taker { id }
    market { id }
    side
    size
    price
  }
}
""")


class SubgraphCollector(BaseCollector):
    name = "subgraph_trades"

    async def run(
        self,
        target: str | None = None,
        market_id: str | None = None,
        from_ts: datetime | None = None,
        dry_run: bool = False,
    ) -> CollectorResult:
        mid = market_id or target
        result = self._start_result(mid)
        async with AsyncSessionLocal() as session:
            run_id = await self._record_run_start(session, result)
            try:
                yes_token = await self._resolve_yes_token(session, mid)
                trades = await self._fetch_trades(mid, yes_token, from_ts)
                if not dry_run:
                    result.n_written, result.n_wallets = await self._upsert_trades(session, mid, yes_token, trades)
                else:
                    result.n_written = len(trades)
                result.status = "success"
            except Exception as exc:
                result.status = "failed"
                result.error = str(exc)
                log.error("subgraph_collector_failed", market=mid, error=str(exc))
                raise
            finally:
                result.finished_at = datetime.now(UTC)
                await self._record_run_end(session, run_id, result)
        return result

    async def _resolve_yes_token(self, session, market_id: str) -> str:
        import json
        from sqlalchemy import select
        from fflow.models import Market

        row = await session.execute(
            select(Market.raw_metadata).where(Market.id == market_id)
        )
        meta = row.scalar_one()
        token_ids_raw = meta.get("clobTokenIds", "[]")
        token_ids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw
        return str(token_ids[1]) if len(token_ids) > 1 else ""

    def _make_client(self) -> Client:
        headers = {"Accept": "application/json"}
        if settings.thegraph_api_key:
            headers["Authorization"] = f"Bearer {settings.thegraph_api_key}"
        transport = HTTPXAsyncTransport(
            url=settings.subgraph_url,
            headers=headers,
            timeout=60.0,
        )
        return Client(transport=transport, fetch_schema_from_transport=False, execute_timeout=60)

    async def _fetch_trades(
        self,
        market_id: str,
        yes_token: str,
        from_ts: datetime | None,
    ) -> list[dict]:
        import asyncio as _asyncio
        from gql.transport.exceptions import TransportConnectionFailed

        from_unix = int(from_ts.timestamp()) if from_ts else 0
        all_trades: list[dict] = []
        last_id = ""

        async with self._make_client() as client:
            while True:
                for attempt in range(3):
                    try:
                        result = await client.execute(
                            _TRADES_QUERY,
                            variable_values={
                                "market": yes_token,
                                "lastId": last_id,
                                "first": _PAGE_SIZE,
                            },
                        )
                        break
                    except (TransportConnectionFailed, Exception) as exc:
                        from gql.transport.exceptions import TransportQueryError
                        if isinstance(exc, TransportQueryError) and "bad indexers" in str(exc):
                            raise  # indexer unavailable — no point retrying
                        if attempt == 2:
                            raise
                        await _asyncio.sleep(2 ** attempt)

                page = result.get("enrichedOrderFilleds", [])
                if not page:
                    break

                for trade in page:
                    if from_ts and int(trade["timestamp"]) < from_unix:
                        continue
                    all_trades.append(trade)

                if len(page) < _PAGE_SIZE:
                    break
                last_id = page[-1]["id"]

        log.info("subgraph_fetched", market=market_id, n=len(all_trades))
        return all_trades

    async def _upsert_trades(
        self, session, market_id: str, yes_token: str, raw_trades: list[dict]
    ) -> int:
        if not raw_trades:
            return 0

        now = datetime.now(UTC)
        trade_rows = []
        wallet_set: dict[str, datetime] = {}

        for t in raw_trades:
            tx = t.get("transactionHash", "")
            raw_id = t.get("id", "")
            log_idx = _parse_log_index(raw_id)
            ts = datetime.fromtimestamp(int(t["timestamp"]), tz=UTC)
            taker = ((t.get("taker") or {}).get("id") or "").lower()
            maker = ((t.get("maker") or {}).get("id") or "").lower() or None

            raw_side = t.get("side", "Buy")
            side = "BUY" if raw_side.lower() == "buy" else "SELL"
            outcome_index = 1  # all enrichedOrderFilleds filtered by YES token

            raw_size = int(t.get("size", 0))
            size_shares = raw_size / 1e6
            price_val = float(t.get("price", 0))
            notional = size_shares * price_val

            trade_rows.append({
                "market_id": market_id,
                "tx_hash": tx,
                "log_index": log_idx,
                "ts": ts,
                "taker_address": taker,
                "maker_address": maker,
                "side": side,
                "outcome_index": outcome_index,
                "size_shares": str(round(size_shares, 6)),
                "price": str(round(price_val, 6)),
                "notional_usdc": str(round(notional, 6)),
                "raw_event": t,
            })

            # seed wallets
            for addr in filter(None, [taker, maker]):
                if addr not in wallet_set or wallet_set[addr] > ts:
                    wallet_set[addr] = ts

        # upsert trades
        chunk_size = 500
        total = 0
        for i in range(0, len(trade_rows), chunk_size):
            chunk = trade_rows[i : i + chunk_size]
            stmt = (
                insert(Trade)
                .values(chunk)
                .on_conflict_do_nothing(constraint="uq_trades_tx_log")
            )
            await session.execute(stmt)
            total += len(chunk)
        await session.commit()

        # upsert wallets — chunked (PostgreSQL param limit: 32767; 3 cols × 10000 = 30000)
        wallet_chunk_size = 10_000
        if wallet_set:
            wallet_rows = [
                {
                    "address": addr,
                    "first_seen_polymarket_at": ts,
                    "last_refreshed_at": now,
                }
                for addr, ts in wallet_set.items()
            ]
            for i in range(0, len(wallet_rows), wallet_chunk_size):
                chunk = wallet_rows[i : i + wallet_chunk_size]
                wallet_stmt = (
                    insert(Wallet)
                    .values(chunk)
                    .on_conflict_do_update(
                        index_elements=["address"],
                        set_={
                            "first_seen_polymarket_at": insert(Wallet).excluded.first_seen_polymarket_at,
                        },
                        where=(
                            Wallet.first_seen_polymarket_at.is_(None)
                            | (
                                Wallet.first_seen_polymarket_at
                                > insert(Wallet).excluded.first_seen_polymarket_at
                            )
                        ),
                    )
                )
                await session.execute(wallet_stmt)
            await session.commit()

        log.info("subgraph_upserted", market=market_id, trades=total, wallets=len(wallet_set))
        return total, len(wallet_set)


def _parse_log_index(raw_id: str) -> int:
    # enrichedOrderFilleds id format: txHash_orderHash — hash the orderHash part
    if "_" in raw_id:
        order_hash_part = raw_id.split("_", 1)[-1]
        return int(order_hash_part, 16) % 2**31 if order_hash_part.startswith("0x") else hash(order_hash_part) % 2**31
    if "-" in raw_id:
        try:
            return int(raw_id.split("-")[-1])
        except ValueError:
            pass
    try:
        return int(raw_id) % 2**31
    except (ValueError, TypeError):
        return 0
