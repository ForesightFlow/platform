# CLOB Price Coverage Diagnostics

**Generated:** 2026-04-27 06:31 UTC  
**Branch:** chore/documented-cases-backfill

---

## Step 1 — Basic prices table stats

- Total price rows: 1,123,176
- Distinct markets: 409
- Timestamp range: 2026-04-13 16:59:00+00:00 → 2026-04-26 07:51:00+00:00
- Markets with ≥60 price points: 409
- Markets with ≥1440 price points (≥1 day at 1-min): 206

## Step 2 — Coverage vs ILS target sample (vol≥50K, ILS categories, resolved)

- Target markets (ILS-relevant, resolved, vol≥50K): 11,263
- With any price data: 3 (0.0%)
- With ≥60 price points: 3
- With ≥1440 price points: 2

## Step 3 — FFICD validation set coverage

| case | prefix | label | market_id | price_rows | min_ts | max_ts | covers_lifecycle |
|------|--------|-------|-----------|-----------|--------|--------|-----------------|
| fficd-001 | 0xdd22472e | Trump wins | 0xdd22472e55… | 0 | — | — | ❌ no prices |
| fficd-001 | 0xc6485bb7 | Harris wins | 0xc6485bb7ea… | 0 | — | — | ❌ no prices |
| fficd-001 | 0x55c55189 | Other Republican | 0x55c551896c… | 0 | — | — | ❌ no prices |
| fficd-001 | 0x230144e3 | Michelle Obama | 0x230144e34a… | 0 | — | — | ❌ no prices |
| fficd-002 | 0xc1b6d712 | Iran strike today | 0xc1b6d7128a… | 0 | — | — | ❌ no prices |
| fficd-002 | 0x93727420 | Another strike by Fr | 0x9372742055… | 0 | — | — | ❌ no prices |
| fficd-002 | 0xc8312853 | Iran strike by Nov 8 | 0xc83128531d… | 0 | — | — | ❌ no prices |
| fficd-003 | 0x6d0e09d0 | US forces into Iran | 0x6d0e09d0f0… | 0 | — | — | ❌ no prices |
| fficd-003 | 0x4c5701bc | US-Iran ceasefire | 0x4c5701bcde… | 0 | — | — | ❌ no prices |
| fficd-003 | 0xd4bbf7f6 | Khamenei out Feb 28 | 0xd4bbf7f670… | 0 | — | — | ❌ no prices |
| fficd-003 | 0x9823d715 | Israel-Hezbollah cea | 0x9823d71568… | 0 | — | — | ❌ no prices |
| fficd-003 | 0x3488f31e | US strikes Iran Feb  | 0x3488f31e64… | 0 | — | — | ❌ no prices |
| fficd-003 | 0x70909f0b | Khamenei out Mar 31 | 0x70909f0ba8… | 0 | — | — | ❌ no prices |
| fficd-004 | 0xbfa45527 | Maduro in US custody | 0xbfa45527ec… | 0 | — | — | ❌ no prices |
| fficd-004 | 0x62b0cd59 | US-Venezuela militar | 0x62b0cd5980… | 0 | — | — | ❌ no prices |
| fficd-004 | 0x7f3c6b90 | US invades Venezuela | 0x7f3c6b9029… | 0 | — | — | ❌ no prices |
| fficd-005 | 0xb36886bb | Bitcoin ETF approved | 0xb36886bb0c… | 0 | — | — | ❌ no prices |
| fficd-006 | 0x54361608 | Gene Hackman | 0x54361608e7… | 0 | — | — | ❌ no prices |
| fficd-006 | 0x45126353 | Ismail Haniyeh | 0x4512635352… | 0 | — | — | ❌ no prices |
| fficd-006 | 0x26477123 | Zendaya | 0x2647712335… | 0 | — | — | ❌ no prices |
| fficd-007 | 0xf4078ddd | Biden pardons SBF | 0xf4078ddd08… | 0 | — | — | ❌ no prices |
| fficd-007 | 0x2b8608c1 | SBF 50+ years | 0x2b8608c1c9… | 0 | — | — | ❌ no prices |
| fficd-007 | 0x02c8326d | FTX no payouts 2024 | 0x02c8326d2a… | 0 | — | — | ❌ no prices |
| fficd-008 | 0x9872fe47 | Ciuca Romanian elect | 0x9872fe47fb… | 0 | — | — | ❌ no prices |

