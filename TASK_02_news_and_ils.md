# ForesightFlow — Claude Code Task 02: T_news Recovery and ILS Computation

**Project:** ForesightFlow
**Python package:** `fflow`
**Repo:** https://github.com/ForesightFlow/platform
**Site:** https://foresightflow.xyz
**Author / lead:** Maksym Nechepurenko (Devnull FZCO)
**Companion documents:** `CHARTER.md`, `TASK_01_scaffold_collectors.md` (prerequisite)
**Companion paper:** `foresightflow_draft_v0.3.pdf` (Section 4 — Information Leakage Score)

---

## 0. How to read this document

This is **Task 02** of the ForesightFlow implementation. It depends on **Task 01** being complete: the data pipeline must be functional, with markets, prices, trades, wallets, and UMA resolution metadata already populated for at least the sample of 10+ markets. If `python scripts/backfill_sample.py` is not green, do not start Task 02 — fix Task 01 first.

The deliverable of Task 02 is the historical labelling layer: for every resolved market in the database, recover the news timestamp `T_news`, compute the Information Leakage Score (ILS) and its auxiliary metrics, and persist the labels in a new table. No real-time detection, no microstructure features beyond what's needed for ILS, no UI. Just: **for every resolved market, compute and store the labels described in Section 4 of the paper**.

---

## 1. Context (one page)

### 1.1 Why this task is the methodological heart of the project

The paper (Section 4) defines the Information Leakage Score as

```
ILS(M) = (p(T_news) - p(T_open)) / (p_resolve - p(T_open))
```

This single quantity is the supervised label that every downstream component will be trained against, calibrated to, or evaluated on. If `T_news` is wrong, every downstream claim is wrong. If ILS is computed inconsistently across categories or windows, ablation studies will be uninterpretable.

**Therefore: this task prioritizes correctness, traceability, and reproducibility over throughput or feature breadth.** Every label written to the database must carry enough provenance to be re-derived.

### 1.2 What we have after Task 01

- `markets` table populated with metadata, including `created_at_chain` (= `T_open`), `resolved_at` (= `T_resolve`), `resolution_outcome`, and `resolution_evidence_url` from UMA.
- `prices` hypertable with one-minute mid-price history for each market.
- `trades` table with full trade log per market.
- `wallets` table with on-chain context for traders we've seen.
- `data_collection_runs` for observability.

### 1.3 What we need to add in Task 02

A new schema layer for labels and provenance, three new collectors / processors, and the ILS computation itself. Fully described in Section 3.

### 1.4 Key formal references (paper Sec. 4)

- **Definition 1 (ILS):** as above. `ε = 0.05` threshold on `|Δ_total|` filters markets that barely moved.
- **Multi-window variants:** `ILS_w` for `w ∈ {30min, 2h, 6h, 24h, 7d}` measures the fraction of pre-news drift that occurred in the last `w` before `T_news`.
- **Pre-news volume share:** `V_pre(M) = vol(t < T_news) / vol(t ≤ T_resolve)`.
- **Pre-news price jump:** max single-trade price impact in `[T_open, T_news]`.
- **Wallet concentration HHI:** Herfindahl over top-10 winning trades.
- **Time-to-news distribution:** for each of top-10 winning trades, gap `T_news − t_i`.
- **Wallet Novelty Score:** weighted composite (weights left as TBD constants in DB; for Task 02, store the components, not the weighted sum).

---

## 2. Deliverables

```
fflow/
├── fflow/
│   ├── news/
│   │   ├── __init__.py
│   │   ├── proposer_url.py     # Tier 1: UMA proposer evidence URL → publish timestamp
│   │   ├── gdelt.py            # Tier 2: GDELT GKG keyword matching via BigQuery
│   │   └── llm_match.py        # Tier 3: LLM-assisted matching (validation set only, opt-in)
│   ├── scoring/
│   │   ├── __init__.py
│   │   ├── ils.py              # ILS + multi-window variants
│   │   ├── volume.py           # pre-news volume share, price jump
│   │   ├── wallet_features.py  # HHI, time-to-news distribution, WN components
│   │   └── pipeline.py         # orchestrates per-market label computation
│   ├── cli.py                  # extended with: news, score subcommands
│   └── ...                     # existing Task 01 modules unchanged
├── alembic/versions/
│   └── 0002_labels_schema.py
├── scripts/
│   ├── label_sample.py         # end-to-end: T_news + ILS for the Task 01 sample
│   └── validate_labels.py      # sanity checks on label distributions
└── tests/
    ├── test_proposer_url.py
    ├── test_gdelt.py
    ├── test_ils.py             # synthetic price series with known ILS
    ├── test_wallet_features.py
    └── cassettes/              # extended with GDELT and LLM cassettes
```

