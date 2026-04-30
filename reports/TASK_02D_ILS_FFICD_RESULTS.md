# Task 02D Phase 4 — ILS Results on FFICD Validation Set

**Generated:** 2026-04-27  
**Branch:** task02d/price-reconstruction-and-uma  
**Status:** STOP — awaiting user review before Phase 5

---

## Summary

| Metric | Value |
|---|---|
| FFICD markets total | 24 |
| Scored (ILS computed) | 4 |
| Skip: no price data | 16 |
| Skip: T_news proxy predates T_open | 2 |
| Skip: T_news proxy too far from any trade | 2 |
| Price source for all scored | trade_vwap |

All 24 FFICD markets are **Polymarket admin-resolved** (no UMA evidence URL), so T_news was seeded as a proxy: `end_date - 1 day`, tier=2, confidence=0.50.

---

## Scored Markets

| Case | Question | ILS | p_open | p_news | p_resolve | Outcome |
|---|---|---|---|---|---|---|
| fficd-003 Iran Fri | Another Iran strike on Israel by Friday? | **−2.714** | 0.258 | 0.957 | 0 (NO) | Iran didn't strike |
| fficd-003 Iran Nov8 | Iran strike on Israel by Nov 8? | **−0.390** | 0.700 | 0.973 | 0 (NO) | Iran didn't strike |
| fficd-007 FTX payouts | FTX doesn't start payouts in 2024? | **−2.922** | 0.746 | 0.004 | 1 (YES) | FTX didn't pay in 2024 |
| fficd-008 Ciucă | Will Nicolae Ciucă win the 2024 Romanian Presidential election? | **−0.0005** | 0.991 | 0.991 | 0 (NO) | Ciucă lost |

Additional trade features:

| Question | n_trades_total | n_trades_pre_news | vol_pre_share | pre_news_max_jump ($) |
|---|---|---|---|---|
| Iran strike Fri | 607 | 383 | 0.485 | 4,365 |
| Iran strike Nov8 | 1,929 | 1,491 | 0.629 | 25,625 |
| FTX no payouts | 2,148 | 2,105 | 1.000 | 2,533 |
| Ciucă Romanian | 9,288 | 4,279 | 0.383 | 103,619 |

All flags: `window_7d_predates_topen` on Iran markets (market open < 7 days before T_news proxy). FTX and Ciucă are flag-free.

---

## Interpretation

### Iran markets (ILS ≈ −0.4 to −2.7)

For both Iran strike markets, prices peaked near 95–97% YES just before the proxy T_news window (end_date − 1d), then resolved NO. The large negative ILS reflects **price moving strongly opposite to resolution**. This pattern is consistent with late retail speculation / herd behavior (not informed trading), because:
- Informed insiders would have BID UP the NO side (lowering the YES price), not the YES side  
- The proxy T_news quality is poor for these short-lived markets: `end_date − 1d` captures the final day of speculative frenzy, not an actual news break

**Data quality note:** Both markets opened within hours of end_date, so `t_open` was snapped to the first available trade (15–29 minutes after creation). ILS reflects activity from market open through the proxy T_news.

### FTX payouts (ILS = −2.92)

- p_open=0.746 (first trade Feb 1, 2024): market started at 75% chance FTX WON'T pay in 2024  
- p_news=0.004 (near Dec 29, 2024 proxy): market crashed to 0.4% chance — traders expected payouts  
- p_resolve=1 (YES, FTX did NOT start payouts by Dec 30, 2024 end_date)  
- ILS = (0.004 − 0.746) / (1 − 0.746) = −2.92

The proxy T_news (Dec 29) is poorly positioned: the actual informative news would be the FTX restructuring announcement and judge approval in Oct–Nov 2024. Using `end_date − 1d` captures the tail end of price convergence to 0%, but the actual "news event" that moved prices happened months earlier. This distorts ILS significantly.

### Ciucă Romanian (ILS ≈ 0)

- Market priced Ciucă winning at ~99% throughout → virtually no price movement  
- ILS ≈ 0: price didn't move meaningfully either toward or away from actual resolution  
- High pre-news jump ($103K) indicates a few large trades, but price was sticky  
- **Genuine informed trading signal would show ILS approaching 1.0** (price moved toward resolution before news). Instead ILS ≈ 0 suggests either: (a) market was mispriced with no correction, or (b) the T_news proxy is too far from the actual event (Romanian election results came in unexpectedly, the "news" was election night itself)

---

## Why 16 Markets Scored Zero

The 16 unscorable FFICD markets include:

- **Election 2024 markets** (Trump, Harris, Michelle Obama, Other Rep): These were the highest-volume Polymarket markets ever. The subgraph collector was **not run for these markets** — they were created in early 2024 and their trades are not in the DB. Volume was ~$500M+ for Trump/Harris alone.
- **2026 military markets** (Iran ceasefire, Hezbollah, US forces Iran, Khamenei, Maduro, Venezuela, US strikes Iran Feb): All created March–April 2026; zero trades collected.
- **Others** (Bitcoin ETF, Biden/SBF, Gene Hackman, Biden pardon): Various reasons including no subgraph run or sparse trading.

**Root cause:** These FFICD markets were chosen as interesting test cases, but the subgraph collector was not backfilled for them. The trade data gap is a data collection gap, not a signal gap.

---

## 2 T_news Proxy Failures

| Market | T_news proxy | T_open | Gap |
|---|---|---|---|
| Iran strike today | 2024-09-30 12:00 | 2024-10-01 15:14 | proxy 27h BEFORE market opened |
| Hezbollah ceasefire Apr18 | 2026-04-14 00:00 | 2026-04-15 20:21 | proxy 44h BEFORE market opened |

For these short-duration markets, `end_date − 1d` predates market creation. ILS is undefined because there is no price series before the proxy date.

---

## Key Findings for Phase 5 Design

1. **Trade VWAP works** as a price series source for markets with ≥300 trades.
2. **T_news proxy quality is the dominant error source.** For sports/Iran/election markets, `end_date − 1d` is a poor proxy; the actual news event is hours to months earlier.
3. **Negative ILS ≠ informed trading signal.** Strongly negative ILS means the price moved opposite to resolution, which can be:
   - Retail speculation run-up (not informed)
   - Poor T_news proxy that captures price convergence noise
4. **High |ILS| threshold for reliability:** Only markets with |ILS| < 2 and no flag `window_7d_predates_topen` should be considered reliable. That leaves 0 of 4 FFICD markets as definitively clean.
5. **Ciucă (ILS ≈ 0) is the most interesting:** The market was priced "wrong" at 99% throughout, yet Ciucă lost. ILS ≈ 0 means informed traders did NOT move the price ahead of the outcome. This is the null hypothesis case — no detectable informed flow.

---

## Phase 5 Readiness Assessment

**Proceeding to Phase 5 (control group) requires user confirmation.** Key decision:

- The 4 FFICD scored markets have ILS values of doubtful interpretability due to poor T_news proxies
- Phase 5 random control group would use the same proxy → same quality issues
- **Alternative:** Run Phase 5 only on the ~494 markets with proper Tier 1 T_news (UMA evidence URL). These failed tier1-batch because evidence URLs are sports-results pages (not articles), not because T_news is wrong — the T_news is the resolution timestamp itself

**Recommendation:** Before Phase 5, improve T_news for FFICD markets by using `resolved_at − hours` instead of `end_date − 1d` for markets that resolved much earlier than end_date.
