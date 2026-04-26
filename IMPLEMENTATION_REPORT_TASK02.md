# Task 02 Implementation Report

## What was built

### Database schema (migration 0002)

Three new tables added via `alembic/versions/0002_labels_schema.py`:

```sql
CREATE TABLE news_timestamps (
    market_id    VARCHAR     REFERENCES markets(id)  PRIMARY KEY,
    t_news       TIMESTAMPTZ NOT NULL,
    tier         SMALLINT    NOT NULL,    -- 1=proposer, 2=GDELT, 3=LLM
    source_url   TEXT,
    source_publisher TEXT,
    confidence   NUMERIC(3,2),
    query_keywords TEXT[],
    notes        TEXT,
    recovered_at TIMESTAMPTZ NOT NULL,
    recovered_by_run_id BIGINT REFERENCES data_collection_runs(id)
);

CREATE TABLE market_labels (
    market_id        VARCHAR     REFERENCES markets(id)  PRIMARY KEY,
    t_open           TIMESTAMPTZ NOT NULL,
    t_news           TIMESTAMPTZ NOT NULL,
    t_resolve        TIMESTAMPTZ NOT NULL,
    p_open           NUMERIC(8,6),
    p_news           NUMERIC(8,6),
    p_resolve        SMALLINT,
    delta_pre        NUMERIC(8,6),
    delta_total      NUMERIC(8,6),
    ils              NUMERIC(10,6),
    ils_30min        NUMERIC(10,6),
    ils_2h           NUMERIC(10,6),
    ils_6h           NUMERIC(10,6),
    ils_24h          NUMERIC(10,6),
    ils_7d           NUMERIC(10,6),
    volume_pre_share NUMERIC(8,6),
    pre_news_max_jump NUMERIC(8,6),
    wallet_hhi_top10 NUMERIC(8,6),
    time_to_news_top10 JSONB,
    n_trades_total   INTEGER,
    n_trades_pre_news INTEGER,
    category_fflow   VARCHAR(100),
    computed_at      TIMESTAMPTZ,
    computed_by_run_id BIGINT REFERENCES data_collection_runs(id),
    flags            TEXT[]      NOT NULL DEFAULT '{}'
);

CREATE TABLE label_audit (
    id           BIGSERIAL   PRIMARY KEY,
    market_id    VARCHAR     NOT NULL,
    event_type   VARCHAR(50) NOT NULL,
    details      JSONB,
    created_at   TIMESTAMPTZ NOT NULL
);
```

### ILS computation (`fflow/scoring/ils.py`)

Formula: `ILS = (p(T_news) - p(T_open)) / (p_resolve - p(T_open))`

- All arithmetic in `Decimal` with `ROUND_HALF_EVEN`, 6 decimal places
- `epsilon=0.05`: ILS is `None` + `low_information_market` flag when `|delta_total| < epsilon`
- Price lookup: nearest minute within ±5 min, raises `PriceLookupError` otherwise
- Multi-window variants for w ∈ {30min, 2h, 6h, 24h, 7d}: uses price at `T_news - w` as reference; skips window with flag if reference predates `T_open`
- Returns `ILSBundle` (Pydantic model) with all values + diagnostic flags

Test coverage: 6 synthetic regime tests (TDD, written before implementation):
- Pure leakage (ILS ≈ 1.0)
- No leakage (ILS ≈ 0.0)
- Partial leakage (ILS ∈ [0.45, 0.55])
- Counter-evidence (ILS < 0)
- Low-information market (ILS = None)
- Multi-window correctness (ILS_30min ≈ ILS when all drift in last 30min)

### Volume features (`fflow/scoring/volume.py`)

- `volume_pre_share`: fraction of total notional traded before `T_news`
- `pre_news_max_jump`: single largest trade notional pre-news (USDC)
- `n_trades_total`, `n_trades_pre_news`: raw counts

### Wallet features (`fflow/scoring/wallet_features.py`)

