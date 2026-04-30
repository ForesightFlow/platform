# ForesightFlow — Project Charter

**Working name:** ForesightFlow
**Python package:** `fflow` (short import name; pattern: numpy/NumPy, tf/TensorFlow)
**Status:** v0.2 — paper draft v0.3, Task 01 in progress
**Last updated:** April 25, 2026
**Languages:** Code & publication in English; team communication in Russian/English
**GitHub org:** https://github.com/ForesightFlow
**Site:** https://foresightflow.xyz
**Author / lead:** Maksym Nechepurenko (Devnull FZCO, Dubai)

---

## 1. Project Purpose

**One-line:** Build an early-warning system that detects informed-flow signatures in Polymarket prediction markets in the final hours before resolution, producing actionable signals for both research and operational use.

**Two parallel deliverables:**

1. **Research paper** targeting the *Workshop on Mechanism Design for Social Good* (with arXiv preprint as intermediate milestone).
2. **Production monitoring system** deployed on AWS, with web dashboard and Telegram alerting.

The research paper is written first as a theoretical preprint (sections 1–5). System implementation follows. Backtest results are then incorporated into the paper for the full version.

---

## 2. Task Reformulation (canonical)

The task is **NOT** post-hoc identification of insiders in resolved markets. It is **NOT** building a "leakage atlas" as a research artifact.

The task **IS**: real-time inference on active, unresolved markets — for a given market in its final hours, estimate the probability that microstructure and on-chain features indicate informed trading is occurring, such that an outside observer could enter a comparable position before resolution.

**Implications:**
- Historical labeled data (ILS computed on resolved markets) is the **training set**, not the deliverable.
- Detection horizon: typically the last 2 hours before resolution, but extendable.
- Output: a calibrated probability + feature attribution for active markets, not a wallet identity.
- We are doing **online change detection** on order flow, augmented by on-chain wallet features.

---

## 3. Scope — Categories (PoC)

We restrict to three high-priority categories where insider information is plausible and historically documented:

### 3.1 Military / Geopolitics actions

**Operational definition:** Markets resolving on specific state actions whose date and content become public at the moment of announcement or execution.

**Includes:** military strikes, troop movements, diplomatic recognition, treaty signings, prisoner exchanges, sanction announcements, embassy openings/closings, hostage releases.

**Excludes:** outcome of ongoing conflicts ("will war end by date X"), election outcomes, opinion polls, generic geopolitical sentiment.

**Documented insider cases:** US strike on Iran (Feb 28, 2026), Venezuela operation (Jan 2026), Maduro capture market.

### 3.2 Corporate proprietary disclosures

**Operational definition:** Markets resolving on specific corporate events whose date or content is known to a narrow circle within the company prior to public announcement.

**Includes:** product launch dates, M&A announcements, earnings beats/misses on specific metrics, executive hires/fires, regulatory filings, IP releases, proprietary dataset publications (e.g., Google Year in Search).

**Excludes:** stock price levels, generic "will company X succeed", broad sentiment.

**Documented insider cases:** AlphaRaccoon on Google Year in Search, OpenAI browser launch, Gemini 3.0 release date.

### 3.3 Regulatory decisions

**Operational definition:** Markets resolving on specific regulatory decisions with date-bounded resolution criteria.

**Includes:** FDA approvals, FCC rulings, SEC enforcement actions, central bank rate decisions (only where outcomes are concrete numerical levels), court rulings, antitrust decisions.

**Excludes:** generic "will regulation X happen this year", broad policy direction predictions.

### 3.4 Out of scope (PoC)

Sports, weather, election polling outcomes, cryptocurrency price levels, entertainment awards (note: Taylor Swift engagement case crosses into corporate; if needed handled as one-off). These categories serve as **null-hypothesis controls** for metric calibration only — not for detection.

---

## 4. Information Leakage Score (ILS) — formal definition

For a resolved market $M$ with three known timestamps:
- $T_{\text{open}}$ — market creation / first trade
- $T_{\text{news}}$ — first public mention of resolution-relevant information
- $T_{\text{resolve}}$ — UMA Optimistic Oracle resolution

Let $p(t)$ denote the mid-price at time $t$, and let $p_{\text{resolve}} \in \{0, 1\}$ be the binary resolution.

