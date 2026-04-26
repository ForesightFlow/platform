# TASK_02B_DIAGNOSTICS — Subgraph & Backfill Window

Generated: 2026-04-26 · scripts/diagnose_subgraph.py + scripts/diagnose_backfill_window.py

---

## 1. Subgraph Diagnosis

### What we tested

Target market: `0xa772acec...` — "Will CS Herediano vs. Sporting FC end in a draw?"  
YES token (clobTokenIds[1]): `17668809327328219504003917947221347901585485692946225330492575863390915623843`  
NO token  (clobTokenIds[0]): `41321169567770421426036471643984318883315302322764113316537194267351270503902`

### Finding 1 — Auth works, subgraph is live

- API key loaded correctly (len=32, first 4 chars verified)  
- Subgraph URL: `https://gateway.thegraph.com/api/subgraphs/id/81Dm16JjuFSrqz813HysXoUPvzTwE7fsfPk2RTf66nyC`
- All introspection queries return HTTP 200 with signed `graph-attestation` headers
- Recent `enrichedOrderFilleds` exist (newest ts = 2026-04-26 09:25:44 UTC)

### Finding 2 — CRITICAL BUG in subgraph.py (wrong market ID format)

`fflow/collectors/subgraph.py`, `_fetch_trades()`:

```python
result = await client.execute(
    _TRADES_QUERY,
    variable_values={
        "market": market_id.lower(),   # ← BUG: passes condition ID (hex 0x...)
        ...
    },
)
```

The `enrichedOrderFilleds.market` filter expects the **YES token decimal ID** (e.g., `"17668809..."`).  
It receives the **condition ID** (e.g., `"0xa772acec..."`). These are completely different values.  
The subgraph will always return 0 rows because no Orderbook has the hex condition ID as its `id`.

**Fix**: pass `yes_token` (already resolved by `_resolve_yes_token`) instead of `market_id.lower()`.

### Finding 3 — The test market (football) genuinely has no CLOB trades

Even when queried with the correct YES token decimal:
- `orderbook(id: yes_token)` → `null` (no Orderbook entity)
- `enrichedOrderFilleds(where: { market: yes_token })` → 0 rows
- `orderFilledEvents(where: { makerAssetId: yes_token })` → 0 rows
- `orderFilledEvents(where: { takerAssetId: yes_token })` → 0 rows

Costa Rican football markets are micro-markets that resolve via data feeds (ligamx.net, unafut.com) and have no CLOB order book activity. The subgraph only indexes Polymarket CLOB fills — not AMM or direct-resolution markets.

**This means**: even after fixing the market ID bug, the 599 current resolved markets (football, weather, crypto prices) will return 0 trades. The fix is necessary but not sufficient — we also need to target markets that actually trade on the CLOB (see Section 2).

### Finding 4 — orderFilledEvents field format (for reference)

From the unfiltered sample:
```json
{
  "makerAssetId": "0",                              ← "0" = USDC collateral
  "takerAssetId": "237811712815390072...",           ← decimal YES token ID
  "makerAmountFilled": "947200",                    ← raw units (÷ 1e6 = USDC)
  "takerAmountFilled": "2960000",                   ← raw units (÷ 1e6 = shares)
  "maker": { "id": "0x94100dca..." },
  "taker": { "id": "0x927f7694..." }
}
```

`takerAssetId = yes_token_decimal` → taker receives YES shares → BUY trade.  
`makerAssetId = yes_token_decimal` → maker delivers YES shares → SELL trade.  
This is an alternative filter path if `enrichedOrderFilleds` proves problematic.

### Summary

| Issue | Status | Fix |
|---|---|---|
| Auth / connectivity | ✅ Working | — |
| Wrong entity name (`orderFilleds`) | ✅ Already fixed | Used `enrichedOrderFilleds` |
| Wrong market ID format (condition ID vs token ID) | 🔴 Bug present | Pass `yes_token` not `market_id.lower()` |
| Football/weather markets have 0 CLOB trades | Expected behavior | Target high-volume geopolitical markets |

---

## 2. Backfill Window Diagnosis

### Finding A — resolved_at comes from Gamma's closedTime (not UMA)