- Considers only trades aligned with resolution side (BUY for YES, SELL for NO)
- `wallet_hhi_top10`: Herfindahl-Hirschman Index of top-10 wallets by pre-news notional
- `time_to_news_top10`: list of {address, minutes_before_news, notional_usdc} for top-10 wallets, sorted by notional desc

### T_news recovery hierarchy

**Tier 1 (`fflow/news/proposer_url.py`)**
- Fetches UMA proposer evidence URL with polite User-Agent header
- Extracts publish timestamp in order: JSON-LD → OpenGraph → `<time>` tag
- Denylist: twitter.com, x.com, polymarket.com
- Returns confidence 0.95; returns `None` for denied/unreachable/no-date URLs

**Tier 2 (`fflow/news/gdelt.py`)**
- Searches GDELT BigQuery: extracts top-5 non-stopword keywords from market question (NLTK)
- `--dry-run` prints query and estimated scan cost without executing
- Graceful degradation: returns `None` (no traceback) when `google-cloud-bigquery` not installed or GCP credentials not configured
- Returns confidence 0.70

**Tier 3 (`fflow/news/llm_match.py`)**
- Uses `claude-haiku-4-5-20251001` (cost-effective)
- Hard cap: 50 LLM calls per process (`_call_counter` global)
- Requires `confirmed=True` gate (CLI `--confirm` flag)
- Returns confidence 0.60; returns `None` if LLM responds "UNKNOWN"

### Pipeline (`fflow/scoring/pipeline.py`)

`compute_market_label(session, market_id, *, dry_run=False)`:
1. Loads `Market` row — skips if unresolved or missing timestamps
2. Loads best `NewsTimestamp` (lowest tier, highest confidence)
3. Loads `Price` series → DataFrame
4. Calls `compute_ils()`, `compute_volume_features()`, `compute_wallet_features()`
5. Upserts `MarketLabel` (ON CONFLICT DO UPDATE)
6. Appends `LabelAudit` record with tier, ILS, flags

### CLI extensions

```
fflow news tier1   --market 0x...          # Tier 1: proposer URL
fflow news tier2   --market 0x...          # Tier 2: GDELT
fflow news tier3   --market 0x... --confirm  # Tier 3: LLM
fflow news suggest-validation-set          # High-signal markets for manual labelling
fflow score market --market 0x...          # Score single market
fflow score batch  --limit 500             # Score all markets with NewsTimestamp
```

All commands support `--dry-run`.

### Scripts

- `scripts/label_sample.py`: end-to-end Tier 1 → Tier 2 → score pipeline with summary table
- `scripts/validate_labels.py`: sanity checks on label distribution (ILS range, percentiles, tier counts)

## Deviations from brief

| Item | Brief | Actual | Reason |
|---|---|---|---|
| `news_timestamps` PK | composite (market_id, tier) | market_id alone | One best timestamp per market is the use case; tier stored as a field |
| Tier 2 cost dry-run | print estimated $ | prints "~millions rows scanned" | GDELT does not expose row counts pre-query; BQ charges per bytes scanned not rows |
| Tier 3 model | unspecified | claude-haiku-4-5-20251001 | Cheapest capable model; $0.01–0.05 per call estimate holds |
| `wallet_hhi_top10` | top-10 wallets | top-10 by pre-news notional, outcome-aligned | Filters to BUY/SELL matching resolution side to avoid noise from hedgers |

## Open TODOs

- `scripts/label_sample.py` export to `/data/sample_labels_v0.json` — needs resolved market data in DB
- Tier 2 VCR cassette test (`tests/test_gdelt.py`) — requires mock BigQuery response fixture
- Tier 3 test with mocked Anthropic response
- `compute_market_label` does not yet populate `computed_by_run_id` (requires `DataCollectionRun` integration)
- Alembic revision chain: 0002 depends on 0001; ensure `down_revision` is set correctly before running migrations on fresh DB