**Pre-news drift:** $\Delta_{\text{pre}} = p(T_{\text{news}}) - p(T_{\text{open}})$

**Total information move:** $\Delta_{\text{total}} = p_{\text{resolve}} - p(T_{\text{open}})$

**Information Leakage Score:**

$$\text{ILS} = \frac{\Delta_{\text{pre}}}{\Delta_{\text{total}}}, \quad \text{when } |\Delta_{\text{total}}| > \varepsilon$$

**Interpretation:**
- $\text{ILS} \approx 1$: full information was priced in before public news (strong leakage)
- $\text{ILS} \approx 0$: market reacted to public news as expected (no leakage)
- $\text{ILS} > 1$: overshoot before news (overreaction or speculation correctly directed)
- $\text{ILS} < 0$: pre-news price moved against the eventual outcome (counter-evidence)

**Multi-window variants:** $\text{ILS}_{24h}$, $\text{ILS}_{2h}$, $\text{ILS}_{30\text{min}}$ — leakage measured at varying lookback windows before $T_{\text{news}}$. Together they form a **timing profile** of information arrival.

---

## 5. Auxiliary Metrics

**Pre-news volume share:**
$$V_{\text{pre}} = \frac{\sum_{t < T_{\text{news}}} v(t)}{\sum_{t \leq T_{\text{resolve}}} v(t)}$$

**Pre-news price jump:** maximum single-trade price impact in the window $[T_{\text{open}}, T_{\text{news}}]$.

**Wallet concentration index (HHI):** Herfindahl-Hirschman index over the top-10 winning trades in the market.

**Time-to-news distribution:** for each of the top-10 winning trades, the time gap to $T_{\text{news}}$. Heavy right-tail (many trades clustered just before news) is a leakage signature.

**Wallet Novelty Score:** weighted composite of indicators per trader $w$ at trade time $t$:

$$\text{WN}(w, t) = \alpha_1 \mathbb{1}_{\text{age}(w) < 48h} + \alpha_2 \mathbb{1}_{|\text{markets}(w, < t)| < 3} + \alpha_3 \cdot \text{funding\_concentration}(w) + \alpha_4 \mathbb{1}_{\text{entered\_within\_2h\_of\_resolution}}$$

Weights $\alpha_i$ fitted on labeled cases.

---

## 6. Microstructure Signatures

We adapt classical informed-trading detection to discrete binary markets.

**PIN (Probability of Informed Trading)** — Easley, Kiefer, O'Hara, Paperman (1996). Decomposes order flow into uninformed and informed components.

**VPIN (Volume-Synchronized PIN)** — Easley, López de Prado, O'Hara (2012). Uses volume buckets instead of time, more robust under varying activity.

**Kyle's lambda** — price impact per unit of order flow. Higher lambda implies more informed flow.

**Order imbalance:** $\text{OI}(t) = \frac{V_{\text{buy}}(t) - V_{\text{sell}}(t)}{V_{\text{buy}}(t) + V_{\text{sell}}(t)}$ over rolling windows.

**Trade size distribution:** informed trades cluster at specific sizes (typically larger than retail, smaller than market-maker).

**Time-clustering of trades:** Hawkes-process-style self-excitation as informed trader breaks position into pieces.

**Adaptation note:** Classical PIN assumes a continuous-quote market with known buy/sell classification. Polymarket CLOB has explicit trade direction in subgraph data, simplifying classification. Binary outcome bounds prices in $[0, 1]$, requiring rescaling for some metrics.

---

## 7. Data Sources

### 7.1 Polymarket (primary)

| Source | Access | Use |
|---|---|---|
| Gamma API (`gamma-api.polymarket.com`) | REST, no auth | Market metadata, tags, resolution criteria |
| CLOB API (`clob.polymarket.com`) | REST + WebSocket | Live and historical price/volume, order book |
| Subgraph (The Graph) | GraphQL, API key | Full historical trade log per market — **critical** |
| UMA Optimistic Oracle | On-chain + subgraph | Resolution timestamps and proposer evidence URLs |
| Polygonscan | REST API | Wallet-level on-chain data, funding sources |

**Subgraph access:** project has API key (acquired). Decision: hosted service or decentralized network — **decision pending**, default to hosted for PoC.

### 7.2 News timestamps

