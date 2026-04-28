# Task 03 — Hazard Estimation Report

Generated: 2026-04-28 05:39 UTC  
Total Tier-3 calls: 60 | Est. cost: ~$5.40

## Methodology

For each category, 20 YES-resolved deadline markets were sampled randomly.
T_event was recovered via Tier 3 (Claude + web search, `recovery_mode='t_event'`).
τ = T_event − T_open in days. Exponential MLE: λ̂ = 1/mean(τ).
KS test: pvalue < 0.05 → reject exponential (use λ as approximate).

## Results by Category

| Category | n | λ (events/day) | Half-life (days) | mean τ | p25 | p50 | p75 | KS stat | KS p |
|---|---|---|---|---|---|---|---|---|---|
| military_geopolitics | 9 | 0.3064 | 2.3 | 3.3 | 2.0 | 2.2 | 4.1 | 0.238 | 0.609 |
| regulatory_decision | 15 | 0.0348 | 19.9 | 28.7 | 1.7 | 4.3 | 34.2 | 0.394 | 0.013 |
| corporate_disclosure | 5 | 0.1556 | 4.5 | 6.4 | 0.6 | 6.1 | 11.5 | 0.312 | 0.616 |

## Interpretation

- **military_geopolitics**: median event occurs 2.2 days after market open; half-life 2.3 d. KS: exponential fit adequate.
- **regulatory_decision**: median event occurs 4.3 days after market open; half-life 19.9 d. KS: REJECT exponential (p<0.05) — use λ as rough approximation only.
- **corporate_disclosure**: median event occurs 6.1 days after market open; half-life 4.5 d. KS: exponential fit adequate.

## Per-Market Detail

### military_geopolitics

| Market (truncated) | T_open | T_event | τ (days) | conf | Sources |
|---|---|---|---|---|---|
| Will Trump say "China" 10+ times during his cabinet meeting  | 2025-04-09 | 2025-04-10 | 0.1 | 0.80 | Roll Call, Deseret News, Fox 4 Dallas-Fort Worth |
| Will Trump say "Dome" during Fort Bragg remarks on June 10? | 2025-06-09 | 2025-06-10 | 0.1 | 0.80 | C-SPAN, Reuters (PBS News), Senate Democratic Leadership |
| Will Trump say "Hottest" during Egypt summit? | 2025-10-10 | 2025-10-13 | 2.0 | 0.80 | ABC News, Reuters, Al Jazeera |
| Will Trump say "Secretary of War" during Medal of Honor cere | 2026-02-27 | 2026-03-02 | 2.1 | 0.80 | AP (Associated Press), PBS News Hour, National Guard |
| Will Trump say "Nuclear" during Board of Peace events on Feb | 2026-02-16 | 2026-02-19 | 2.2 | 0.80 | NPR, CNN, Time |
| Will Trump say "Nuclear" during Bukele visit on April 14? | 2025-04-10 | 2025-04-14 | 3.1 | 0.80 | CNN, ABC News, NBC Washington |
| Will Trump say "China" 7+ times during his AI speech on July | 2025-07-18 | 2025-07-23 | 4.1 | 0.80 | PBS NewsHour (AP), Axios, CNN |
| Will John Oliver say "Iran" on Last Week Tonight? | 2026-02-16 | 2026-02-22 | 6.3 | 0.80 | HBO Max, IMDB, Rotten Tomatoes |
| Will Hamas release more hostages by November 30? | 2023-11-14 | 2023-11-24 | 9.3 | 0.80 | Al Jazeera, Washington Post, NPR |

### regulatory_decision

