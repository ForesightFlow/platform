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

_TRADES_QUERY = gql("""
query Trades($market: String!, $lastId: String!, $first: Int!) {
  orderFilleds(
    where: { market: $market, id_gt: $lastId }
    first: $first
    orderBy: id
    orderDirection: asc
  ) {
    id
    timestamp
    transactionHash
    maker
    taker
    makerAssetId
    takerAssetId
    makerAmountFilled
    takerAmountFilled
    fee
    market {
      id
    }
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
                    result.n_written = await self._upsert_trades(session, mid, yes_token, trades)
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
        transport = HTTPXAsyncTransport(url=settings.subgraph_url, headers=headers)
        return Client(transport=transport, fetch_schema_from_transport=False)

    async def _fetch_trades(
        self,
        market_id: str,
        yes_token: str,
        from_ts: datetime | None,
    ) -> list[dict]:
        from_unix = int(from_ts.timestamp()) if from_ts else 0
        all_trades: list[dict] = []
        last_id = ""

        async with self._make_client() as client:
            while True:
                result = await client.execute(
                    _TRADES_QUERY,
                    variable_values={
                        "market": market_id.lower(),
                        "lastId": last_id,
                        "first": _PAGE_SIZE,
                    },
                )
                page = result.get("orderFilleds", [])
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
            # log_index from id (format: txHash-logIndex or sequential id)
            raw_id = t.get("id", "")
            log_idx = _parse_log_index(raw_id)
            ts = datetime.fromtimestamp(int(t["timestamp"]), tz=UTC)
            taker = (t.get("taker") or "").lower()
            maker = (t.get("maker") or "").lower() or None

            taker_asset = t.get("takerAssetId", "")
            maker_amount = int(t.get("makerAmountFilled", 0))
            taker_amount = int(t.get("takerAmountFilled", 0))

            # taker receives YES token → BUY; taker gives YES token → SELL
            if str(taker_asset) == yes_token:
                side = "BUY"
                outcome_index = 1
                size_shares = taker_amount
                usdc_paid = maker_amount
            else:
                side = "SELL"
                outcome_index = 1
                size_shares = maker_amount
                usdc_paid = taker_amount

            price_val = (usdc_paid / size_shares / 1e6) if size_shares else 0
            notional = usdc_paid / 1e6

            trade_rows.append({
                "market_id": market_id,
                "tx_hash": tx,
                "log_index": log_idx,
                "ts": ts,
                "taker_address": taker,
                "maker_address": maker,
                "side": side,
                "outcome_index": outcome_index,
                "size_shares": str(size_shares / 1e6),
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

        # upsert wallets
        if wallet_set:
            wallet_rows = [
                {
                    "address": addr,
                    "first_seen_polymarket_at": ts,
                    "last_refreshed_at": now,
                }
                for addr, ts in wallet_set.items()
            ]
            wallet_stmt = (
                insert(Wallet)
                .values(wallet_rows)
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
        return total


def _parse_log_index(raw_id: str) -> int:
    if "-" in raw_id:
        try:
            return int(raw_id.split("-")[-1])
        except ValueError:
            pass
    try:
        return int(raw_id) % 2**31
    except (ValueError, TypeError):
        return 0
