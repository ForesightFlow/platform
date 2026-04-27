# Task 02F Phase 3 — Epstein Cluster Case Study

**Generated:** 2026-04-27  
**Branch:** task02f/control-group-and-proxy-refinement  
**Markets:** 3 Polymarket binary markets on Dec 2025 Epstein file release

---

## Market Overview

| Market | Abbr | Vol ($) | ILS | p_open | p_news | p_resolve | HHI |
|---|---|---|---|---|---|---|---|
| Will AOC be named in newly released Epstein files? | AOC | 86,603 | **0.933** | 0.940 | 0.996 | 1 | 0.652 |
| Will Bernie Sanders be named...? | Sanders | 57,259 | **0.642** | 0.910 | 0.968 | 1 | 0.241 |
| Will Ehud Barak be named...? | Barak | 178,531 | **0.553** | 0.170 | 0.629 | 1 | 0.576 |

All three markets opened 2025-11-19 and resolved YES 2025-12-23.  
T_news proxy: `resolved_at − 24h` → 2025-12-22 ~12:08–12:17 UTC.

**Token note:** `outcome_index=1` in the trades table is the YES token. The trade `price` column gives the YES probability directly (confirmed: first AOC trade at 04:50 Nov 19 has price=0.940 = p_open=0.940; first Barak trade at 04:50 Nov 19 has price=0.170 = p_open=0.170).

---

## Price Trajectories

### AOC — "High consensus" market

Market opened with 94% YES probability. Price drifted steadily upward, reaching 99.6% by T_news. The market was never uncertain — the ILS measures confirmation of an already-high consensus, not price discovery ahead of news.

```
Date        YES%   Vol
2025-11-19  94.4%  $128
2025-11-21  97.9%  $178
2025-11-22  95.6%  $831
2025-12-01  98.0%  $637
2025-12-10  98.8%  $782
2025-12-14  99.1%  $3,395  ← largest pre-news volume day
2025-12-19  98.1%  $4,156  ← volume spike (+3 days before T_news)
2025-12-20  98.6%  $684
2025-12-21  99.0%  $1,117
2025-12-22  99.6%  $1,387  ← T_news day
2025-12-23  60.2%  $4,527  ← resolution day (sell activity during settlement)
```

ILS=0.933 reflects a 5.6% absolute price move (0.940→0.996) out of a possible 6% to full resolution. Small absolute move, high relative ratio.

### Sanders — "High consensus" market

Similar structure to AOC: market opened at 91-94% YES, drifted to 96.8% by T_news.

```
Date        YES%   Vol
2025-11-19  93.7%  $210
2025-11-27  94.9%  $981
2025-12-02  96.4%  $10
2025-12-13  98.6%  $93
2025-12-19  95.7%  $9,351  ← largest volume day (volume spike)
2025-12-21  97.0%  $775
2025-12-22  96.7%  $1,317  ← T_news day
2025-12-23  73.5%  $990    ← resolution day
```

### Barak — "Price discovery" market

Barak opened at 17% YES (first trade, tiny $0.07 notional at 04:50 Nov 19). The broader market settled at 63% by end of day as volume came in. Subsequent weeks showed genuine uncertainty (33%–65% range) with a dramatic Dec 20 crash followed by recovery.

```
Date        YES%    Vol    Notes
2025-11-19  63.3%  $127   (day VWAP; t_open price=0.170 from first $0.07 trade)
2025-11-20  44.9%  $491
2025-11-21  38.2%  $139
2025-11-24  33.3%  $153   ← low point
2025-11-26  46.6%  $325
2025-11-27  51.7%  $102
2025-12-03  54.1%  $750
2025-12-11  61.3%  $778
2025-12-18  57.3%  $671
2025-12-19  45.8%  $1,256  ← sudden sell-off begins
2025-12-20  21.6%  $933    ← crash to 21.6% (767 trades) — 2 days before T_news
2025-12-21  52.9%  $9,332  ← recovery (852 trades, $9.3K) — 1 day before T_news
2025-12-22  69.2%  $9,946  ← T_news day (337 trades, final push)
2025-12-23  33.0%  $1,951  ← resolution day
```

The Dec 20 crash (YES 57% → 21.6%) followed by Dec 21-22 recovery (→ 69%) on very high volume suggests a contested price discovery episode. p_news=0.629 is the minute-level price at T_news, consistent with the Dec 22 daily VWAP of 69.2%.

---

## Wallet Analysis

### Top-10 Wallets by Pre-News YES Volume

**AOC** (t_news=2025-12-22 12:16, total pre-news YES vol=$10,830):

