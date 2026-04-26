"""Gamma API collector — market metadata.

API note: the Gamma API does not return a 'tags' field on individual markets.
Category information is derived from the event title (events[0].title) and
the filter tag used during collection, stored together in category_raw.
clobTokenIds is a JSON-encoded string and must be parsed with json.loads().
"""

import json
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert

from fflow.collectors.base import BaseCollector, CollectorResult, RetryableHTTPClient
from fflow.config import settings
from fflow.db import AsyncSessionLocal
from fflow.log import get_logger
from fflow.models import Market

log = get_logger(__name__)

_PAGE_SIZE = 500


class GammaCollector(BaseCollector):
    name = "gamma"

    async def run(
        self,
        target: str | None = None,
        since: datetime | None = None,
        categories: list[str] | None = None,
        dry_run: bool = False,
    ) -> CollectorResult:
        result = self._start_result(target)
        async with AsyncSessionLocal() as session:
            run_id = await self._record_run_start(session, result)
            try:
                markets = await self._fetch_markets(since=since, categories=categories)
                if not dry_run:
                    result.n_written = await self._upsert_markets(session, markets)
                else:
                    result.n_written = len(markets)
                result.status = "success"
            except Exception as exc:
                result.status = "failed"
                result.error = str(exc)
                log.error("gamma_collector_failed", error=str(exc))
                raise
            finally:
                result.finished_at = datetime.now(UTC)
                await self._record_run_end(session, run_id, result)
        return result

    async def _fetch_markets(
        self,
        since: datetime | None = None,
        categories: list[str] | None = None,
    ) -> list[dict]:
        all_markets: list[dict] = []
        tags = categories or []

        async with RetryableHTTPClient(base_url=settings.gamma_api_url) as client:
            if tags:
                for tag in tags:
                    markets = await self._paginate(client, tag=tag, since=since)
                    # dedup by conditionId
                    seen = {m["conditionId"] for m in all_markets}
                    all_markets.extend(m for m in markets if m["conditionId"] not in seen)
            else:
                all_markets = await self._paginate(client, tag=None, since=since)

        log.info("gamma_fetched", n=len(all_markets))
        return all_markets

    async def _paginate(
        self,
        client: RetryableHTTPClient,
        tag: str | None,
        since: datetime | None,
    ) -> list[dict]:
        results = []
        offset = 0
        while True:
            params: dict = {
                "limit": _PAGE_SIZE,
                "offset": offset,
                "order": "createdAt",
                "ascending": "false",
            }
            if tag:
                params["tag"] = tag

            resp = await client.get("/markets", params=params)
            resp.raise_for_status()
            page: list[dict] = resp.json()
            if not page:
                break

            for market in page:
                created_raw = market.get("createdAt", "")
                if since and created_raw:
                    created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                    if created < since.replace(tzinfo=UTC):
                        return results
                results.append(market)

            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

        return results

    async def _upsert_markets(self, session, raw_markets: list[dict]) -> int:
        if not raw_markets:
            return 0

        now = datetime.now(UTC)
        seen_ids: set[str] = set()
        rows = []
        for m in raw_markets:
            condition_id = m.get("conditionId") or m.get("id")
            if not condition_id or condition_id in seen_ids:
                continue
            seen_ids.add(condition_id)

            event = (m.get("events") or [{}])[0]
            event_title = event.get("title", "")
            category_raw = event_title or m.get("groupItemTitle", "")

            rows.append({
                "id": condition_id,
                "question": m.get("question", ""),
                "description": m.get("description"),
                "category_raw": category_raw,
                "category_fflow": None,
                "created_at_chain": _parse_dt(m.get("createdAt") or m.get("startDate")),
                "end_date": _parse_dt(m.get("endDate")),
                "volume_total_usdc": m.get("volume"),
                "liquidity_usdc": m.get("liquidity"),
                "slug": m.get("slug"),
                "raw_metadata": m,
                "last_refreshed_at": now,
            })

        # asyncpg limit: 32767 params per query; with 12 cols per row → max ~2730 rows/batch
        _BATCH = 2000
        for i in range(0, len(rows), _BATCH):
            batch = rows[i : i + _BATCH]
            stmt = (
                insert(Market)
                .values(batch)
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "question": insert(Market).excluded.question,
                        "description": insert(Market).excluded.description,
                        "category_raw": insert(Market).excluded.category_raw,
                        "created_at_chain": insert(Market).excluded.created_at_chain,
                        "end_date": insert(Market).excluded.end_date,
                        "volume_total_usdc": insert(Market).excluded.volume_total_usdc,
                        "liquidity_usdc": insert(Market).excluded.liquidity_usdc,
                        "slug": insert(Market).excluded.slug,
                        "raw_metadata": insert(Market).excluded.raw_metadata,
                        "last_refreshed_at": insert(Market).excluded.last_refreshed_at,
                    },
                )
            )
            await session.execute(stmt)
        await session.commit()
        log.info("gamma_upserted", n=len(rows))
        return len(rows)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