The UMA collector ran exactly once and **failed** (auth error, 1 second runtime, 0 written):
```
started: 2026-04-26 07:31:07  finished: 2026-04-26 07:31:08
status: failed
error: "auth error: missing authorization header"
```

All 599 `resolved_at` values match `raw_metadata['closedTime']` **to the second** (verified: 599/599 markets, 0-second diff). The UMA collector never ran successfully.

The current `fflow/collectors/gamma.py` does **not** map `closedTime → resolved_at` (verified in code):
```python
rows.append({
    "id": condition_id,
    "question": m.get("question", ""),
    "created_at_chain": _parse_dt(m.get("createdAt") or m.get("startDate")),
    "end_date": _parse_dt(m.get("endDate")),
    # resolved_at NOT PRESENT
    "raw_metadata": m,
    ...
})
```

**Root cause**: An earlier version of gamma.py mapped `closedTime → resolved_at`. That version ran once (explaining the 599 records), then the mapping was removed. The ON CONFLICT DO UPDATE preserves existing `resolved_at` values, so they survived subsequent Gamma runs.

**Consequence**: No new resolved markets will accumulate in the DB unless gamma.py is fixed to re-add the mapping, or UMA collector is fixed (it needs The Graph auth — same API key, but UMA subgraph URL is different).

### Finding B — Why the window is only "last 2 hours"

The 599 resolved markets all have `closedTime` between 2026-04-26 06:28 and 08:10. This is NOT a Gamma API bug — it's because the earlier gamma.py that mapped `closedTime` ran exactly once, around 07:30–07:31 today. It fetched markets ordered by `createdAt DESC` (most recently created first), which happens to pick up only the most recently resolved markets at that moment.

### Finding C — gamma.py does NOT use `closed=true` and does NOT paginate by resolution date

Current `_paginate()` parameters:
```python
params = {
    "limit": 500,
    "offset": offset,
    "order": "createdAt",
    "ascending": "false",
}
if tag:
    params["tag"] = tag
# NO: closed=true, end_date_min, end_date_max, closedTime ordering
```

The pagination stop condition is `createdAt < since`, which is a creation date filter, not a resolution date filter. To get 2 years of resolved markets, you need `closed=true + end_date_min/end_date_max` pagination.

### Finding D — Gamma API DOES support historical date-range queries

Test confirmed: `GET /markets?closed=true&end_date_min=2024-08-01&end_date_max=2024-08-31` returns genuine August 2024 markets:
```
[2024-08-31] Will Donald Trump say "crypto" or "Bitcoin" during Pennsylvania rally?
[2024-08-29] Will Elon tweet between 110-119 times?
[2024-08-30] Will Donald Trump say "Zuckerberg" or "Zuck" during Pennsylvania rally
[2024-08-25] Trump posts between 5 and 9 times on X?
```

**This is the mechanism for historical backfill.** By sweeping `end_date_min/end_date_max` in 1-month windows from 2020 to present, we can retrieve all historical resolved markets.

| Parameter | Behavior |
|---|---|
| `closed=true + end_date_min/max` | ✅ Works — filters by market end_date (resolution window) |
| `closed=true + start_date_min/max` | Works but selects by creation date, not resolution |
| `closed=true + closed_time_min/max` | ⚠️ Broken — returns markets from 2020 for any date range |
| `closed=true + order=closedTime` | ✅ Works — orders by resolution date (usable for pagination) |
| `closed=true + order=volume + ascending=false` | Returns, but dominated by crypto micro-markets ($100 vol) |
| `q=iran` or `tag=iran` | 🔴 No-op — server ignores filter, returns default set |

---

## 3. Tags Assessment

### Finding — Gamma tags are non-functional for closed markets

All `q=` (text search) and `tag=` parameter tests for `closed=true` markets returned the **same identical response** (10 markets from 2020–2021), regardless of the tag value passed. Tag filtering does not work server-side for historical closed markets.

From the DB: `raw_metadata.tags` is either absent or stored in a non-array format:
```
Top 30 tags (from raw_metadata.tags array): → No array tags found.
```