| Market (truncated) | T_open | T_event | τ (days) | conf | Sources |
|---|---|---|---|---|---|
| FDA approves Merck’s clesrovimab infant RSV prevention (MK‑1 | 2025-06-08 | 2025-06-09 | 0.2 | 0.80 | Merck, FDA (accessdata.fda.gov), CDC MMWR |
| Will Trump say "Million" or "Billion" or "Trillion" 20+ time | 2026-01-12 | 2026-01-13 | 0.3 | 0.80 | NPR, CNN, PolitiFact |
| Will anyone say "Inflation" during the FED board meeting on  | 2025-10-23 | 2025-10-24 | 0.7 | 0.80 | Federal Reserve Board (official transcript), Federal Reserve on X/Twitter |
| Will Trump say "Big Beautiful Bill" at the Turkey Pardon on  | 2025-11-23 | 2025-11-25 | 1.2 | 0.80 | CNN, NBC News, PBS NewsHour/AP |
| Will Bernie say "Million" or "Billion" or "Trillion" 10+ tim | 2025-10-13 | 2025-10-15 | 2.1 | 0.80 | CNN Politics, CNN Pressroom, Variety |
| Will Bernie Sanders say "Corporation" during Fighting Oligar | 2025-08-21 | 2025-08-24 | 2.2 | 0.80 | Chicago Sun-Times, People's World, Hoodline |
| Bonnie Blue leaves Indonesia by December 31? | 2025-12-09 | 2025-12-13 | 3.2 | 0.80 | Jakarta Globe, ANTARA News (Indonesian state news agency), Yahoo News Singapore |
| Cho Tae-yong in jail by November 30?  | 2025-11-07 | 2025-11-12 | 4.3 | 0.80 | Reuters, AP/Yonhap, Al Jazeera |
| Oscars 2022: Will any film win 6 or more awards? | 2022-03-17 | 2022-03-27 | 9.1 | 0.80 | ABC News, Rotten Tomatoes, Good Morning America |
| Will South Korea qualify from Group H? | 2022-11-18 | 2022-12-02 | 13.1 | 0.80 | CNN, Al Jazeera, Wikipedia |
| Will Robert MacIntyre make the 2025 Europe Ryder Cup team? | 2025-07-21 | 2025-08-18 | 27.2 | 0.80 | Ryder Cup (official), ESPN, PGA Tour |
| Will Jon Rahm make the 2025 Europe Ryder Cup team? | 2025-07-21 | 2025-09-01 | 41.2 | 0.80 | LIV Golf, Ryder Cup (Official), Golf.com |
| Will Jean Smart win the Emmy for Outstanding Lead Actress in | 2025-07-16 | 2025-09-14 | 59.2 | 0.80 | ABC News, CBS News, Deadline |
| Will Mark Teixeira be the Republican nominee for TX-21? | 2025-11-25 | 2026-03-03 | 97.1 | 0.80 | KSAT, KUT Radio, FOX 7 Austin |
| Will Sean Penn win Best Supporting Actor at the 98th Academy | 2025-09-26 | 2026-03-15 | 169.3 | 0.80 | ABC7 Los Angeles, ABC7 New York, ABC News |

### corporate_disclosure

| Market (truncated) | T_open | T_event | τ (days) | conf | Sources |
|---|---|---|---|---|---|
| Will Biden announce he is running for president by Friday? | 2023-04-24 | 2023-04-25 | 0.3 | 0.80 | Wikipedia, PBS NewsHour, Washington Post |
| Will Eli Lilly say "Impact" during earnings call? | 2026-02-03 | 2026-02-04 | 0.6 | 0.80 | Eli Lilly official investor relations, Yahoo Finance, Public.com |
| Will Microsoft say "Windows" during earnings call? | 2025-10-23 | 2025-10-29 | 6.1 | 0.80 | Microsoft Investor Relations, CNBC, The Motley Fool |
| Will Uber say "Delivery" during earnings call? | 2025-10-23 | 2025-11-04 | 11.5 | 0.80 | SEC filing (investor.uber.com), CNBC, Benzinga |
| Will Jensen Huang say "AI" or "Artificial Intelligence" 10+  | 2026-03-02 | 2026-03-16 | 13.6 | 0.80 | NVIDIA Blog, CNBC, Tom's Hardware |