---

## 3. Implementation details

### 3.1 New tables (Alembic migration `0002_labels_schema.py`)

#### `news_timestamps`

The recovered `T_news` for each market, with provenance.

- `market_id` (str, FK markets.id, PK)
- `t_news` (timestamptz, NOT NULL)
- `tier` (smallint, NOT NULL) — `1` = UMA proposer URL, `2` = GDELT, `3` = LLM-assisted
- `source_url` (text, nullable) — the article/publication used to derive `t_news`
- `source_publisher` (text, nullable) — e.g., `reuters.com`, `bbc.com`
- `confidence` (numeric(3, 2)) — heuristic 0–1 confidence in the recovered timestamp
- `query_keywords` (text[]) — for tier 2/3, the keywords used in the search
- `notes` (text, nullable) — anything worth recording for later audit
- `recovered_at` (timestamptz, NOT NULL) — when we wrote this row
- `recovered_by_run_id` (bigint, FK `data_collection_runs.id`) — for full traceability

Index: `tier`, `confidence`.

#### `market_labels`

The full label vector per market, recomputable from the underlying tables but materialized for query speed.

- `market_id` (str, FK markets.id, PK)
- `t_open` (timestamptz, NOT NULL) — copy of `markets.created_at_chain`, denormalized for self-containment
- `t_news` (timestamptz, NOT NULL) — copy of `news_timestamps.t_news`
- `t_resolve` (timestamptz, NOT NULL) — copy of `markets.resolved_at`
- `p_open` (numeric(8, 6))
- `p_news` (numeric(8, 6))
- `p_resolve` (smallint) — 0 or 1
- `delta_pre` (numeric(8, 6)) — `p_news − p_open`
- `delta_total` (numeric(8, 6)) — `p_resolve − p_open`
- `ils` (numeric(10, 6), nullable) — NULL when `|delta_total| < ε`
- `ils_30min` (numeric(10, 6), nullable)
- `ils_2h` (numeric(10, 6), nullable)
- `ils_6h` (numeric(10, 6), nullable)
- `ils_24h` (numeric(10, 6), nullable)
- `ils_7d` (numeric(10, 6), nullable)
- `volume_pre_share` (numeric(8, 6))
- `pre_news_max_jump` (numeric(8, 6))
- `wallet_hhi_top10` (numeric(8, 6))
- `time_to_news_top10` (jsonb) — list of `{wallet, t_trade, gap_seconds, size_shares}`
- `n_trades_total` (int)
- `n_trades_pre_news` (int)
- `category_pmscope` (str) — denormalized from `markets.category_pmscope` for fast filtering (called `category_fflow` here for naming consistency — choose either, just be consistent)
- `computed_at` (timestamptz)
- `computed_by_run_id` (bigint, FK `data_collection_runs.id`)
- `flags` (text[], default `'{}'`) — list of warnings/issues, e.g., `['low_volume_at_tnews', 'price_history_gap_pre_news']`

Indexes: `category_pmscope`, `ils`, `volume_pre_share`, `t_news`.

**Note on naming:** Task 01's `markets.category_pmscope` was an artifact of the earlier `pmscope` package name. After D15 in CHARTER, the correct column name is `category_fflow`. Either rename the column in this migration or keep the old name and use it consistently — but document the choice. **Preferred:** rename to `category_fflow` in `0002_labels_schema.py` to align with the package name.

#### `label_audit`

Append-only event log for label changes. Useful when re-running labels with revised methodology.

- `id` (bigserial PK)
- `market_id` (str)
- `event_type` (str) — e.g., `'tnews_added'`, `'tnews_revised'`, `'ils_computed'`, `'ils_recomputed'`, `'flagged'`
- `details` (jsonb)
- `created_at` (timestamptz)

