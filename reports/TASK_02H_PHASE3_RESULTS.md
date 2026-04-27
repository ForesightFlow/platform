# Task 02H Phase 3 — Results

**Branch:** `task02h-phase3/polygonscan-logs`  
**Date:** 2026-04-27  
**Targets:** 2 indexer-failed FFIC fficd-003 markets

---

## Targets

| Label | Market ID | Volume | Resolved |
|---|---|---|---|
| US forces enter Iran by April 30 | `0x6d0e09d0f04572d9b1adad84703458b0297bc5603b69dccbde93147ee4443246` | $269M | YES — 2026-04-09 |
| US x Iran ceasefire by April 7 | `0x4c5701bcde0b8fb7d7f48c8e9d20245a6caa58c61a77f981fad98f2bfa0b1bc7` | $174M | YES — 2026-04-11 |

Both markets resolved **YES** (outcome_index=1).

---

## Approach History

### Attempt 1 — Polygonscan getLogs (Etherscan V2 API)
- **Strategy:** Fetch all CTF Exchange `OrderFilled` events in the market's block range, filter by YES-token ID in the non-indexed `data` field.
- **CTF Exchange:** `0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e`
- **OrderFilled topic0:** `0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6`
- **Block ranges:** Iran 84,365,653 – 85,287,221 (22 days); Ceasefire 84,627,342 – 85,373,621 (18 days)
- **Result:** Failed. The CTF Exchange processes ~300 OrderFilled events per Polygon block (entire exchange). With the minimum window forced to 200 blocks and 1,000 events per window, scraping Iran-Apr30 alone would require ~4,600 API calls at the 3 req/s free tier → ~5 hours. Script timed out (`httpx.ReadTimeout`) at 13.3%.

### Attempt 2 — Polygon RPC eth_getLogs (concurrent workers)
- **Strategy:** Use `eth_getLogs` on public Polygon RPC with 10 concurrent workers to parallelize the block range.
- **Tested endpoints:** `polygon-rpc.com` (disabled), `rpc.ankr.com` (requires key), `1rpc.io/matic` (works).
- **Result:** Infeasible. 1rpc.io returns **59,495 events per 200-block window** (vs. Polygonscan's truncated 1,000). Downloading all raw events for market 1 requires **~82 GB of data transfer** to filter for one YES token client-side. Not practical.

### Attempt 3 — The Graph subgraph (confirmed empty)
- `enrichedOrderFilleds` queried with YES token and NO token decimal IDs — returns `[]` for both markets.
- The indexer truly has no data; not a query error.

### Attempt 4 — CLOB API `/trades`
- Returns `{"error": "Unauthorized/Invalid api key"}` — requires Polymarket trader credentials.

### Attempt 5 — Polymarket data-api `/trades` + CLOB `/prices-history` ✅
- **Source:** `https://data-api.polymarket.com/trades?market=<conditionId>&limit=1000&offset=N`
- **Limitation:** Offset-based pagination caps at ~4,000 most-recent trades; time-range parameters (`startTs`/`endTs`) are ignored by the API.
- **Coverage:** The 4,000 available trades cover the last 1–2 days before resolution — i.e., the highest-activity period.
- **CLOB prices:** `GET /prices-history?market=<yesToken>&startTs=<created>&endTs=<batch>&fidelity=1` — 14-day batch windows (API enforces ≤15 days per request); gives full 1-minute price history from market creation to resolution.

---

## Results

| Metric | Iran Apr30 | Ceasefire Apr7 |
|---|---|---|
| CLOB price candles collected | 28,774 | 23,127 |
| Price date range | 2026-03-18 – 2026-04-09 | 2026-03-24 – 2026-04-11 |
| Price range (probability) | 0.05% – 64.5% | 0.05% – 99.2% |
| Trades collected | 4,000 | 4,000 |
| Trade date range | 2026-04-08 – 2026-04-09 | 2026-04-09 – 2026-04-11 |
| Notional (4K trades) | $9,780,639 | $10,680,849 |
| Avg price in trade window | 28.8% | 32.4% |
| Unique wallets | 2,595 | 2,261 |
| Total elapsed | 22.8s | 14.9s |
| Status | success | success |

---

## Notable Findings

### Iran Apr30 — dramatic price collapse before YES resolution
The CLOB price history shows the market opened at ~50% probability (market just created), peaked at **64.5%** in early trading, then fell steadily toward zero over the following weeks, before resolving **YES** on April 9 at 00:28 UTC. This is a counterintuitive pattern — the market was pricing the event as increasingly unlikely, yet it happened. A pre-resolution ILS analysis may reveal abnormal buying activity in the final hours.

### Ceasefire Apr7 — near-certainty price before resolution  
The price range reached **99.2%** probability before resolving YES on April 11. The market tracked the ceasefire expectation closely, suggesting the information was fairly reflected — or the price rise was the informed signal. The 4,000 available resolution-window trades average **32.4%** price (mid-resolution trading, before full certainty).

---

## Limitations

1. **Full trade history not accessible.** The `data-api.polymarket.com` endpoint only serves the ~4,000 most recent trades; the complete historical log (estimated 60K–300K trades per market over their full lifetime) is not available through any free public endpoint.

2. **CLOB prices are sufficient for ILS.** ILS = `(p_news − p_open) / (p_resolve − p_open)` requires only the price series, which we now have in full from `prices` table.

3. **`resolution_type = 'unclassifiable'`** for both markets. Standard FFIC eligibility requires `event_resolved`. Phase 4 re-audit will confirm whether the new data changes eligibility.

4. **Full wallet-level analysis requires more trades.** Features like `wallet_hhi_top10` and `time_to_news_top10` would need the full pre-news trade history, not just the resolution window.

---

## Phase 4 Target

Re-run `scripts/audit_ffic_eligibility.py` after completing Task 02H Phases 1–3.  
Expected outcome: both markets will still fail on `resolution_type = 'unclassifiable'` but will now have price data enabling a deadline-market ILS variant.

---

## Data Recovery Path (future work)

For the complete trade history: **Dune Analytics** query:
```sql
SELECT *
FROM polymarket_polygon.ctf_exchange_OrderFilled
WHERE maker_asset_id = '<YES_TOKEN_DECIMAL>'
   OR taker_asset_id = '<YES_TOKEN_DECIMAL>'
ORDER BY block_time;
```
This bypasses the indexer failure and filters by token ID server-side.