| Source | Use |
|---|---|
| **GDELT 2.0** (BigQuery) | Primary — global news with minute-level timestamps, multi-language. Free tier on GCP (1 TB/month) sufficient. |
| UMA proposer evidence URLs | Highest-authority $T_{\text{news}}$ per market — proposer often links the source article. |
| LLM-assisted matching (Tavily/Exa) | Disambiguation only, for validation set |
| Internet Archive Wayback | URL-level "first seen" verification |

**T_news methodology hierarchy:**
1. UMA proposer evidence URL → fetch original article timestamp
2. GDELT GKG keyword match against market question
3. LLM-assisted matching for failed cases (validation set only)

### 7.3 Wallet intelligence

| Source | Use | Decision |
|---|---|---|
| Polygonscan API | Free wallet on-chain data | Use |
| Polysights | Pre-labeled suspicious wallets | Investigate API; use if cheap |
| Wallet Master Polymarket Radar | 7M wallets, 80+ metrics, $125/mo | **Defer** — build our own, save budget |
| Arkham / Nansen | Institutional labels | **Skip** — too expensive |

---

## 8. Architecture

### 8.1 System diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    DATA LAYER                                │
├─────────────────────────────────────────────────────────────┤
│  Polymarket Gamma     │  CLOB Price History                 │
│  Polymarket Subgraph  │  UMA Optimistic Oracle              │
│  GDELT 2.0 (BigQuery) │  Polygonscan API                    │
└─────────────────┬───────────────────────────┬───────────────┘
                  │                           │
        ┌─────────▼──────────┐    ┌──────────▼──────────┐
        │ HISTORICAL BACKFILL│    │  REAL-TIME INGEST   │
        │ (batch, scheduled) │    │  (streaming)        │
        └─────────┬──────────┘    └──────────┬──────────┘
                  │                           │
        ┌─────────▼───────────────────────────▼──────────┐
        │           POSTGRES + TIMESCALEDB                │
        │  markets │ trades │ prices │ scores │ alerts   │
        └─────────┬───────────────────────────┬──────────┘
                  │                           │
        ┌─────────▼──────────┐    ┌──────────▼──────────┐
        │  ANALYTICS ENGINE  │    │  DETECTION ENGINE   │
        │  ILS computation   │    │  PIN/microstructure │
        │  Category stats    │    │  Wallet novelty     │
        │  Model training    │    │  News correlation   │
        └─────────┬──────────┘    └──────────┬──────────┘
                  │                           │
                  └─────────┐    ┌────────────┘
                            │    │
                  ┌─────────▼────▼─────────┐
                  │       API LAYER         │
                  │  FastAPI + WebSocket    │
                  └────────┬────────────────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
      ┌─────▼─────┐  ┌────▼─────┐  ┌────▼─────┐
      │  React    │  │ Telegram │  │  Public  │
      │ Dashboard │  │   Bot    │  │   API    │
      └───────────┘  └──────────┘  └──────────┘
```

### 8.2 Module layout (Python package `fflow`)

| Module | Responsibility |
|---|---|
| `fflow.collectors` | Source-specific clients (gamma, clob, subgraph, gdelt, polygonscan, uma) |
| `fflow.taxonomy` | Market categorization — Polymarket tags + LLM fine-grained classifier |
| `fflow.scoring` | ILS, microstructure (PIN/VPIN), wallet novelty, news lag |
| `fflow.detector` | Real-time feature extraction, inference, alert generation |
| `fflow.api` | FastAPI app — REST + WebSocket |
| `fflow.workers` | Background jobs — backfill, scheduled refresh, stream consumers |
| `fflow.ui` | React frontend (separate codebase) |
| `fflow.bot` | Telegram bot (separate service) |

### 8.3 Stack

**Backend:** Python 3.12, FastAPI, asyncio, SQLAlchemy + Alembic, Pydantic.  
**Storage:** PostgreSQL 16 + TimescaleDB extension; Redis for real-time state & alert dedup.  
**ML:** scikit-learn (logistic, GBM baselines); PyTorch only if sequence models needed.  
**Frontend:** React + Vite, TypeScript, TanStack Query, Recharts, shadcn/ui.  
**Deployment:** AWS — ECS Fargate (backend), RDS Postgres, ElastiCache Redis, CloudFront + S3 (frontend), EventBridge (cron).  
**Telegram:** python-telegram-bot, separate microservice.  
**Cost target:** $80–120/month within $1K AWS credits.

---

## 9. Research Paper — Structure

Target venue: **Workshop on Mechanism Design for Social Good**. Preprint on arXiv (cs.CY or q-fin.TR).

```
1. Introduction
   - Insider trading documented at scale ($143M, Mitts & Ofir 2026)
   - Post-hoc detection ≠ actionable signal
   - Gap: real-time detection in last hours before resolution
   - Contribution: PIN-style microstructure detector + on-chain wallet
     features, validated on labeled insider cases

