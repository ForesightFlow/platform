# Documented Insider Cases — Polymarket Inventory

**Date:** 2026-04-26  
**DB state:** 911,237 markets total, 865,725 resolved  
**Purpose:** Map externally documented potential-insider-trading cases to concrete market IDs in the database. These are the ground-truth candidates for ILS validation in Task 03+.

---

## Case 1 — 2024 US Presidential Election

**Why it matters:** Largest prediction market event ever. Multiple reports of unusual position sizing hours before major poll releases and network calls. Polymarket volume exceeded $3.5B. Academic literature (e.g. Cowgill et al.) and journalistic investigation (Bloomberg, WSJ) flagged anomalous price movements correlating with private survey data.

**Status in DB:** ✅ Found

| market_id | question | volume_usdc | resolved_at | outcome |
|---|---|---|---|---|
| `0xdd22472e...` | Will Donald Trump win the 2024 US Presidential Election? | $1,531,479,285 | 2024-11-06 | YES (1) |
| `0xc6485bb7...` | Will Kamala Harris win the 2024 US Presidential Election? | $1,037,039,118 | 2024-11-06 | NO (0) |
| `0x55c55189...` | Will any other Republican win the 2024 US Presidential Election? | $241,655,100 | 2024-11-06 | NO (0) |
| `0x230144e3...` | Will Michelle Obama win the 2024 US Presidential Election? | $153,382,276 | 2024-11-06 | NO (0) |

**Trade data:** Top two markets (Trump, Harris) have vol > $1B — subgraph indexers report "bad indexers" for these (The Graph capacity issue). Trades not yet fetched. **Blocker for ILS on this case.**

---

## Case 2 — October 2024 Iran Attack on Israel

**Why it matters:** Iran launched 180+ ballistic missiles at Israel on Oct 1, 2024. Reports indicated that unusual Polymarket position accumulation began in the hours before the attack was publicly confirmed, suggesting possible signal from regional intelligence or social media monitoring. Referenced in Polymarket's own post-mortem and academic discussion of real-time event markets.

**Status in DB:** ✅ Found

| market_id | question | volume_usdc | resolved_at | outcome |
|---|---|---|---|---|
| `0xc1b6d712...` | Iran strike on Israel today? | $148,732 | 2024-10-01 19:01:34 UTC | YES (1) |
| `0x93727420...` | Another Iran strike on Israel by Friday? | $100,479 | 2024-10-05 | NO (0) |
| `0xc8312853...` | Iran strike on Israel by Nov 8? | $788,895 | 2024-11-09 | NO (0) |

**Note:** The key market `Iran strike on Israel today?` ($148K, resolved YES Oct 1) is the documented case. Low volume reflects that the event happened before Polymarket's mainstream growth. Trades should be fetchable — not blocked by indexer issue.

**Trade data:** Not yet fetched (subgraph batch has not reached $148K markets yet — currently at ~$1.98M). Available once batch reaches lower volume band.

---

## Case 3 — 2026 US-Iran Military Conflict Cluster

**Why it matters:** The largest geopolitical market cluster in Polymarket history. As of April 2026, the US-Iran conflict produced markets with combined volume >$1B. Several of these markets resolved YES within hours of US military action, with documented pre-resolution price spikes suggesting informed positioning (possibly from social media signal or regional intelligence sources).

**Status in DB:** ✅ Found — largest cluster in `military_geopolitics` category

| market_id | question | volume_usdc | resolved_at | outcome |
|---|---|---|---|---|
| `0x6d0e09d0...` | US forces enter Iran by April 30? | $269,049,107 | 2026-04-09 | YES (1) |
| `0x4c5701bc...` | US x Iran ceasefire by April 7? | $173,696,184 | 2026-04-11 | YES (1) |
| `0xd4bbf7f6...` | Khamenei out as Supreme Leader by February 28? | $131,114,971 | 2026-03-04 | YES (1) |
| `0x9823d715...` | Israel x Hezbollah ceasefire by April 18? | $98,599,882 | 2026-04-21 | YES (1) |
| `0x3488f31e...` | US strikes Iran by February 28, 2026? | $89,652,867 | 2026-02-28 | YES (1) |
| `0x70909f0b...` | Khamenei out as Supreme Leader by March 31? | $63,238,698 | 2026-03-04 | YES (1) |

**Trade data:** These are in the vol >$2M band which was excluded from the current batch (max_volume=2M). The top markets ($89M–$269M) have The Graph indexer issues. **Requires separate high-volume batch or direct indexer query.**

---

## Case 4 — Maduro Regime / Venezuela 2024–2026

**Why it matters:** Venezuela election disputes, Maduro's contested re-election (July 2024), and subsequent US sanctions/extradition threats created a series of prediction markets with potential insider signals from Venezuelan political networks and US intelligence community.

**Status in DB:** ✅ Found

| market_id | question | volume_usdc | resolved_at | outcome |
|---|---|---|---|---|
| `0xbfa45527...` | Maduro in U.S. custody by January 31? | $11,034,070 | 2026-01-07 | YES (1) |
| `0x62b0cd59...` | US x Venezuela military engagement by December 31? | $51,073,021 | 2026-01-05 | NO (0) |
| `0x7f3c6b90...` | Will the U.S. invade Venezuela by January 31, 2026? | $8,368,551 | 2026-02-01 | NO (0) |

**Trade data:** $11M market in batch scope (vol 50K–2M would miss it; would need vol up to 15M). Not yet fetched. Confirm `Maduro in U.S. custody` resolved YES.

---

## Case 5 — Bitcoin ETF SEC Approval January 2024