| Rank | Wallet (prefix) | Vol ($) | Share | Avg YES price | First trade | Lead time | Total mkts | Poly since |
|---|---|---|---|---|---|---|---|---|
| 1 | `0x4bfb41d5b357` | 8,707 | **80.4%** | ~0.985 | Nov 19 02:00 | 33.4 days | 5,115 | 2022-12 |
| 2 | `0x4014e472d9ae` | 460 | 4.2% | ~0.992 | Dec 19 08:29 | 3.2 days | 13 | 2025-12 |
| 3 | `0x44c1dfe43260` | 426 | 3.9% | ~0.966 | Dec 19 13:54 | 2.9 days | 264 | 2024-01 |
| 4 | `0x6c2d097c5c82` | 323 | 3.0% | ~0.985 | Dec 19 15:57 | 2.9 days | 9 | 2025-01 |
| 5 | `0xf4d36357d6ee` | 300 | 2.8% | ~0.952 | Nov 22 15:07 | 29.9 days | 22 | 2025-07 |

HHI=0.652 — highly concentrated in wallet #1.

**Sanders** (t_news=2025-12-22 11:20, total pre-news YES vol=$15,243):

| Rank | Wallet (prefix) | Vol ($) | Share | Avg YES price | First trade | Lead time | Total mkts | Poly since |
|---|---|---|---|---|---|---|---|---|
| 1 | `0x44c1dfe43260` | 6,185 | **40.6%** | ~0.957 | Dec 19 13:53 | 2.9 days | 264 | 2024-01 |
| 2 | `0x4bfb41d5b357` | 2,774 | 18.2% | ~0.957 | Nov 19 02:26 | 33.4 days | 5,115 | 2022-12 |
| 3 | `0x993c07251930` | 2,467 | 16.2% | ~0.946 | Nov 22 21:00 | 29.6 days | 185 | 2025-07 |
| 4 | `0xd1a535ed8543` | 1,466 | 9.6% | ~0.934 | Nov 21 02:40 | 31.4 days | 19 | 2025-09 |
| 5 | `0x32ee4a83ae93` | 1,310 | 8.6% | ~0.963 | Dec 20 03:25 | 2.3 days | 11 | 2025-07 |

HHI=0.241 — more distributed.

**Barak** (t_news=2025-12-22 12:08, total pre-news YES vol=$12,480):

| Rank | Wallet (prefix) | Vol ($) | Share | Avg YES price | First trade | Lead time | Total mkts | Poly since |
|---|---|---|---|---|---|---|---|---|
| 1 | `0x4bfb41d5b357` | 9,395 | **75.3%** | ~0.457 | Nov 20 00:20 | 32.5 days | 5,115 | 2022-12 |
| 2 | `0xe598435df0cd` | 822 | 6.6% | ~0.607 | Dec 21 13:16 | 0.95 days | 277 | 2025-11 |
| 3 | `0xbacd00c9080a` | 471 | 3.8% | ~0.414 | Dec 19 23:09 | 2.5 days | 542 | 2025-05 |
| 4 | `0x9bb397feaa8b` | 335 | 2.7% | ~0.582 | Dec 21 22:11 | 0.6 days | 10 | 2025-12 |
| 5 | `0x50f7710e4ae4` | 326 | 2.6% | ~0.512 | Dec 20 15:19 | 1.87 days | 38 | 2025-10 |

HHI=0.576 — concentrated in wallet #1 but less than AOC.

*Avg YES price is computed as `AVG(t.price)` from the pre-news BUY trades with outcome_index=1 (YES token).*

### Top-10 vs Bottom-10 Comparison

**Top-10 characteristics (pre-news YES buyers):**
- Lead times: bimodal distribution — either at market open (29–33 days) or in the final 3 days before T_news
- Volume: $8,707–$326 (top-5); tail drops rapidly
- Wallet age: #1 wallet is a veteran (5,115 markets, Polymarket since Dec 2022)
- 2 of top-10 in AOC are brand-new accounts (Dec 2025 creation) → possible sybils

**Bottom-10 characteristics (smallest pre-news YES buyers):**
- Volume: $0–$20 per wallet
- 1 trade each (noise/retail participants)
- Many created Dec 19–22 (last 3 days before T_news)
- No clear pattern distinguishing them from random retail activity

---

## Cross-Market Wallet Overlap

Wallets appearing in 2+ Epstein markets (pre- AND post-resolution trades counted):

| Wallet (prefix) | N markets | Vol ($) | Earliest trade | Chain age | Poly since | Total mkts |
|---|---|---|---|---|---|---|
| `0x4bfb41d5b357` | **3** (all) | **34,034** | Nov 19 02:00 | Sep 2022 | Dec 2022 | 5,115 |
| `0x44c1dfe43260` | **3** (all) | 6,640 | Dec 19 13:53 | Feb 2025 | Jan 2024 | 264 |
| `0xe598435df0cd` | **3** (all) | 1,034 | Dec 20 07:29 | Dec 2024 | Nov 2025 | 277 |
| `0x4014e472d9ae` | **3** (all) | 680 | Dec 19 08:19 | — | Dec 2025 | 13 |
| `0xf0b0ef1d6320` | **3** (all) | 134 | Dec 01 15:55 | Jul 2024 | Jul 2024 | 4,348 |
| `0xd1a535ed8543` | 2 (Sanders+Barak) | 2,823 | Nov 19 13:25 | — | Sep 2025 | 19 |
| `0x993c07251930` | 2 (Sanders+Barak) | 2,713 | Nov 19 07:00 | Jul 2025 | Jul 2025 | 185 |
| `0x32ee4a83ae93` | 2 (Sanders+Barak) | 1,618 | Dec 20 03:25 | — | Jul 2025 | 11 |