### 3.2 Tier 1: UMA proposer URL → timestamp (`fflow/news/proposer_url.py`)

For each resolved market, `markets.resolution_evidence_url` is a URL extracted from UMA `ancillaryData` during Task 01.

**Steps:**

1. Validate URL: schema must be `http(s)://`, host must not be a Polymarket-internal URL or a UMA dispute resolution URL (these are circular). Maintain a denylist: `{polymarket.com, uma.xyz, oracle.uma.xyz}`.
2. Fetch the URL with `httpx`, follow redirects, extract publish-timestamp candidates from:
   - HTTP `Last-Modified` header (weak signal, cache-influenced).
   - `<meta property="article:published_time" content="...">` (strongest, most outlets).
   - `<meta property="og:published_time" content="...">`.
   - JSON-LD `<script type="application/ld+json">` with `datePublished` field.
   - `<time datetime="...">` element (fallback).
3. Pick the earliest plausible timestamp from the above. Plausibility check: must be within `[T_open, T_resolve + 7 days]`. Resolutions can lag the news by up to a week.
4. Persist with `tier=1`, `confidence=0.95` if `article:published_time` was found, `0.85` for og or JSON-LD, `0.65` for `<time>`, `0.40` for `Last-Modified` only.

**Failure handling:** if no timestamp can be extracted, do not insert; log at WARNING and let Tier 2 handle this market.

**Robots and respect:** use a polite User-Agent (`ForesightFlow research bot v0.1; contact: maksym@devnull.ae`), 2-second delay between requests to the same domain, respect 429 responses with `Retry-After`. Do not bypass paywalls — if the page is paywalled, the timestamp is usually still in the meta tags, and that's enough.

**CLI:** `fflow news tier1 --all-resolved` and `fflow news tier1 --market 0x...`.

### 3.3 Tier 2: GDELT keyword matching (`fflow/news/gdelt.py`)

GDELT 2.0 publishes a global event index queryable via Google BigQuery. For markets where Tier 1 failed, we query GDELT for the earliest article matching keywords extracted from the market question.

**Setup:**
- Requires GCP project with BigQuery enabled. User is responsible for creating it; the collector reads `FFLOW_GCP_PROJECT_ID` and `GOOGLE_APPLICATION_CREDENTIALS` from env.
- Free tier: 1 TB/month of query data. Each query against GDELT GKG should be tightly scoped to a date range and a small set of keywords to stay well under the limit.

