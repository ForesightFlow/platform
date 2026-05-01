"""UMA Optimistic Oracle collector.

Recovers resolution data for Polymarket markets:
  - resolved_at (T_resolve)
  - resolution_outcome (0=NO, 1=YES)
  - resolution_evidence_url (from ancillaryData)
  - resolution_proposer

Primary: UMA subgraph on The Graph (requires FFLOW_THEGRAPH_API_KEY).
Fallback: direct Polygon JSON-RPC eth_getLogs on the UMA OOv2 contract
          (uses FFLOW_POLYGON_RPC_URL; needs an archive node for historical data).

NOTE (2026-04-27): Many Polymarket markets are resolved by a Polymarket admin
multisig, NOT via UMA. Those markets will never have resolution_evidence_url
populated by this collector. Check raw_metadata['resolvedBy'] to confirm.
"""

import re
from datetime import UTC, datetime

import httpx
from gql import Client, gql
from gql.transport.httpx import HTTPXAsyncTransport
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from fflow.collectors.base import BaseCollector, CollectorResult, RetryableHTTPClient
from fflow.config import settings
from fflow.db import AsyncSessionLocal
from fflow.log import get_logger
from fflow.models import Market

log = get_logger(__name__)


# Subgraph URL — key embedded in path so the Authorization header is a redundant safety net
def _uma_subgraph_url() -> str:
    key = settings.thegraph_api_key or ""
    return (
        f"https://gateway.thegraph.com/api/{key}/subgraphs/id/"
        "C8jHSA2ZEaJ8h9pK7XFMnNGnNsA4cNJgN6eHmJWjxBqv"
    )


# Polymarket UMA Adapter on Polygon (the "requester" in UMA terms)
_POLYMARKET_UMA_REQUESTER = "0xCB1822859cEF82Cd2Eb4E6276C7916e692995130".lower()

# UMA OptimisticOracleV2 on Polygon (verified active on Polygonscan)
_UMA_OOV2_ADDRESS = "0xeE3Afe347D5C74317041E2618C49534dAf887c24"

# Keccak-256 of Settle(address,address,address,bytes32,uint256,bytes,int256,uint256)
# Computed offline from the verified ABI (Polygonscan 2026-04-27)
_SETTLE_TOPIC = "0x7c0709b4680a05f8e24d4ff9144f17d3c7569f85ddfa075582d5c919d6e4cabd"

# Polymarket adapter address zero-padded to 32 bytes for topic[1] filter
_REQUESTER_TOPIC = "0x000000000000000000000000cb1822859cef82cd2eb4e6276c7916e692995130"

# Approximate Polygon block where Polymarket UMA activity began (~late 2022)
_RPC_FROM_BLOCK = 35_000_000
# Polygon genesis Unix timestamp (~May 30 2020) and avg block time for block estimation
_POLYGON_GENESIS_TS = 1_590_850_000
_POLYGON_BLOCK_TIME = 2.2  # seconds; conservative estimate

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

_URL_RE = re.compile(r"https?://[^\s,\"']+")