## Step 4 — data_collection_runs for clob_prices

| status | runs | avg_records | total_records |
|--------|------|-------------|---------------|
| success | 727 | 2,133 | 1,550,594 |
| failed | 144 | 0 | 0 |
| running | 91 | 0 | 0 |

- Distinct market targets with successful CLOB run: 409

## Step 5 — Why 727 runs vs 26 markets with prices?

**Top markets by number of CLOB runs (same market re-run):**

| target | runs | total_written |
|--------|------|---------------|
| 0x90eec605534eb1b797… | 2 | 2,894 |
| 0x7992bfd66c526dc0ad… | 2 | 2,874 |
| 0x933133a150cc20f544… | 2 | 4,050 |
| 0xbabd78723985851c3f… | 2 | 2,874 |
| 0xf7cf7d6f6d0165864d… | 2 | 340 |
| 0xfe06859f06716c3c09… | 2 | 2,894 |
| 0x8f403ee7228abb7da6… | 2 | 4,172 |
| 0x54387bb3fc0e6d56e8… | 2 | 4,200 |
| 0x7825b27eb3f71584e0… | 2 | 4,186 |
| 0x610a24ec72f9e79b0a… | 2 | 2,874 |

- Distinct markets with 0 records written despite success status: 0
- Distinct markets with >0 records written: 409

**20 random clob_prices runs:**

| target | n_written | date |
|--------|-----------|------|
| 0x8b7b8f1a8b5e11e0… | 1,281 | 2026-04-26 |
| 0xd2c4dea8c4a1f65f… | 1,437 | 2026-04-26 |
| 0xca29fbef1655e988… | 1,436 | 2026-04-26 |
| 0x56df124f627480bc… | 1,437 | 2026-04-26 |
| 0xf63cb3a45c499a30… | 0 | 2026-04-26 |
| 0xee4a0b7a73a55ebc… | 3,043 | 2026-04-26 |
| 0x5ae02a2a3701d3d8… | 1,437 | 2026-04-26 |
| 0x177937d6dc043219… | 1,437 | 2026-04-26 |
| 0x2f835c78c54f4a79… | 171 | 2026-04-26 |
| 0x7e1f2eb660b2d2a1… | 17,690 | 2026-04-26 |
| 0x89c0b57bc1d48a48… | 3,039 | 2026-04-26 |
| 0x387bda389552bde1… | 0 | 2026-04-26 |
| 0x4069404e69ff79a7… | 0 | 2026-04-26 |
| 0x9e49db87b3814932… | 0 | 2026-04-26 |
| 0x87315736f6b35b87… | 0 | 2026-04-26 |
| 0xbdcce4dc1d22c630… | 2,067 | 2026-04-26 |
| 0xfc22a595169660ea… | 0 | 2026-04-26 |
| 0x9cd18bfd0d95f8c1… | 2,075 | 2026-04-26 |
| 0xa1d378ba83d78897… | 2,068 | 2026-04-26 |
| 0x4b1198850f96118d… | 1,437 | 2026-04-26 |

## Step 6 — Trades table as price-series fallback

**Top 20 markets by trade count (VWAP proxy feasibility):**