**Keyword extraction from market question:**
- Use a simple NER-free heuristic for Task 02:
  - Tokenize the question.
  - Drop stopwords (use NLTK's English stopword list plus prediction-market-specific ones: `will`, `before`, `by`, `who`, `what`, `when`).
  - Drop ordinals, dates, year tokens.
  - Keep proper nouns (capitalized tokens) and content nouns.
  - Return top 3–6 keywords by length.
- Store the resulting keyword list in `news_timestamps.query_keywords` for auditability.

**BigQuery query:**

```sql
SELECT
  DATE,
  SourceCommonName,
  DocumentIdentifier,
  Themes,
  V2Tone
FROM `gdelt-bq.gdeltv2.gkg`
WHERE
  DATE BETWEEN @start_date AND @end_date
  AND REGEXP_CONTAINS(LOWER(V2Themes || ' ' || V2Persons || ' ' || V2Locations),
                      r'(?i)(\b{kw1}\b)(?:.*\b{kw2}\b)?')  -- adjust per query
ORDER BY DATE ASC
LIMIT 50
```

(The exact form of the regex match should be verified against GDELT GKG schema docs at implementation time. The robust path is to use `gdelt-bq.gdeltv2.gkg_partitioned` with date partitioning to control query bytes.)

**Time window:** query the period `[T_open, min(T_resolve, T_open + 90 days)]`. For long-running markets, cap at 90 days post-open to keep query cost bounded.

**Source filtering:** prefer reputable outlets via `SourceCommonName` whitelist (configurable). Default whitelist: `reuters.com`, `apnews.com`, `bbc.com`, `bloomberg.com`, `wsj.com`, `nytimes.com`, `ft.com`, `cnn.com`, `politico.com`, `aljazeera.com`. If multiple matches, pick the earliest.

**Persistence:** `tier=2`, `confidence=0.70` if a whitelisted source matched, `0.50` otherwise.

**CLI:** `fflow news tier2 --all-pending` (markets with no `news_timestamps` row and no Tier-1 success), `fflow news tier2 --market 0x...`.

### 3.4 Tier 3: LLM-assisted matching (`fflow/news/llm_match.py`)

For the labelled validation set only — a small list of 10–30 documented insider-case markets that we need high-confidence `T_news` for.

**Approach:**
- Use Anthropic Claude (or any provider via a generic client) with a structured prompt.
- Input: market question, market description, resolution criteria, `T_open`, `T_resolve`, `resolution_evidence_url` (if any), and any Tier-2 candidates that scored above a threshold.
- Output: a single URL + ISO-8601 timestamp + confidence (0–1) + reasoning.
- Validate the URL by fetching it and re-extracting the publish timestamp using Tier 1 logic; if the LLM-supplied timestamp matches the page metadata within a few minutes, accept; otherwise, flag for manual review.

**Cost discipline:**
- Hard cap: at most 50 LLM calls per CLI invocation (configurable).
- Validation-set markets must be explicitly listed in a YAML file at `config/validation_markets.yaml` — Tier 3 is opt-in, never run on the full backfill.
- Total Tier-3 budget for the whole project: ≤ $50 worth of API calls. Track via `data_collection_runs.metadata`.

**Persistence:** `tier=3`, `confidence` = LLM-supplied (clipped to `[0, 0.99]`).

**CLI:** `fflow news tier3 --validation-set` (reads `config/validation_markets.yaml`), `fflow news tier3 --market 0x... --confirm` (single market, requires `--confirm` flag to actually call the API).

### 3.5 ILS computation (`fflow/scoring/ils.py`)

Pure computation, no I/O. Takes a price series (DataFrame with `ts, mid_price`) and three timestamps; returns the ILS bundle.

**Public API:**

```python
from datetime import datetime
from decimal import Decimal
import pandas as pd
from pydantic import BaseModel

class ILSBundle(BaseModel):
    ils: Decimal | None              # NULL when |delta_total| < epsilon
    ils_30min: Decimal | None
    ils_2h: Decimal | None
    ils_6h: Decimal | None
    ils_24h: Decimal | None
    ils_7d: Decimal | None
    delta_pre: Decimal
    delta_total: Decimal
    p_open: Decimal
    p_news: Decimal
    p_resolve: int                   # 0 or 1
    flags: list[str]

def compute_ils(
    prices: pd.DataFrame,            # columns: ts (UTC), mid_price
    t_open: datetime,
    t_news: datetime,
    t_resolve: datetime,
    p_resolve: int,
    epsilon: Decimal = Decimal("0.05"),
) -> ILSBundle:
    ...
```

**Implementation rules:**

1. All arithmetic in `Decimal`, not `float`. Prices are bounded in `[0, 1]` with 6 decimals of precision.
2. `p(t)` = price at the minute closest to `t`. If exact minute is missing, take the nearest available minute within ±5 minutes; if still missing, raise `PriceLookupError` and let the caller add a flag.
3. `epsilon = Decimal("0.05")` default; configurable.
4. ILS undefined (`None`) when `|delta_total| < epsilon`. This is normal and expected for low-information markets — flag with `low_information_market`.
5. Multi-window: `ILS_w = (p(t_news) − p(t_news − w)) / (p_resolve − p(t_news − w))`. If `t_news − w < t_open`, set the corresponding window to `None` and add flag `window_w_predates_topen`.
6. Flags possible: `low_information_market`, `low_volume_at_tnews`, `window_30min_predates_topen`, `window_2h_predates_topen`, ..., `price_history_gap_pre_news`, `nonmonotonic_price_drift`.

**Crucial unit tests** (`tests/test_ils.py`):

Provide synthetic price series for each regime (paper Figure 2):
- **Pure leakage:** price drifts from 0.15 to 0.95 before `t_news`, then flat to resolution at 1.0. Assert `ILS ≈ 1.0` (within `0.05`).
- **No leakage:** price flat at 0.15 until `t_news`, then jumps to 0.99. Assert `ILS ≈ 0.0`.
- **Partial leakage:** linear drift `0.15 → 0.55` before, jump `0.55 → 0.99` after. Assert `ILS ∈ [0.45, 0.55]`.
- **Counter-evidence:** price drifts down `0.30 → 0.20` before, then jumps to `0.99`. Assert `ILS < 0`.
- **Low-information:** flat at `0.50`, resolves YES with no real movement. Assert `ils is None` and flag set.
- **Multi-window correctness:** construct a series where pre-news drift is concentrated in the last 30 minutes and verify `ILS_30min ≈ ILS` while `ILS_24h` reflects the broader window.

These tests are the contract for the scoring module. They must pass before any backfill is run.

### 3.6 Volume, jump, wallet features (`fflow/scoring/volume.py`, `fflow/scoring/wallet_features.py`)

Mostly straightforward database queries plus aggregations.

**`compute_volume_features(market_id, t_news, t_resolve)` returns:**
- `volume_pre_share`: ratio of pre-news to total volume.
- `pre_news_max_jump`: maximum single-trade price delta in `[T_open, T_news]`.
- `n_trades_total`, `n_trades_pre_news`.

**`compute_wallet_features(market_id, t_news, p_resolve)` returns:**
- `wallet_hhi_top10`: HHI of trade-size shares among the top-10 winning trades.
- `time_to_news_top10`: list of dicts as defined in `market_labels` schema.

A "winning trade" is a trade whose `side` matches the resolution outcome (BUY YES if resolution is YES, SELL YES if resolution is NO). Rank by absolute notional, take top 10.

### 3.7 Orchestration (`fflow/scoring/pipeline.py`)

Single function `compute_market_label(market_id) -> MarketLabel | None` that:
1. Loads market row, news_timestamps row, prices, trades.
2. Calls `compute_ils`, `compute_volume_features`, `compute_wallet_features`.
3. Assembles flags from all sub-computations.
4. Writes one row to `market_labels` (upsert by `market_id`).
5. Writes an entry to `label_audit`.

**Idempotency:** rerunning on the same market overwrites the row and appends an `ils_recomputed` audit entry.

**CLI:** `fflow score --all-resolved`, `fflow score --market 0x...`, `fflow score --category geopolitics`.

### 3.8 Sample script (`scripts/label_sample.py`)

End-to-end execution against the Task 01 sample:
1. `fflow news tier1 --all-resolved`
2. `fflow news tier2 --all-pending`
3. (Skip tier 3 unless `--with-llm` flag passed.)
4. `fflow score --all-resolved`
5. Print summary: how many markets got `T_news`, distribution by tier, distribution of ILS values.

### 3.9 Validation script (`scripts/validate_labels.py`)

Sanity checks that flag suspicious distributions. Prints WARNING-level messages, does not crash.

Checks:
- ILS distribution should not be heavily concentrated at `1.0` or `0.0` (would suggest a methodology bug).
- For `category=sports` (control), median ILS should be near 0 — if not, the news-timestamp recovery is suspect.
- `volume_pre_share` should correlate positively with ILS within each category — if not, either ILS or volume features have a bug.
- Number of markets with `low_information_market` flag should be < 30 % of total — if higher, lower `epsilon` or revisit market selection.
- All `t_news` values should satisfy `t_open < t_news ≤ t_resolve + 7 days`.

### 3.10 Tests

Beyond `test_ils.py` (Section 3.5), three additional suites:

- `test_proposer_url.py`: HTML fixture files in `tests/fixtures/` representing real article pages from Reuters, BBC, AP, NYT — assert that publish timestamps are correctly extracted from each.
- `test_gdelt.py`: VCR cassette of one BigQuery response; assert that keyword extraction for a hand-crafted market question produces the expected keyword set, and that the BigQuery client correctly parses the response.
- `test_wallet_features.py`: synthetic trade list, assert HHI and time-to-news distribution match expected values.

---

## 4. Acceptance criteria

Task 02 is **done** when:

1. Migration `0002_labels_schema.py` applies cleanly on top of the Task 01 DB.
2. `fflow news tier1 --all-resolved` runs end-to-end and populates `news_timestamps` for every resolved market with a non-empty `resolution_evidence_url`.
3. `fflow news tier2 --all-pending` (with GCP credentials configured) populates `news_timestamps` for at least 80 % of remaining resolved markets, OR fails gracefully with a clear log message if BigQuery is not configured.
4. `fflow score --all-resolved` runs end-to-end and populates `market_labels` for every market with both a `t_news` and a price series.
5. `python scripts/label_sample.py` produces a summary showing:
   - ≥ 8 markets with non-NULL ILS
   - At least one market in each of the three target categories
   - Tier distribution: at least 1 Tier-1 success, at least 1 Tier-2 success
6. `python scripts/validate_labels.py` runs and either (a) reports all checks passing, or (b) reports specific warnings that are documented and explained in `IMPLEMENTATION_REPORT_TASK02.md`.
7. `uv run pytest` passes including all `test_ils.py` synthetic regime tests.
8. Re-running any `fflow score` or `fflow news` command twice produces no duplicate rows; `label_audit` correctly records both runs.
9. For at least three documented insider cases (Iran strike, Year-in-Search, Venezuela operation, Maduro, etc., where data is available in the sample), the computed ILS is `≥ 0.5`. This is the qualitative validation against ground truth.

---

## 5. Out of scope for Task 02

- Microstructure features beyond pre-news jump (PIN, VPIN, VR(6), TS, Hawkes, kurtosis) — these are Task 04.
- Real-time inference — Task 05.
- Detector model training — Task 06.
- FastAPI server — Task 07.
- Frontend — Task 08.
- Telegram bot — Task 09.
- Cross-platform (Kalshi) labels — explicitly out of scope per CHARTER §3.4.
- Adversarial-robustness testing — out of scope per paper §5.6 limitations.

If Tier 1 or Tier 2 produces unexpectedly low coverage in practice (e.g., < 50 % of resolved markets), do not improvise — log the gap, document it in `IMPLEMENTATION_REPORT_TASK02.md`, and stop. The remediation strategy will be a Task 02b discussion, not a Task 02 deliverable.

---

## 6. Working notes for Claude Code

- **Decimals everywhere.** No `float` for prices, ratios, or anything ILS-derived. Use `decimal.Decimal` and SQLAlchemy `Numeric(8, 6)` types. Single `float` slip in this module will silently corrupt downstream comparisons.
- **Time discipline (still).** All datetimes UTC, all timestamps `TIMESTAMPTZ`. Pandas DataFrames must use `datetime64[ns, UTC]`.
- **Test-first for ILS.** Write the synthetic regime tests in `test_ils.py` first, then implement `compute_ils` until they pass. This prevents "adjusting tests to match implementation" anti-patterns.
- **Idempotency is non-negotiable.** Re-running the labelling pipeline must converge to the same DB state, never duplicate. Use upserts with explicit `ON CONFLICT DO UPDATE` and audit-log entries.
- **GDELT cost discipline.** Every BigQuery call should print its estimated cost (BigQuery dry-run gives `totalBytesProcessed`) into the log. Abort if a single call would scan more than 100 GB.
- **Tier 3 is gated.** Tier 3 (LLM-assisted) requires explicit `--confirm` and a budget environment variable. Default is to never call the LLM provider. This is a hard rule — accidental LLM bills are a real failure mode.
- **Be honest about gaps.** If GDELT keyword matching doesn't find a hit for a market, that's fine. Don't lower the threshold. Don't insert a "best guess" with low confidence. Skip the market and let it appear in the `validate_labels.py` report so we know about it.

---

## 7. Hand-off

When Task 02 is complete:
- All tables populated for the Task 01 sample with full provenance.
- `IMPLEMENTATION_REPORT_TASK02.md` summarizing: tier coverage statistics, ILS distribution by category, any gaps or surprises, any deviations from this brief.
- A short JSON or CSV export at `/data/sample_labels_v0.json` with the labels for the sample — this becomes the input artifact for Task 04 (microstructure features) and Task 06 (detector training).

Task 03 will pick up the LLM-assisted taxonomy classifier (replacing the keyword-based one from Task 01). Task 04 will compute the live microstructure features.

---

*End of Task 02 brief. Document version: v0.1, 2026-04-25.*
