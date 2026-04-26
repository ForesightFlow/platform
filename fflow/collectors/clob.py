"""CLOB price-history collector.

API notes (verified against live endpoint 2026-04-25):
- Response: {"history": [{"t": unix_ts_int, "p": float}]}
- No volume field in price-history endpoint.
- fidelity=1 gives 1-minute candles when using startTs/endTs params.
- interval param (1m/1w/1d/6h/1h) is a time-range shortcut; startTs/endTs override it.
- clobTokenIds in Gamma metadata is a JSON-encoded string; YES token is index 1.
"""

import json
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert

from fflow.collectors.base import BaseCollector, CollectorResult, RetryableHTTPClient
from fflow.config import settings
from fflow.db import AsyncSessionLocal
from fflow.log import get_logger
from fflow.models import Market, Price

log = get_logger(__name__)

_BATCH_SECONDS = 30 * 24 * 3600  # fetch 30 days per request


class ClobCollector(BaseCollector):
    name = "clob_prices"

    async def run(
        self,
        target: str | None = None,
        market_id: str | None = None,
        start_ts: datetime | None = None,
        end_ts: datetime | None = None,
        dry_run: bool = False,
    ) -> CollectorResult:
        mid = market_id or target
        result = self._start_result(mid)
        async with AsyncSessionLocal() as session:
            run_id = await self._record_run_start(session, result)
            try:
                yes_token = await self._resolve_yes_token(session, mid)
                prices = await self._fetch_prices(yes_token, mid, start_ts, end_ts)
                if not dry_run:
                    result.n_written = await self._upsert_prices(session, mid, prices)
                else:
                    result.n_written = len(prices)
                result.status = "success"
            except Exception as exc:
                result.status = "failed"
                result.error = str(exc)
                log.error("clob_collector_failed", market=mid, error=str(exc))
                raise
            finally:
                result.finished_at = datetime.now(UTC)
                await self._record_run_end(session, run_id, result)
        return result

    async def _resolve_yes_token(self, session, market_id: str) -> str:
        from sqlalchemy import select

        row = await session.execute(
            select(Market.raw_metadata).where(Market.id == market_id)
        )
        meta = row.scalar_one()
        token_ids_raw = meta.get("clobTokenIds", "[]")
        token_ids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw
        if len(token_ids) < 2:
            raise ValueError(f"No YES token found for market {market_id}: {token_ids}")
        return str(token_ids[1])

    async def _fetch_prices(
        self,
        yes_token: str,
        market_id: str,
        start_ts: datetime | None,
        end_ts: datetime | None,
    ) -> list[dict]:
        t_end = int((end_ts or datetime.now(UTC)).timestamp())
        # default to market's full history if no start given
        t_start = int(start_ts.timestamp()) if start_ts else 0

        all_prices: list[dict] = []
        cursor = t_start

        async with RetryableHTTPClient(base_url=settings.clob_api_url) as client:
            while cursor < t_end:
                batch_end = min(cursor + _BATCH_SECONDS, t_end)
                params = {
                    "market": yes_token,
                    "startTs": cursor,
                    "endTs": batch_end,
                    "fidelity": 1,
                }
                resp = await client.get("/prices-history", params=params)
                resp.raise_for_status()
                data = resp.json()
                history = data.get("history", [])
                all_prices.extend(history)
                if len(history) < 2:
                    break
                cursor = history[-1]["t"] + 60  # advance past last candle

        log.info("clob_fetched", market=market_id, n=len(all_prices))
        return all_prices

    async def _upsert_prices(
        self, session, market_id: str, raw_prices: list[dict]
    ) -> int:
        if not raw_prices:
            return 0

        rows = []
        for p in raw_prices:
            ts_raw = p["t"]
            ts = datetime.fromtimestamp(ts_raw, tz=UTC)
            ts_snapped = ts.replace(second=0, microsecond=0)
            price_val = str(p["p"])
            rows.append({
                "market_id": market_id,
                "ts": ts_snapped,
                "mid_price": price_val,
                "bid": None,
                "ask": None,
                "volume_minute": None,
            })

        # batch upsert in chunks
        chunk_size = 1000
        total = 0
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i : i + chunk_size]
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
        log.info("clob_upserted", market=market_id, n=total)
        return total