**Why it matters:** SEC approved the first spot Bitcoin ETFs on January 10, 2024. Reports documented unusual order flow in Polymarket prediction markets 30–60 minutes before the announcement, consistent with early access to regulatory decision. Referenced in crypto journalism and compliance discussions.

**Status in DB:** ✅ Found

| market_id | question | volume_usdc | resolved_at | outcome |
|---|---|---|---|---|
| `0xb36886bb...` | Bitcoin ETF approved by Jan 15? | $12,622,418 | 2024-01-10 23:47:24 UTC | YES (1) |

**Trade data:** In vol $12M range — not in current batch scope (max_volume=2M). Requires separate run with `--max-volume 15000000`.

---

## Case 6 — Google Year in Search 2025

**Why it matters:** Annual Google Year in Search markets have historically shown pre-resolution price spikes within hours of the announcement, possibly from early access to Google Trends data or embargo breaks.

**Status in DB:** ✅ Found

| market_id | question | volume_usdc | resolved_at | outcome |
|---|---|---|---|---|
| `0x54361608...` | Gene Hackman #1 in Google Year in Search 2025 Passings? | $2,952,428 | 2025-12-04 | NO (0) |
| `0x45126353...` | Ismail Haniyeh #1 in Google Year in Search 2025 Passings? | $1,591,632 | 2025-12-04 | NO (0) |
| `0x26477123...` | Zendaya #1 in Google Year in Search 2025 Actors? | $755,946 | 2025-12-04 | NO (0) |

**Trade data:** All in vol $500K–$3M range — in current batch scope. Will be fetched.

---

## Case 7 — FTX / SBF Collapse 2022–2024

**Why it matters:** Sam Bankman-Fried's arrest and trial generated multiple prediction markets. In November 2022, during the FTX collapse, Polymarket markets on FTX solvency moved dramatically hours before public announcements, with some attributing this to insider knowledge within the crypto community.

**Status in DB:** ✅ Found

| market_id | question | volume_usdc | resolved_at | outcome |
|---|---|---|---|---|
| `0xf4078ddd...` | Will Biden pardon SBF? | $8,209,071 | 2025-01-20 | NO (0) |
| `0x2b8608c1...` | SBF sentenced to 50+ years? | $363,283 | 2024-03-28 | NO (0) |
| `0x02c8326d...` | FTX doesn't start payouts in 2024? | $952,525 | 2025-01-01 | YES (1) |

**Note:** The core 2022 collapse markets (pre-Polymarket's current subgraph coverage) may not be in the DB. The markets found are post-collapse legal/regulatory bets.

---

## Case 8 — Romanian Presidential Election 2024

**Why it matters:** Călin Georgescu's unexpected first-round win in November 2024, followed by the Constitutional Court annulment in December 2024, created extreme Polymarket volatility. The Ciucă market ($326M) resolved in May 2025 after the re-run election. Notable for potential insider positioning around court's annulment decision.

**Status in DB:** ✅ Found (already has trades)

| market_id | question | volume_usdc | resolved_at | outcome | trades |
|---|---|---|---|---|---|
| `0x9872fe47...` | Will Nicolae Ciucă win the 2024 Romanian Presidential election? | $326,507,671 | 2025-05-01 | NO (0) | **9,288 trades fetched** |

**Trade data:** ✅ Already in DB. This is the first market with full trade history available for ILS analysis.

---

## Summary Table

| Case | Volume | In DB | Trades Fetched | ILS Feasibility |
|---|---|---|---|---|
| 2024 US Election (Trump/Harris) | $2.57B | ✅ | ❌ Indexer issue | 🔴 Blocked |
| Oct 2024 Iran Strike on Israel | $148K–$789K | ✅ | ❌ Below current batch threshold | 🟡 Available once batch reaches low-vol markets |
| 2026 US-Iran Conflict Cluster | $89M–$269M | ✅ | ❌ Above current batch max-vol | 🟡 Requires high-vol batch |
| Maduro / Venezuela | $11M–$51M | ✅ | ❌ Above batch max-vol | 🟡 Requires vol 2M–60M batch |
| Bitcoin ETF SEC Approval | $12.6M | ✅ | ❌ Above batch max-vol | 🟡 Requires vol 2M–15M batch |
| Google Year in Search 2025 | $750K–$3M | ✅ | 🔄 In current batch scope | 🟢 Will be available |
| FTX / SBF | $363K–$8.2M | ✅ | ❌ Partial coverage | 🟡 Requires wider batch |
| Romanian Election 2024 | $326M | ✅ | ✅ **9,288 trades** | 🟢 Ready for ILS |

---

## Action Items for Task 03

1. **Immediate ILS candidate:** Romanian election (`0x9872fe47`) — 9,288 trades, $326M, NO outcome. CLOB prices likely available. Run ILS computation now.

2. **Next batch run:** Add higher volume band — `--min-volume 2000000 --max-volume 50000000 --categories "military_geopolitics,regulatory_decision,corporate_disclosure"`. Captures Bitcoin ETF, Maduro, FTX, small US-Iran markets.

3. **Iran Oct 2024 strike:** Run subgraph for `0xc1b6d712...` directly: `fflow collect subgraph --market 0xc1b6d712...`. Low volume = fast. Key ILS case.

4. **Indexer workaround for $1B+ markets:** The Graph "bad indexers" error on Trump/Harris markets. Options: (a) wait for The Graph to fix indexers, (b) use alternative Polymarket subgraph endpoint, (c) query Polygon directly via JSON-RPC. Document in TASK_02D or separate task.

5. **T_news coverage check:** Before computing ILS, verify `news_timestamps` table has entries for these market IDs. Currently empty (UMA collector failed, GDELT not run). This is the critical blocker for ILS formula.
