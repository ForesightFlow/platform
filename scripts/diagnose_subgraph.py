"""Subgraph diagnostic — raw HTTP queries, no gql wrapper.

Diagnoses why enrichedOrderFilleds returns 0 trades for resolved markets.

Usage:
    uv run python scripts/diagnose_subgraph.py
    uv run python scripts/diagnose_subgraph.py --market 0xABCD...
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fflow.config import settings
from fflow.log import configure_logging

configure_logging(log_level="WARNING")

# Default: a market for which Tier 1 found a T_news (Costa Rican football)
DEFAULT_MARKET = "0xa772acec556629f76d8bca3708761f05f7af3d66cd182411f5523f805a37abb1"

SEP = "─" * 70


def _hdr(title: str) -> None:
    print(f"\n{SEP}\n{title}\n{SEP}")


def _key_preview(k: str | None) -> str:
    if not k:
        return "(not set)"
    return k[:4] + "..." + f" (len={len(k)})"


async def raw_post(url: str, payload: dict, headers: dict | None = None) -> dict:
    import httpx

    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if settings.thegraph_api_key:
        h["Authorization"] = f"Bearer {settings.thegraph_api_key}"
    if headers:
        h.update(headers)

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=h)

    print(f"  HTTP {resp.status_code}")
    for k, v in resp.headers.items():
        if any(x in k.lower() for x in ["rate", "error", "graph", "retry", "remain"]):
            print(f"  {k}: {v}")
    return resp.json()


async def step1_env(url: str) -> None:
    _hdr("STEP 1 — Environment check")
    key = settings.thegraph_api_key
    print(f"  FFLOW_THEGRAPH_API_KEY : {_key_preview(key)}")
    print(f"  settings.subgraph_url  : {url}")


async def step2_introspection(url: str) -> list[str]:
    _hdr("STEP 2 — Schema introspection (query type fields)")
    payload = {"query": "{ __schema { queryType { fields { name } } } }"}
    data = await raw_post(url, payload)
    if "errors" in data:
        print(f"  Introspection errors: {data['errors']}")
        return []
    fields = [f["name"] for f in data["data"]["__schema"]["queryType"]["fields"]]
    print(f"  Available query root fields ({len(fields)}):")
    for f in sorted(fields):
        print(f"    {f}")
    return fields


async def step3_find_trade_entities(url: str, schema_fields: list[str]) -> list[str]:
    _hdr("STEP 3 — Trade-like entity candidates")
    candidates_keywords = [
        "fill", "trade", "order", "match", "swap", "transaction",
        "orderbook", "enrich",
    ]
    found = [
        f for f in schema_fields
        if any(kw in f.lower() for kw in candidates_keywords)
    ]
    print(f"  Trade-like entities found: {found}")
    return found


async def step4_resolve_token(market_id: str) -> tuple[str, str]:
    _hdr("STEP 4 — Resolve YES/NO token IDs from DB")
    from fflow.db import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as session:
        r = await session.execute(
            text("""
                SELECT
                    raw_metadata->>'clobTokenIds' AS token_ids,
                    raw_metadata->>'closedTime' AS closed_time,
                    raw_metadata->>'active' AS active,
                    raw_metadata->>'closed' AS closed_flag,
                    resolved_at,
                    question
                FROM markets
                WHERE id = :mid
            """),
            {"mid": market_id},
        )
        row = r.fetchone()

    if not row:
        print(f"  Market {market_id} NOT found in DB")
        return "", ""

    print(f"  question    : {row.question[:80]}")
    print(f"  closed_time : {row.closed_time}")
    print(f"  active      : {row.active}")
    print(f"  closed_flag : {row.closed_flag}")
    print(f"  resolved_at : {row.resolved_at}")
    raw_ids = row.token_ids
    print(f"  clobTokenIds raw: {raw_ids}")

    token_ids = json.loads(raw_ids) if raw_ids else []
    no_token = str(token_ids[0]) if len(token_ids) > 0 else ""
    yes_token = str(token_ids[1]) if len(token_ids) > 1 else ""
    print(f"  NO  token (index 0): {no_token}")
    print(f"  YES token (index 1): {yes_token}")
    print(f"  (subgraph.py passes: yes_token = '{yes_token[:30]}...')")
    return yes_token, no_token


async def step5_query_orderbook(url: str, yes_token: str, no_token: str) -> None:
    _hdr("STEP 5 — Does this token have an Orderbook entry in the subgraph?")
    for label, token in [("YES", yes_token), ("NO", no_token)]:
        if not token:
            continue
        payload = {
            "query": f"""{{
  orderbook(id: "{token}") {{
    id
    tradesQuantity
    buysQuantity
    sellsQuantity
    collateralVolume
    lastActiveDay
  }}
}}"""
        }
        print(f"\n  Orderbook for {label} token ({token[:20]}...):")
        data = await raw_post(url, payload)
        if "errors" in data:
            print(f"    Errors: {data['errors']}")
        else:
            ob = data.get("data", {}).get("orderbook")
            if ob:
                print(f"    id              : {ob['id'][:30]}...")
                print(f"    tradesQuantity  : {ob['tradesQuantity']}")
                print(f"    buysQuantity    : {ob['buysQuantity']}")
                print(f"    sellsQuantity   : {ob['sellsQuantity']}")
                print(f"    collateralVolume: {ob['collateralVolume']}")
                print(f"    lastActiveDay   : {ob['lastActiveDay']}")
            else:
                print(f"    → Orderbook NOT found for {label} token")


async def step6_query_enriched(url: str, yes_token: str, no_token: str) -> None:
    _hdr("STEP 6 — enrichedOrderFilleds with various market ID formats")

    formats_to_try = [
        ("YES token decimal", yes_token),
        ("NO token decimal", no_token),
        ("market ID without 0x (lower)", None),  # filled below
        ("market ID raw", None),
    ]

    for label, token in [("YES decimal", yes_token), ("NO decimal", no_token)]:
        if not token:
            continue
        payload = {
            "query": f"""{{
  enrichedOrderFilleds(
    first: 5
    orderBy: id
    orderDirection: asc
    where: {{ market: "{token}" }}
  ) {{
    id
    timestamp
    maker {{ id }}
    taker {{ id }}
    market {{ id }}
    side
    size
    price
  }}
}}"""
        }
        print(f"\n  enrichedOrderFilleds where market = {label} ({token[:30]}...):")
        data = await raw_post(url, payload)
        if "errors" in data:
            print(f"    Errors: {json.dumps(data['errors'], indent=4)}")
        else:
            rows = data.get("data", {}).get("enrichedOrderFilleds", [])
            print(f"    → {len(rows)} rows returned")
            for r in rows[:3]:
                print(f"    {r}")


async def step7_query_orderfilledevent(url: str, yes_token: str) -> None:
    _hdr("STEP 7 — orderFilledEvents (alternative entity)")
    payload = {
        "query": f"""{{
  orderFilledEvents(
    first: 5
    orderBy: id
    orderDirection: asc
  ) {{
    id
    timestamp
    transactionHash
    maker {{ id }}
    taker {{ id }}
    makerAssetId
    takerAssetId
    makerAmountFilled
    takerAmountFilled
  }}
}}"""
    }
    print("  orderFilledEvents (first 5, unfiltered — checking field format):")
    data = await raw_post(url, payload)
    if "errors" in data:
        print(f"  Errors: {data['errors']}")
    else:
        rows = data.get("data", {}).get("orderFilledEvents", [])
        print(f"  → {len(rows)} rows returned")
        for r in rows[:2]:
            print(f"  {json.dumps(r, indent=4)}")

    # Now try filtering by makerAssetId or takerAssetId = yes_token
    print(f"\n  orderFilledEvents where makerAssetId = YES token:")
    payload2 = {
        "query": f"""{{
  orderFilledEvents(
    first: 5
    where: {{ makerAssetId: "{yes_token}" }}
    orderBy: id
    orderDirection: asc
  ) {{
    id
    timestamp
    makerAssetId
    takerAssetId
    maker {{ id }}
    taker {{ id }}
  }}
}}"""
    }
    data2 = await raw_post(url, payload2)
    if "errors" in data2:
        print(f"  Errors: {data2['errors']}")
    else:
        rows2 = data2.get("data", {}).get("orderFilledEvents", [])
        print(f"  → {len(rows2)} rows for makerAssetId = YES token")

    payload3 = {
        "query": f"""{{
  orderFilledEvents(
    first: 5
    where: {{ takerAssetId: "{yes_token}" }}
    orderBy: id
    orderDirection: asc
  ) {{
    id
    timestamp
    makerAssetId
    takerAssetId
    maker {{ id }}
    taker {{ id }}
  }}
}}"""
    }
    data3 = await raw_post(url, payload3)
    if "errors" in data3:
        print(f"  Errors: {data3['errors']}")
    else:
        rows3 = data3.get("data", {}).get("orderFilledEvents", [])
        print(f"  → {len(rows3)} rows for takerAssetId = YES token")


async def step8_broad_sample(url: str) -> None:
    _hdr("STEP 8 — Broad sanity check: any enrichedOrderFilleds in the subgraph?")
    payload = {
        "query": """
{
  enrichedOrderFilleds(first: 3, orderBy: timestamp, orderDirection: desc) {
    id
    timestamp
    market { id tradesQuantity }
    side
    size
    price
    maker { id }
    taker { id }
  }
}"""
    }
    data = await raw_post(url, payload)
    if "errors" in data:
        print(f"  Errors: {data['errors']}")
    else:
        rows = data.get("data", {}).get("enrichedOrderFilleds", [])
        print(f"  Most recent enrichedOrderFilleds (newest first): {len(rows)} rows")
        for r in rows:
            import datetime
            ts = int(r["timestamp"])
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
            print(f"    ts={dt}  market={r['market']['id'][:20]}...  "
                  f"tradesQ={r['market']['tradesQuantity']}  side={r['side']}  "
                  f"price={r['price']}  maker={r['maker']['id'][:12]}...")


async def step9_subgraph_code_audit() -> None:
    _hdr("STEP 9 — subgraph.py code audit (what it sends vs what schema expects)")
    code_path = ROOT / "fflow" / "collectors" / "subgraph.py"
    src = code_path.read_text()
    # extract query block
    start = src.find("_TRADES_QUERY = gql")
    end = src.find('""")', start) + 4
    print("  Current _TRADES_QUERY:")
    print(src[start:end])
    # show how market variable is set
    idx = src.find('"market": market_id.lower()')
    if idx == -1:
        idx = src.find('"market"')
    ctx = src[max(0, idx - 100):idx + 200]
    print("\n  How 'market' variable is built:")
    print(ctx)


async def main(market_id: str) -> None:
    url = settings.subgraph_url

    await step1_env(url)
    schema_fields = await step2_introspection(url)
    await step3_find_trade_entities(url, schema_fields)
    yes_token, no_token = await step4_resolve_token(market_id)
    if yes_token:
        await step5_query_orderbook(url, yes_token, no_token)
        await step6_query_enriched(url, yes_token, no_token)
        await step7_query_orderfilledevent(url, yes_token)
    await step8_broad_sample(url)
    await step9_subgraph_code_audit()

    print(f"\n{SEP}\nDone. Review findings above.\n{SEP}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", default=DEFAULT_MARKET, help="Market condition ID")
    args = parser.parse_args()
    asyncio.run(main(args.market))