class UmaCollector(BaseCollector):
    name = "uma"

    async def run(
        self,
        target: str | None = None,
        market_id: str | None = None,
        all_resolved: bool = False,
        event_resolved: bool = False,
        min_volume: float = 50000.0,
        dry_run: bool = False,
    ) -> CollectorResult:
        mid = market_id or target
        label = mid or ("event_resolved" if event_resolved else "all_resolved")
        result = self._start_result(label)
        async with AsyncSessionLocal() as session:
            run_id = await self._record_run_start(session, result)
            try:
                if event_resolved:
                    market_ids = await self._get_event_resolved_market_ids(session, min_volume)
                elif all_resolved:
                    market_ids = await self._get_unresolved_market_ids(session)
                else:
                    market_ids = [mid] if mid else []

                log.info("uma_batch_start", n=len(market_ids), mode=label)
                total = 0
                for i, m_id in enumerate(market_ids):
                    n = await self._process_market(session, m_id, dry_run)
                    total += n
                    if (i + 1) % 100 == 0:
                        log.info("uma_batch_progress", done=i + 1, total=len(market_ids), found=total)

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

    async def _get_event_resolved_market_ids(self, session, min_volume: float) -> list[str]:
        rows = await session.execute(
            select(Market.id)
            .where(Market.resolution_type == "event_resolved")
            .where(Market.resolution_evidence_url.is_(None))
            .where(Market.volume_total_usdc >= min_volume)
        )
        return [r[0] for r in rows.all()]

    def _make_gql_client(self) -> Client:
        url = _uma_subgraph_url()
        headers = {"Accept": "application/json"}
        if settings.thegraph_api_key:
            headers["Authorization"] = f"Bearer {settings.thegraph_api_key}"
        transport = HTTPXAsyncTransport(url=url, headers=headers)
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
        # Try subgraph first; fall back to direct RPC on any failure
        try:
            result = await self._fetch_via_subgraph(market_id)
            if result is not None:
                return result
            log.debug("uma_subgraph_no_match", market=market_id)
        except Exception as exc:
            log.warning("uma_subgraph_unavailable", error=str(exc), fallback="rpc")

        return await self._fetch_via_rpc(market_id)

    async def _fetch_via_subgraph(self, market_id: str) -> dict | None:
        last_id = ""
        async with self._make_gql_client() as client:
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

    async def _fetch_via_rpc(self, market_id: str) -> dict | None:
        """Scan UMA OOv2 Settle events via eth_getLogs. Uses chunked pagination."""
        rpc_url = settings.polygon_rpc_url
        client = RetryableHTTPClient()

        # Estimate current block number
        try:
            resp = await client.post(
                rpc_url,
                json={"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1},
            )
            current_block = int(resp.json()["result"], 16)
        except Exception as exc:
            log.warning("uma_rpc_block_number_failed", error=str(exc))
            await client.aclose()
            return None

        chunk_size = 100_000
        from_block = _RPC_FROM_BLOCK

        log.info(
            "uma_rpc_scan_start",
            market=market_id,
            from_block=from_block,
            to_block=current_block,
            chunks=(current_block - from_block) // chunk_size + 1,
        )

        matched = None
        block = from_block
        while block <= current_block:
            to_block = min(block + chunk_size - 1, current_block)
            try:
                logs = await _eth_get_logs(
                    client, rpc_url, block, to_block
                )
            except Exception as exc:
                log.warning("uma_rpc_chunk_error", from_block=block, error=str(exc))
                block += chunk_size
                continue

            for entry in logs:
                try:
                    decoded = _decode_settle_log(entry)
                except Exception:
                    continue
                if market_id.lower() in decoded["ancillary_text"].lower():
                    matched = decoded
                    matched["_log"] = entry
                    break

            if matched:
                break
            block += chunk_size

        await client.aclose()

        if not matched:
            return None

        # Fetch block timestamp for resolved_at
        block_num = int(matched["_log"]["blockNumber"], 16)
        try:
            resp = await _rpc_call(
                rpc_url,
                "eth_getBlockByNumber",
                [hex(block_num), False],
            )
            block_ts = int(resp["result"]["timestamp"], 16)
        except Exception:
            # Fall back to estimation from block number
            block_ts = int(_POLYGON_GENESIS_TS + block_num * _POLYGON_BLOCK_TIME)

        topics = matched["_log"].get("topics", [])
        proposer = ("0x" + topics[2][26:]) if len(topics) > 2 else None

        return {
            "ancillaryData": matched["ancillary_hex"],
            "resolvedPrice": str(matched["resolved_price_raw"]),
            "resolveTimestamp": str(block_ts),
            "proposer": proposer,
            "settled": True,
        }


# ─── ABI helpers ──────────────────────────────────────────────────────────────

async def _eth_get_logs(
    client: RetryableHTTPClient,
    rpc_url: str,
    from_block: int,
    to_block: int,
) -> list[dict]:
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_getLogs",
        "params": [
            {
                "fromBlock": hex(from_block),
                "toBlock": hex(to_block),
                "address": _UMA_OOV2_ADDRESS,
                "topics": [_SETTLE_TOPIC, _REQUESTER_TOPIC],
            }
        ],
        "id": 1,
    }
    resp = await client.post(rpc_url, json=payload)
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"eth_getLogs error: {body['error']}")
    return body.get("result", [])


async def _rpc_call(rpc_url: str, method: str, params: list) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.post(
            rpc_url,
            json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
        )
        resp.raise_for_status()
        return resp.json()


def _decode_settle_log(log_entry: dict) -> dict:
    """Decode Settle event non-indexed data.

    ABI: (bytes32 identifier, uint256 timestamp, bytes ancillaryData,
          int256 resolvedPrice, uint256 finalFee)
    The first three params (requester, proposer, disputer) are indexed (in topics).
    """
    data_hex = log_entry.get("data", "0x")[2:]  # strip 0x
    raw = bytes.fromhex(data_hex)

    if len(raw) < 160:
        raise ValueError(f"Settle log data too short: {len(raw)} bytes")

    # Slot 2 (offset 64) = pointer to dynamic bytes (ancillaryData)
    anc_offset = int.from_bytes(raw[64:96], "big")

    # resolvedPrice at slot 3 (offset 96) — int256, signed
    resolved_price_raw = int.from_bytes(raw[96:128], "big", signed=True)

    # ancillaryData at the dynamic offset
    anc_len = int.from_bytes(raw[anc_offset : anc_offset + 32], "big")
    anc_bytes = raw[anc_offset + 32 : anc_offset + 32 + anc_len]
    anc_hex = "0x" + anc_bytes.hex()

    anc_text = anc_bytes.decode("utf-8", errors="replace")

    return {
        "ancillary_hex": anc_hex,
        "ancillary_text": anc_text,
        "resolved_price_raw": resolved_price_raw,
    }


# ─── Pure helpers ──────────────────────────────────────────────────────────────

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
