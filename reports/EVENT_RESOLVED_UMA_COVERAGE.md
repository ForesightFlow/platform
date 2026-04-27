# Event-Resolved UMA Coverage

**Generated:** 2026-04-27  
**Branch:** task02e/resolution-typology  
**Status:** STOP — architectural finding blocks Phase 4 and Phase 5 as planned

---

## Summary

| Metric | Value |
|---|---|
| event_resolved markets queried (vol≥50K) | 1,145 |
| Markets with resolution_proposer set | 0 |
| Markets with resolution_evidence_url | 0 |
| Evidence URLs obtained by UMA collector | 0 |

**All 1,145 event_resolved markets are Polymarket admin-resolved.** None went through the UMA Optimistic Oracle. The UMA collector cannot obtain evidence URLs for them.

---

## Architectural Finding: Two Resolution Regimes

Polymarket operates two distinct resolution regimes that are architecturally incompatible with the originally planned T_news approach:

### Regime 1 — UMA Oracle Resolution (494 markets in our DB)

Used for markets with objectively verifiable data feeds:
- **Crypto price oracles** (`data.chain.link`, 197 markets): BTC price, ETH price, token prices
- **Sports/esports results** (`hltv.org` 140, `mlssoccer.com` 29, `ufc.com` 12, etc.): match winners

In UMA-resolved markets, the resolution IS the data event. There is no "news article" — the oracle timestamp IS T_news. T_news = T_resolve is conceptually correct here, not a proxy.

**Problem for ILS:** Only 2 of these 494 markets have trade data in our DB (both are Counter-Strike matches). The rest were never subgraph-collected.

### Regime 2 — Polymarket Admin Multisig Resolution (all others)

Used for all subjective/judgment markets:
- Elections, legislative votes, political events
- Tech product launches, regulatory approvals
- Geopolitical events, military operations
- All 1,145 markets classified as `event_resolved`
- All 1,224 markets classified as `deadline_resolved`

Admin-resolved markets have `resolution_proposer = NULL` and `resolution_evidence_url = NULL` by construction — the resolution happens off-chain with no on-chain evidence URL.

---

## Domain Distribution (494 UMA-resolved markets in DB)

| Domain | N | Category | Type |
|---|---|---|---|
| data.chain.link | 197 | other | Chainlink oracle (crypto prices) |
| hltv.org | 140 | military_geopolitics | CS:GO match results |
| wunderground.com | 41 | other | Weather data |
| mlssoccer.com | 29 | other | MLS football results |
| ligamx.net | 21 | other | Liga MX results |
| binance.com | 14 | other | Crypto price/listing |
| unafut.com | 12 | other | UNAF football |
| ufc.com | 12 | other | UFC fight results |
| dimayor.com.co | 10 | other | Colombian football |
| atptour.com | 5 | other | ATP tennis |
| gol.gg / vlr.gg | 8 | other | Esports (LoL, Valorant) |
| super.rugby | 3 | other | Rugby |
| liquipedia.net | 2 | other | Esports |

**Zero article-quality domains.** None match the whitelist (reuters, bloomberg, wsj, ft, nytimes, apnews, sec.gov, fda.gov, etc.). The tier1-batch from Task 02D Phase 3 already confirmed this: `tier1-batch done: ok=0 skip=482 fail=0`.

---

## Why Phase 4 and Phase 5 (as planned) Are Blocked

| Phase | Plan | Status | Reason |
|---|---|---|---|
| Phase 4 | Tier 1 on article-whitelist URLs | **SKIPPED** | 0 article URLs exist |
| Phase 5 | ILS pilot on ≥30 article-T_news markets | **BLOCKED** | Phase 4 condition not met |

---

## Pivot Options for Phase 5

Two viable alternatives, pending user decision:

### Option A — UMA oracle markets as ILS test bed
The 2 CS:GO Counter-Strike matches (hltv.org) have trade data and a real evidence timestamp. Small but clean: T_news = match start time (derivable from hltv.org page). ILS should be near 1.0 if any pre-match insider flow existed.

**Problem:** n=2 is not a meaningful sample.

### Option B — Admin-resolved markets with `resolved_at` as T_news proxy
For admin-resolved event markets (elections, regulatory decisions), `resolved_at` is the timestamp when the Polymarket admin pushed the resolution transaction. This typically occurs within hours of the observable outcome (e.g., election called, bill signed). 

Using T_news = `resolved_at - Δ` where Δ is a configurable offset (e.g., 24h) gives a principled proxy: it is the last moment before the market could be formally resolved, and ILS would measure whether the price had already moved toward the outcome before formal resolution.

This is **different** from `end_date - 1d` (the FFICD proxy, which is bad): `resolved_at - 24h` is anchored to the actual resolution event, not an arbitrary deadline.

**Advantage:** 1,145 event_resolved markets available; `resolved_at` is populated for all of them.

### Option C — Defer Phase 5 until GDELT or LLM tier is available
Clean but slow. Requires Task 03 first.

---

## Recommendation

Proceed with **Option B** — seed T_news as `resolved_at - 24h` (tier=2, confidence=0.60, notes="proxy:resolved_at-24h") for all event_resolved markets with trades, then run ILS. Compare ILS distribution against:
- The FFICD proxy cohort (T_news = end_date - 1d) → expected: noisy, negative ILS
- The event_resolved cohort (T_news = resolved_at - 24h) → expected: cleaner distribution, some positive ILS on elections where outcomes leaked

This comparison is itself a publishable result about T_news proxy quality.