All 30 randomly sampled geopolitical/political markets show `(no tag)` in the tags field. The `category_fflow` classification (which IS informative) is derived entirely by our regex taxonomy classifier from the `question` text and `category_raw` (event title) field — not from Gamma tags.

### Finding — Category classifier works; sample has right markets, wrong resolution window

30 random `military_geopolitics` / `politics_intl` markets from the DB include:
```
Will Iran strike Spain by April 30, 2026?
US x Iran permanent peace deal by May 31, 2026?
Will Oman join the Abraham Accords before 2027?
U.S. recognizes Russian sovereignty over Crimea before 2027?
Will Donald Trump visit Taiwan in 2026?
```

These are exactly the market types we want. They exist in the DB (3,363 total in this category). They are NOT in the 599 resolved markets because those markets haven't resolved yet (or resolved before the single gamma.py run that had closedTime mapping).

**Tags are useless; category_fflow classifier is the right approach and is already working.**

---

## 4. Recommended Fixes (Priority Order)

### Fix 1 — subgraph.py: pass yes_token as market filter (CRITICAL)

File: `fflow/collectors/subgraph.py`, `_fetch_trades()`, line with `"market": market_id.lower()`

Change:
```python
"market": market_id.lower(),    # WRONG: condition ID hex
```
To:
```python
"market": yes_token,            # CORRECT: YES token decimal ID
```

`yes_token` is already available in `_fetch_trades` because it's passed as a parameter. This is a 1-line fix.

### Fix 2 — gamma.py: re-add closedTime → resolved_at mapping (HIGH)

File: `fflow/collectors/gamma.py`, `_upsert_markets()`

Add to the INSERT rows dict:
```python
"resolved_at": _parse_dt(m.get("closedTime")),
"resolution_outcome": _gamma_outcome(m),   # from outcomePrices
```

And to `on_conflict_do_update` set_:
```python
"resolved_at": insert(Market).excluded.resolved_at,
```

Note: `outcomePrices: ["1","0"]` = YES resolved; `["0","1"]` = NO resolved. Gamma provides this in the market data.

### Fix 3 — gamma.py: add historical backfill mode (HIGH)

Add `--closed` / `--end-date-min` / `--end-date-max` CLI options to `fflow collect gamma` that use the working Gamma API parameters for historical sweeps. Sweep in 1-month windows from 2020-01 to present to populate 5+ years of resolved markets with volume > $10K.

### Fix 4 — subgraph.py: target high-volume markets (MEDIUM)

The subgraph only has CLOB trades. Markets with `volume_total_usdc > $50K` are almost always CLOB-traded. Before running the subgraph collector, pre-filter by `volume_total_usdc`. The 599 current resolved markets all have essentially 0 volume ($0–$200 range based on the `vol=$100` pattern seen in the data).

### Fix 5 — UMA collector auth (LOW — defer)

The UMA subgraph at `C8jHSA2ZEaJ8h9pK7XFMnNGnNsA4cNJgN6eHmJWjxBqv` requires the same The Graph API key as the Polymarket subgraph. The auth header format is identical. However, with Fix 2 and Fix 3 implemented, UMA is no longer needed for `resolved_at` or `resolution_outcome`. UMA is still valuable for `resolution_evidence_url` but can be deferred.

---

## Summary Table

| Root cause | Impact | Fix | Priority |
|---|---|---|---|
| `market_id.lower()` instead of `yes_token` in subgraph query | All CLOB trade queries return 0 rows | 1-line fix in subgraph.py | CRITICAL |
| gamma.py doesn't map closedTime → resolved_at | No new resolved markets accumulate in DB | Add field to gamma upsert | HIGH |
| gamma.py has no historical backfill mode | Only last 2h of closures in DB | Add `closed=true + end_date` pagination | HIGH |
| Current resolved sample = sports/weather/crypto with no CLOB | 0 trades, 0 T_news from news outlets | Backfill 2 years of political/high-volume markets | HIGH |
| Gamma tags non-functional for closed markets | Cannot filter by tag | Ignore tags; use category_fflow classifier | Already done |
| UMA collector fails (auth) | No resolution_evidence_url from UMA | Fix auth OR extract from Gamma closedTime | LOW |