2. Related Work
   - Market microstructure: PIN (Easley et al. 1996), VPIN (2012), Kyle's lambda
   - Prediction market efficiency (Wolfers & Zitzewitz; Hanson; Berg & Rietz)
   - Blockchain forensics on Polymarket (IMDEA 2025, Mitts & Ofir 2026)
   - Gap statement

3. Data & Categorization
   - 3 high-priority categories: definitions, examples, scope (this charter §3)
   - 2-year sample (Apr 2024 – Apr 2026), sources (§7)
   - News-timestamp methodology (§7.2)

4. Information Leakage Score (ILS)
   - Formal definition (this charter §4)
   - Auxiliary metrics (§5)
   - Validation against known insider cases (Iran, Venezuela, Google
     Year in Search, OpenAI launches, Maduro, Taylor Swift)

5. Microstructure Signatures of Informed Flow
   - Adaptation of PIN/VPIN to discrete binary markets (§6)
   - Order imbalance, trade size, time-clustering
   - Wallet-novelty as on-chain native feature
   - Detector model (logistic / GBM / lightweight transformer)

6. Real-Time Detection System
   - Architecture (§8 — full system spec is parallel deliverable)
   - Feature pipeline at minute resolution
   - Calibration on backtest data
   - Latency budget

7. Backtest Results [populated after implementation]
   - Precision/recall on labeled test set
   - Time-to-detection distribution
   - PnL of "follow detected signal" strategy with realistic execution
   - Ablations (no microstructure / no on-chain / no news context)

8. Discussion
   - What signals are actually predictive
   - Limitations: small N of confirmed insider cases, label noise
   - Ethical & legal considerations
   - Public-good angle: same system useful for regulators

