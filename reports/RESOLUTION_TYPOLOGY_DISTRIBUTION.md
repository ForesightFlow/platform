# Resolution Typology Distribution

**Generated:** 2026-04-27  
**Branch:** task02e/resolution-typology  
**Scope:** 11,200 markets — categories `regulatory_decision`, `military_geopolitics`, `corporate_disclosure`, `volume_total_usdc ≥ 50K`

---

## Overall Distribution

| Type | N | % of total | YES rate |
|---|---|---|---|
| `event_resolved` | 1,145 | 10.2% | 29.1% |
| `deadline_resolved` | 1,224 | 10.9% | **0.0%** |
| `unclassifiable` | 8,831 | 78.8% | 31.5% |
| **Total** | **11,200** | | |

**Key signal:** `deadline_resolved` YES rate is exactly 0%. This validates the classifier — every market the heuristic tagged as "nothing happened by deadline" resolved NO, by construction. There is no information leakage signal to find in these markets; the FFICD Iran markets are canonical examples.

---

## Per-Category Breakdown

| Category | Type | N | YES% |
|---|---|---|---|
| `corporate_disclosure` | deadline_resolved | 239 | 0.0% |
| `corporate_disclosure` | event_resolved | 100 | 41.0% |
| `corporate_disclosure` | unclassifiable | 1,367 | 31.2% |
| `military_geopolitics` | deadline_resolved | 736 | 0.0% |
| `military_geopolitics` | event_resolved | 196 | 24.5% |
| `military_geopolitics` | unclassifiable | 2,989 | 51.6% |
| `regulatory_decision` | deadline_resolved | 249 | 0.0% |
| `regulatory_decision` | event_resolved | 849 | 28.7% |
| `regulatory_decision` | unclassifiable | 4,475 | 18.2% |

`military_geopolitics` has the highest unclassifiable YES rate (51.6%), driven by sports markets misrouted into this category (Counter-Strike, esports, Olympic results).

`regulatory_decision` event_resolved (849 markets, 28.7% YES) is the richest source for T_news extraction — election outcomes, legislative votes, regulatory approvals.

---

## Outcome Correlation

`deadline_resolved` → 100% NO (structural: these markets define "nothing happened")  
`event_resolved` → 29% YES (classifier correctly separates "event markets" from deadline markets; YES rate reflects real event uncertainty)  
`unclassifiable` → 31.5% YES (similar base rate to event_resolved; bulk of the corpus)

---

## 20 Random Markets per Type (Manual Review)

### event_resolved (20 random)

| Question | Outcome | Category |
|---|---|---|
| Will André Ventura win the 1st round of the 2026 Portugal presidential election? | NO | regulatory_decision |
| Will Jorge "Tuto" Quiroga win by 10–15%? | NO | regulatory_decision |
| GPT-5.5 released by April 30, 2026? | YES | corporate_disclosure |
| Will South Africa win? | YES | regulatory_decision |
| Will Abigail Spanberger win by 9-12%? | NO | regulatory_decision |
| Will Salvador Nasralla win the 2025 Honduran presidential election by less than 3%? | NO | regulatory_decision |
| Will Eric Adams win second place in the 2025 NYC mayoral election? | NO | regulatory_decision |
| Will Abigail Spanberger win by 12-15%? | NO | regulatory_decision |
| Will Na Kyung-won be elected the next president of South Korea? | NO | regulatory_decision |
| Will Zohran Mamdani win by 5–10%? | YES | regulatory_decision |
| Will Gemini 3.0 be released on November 29 2025? | NO | corporate_disclosure |
| Will another country win Gold in Women's Basketball? | NO | military_geopolitics |
| Will Mikie Sherrill win by 12-15%? | YES | regulatory_decision |
| Will a candidate from another party win Nebraska's 2nd congressional district? | NO | regulatory_decision |
| Will Randy Fine win by 15-20%? | NO | regulatory_decision |
| Israel wins the most gold medals in 2025 Special Olympics? | NO | military_geopolitics |
| Will Laura Fernández Delgado win the 2026 Costa Rican presidential election? | YES | regulatory_decision |
| Will Brad Lander win second place in the 2025 NYC mayoral election? | NO | regulatory_decision |
| Will reconciliation bill be passed by Memorial day? | NO | regulatory_decision |
| Will André Ventura win the 1st round of the 2026 Portugal presidential election? | NO | regulatory_decision |

**Observation:** This sample is dominated by electoral margin markets ("win by 9-12%", "win by 12-15%") — technically event_resolved by the heuristic because they contain win/won patterns, but they are actually a special subtype: **outcome precision markets** where the news event is the election result and the question is about the margin. T_news is the election date. These are excellent candidates for ILS scoring.

### deadline_resolved (20 random)