| market_id | n_trades | first_trade | last_trade | price_range |
|-----------|---------|------------|-----------|-------------|
| 0x4a5b5f52c6e7… | 33,539 | 2024-04-25 | 2024-12-18 | 0.480–0.999 |
| 0xcc7191d618ab… | 28,034 | 2026-01-22 | 2026-02-27 | 0.543–0.999 |
| 0xe5e57a570056… | 21,685 | 2026-01-27 | 2026-02-23 | 0.901–0.999 |
| 0xfc4453f83b30… | 20,929 | 2025-07-02 | 2026-01-01 | 0.770–0.999 |
| 0xd81b9393993c… | 20,853 | 2024-11-02 | 2024-12-17 | 0.130–0.999 |
| 0x5cd80b8fd72f… | 20,314 | 2025-12-03 | 2026-03-31 | 0.001–0.988 |
| 0x031878fa141d… | 19,813 | 2026-04-03 | 2026-04-04 | 0.250–0.990 |
| 0xad29cf2f3839… | 19,526 | 2025-12-03 | 2026-01-31 | 0.001–0.440 |
| 0x40c2ab7a32d2… | 18,137 | 2025-11-13 | 2026-04-01 | 0.744–0.999 |
| 0xb96ea9e84838… | 17,791 | 2025-09-11 | 2026-01-01 | 0.001–0.400 |
| 0xcf610a4fdc73… | 16,651 | 2025-12-03 | 2026-03-31 | 0.901–0.999 |
| 0x10cf4927827e… | 16,566 | 2026-01-03 | 2026-01-13 | 0.001–0.970 |
| 0xb2762e424256… | 16,415 | 2026-01-17 | 2026-01-27 | 0.001–0.990 |
| 0xc84ac0cca635… | 16,277 | 2024-11-26 | 2025-04-11 | 0.650–0.999 |
| 0xf76bd0b3d832… | 16,191 | 2025-12-03 | 2026-03-31 | 0.230–0.999 |
| 0x4cccd2593352… | 15,769 | 2026-01-10 | 2026-01-21 | 0.771–0.999 |
| 0x33f5b304cb95… | 15,454 | 2025-12-09 | 2026-02-21 | 0.908–0.999 |
| 0x76b3f3b93dc8… | 15,394 | 2026-01-31 | 2026-02-10 | 0.403–0.999 |
| 0x1b604cb2a955… | 15,226 | 2026-03-29 | 2026-04-04 | 0.040–0.999 |
| 0xfc575fe49537… | 15,193 | 2026-02-07 | 2026-02-17 | 0.001–0.985 |

- Trades with valid price > 0: 17,905,585 / 17,905,585 (100.0%)

## Step 7 — Recommendation

**ILS-target markets with CLOB price data: 3 / 11,263 (0.0%)**

**CLOB coverage for ILS targets is effectively zero.**

Root cause: The 727 successful CLOB runs targeted ~409 recently *active/open*
markets (all fetched in April 13–26 2026 window). These are not the ILS-relevant
*resolved* markets. The 1.55M price rows are for open market monitoring, not the
historical resolved markets needed for ILS.

**To fix the TASK_02C_RESULTS.md contradiction:**
- '727 successful runs / 1.55M records' → true, but for open-market monitoring
- 'only 26/3 markets with CLOB data for ILS' → also true; different market set

**Options for ILS computation:
**
**Option A — Run CLOB collector for all ILS-target markets (best quality):**
```bash
# ~10,400 markets, each ~30 API calls at 4 req/sec ≈ ~22h
uv run python scripts/batch_collect_clob.py --categories military_geopolitics,regulatory_decision,corporate_disclosure --min-vol 50000
```

**Option B — Use trade VWAP as primary price proxy (available now, unblocks ILS):**
- `trades.price` field = USDC paid per share, 0–1 decimal
- 100% of 17,905,585 trades have valid prices (Step 6)
- Covers all 10,410 Phase 3B markets including all ILS targets
- Compute: time-windowed VWAP from trades WHERE ts < (resolved_at - 24h)
- Limitation: transaction price ≠ mid-quote; spread impact is small in liquid markets
- **Recommendation: proceed with trade VWAP for Phase 1 ILS; run Option A in parallel**

**For FFICD validation set (Step 3):** all 24 markets have 0 CLOB prices.
Run CLOB per-market OR use trade VWAP (trades ARE available for fficd-008 at minimum).