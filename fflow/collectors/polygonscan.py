"""Polygonscan wallet collector.

Rate limit: 5 req/sec on free tier. Token bucket at 4 req/sec.
USDC contract on Polygon PoS: 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
"""

import asyncio
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from fflow.collectors.base import BaseCollector, CollectorResult, RetryableHTTPClient
from fflow.config import settings
from fflow.db import AsyncSessionLocal
from fflow.log import get_logger
from fflow.models import Wallet

log = get_logger(__name__)

_USDC_CONTRACT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
_RATE_LIMIT = 4.0  # req/sec


class PolygonscanCollector(BaseCollector):
    name = "polygonscan"

    def __init__(self) -> None:
        self._token_bucket_lock = asyncio.Lock()
        self._last_request_time: float = 0.0

    async def run(
        self,
        target: str | None = None,
        wallet: str | None = None,
        all_stale: bool = False,
        max_age_days: int = 30,
        min_trades: int = 0,
        dry_run: bool = False,
    ) -> CollectorResult:
        addr = (wallet or target or "").lower()
        result = self._start_result(addr or "all_stale")
        async with AsyncSessionLocal() as session:
            run_id = await self._record_run_start(session, result)
            try:
                if all_stale:
                    wallets = await self._get_stale_wallets(session, max_age_days, min_trades)
                else:
                    wallets = [addr] if addr else []

                total = 0
                n_wallets = len(wallets)
                for i, w_addr in enumerate(wallets, 1):
                    n = await self._process_wallet(session, w_addr, dry_run)
                    total += n
                    if i % 100 == 0:
                        log.info("polygonscan_batch_progress", done=i, total=n_wallets, written=total)

                result.n_written = total
                result.status = "success"
            except Exception as exc:
                result.status = "failed"
                result.error = str(exc)
                log.error("polygonscan_collector_failed", error=str(exc))
                raise
            finally:
                result.finished_at = datetime.now(UTC)
                await self._record_run_end(session, run_id, result)
        return result

    async def _get_stale_wallets(self, session, max_age_days: int, min_trades: int = 0) -> list[str]:
        from datetime import timedelta
        from sqlalchemy import text as sa_text
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        if min_trades > 0:
            rows = await session.execute(
                sa_text("""
                    SELECT w.address
                    FROM wallets w
                    JOIN (
                        SELECT taker_address, COUNT(*) AS tc
                        FROM trades
                        GROUP BY taker_address
                    ) t ON t.taker_address = w.address
                    WHERE (w.last_refreshed_at < :cutoff OR w.first_seen_chain_at IS NULL)
                      AND t.tc >= :min_trades
                    ORDER BY t.tc DESC
                """),
                {"cutoff": cutoff, "min_trades": min_trades},
            )
        else:
            rows = await session.execute(
                select(Wallet.address).where(
                    (Wallet.last_refreshed_at < cutoff)
                    | Wallet.first_seen_chain_at.is_(None)
                )
            )
        result = [r[0] for r in rows.all()]
        log.info("polygonscan_wallets_selected", count=len(result), min_trades=min_trades)
        return result

    async def _rate_limit(self) -> None:
        async with self._token_bucket_lock:
            now = asyncio.get_event_loop().time()
            min_gap = 1.0 / _RATE_LIMIT
            elapsed = now - self._last_request_time
            if elapsed < min_gap:
                await asyncio.sleep(min_gap - elapsed)
            self._last_request_time = asyncio.get_event_loop().time()

    async def _get(self, client: RetryableHTTPClient, params: dict) -> dict:
        await self._rate_limit()
        resp = await client.get(settings.polygonscan_url, params={"chainid": 137, **params})
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "0" and data.get("message") != "No transactions found":
            raise RuntimeError(f"Polygonscan error: {data.get('message')} | {data.get('result')}")
        return data

    async def _process_wallet(self, session, address: str, dry_run: bool) -> int:
        if not settings.polygonscan_api_key:
            log.warning("polygonscan_no_api_key", wallet=address)
            return 0

        async with RetryableHTTPClient() as client:
            # Fetch normal tx list to get first_seen_chain_at
            tx_data = await self._get(client, {
                "module": "account",
                "action": "txlist",
                "address": address,
                "startblock": 0,
                "endblock": 99999999,
                "page": 1,
                "offset": 1,
                "sort": "asc",
                "apikey": settings.polygonscan_api_key,
            })
            txs = tx_data.get("result") or []
            first_seen_chain_at = None
            if txs and isinstance(txs, list):
                first_seen_chain_at = datetime.fromtimestamp(
                    int(txs[0]["timeStamp"]), tz=UTC
                )

            # Fetch USDC token transfers for funding sources
            usdc_data = await self._get(client, {
                "module": "account",
                "action": "tokentx",
                "address": address,
                "contractaddress": _USDC_CONTRACT,
                "startblock": 0,
                "endblock": 99999999,
                "page": 1,
                "offset": 1000,
                "sort": "asc",
                "apikey": settings.polygonscan_api_key,
            })
            usdc_txs = usdc_data.get("result") or []
            funding_sources = _compute_funding_sources(address, usdc_txs)

        if dry_run:
            return 1

        now = datetime.now(UTC)
        stmt = (
            insert(Wallet)
            .values(
                address=address,
                first_seen_chain_at=first_seen_chain_at,
                funding_sources=funding_sources,
                last_refreshed_at=now,
            )
            .on_conflict_do_update(
                index_elements=["address"],
                set_={
                    "first_seen_chain_at": insert(Wallet).excluded.first_seen_chain_at,
                    "funding_sources": insert(Wallet).excluded.funding_sources,
                    "last_refreshed_at": insert(Wallet).excluded.last_refreshed_at,
                },
            )
        )
        async with AsyncSessionLocal() as session:
            await session.execute(stmt)
            await session.commit()

        log.info("polygonscan_upserted", wallet=address, funding_sources=len(funding_sources or []))
        return 1


def _compute_funding_sources(address: str, transfers: list[dict]) -> list[dict]:
    addr_lower = address.lower()
    # only incoming transfers (wallet received USDC)
    incoming = [t for t in transfers if t.get("to", "").lower() == addr_lower]

    by_sender: dict[str, dict] = defaultdict(lambda: {"n_transfers": 0, "total_usdc": 0.0})
    for t in incoming:
        sender = t.get("from", "").lower()
        value = int(t.get("value", 0)) / 1e6
        by_sender[sender]["n_transfers"] += 1
        by_sender[sender]["total_usdc"] += value

    top10 = sorted(
        [{"counterparty": k, **v} for k, v in by_sender.items()],
        key=lambda x: x["total_usdc"],
        reverse=True,
    )[:10]
    return top10
