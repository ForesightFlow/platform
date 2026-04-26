"""UMA Optimistic Oracle collector.

Recovers resolution data for Polymarket markets:
  - resolved_at (T_resolve)
  - resolution_outcome (0=NO, 1=YES)
  - resolution_evidence_url (from ancillaryData)
  - resolution_proposer

Approach: UMA subgraph on The Graph (simpler than direct RPC for Task 01).
TODO Task 02: switch to direct OptimisticOracleV2 RPC event decoding for lower latency.

UMA subgraph: https://thegraph.com/explorer/subgraphs/C8jHSA2ZEaJ8h9pK7XFMnNGnNsA4cNJgN6eHmJWjxBqv
"""

import re
from datetime import UTC, datetime

from gql import Client, gql
from gql.transport.httpx import HTTPXAsyncTransport
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from fflow.collectors.base import BaseCollector, CollectorResult
from fflow.config import settings
from fflow.db import AsyncSessionLocal
from fflow.log import get_logger
from fflow.models import Market

log = get_logger(__name__)

_UMA_SUBGRAPH_URL = (
    "https://gateway.thegraph.com/api/subgraphs/id/"
    "C8jHSA2ZEaJ8h9pK7XFMnNGnNsA4cNJgN6eHmJWjxBqv"
)

_REQUESTS_QUERY = gql("""
query Requests($requester: String!, $lastId: String!, $first: Int!) {
  requestPrices(
    where: { requester: $requester, id_gt: $lastId }
    first: $first
    orderBy: id
    orderDirection: asc
  ) {
    id
    identifier
    ancillaryData
    requester
    proposer
    proposedPrice
    resolvedPrice
    requestTimestamp
    resolveTimestamp
    settled
  }
}
""")

# Polymarket UMA Adapter on Polygon (requests are made by this contract)
_POLYMARKET_UMA_REQUESTER = "0xCB1822859cEF82Cd2Eb4E6276C7916e692995130".lower()
_URL_RE = re.compile(r"https?://[^\s,\"']+")


class UmaCollector(BaseCollector):
    name = "uma"

    async def run(
        self,
        target: str | None = None,
        market_id: str | None = None,
        all_resolved: bool = False,
        dry_run: bool = False,
    ) -> CollectorResult:
        mid = market_id or target
        result = self._start_result(mid or "all_resolved")
        async with AsyncSessionLocal() as session:
            run_id = await self._record_run_start(session, result)
            try:
                if all_resolved:
                    market_ids = await self._get_unresolved_market_ids(session)
                else:
                    market_ids = [mid] if mid else []

                total = 0
                for m_id in market_ids:
                    n = await self._process_market(session, m_id, dry_run)
                    total += n

                result.n_written = total
                result.status = "success"
            except Exception as exc:
                result.status = "failed"
                result.error = str(exc)
                log.error("uma_collector_failed", error=str(exc))
                raise
            finally:
                result.finished_at = datetime.now(UTC)
                await self._record_run_end(session, run_id, result)
        return result

    async def _get_unresolved_market_ids(self, session) -> list[str]:
        rows = await session.execute(
            select(Market.id).where(Market.resolved_at.is_(None))
        )
        return [r[0] for r in rows.all()]

    def _make_client(self) -> Client:
        headers = {"Accept": "application/json"}
        if settings.thegraph_api_key:
            headers["Authorization"] = f"Bearer {settings.thegraph_api_key}"
        transport = HTTPXAsyncTransport(url=_UMA_SUBGRAPH_URL, headers=headers)
        return Client(transport=transport, fetch_schema_from_transport=False)

    async def _process_market(self, session, market_id: str, dry_run: bool) -> int:
        resolution = await self._fetch_resolution(market_id)
        if not resolution:
            return 0
        if dry_run:
            return 1

        resolved_price = resolution.get("resolvedPrice")
        outcome = _price_to_outcome(resolved_price)

        ancillary_raw = resolution.get("ancillaryData", "")
        evidence_url = _extract_evidence_url(ancillary_raw)

        resolve_ts_raw = resolution.get("resolveTimestamp")
        resolved_at = (
            datetime.fromtimestamp(int(resolve_ts_raw), tz=UTC) if resolve_ts_raw else None
        )

        stmt = (
            insert(Market)
            .values(
                id=market_id,
                question="",
                raw_metadata={},
                last_refreshed_at=datetime.now(UTC),
                resolved_at=resolved_at,
                resolution_outcome=outcome,
                resolution_evidence_url=evidence_url,
                resolution_proposer=(resolution.get("proposer") or "").lower() or None,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "resolved_at": insert(Market).excluded.resolved_at,
                    "resolution_outcome": insert(Market).excluded.resolution_outcome,
                    "resolution_evidence_url": insert(Market).excluded.resolution_evidence_url,
                    "resolution_proposer": insert(Market).excluded.resolution_proposer,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()
        log.info("uma_resolved", market=market_id, outcome=outcome)
        return 1

    async def _fetch_resolution(self, market_id: str) -> dict | None:
        # The UMA subgraph indexes by requester (Polymarket adapter) and ancillaryData
        # We query all requests from the Polymarket adapter and match by market_id in ancillaryData
        last_id = ""
        async with self._make_client() as client:
            while True:
                result = await client.execute(
                    _REQUESTS_QUERY,
                    variable_values={
                        "requester": _POLYMARKET_UMA_REQUESTER,
                        "lastId": last_id,
                        "first": 1000,
                    },
                )
                page = result.get("requestPrices", [])
                if not page:
                    break

                for req in page:
                    anc = req.get("ancillaryData", "")
                    anc_decoded = _decode_ancillary(anc)
                    if market_id.lower() in anc_decoded.lower() and req.get("settled"):
                        return req

                if len(page) < 1000:
                    break
                last_id = page[-1]["id"]

        return None


def _decode_ancillary(hex_data: str) -> str:
    if not hex_data:
        return ""
    try:
        cleaned = hex_data.replace("0x", "").replace(" ", "")
        return bytes.fromhex(cleaned).decode("utf-8", errors="replace")
    except Exception:
        return hex_data


def _extract_evidence_url(ancillary_raw: str) -> str | None:
    text = _decode_ancillary(ancillary_raw)
    urls = _URL_RE.findall(text)
    non_polymarket = [u for u in urls if "polymarket.com" not in u]
    return non_polymarket[0] if non_polymarket else (urls[0] if urls else None)


def _price_to_outcome(price_str: str | None) -> int | None:
    if price_str is None:
        return None
    try:
        val = float(price_str) / 1e18
        if val >= 0.5:
            return 1
        return 0
    except (ValueError, TypeError):
        return None