9. Conclusion + Future Work
```

**Drafting order:** sections 1–5 written first as theoretical preprint (no data needed). Sections 6–7 added after implementation produces results.

---

## 10. Decisions Log

| # | Decision | Resolution | Date |
|---|---|---|---|
| D1 | Task formulation | Real-time detection, NOT post-hoc atlas | 2026-04-25 |
| D2 | Categories for PoC | Military/Geopolitics, Corporate, Regulatory | 2026-04-25 |
| D3 | Order of work | Theoretical preprint first, then implementation, then results | 2026-04-25 |
| D4 | Historical horizon | 2 years (Apr 2024 – Apr 2026) | 2026-04-25 |
| D5 | Subgraph access | API key acquired, hosted service | 2026-04-25 |
| D6 | News source | GDELT primary + UMA proposer evidence | 2026-04-25 |
| D7 | LLM matching | Used for validation set only — cost discipline | 2026-04-25 |
| D8 | AWS budget | $1K credits, target ≤$120/month | 2026-04-25 |
| D9 | GCP for BigQuery | Will create account; explore credits | 2026-04-25 |
| D10 | Manual labeling | Use only existing public cases — no manual labeling time budget | 2026-04-25 |
| D11 | Target venue | Workshop on Mechanism Design for Social Good | 2026-04-25 |
| D12 | Output formats | Backend + React frontend (AWS) + Telegram bot | 2026-04-25 |
| D13 | Open data | Yes, with license — to be selected | 2026-04-25 |
| D14 | Working name | ForesightFlow (subject to revision) | 2026-04-25 |
| D15 | Naming convention | Brand: ForesightFlow. Python package import-name: `fflow`. CLI: `fflow`. Env prefix: `FFLOW_`. Pattern follows numpy/NumPy, tf/TensorFlow. | 2026-04-25 |
| D16 | GitHub org and repo | `github.com/ForesightFlow/platform` for the system code. Paper artifacts may live in a separate repo TBD. | 2026-04-25 |
| D17 | Dataset repository | Separate public repository under `ForesightFlow` org for the FFIC inventory and future labelled datasets. Working name: `github.com/ForesightFlow/datasets` with `ffic/` subdirectory. License: CC-BY-4.0 per D13. To be created when FFIC manifest is finalized. | 2026-04-26 |
| D15 | Python package name | `fflow` (short import); brand stays "ForesightFlow" | 2026-04-25 |
| D16 | Paper version | v0.3 (sections 1–5 complete + Limitations + GenAI disclosure) | 2026-04-25 |
| D17 | Repo structure | Single repo `ForesightFlow/platform` for Task 01–10 | 2026-04-25 |

---

## 11. Open Questions / TBD

- ~~**License selection** for published dataset and code~~ — RESOLVED: CC-BY-4.0 for data (D13), MIT for code (D17 implies)
- **Final paper title** — current working: *"ForesightFlow: Real-Time Detection of Informed Trading in Decentralized Prediction Markets"*.
- ~~**Ground-truth set size**~~ — RESOLVED via FFIC: 8 documented cases / 24 markets (see paper §3.5, DOCUMENTED_CASES_INVENTORY.md). Will expand as new public episodes accumulate.
- **Subgraph hosted vs decentralized** — using The Graph gateway with API key (working). Indexer-capacity limits on $1B+ markets documented (paper §5.6).
- **Cost ceiling for LLM matching** — if validation-set matching exceeds $50, switch to manual review.
- **Backtest realism** — slippage and execution-failure modeling for "follow signal" PnL.

### Outstanding TODOs

- **Create `github.com/ForesightFlow/datasets` repository** (per D17) when FFIC manifest is finalized in `task feat/insider-cases-dataset`. Initial structure: `ffic/` subdirectory with `cases.yaml`, `manifest_schema.json`, `sources/` directory. License header: CC-BY-4.0. Should include README citing the paper and explaining usage for reproducibility.
- **Re-attempt indexer access for $1B+ markets** (Trump/Harris 2024 election top-line markets) via either self-hosted subgraph or direct Polygon JSON-RPC event-log decoding. Defer until after Task 06 (detector training) — these markets are not strictly required for initial validation but would close a coverage gap.
- **GCP project setup for GDELT** — required for Tier 2 T_news recovery on markets without UMA evidence URLs. Free tier (1 TB queries/month) sufficient for current scope.

---

## 12. Immediate Next Actions

1. ✅ Charter committed (this document, v0.2).
2. ✅ **Draft preprint sections 1–5** — complete in v0.3, including Limitations and GenAI disclosure.
3. ⏳ **Task 01 (in progress, Claude Code):** scaffold `fflow` repo, set up data layer schemas, implement five collectors.
4. ➡ **Task 02:** T_news recovery (GDELT + UMA proposer) and ILS computation.
5. ➡ **Task 03:** LLM-based taxonomy classifier upgrade.
6. ➡ **Task 04:** Microstructure features (PIN/VPIN/Kyle's lambda/VR/TS/Hawkes).
7. ➡ **Task 05:** Real-time WebSocket streaming layer.
8. ➡ **Task 06:** Detector model training + calibration.
9. ➡ **Task 07:** FastAPI server.
10. ➡ **Task 08:** React frontend.
11. ➡ **Task 09:** Telegram bot.
12. ➡ **Task 10:** AWS deployment.
13. ➡ Backtest results → paper sections 6–7 → v1.0 + submission to Workshop on Mechanism Design for Social Good.

---

## 13. Glossary

- **CLOB** — Central Limit Order Book; Polymarket's hybrid off-chain matching, on-chain settlement system.
- **CTF** — Conditional Token Framework (Gnosis); the smart-contract layer Polymarket uses for outcome tokens.
- **GDELT** — Global Database of Events, Language, and Tone; open-source news event archive.
- **GKG** — Global Knowledge Graph; GDELT's entity-and-theme-tagged news index.
- **HHI** — Herfindahl-Hirschman Index; concentration measure.
- **ILS** — Information Leakage Score; central metric of this work.
- **MNPI** — Material Nonpublic Information.
- **PIN** — Probability of Informed Trading; Easley et al. 1996.
- **UMA** — Universal Market Access; Polymarket's resolution oracle (Optimistic Oracle).
- **VPIN** — Volume-synchronized PIN; Easley, López de Prado, O'Hara 2012.

---

*End of charter v0.2.*