4 wallets were active in ALL THREE markets. Combined vol of top-2 cross-market wallets: **$40,674**.

---

## Key Wallet Profile: `0x4bfb41d5b357...`

This wallet is the single dominant actor in the Epstein cluster.

| Property | Value |
|---|---|
| Polymarket account since | 2022-12-16 |
| On-chain activity since | 2022-09-26 |
| Total markets traded | **5,115** |
| Epstein markets | **3 / 3** |
| Combined Epstein vol | **$34,034** |
| AOC position | $8,707 (80% of pre-news vol), 77 trades, opened Nov 19 |
| Sanders position | $2,774 (18% of pre-news vol), 48 trades, opened Nov 19 |
| Barak position | $9,395 (75% of pre-news vol), 531 trades, opened Nov 20 |

**AOC/Sanders positions:** Wallet bought YES when price was already >94%. Avg YES price ~0.985. On $8,707 invested, maximum additional profit at resolution ≈ $133. These are tiny profit trades at very high prices — consistent with a market maker providing liquidity rather than taking directional informed bets.

**Barak position:** Wallet bought YES at avg ~0.457 when the market opened at 17% and settled at 40-60%. Invested $9,395 in a market that resolved YES. Profit = $9,395 × (1/0.457 − 1) ≈ **$11,165**. This is a real directional bet at meaningful odds.

**Pattern:** The wallet dominates all three Epstein markets from the opening hours, but the Barak position is the economically significant one. Their early AOC/Sanders activity may reflect automated market-making at already-consensual prices, while Barak reflects a genuine directional call.

---

## Interpretation

### Why ILS is high but does not imply insider trading (AOC, Sanders)

AOC opened at 94% YES. The ILS formula `(p_news − p_open) / (p_resolve − p_open)` captures the fraction of remaining price move that occurred before T_news. With p_open=0.940 and p_news=0.996, the numerator is 0.056 (small absolute move) and denominator is 0.060 (tiny remaining room to 1.0). ILS=0.933 simply means "the price was already very close to resolution at open, and moved slightly closer before T_news."

This is not a signal of informed trading — it is a market that already had strong consensus and drifted as expected. A high ILS in a market where p_open ≥ 0.90 is an artifact of the formula's sensitivity near the edges.

### Barak as the more meaningful case

Barak opened with genuine uncertainty (17%→63% daily VWAP by end of day 1) and showed real volatility (21% crash on Dec 20, recovery to 69% on Dec 22). The ILS=0.553 reflects movement from 17% to 63% — a 46 pp absolute move. The dominant wallet entered early at fair odds and accumulated a real directional position.

The Dec 20 crash (21.6%) followed by a Dec 21 recovery (+31 pp, $9,332 vol) immediately before T_news is the most anomalous sequence. If Epstein file contents were known in advance, aggressive selling on Dec 20 (pushing price to 21%) and then buying into the recovery would be consistent with front-running or coordinated price manipulation.

### Limitations

1. T_news proxy is `resolved_at − 24h`, not the actual article timestamp. The actual Epstein files were publicly released on Dec 23 at 00:00 UTC (Polymarket resolver confirmed Dec 23). T_news = Dec 22 12:16 is an approximation, not the real news event.
2. The dominant wallet (5,115 markets) is almost certainly a professional market-maker or arbitrageur — its early positions may reflect general Polymarket activity rather than Epstein-specific intelligence.
3. No on-chain funding source data is available for the dominant wallet yet (polygonscan collection ongoing).

---

## Verdict

The Epstein cluster's high ILS values are primarily driven by:
1. **AOC/Sanders:** Formula sensitivity near p_open~1.0 — these are high-consensus markets from day 1, not informed-trading signals.
2. **Barak:** Genuine price movement from 17% to 63% with meaningful volatility. The ILS=0.553 is more substantive, but the dominant wallet is a known professional with 5,115 markets of activity.

The most anomalous finding is the **Dec 20 Barak crash** (21.6%, 767 trades) followed by immediate recovery (52.9%, 852 trades next day) — this price dislocation immediately before T_news warrants deeper investigation with actual article timestamps (LLM Tier 3 / GDELT) to determine if the "news" pre-dated Dec 22.

**Phase 3 recommendation:** LLM Tier 3 on Barak specifically (not all 3) to recover the actual Epstein files release timestamp and re-compute ILS with the correct T_news anchor.