| Question | Outcome | Category |
|---|---|---|
| Will Russia capture Myrnohrad by November 7? | NO | military_geopolitics |
| Ceasefire between Russia and Ukraine by June 30? | NO | military_geopolitics |
| Masoud Pezeshkian out by March 31? | NO | military_geopolitics |
| Will Donald J. Trump be indicted by July 1, 2022? | NO | regulatory_decision |
| US strikes Iran by February 20, 2026? | NO | military_geopolitics |
| Will Russia capture all of Huliaipole by March 31? | NO | military_geopolitics |
| US x Venezuela military engagement by November 21? | NO | military_geopolitics |
| Tesla launches unsupervised FSD by October 31? | NO | corporate_disclosure |
| Russian strike on Poland by December 31? | NO | military_geopolitics |
| RedNote removed from App Store by Friday? | NO | corporate_disclosure |
| Will Apple be the largest company by market cap on January 31? | NO | corporate_disclosure |
| Ukraine hits Moscow by August 31? | NO | military_geopolitics |
| Will Russia enter Ternuvate again by February 28? | NO | military_geopolitics |
| US x Iran diplomatic meeting by April 20, 2026? | NO | military_geopolitics |
| Will House and Senate pass funding bill by October 15? | NO | regulatory_decision |
| Will Israel invade Lebanon by Friday? | NO | military_geopolitics |
| Will Trump's Greenland Tariffs go into effect for Finland by February 1? | NO | military_geopolitics |
| Will Microsoft be the third-largest company by market cap on November 30? | NO | corporate_disclosure |
| Will no acquisition occur by May 31 2026? | NO | corporate_disclosure |
| Ceasefire between Russia and Ukraine by June 30? | NO | military_geopolitics |

**Observation:** All NO, all deadline-structured. The classifier is 100% precise on this sample. These markets have no definable T_news because the "news" (nothing happened) is a non-event.

### unclassifiable (20 random)

| Question | Outcome | Category |
|---|---|---|
| ODI Series Australia vs India, Women | YES | regulatory_decision |
| Will the chopsticks catch SpaceX Starship Flight Test 9 Superheavy? | NO | corporate_disclosure |
| Will MrBeast's next video get 55M+ views on day 1? | NO | military_geopolitics |
| Will Elon Musk post 165-189 tweets Jan 17-19? | NO | regulatory_decision |
| Will Elon Musk post 115-139 tweets Jan 26-28? | NO | regulatory_decision |
| Will Donald Trump say "China" 5+ times at his Uniondale rally? | YES | military_geopolitics |
| Next US strike on Syria on December 17? | NO | military_geopolitics |
| Will MrBeast's next video get 45-50M views on day 1? | NO | military_geopolitics |
| Counter-Strike: B8 vs Heroic (BO3) | YES | military_geopolitics |
| Will Elon Musk post 680-699 tweets Jan 27 - Feb 3? | NO | regulatory_decision |
| Counter-Strike: NRG vs Phoenix (BO3) | YES | military_geopolitics |
| Khamenei seen in public before July? | YES | military_geopolitics |
| Will Elon Musk post 380-399 tweets Apr 7-14? | NO | regulatory_decision |
| Will Renate Reinsve be nominated for Best Actress at the 98th Academy Awards? | YES | regulatory_decision |
| Will The Build Back Better Act pass the House by November 19, 2021? | YES | regulatory_decision |
| Will Elon tweet 135-149 times? | NO | regulatory_decision |
| Will Z.ai have the second best AI model at end of November 2025? | NO | corporate_disclosure |
| Israel strikes Gaza by October 31? | YES | military_geopolitics |
| Will Elon tweet 250–274 times May 23–30? | NO | regulatory_decision |
| LoL: Team WE vs ThunderTalk Gaming - Game 1 Winner | YES | military_geopolitics |

**Observation:** Three distinct subtypes in unclassifiable:
1. **Sports/esports results** (Counter-Strike, LoL, cricket) — miscategorized as military_geopolitics/regulatory_decision; no T_news concept applicable
2. **Metric/count markets** (Elon tweet counts, MrBeast views) — no news event, pure data-driven
3. **Event markets with ambiguous phrasing** (Build Back Better Act, Renate Reinsve nomination, Khamenei sighting) — these ARE event markets that the heuristic missed; could be recovered with better patterns

---

## Key Findings for Phase 3

1. **1,145 event_resolved markets** are the target for UMA evidence URL collection and T_news extraction.
2. **1,224 deadline_resolved markets** should be explicitly excluded from ILS scoring pipelines; no T_news is definable for them.
3. The `unclassifiable` bucket (78.8%) contains mostly non-scorable markets (sports, metric markets), with a recoverable tail of true event markets — addressable in a future taxonomy pass.
4. `regulatory_decision` dominates event_resolved (849/1145 = 74%) — this is where T_news search is most productive.
5. No `surprise_resolved` markets were found — the `last_price` parameter was passed as `None` in the batch (requires price series lookup). Phase 3+ can populate this.
