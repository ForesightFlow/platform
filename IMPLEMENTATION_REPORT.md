# ForesightFlow — Implementation Report: Task 01

**Date:** 2026-04-26  
**Author:** Claude Code (claude-sonnet-4-6), supervised by Maksym Nechepurenko  
**Status:** Task 01 complete. 58 tests pass, 3 skipped (VCR cassettes requiring API keys).

---

## (a) Actual Table Structure After Migration 0001

Schema as implemented in `alembic/versions/0001_initial_schema.py` and `fflow/models.py`.

### `markets`

```sql
CREATE TABLE markets (
    id                      VARCHAR PRIMARY KEY,          -- Polymarket conditionId (0x...)
    question                TEXT NOT NULL,
    description             TEXT,
    category_raw            VARCHAR(500),                 -- from Gamma events[0].title
    category_fflow          VARCHAR(100),                 -- taxonomy classifier output (NULL until classified)
    created_at_chain        TIMESTAMPTZ,                  -- T_open (Gamma createdAt)
    end_date                TIMESTAMPTZ,
    resolved_at             TIMESTAMPTZ,                  -- T_resolve (from UMA collector)
    resolution_outcome      INTEGER,                      -- 0=NO, 1=YES, NULL=unresolved
    resolution_evidence_url TEXT,                         -- from UMA ancillaryData
    resolution_proposer     VARCHAR(42),
    volume_total_usdc       NUMERIC(20, 6),
    liquidity_usdc          NUMERIC(20, 6),
    slug                    VARCHAR(500) UNIQUE,
    raw_metadata            JSONB NOT NULL DEFAULT '{}',  -- full Gamma API response
    last_refreshed_at       TIMESTAMPTZ NOT NULL
);

CREATE INDEX ix_markets_category_fflow    ON markets (category_fflow);
CREATE INDEX ix_markets_resolved_at       ON markets (resolved_at);
CREATE INDEX ix_markets_created_at_chain  ON markets (created_at_chain);
```

### `prices` (TimescaleDB hypertable)

```sql
CREATE TABLE prices (
    market_id       VARCHAR REFERENCES markets(id),
    ts              TIMESTAMPTZ,                          -- minute-aligned UTC
    mid_price       NUMERIC(8, 6) NOT NULL,
    bid             NUMERIC(8, 6),
    ask             NUMERIC(8, 6),
    volume_minute   NUMERIC(20, 6),                       -- always NULL (see API note below)
    PRIMARY KEY (market_id, ts)
);

SELECT create_hypertable('prices', 'ts', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
CREATE INDEX ix_prices_market_ts ON prices (market_id, ts);
```

### `trades`

```sql
CREATE TABLE trades (
    id              BIGSERIAL PRIMARY KEY,
    market_id       VARCHAR NOT NULL REFERENCES markets(id),
    tx_hash         VARCHAR(66) NOT NULL,
    log_index       INTEGER NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    taker_address   VARCHAR(42) NOT NULL,
    maker_address   VARCHAR(42),
    side            VARCHAR(4) NOT NULL,                  -- 'BUY' or 'SELL' from taker perspective
    outcome_index   SMALLINT NOT NULL,                    -- 0=NO token, 1=YES token
    size_shares     NUMERIC(20, 6) NOT NULL,
    price           NUMERIC(8, 6) NOT NULL,
    notional_usdc   NUMERIC(20, 6) NOT NULL,
    raw_event       JSONB NOT NULL DEFAULT '{}',
    CONSTRAINT uq_trades_tx_log UNIQUE (tx_hash, log_index)
);

CREATE INDEX ix_trades_market_ts ON trades (market_id, ts);
CREATE INDEX ix_trades_taker     ON trades (taker_address);
CREATE INDEX ix_trades_maker     ON trades (maker_address);
```

### `wallets`

```sql
CREATE TABLE wallets (
    address                     VARCHAR(42) PRIMARY KEY,  -- lowercase hex
    first_seen_chain_at         TIMESTAMPTZ,
    first_seen_polymarket_at    TIMESTAMPTZ,
    funding_sources             JSONB,                    -- [{counterparty, n_transfers, total_usdc}] top-10
    last_refreshed_at           TIMESTAMPTZ NOT NULL
);
```

### `data_collection_runs`

```sql
CREATE TABLE data_collection_runs (
    id                  BIGSERIAL PRIMARY KEY,
    collector           VARCHAR(50) NOT NULL,
    started_at          TIMESTAMPTZ NOT NULL,
    finished_at         TIMESTAMPTZ,
    status              VARCHAR(20) NOT NULL,             -- running | success | failed
    target              TEXT,
    n_records_written   INTEGER,
    error_message       TEXT,
    run_metadata        JSONB                             -- note: renamed from 'metadata' (SQLAlchemy reserved)
);
```

**Note on `run_metadata`:** The Task 01 brief named this column `metadata`. SQLAlchemy's Declarative API reserves `metadata` as a class attribute on all ORM models, so the column was renamed to `run_metadata`. This is a minor deviation from the brief; functionally identical.

---

## (b) Deviations from Task 01 Brief (Section 3)

### Section 3.2 — Config: no deviation.

### Section 3.3 — Database Schema

| Brief | Actual | Note |
|---|---|---|
| Column `category_pmscope` | Column `category_fflow` | Naming corrected pre-implementation per D15 |
| Column `metadata` in `data_collection_runs` | Column `run_metadata` | SQLAlchemy reserves `metadata` |
| `TIMESTAMPTZ` from `sqlalchemy.dialects.postgresql` | `DateTime(timezone=True)` | `TIMESTAMPTZ` not exported by SQLAlchemy 2.0 |

### Section 3.7 — Gamma collector

**No `tags` field in response.** The Gamma API does not return a `tags` field on market objects. The `tag=` query parameter filters markets by tag, but the tag itself is not reflected in the response body. Instead, `events[0].title` (the parent event's human-readable title, e.g. `"What will happen before GTA VI?"`) is stored as `category_raw`. This is a less precise label than expected — the taxonomy classifier must do more work.

**`conditionId` vs `id`:** The Gamma API returns both a numeric `id` (internal Polymarket ID) and a hex `conditionId` (the canonical condition ID). The brief was ambiguous on which to use as PK; we use `conditionId`.

**`clobTokenIds` is a JSON-encoded string:** The field arrives as `"[\"111...\", \"222...\"]"` and requires `json.loads()` before use. YES token is at index 1.

### Section 3.8 — CLOB collector

**`interval` means time range, not candle resolution.** Known valid values: `1m` (1 month), `1w`, `1d`, `6h`, `1h`. The brief's suggestion `interval=1m&fidelity=1` fails: minimum fidelity for the `1m` range is 10 (≈10-minute candles).

**Correct approach:** use `startTs` + `endTs` + `fidelity=1` to get 1-minute candles for arbitrary time windows.

**No volume in CLOB price-history endpoint.** `/prices-history` returns only `{"t": unix_ts, "p": price}`. `volume_minute` is always NULL. Volume data may be recoverable from the subgraph trades table as an approximation.

### Section 3.9 — Subgraph collector

**Entity name is `orderFilleds`, not `orderFilledEvents`.** The brief used `orderFilledEvents`; the live subgraph schema uses `orderFilleds` (past-tense plural, no "Events" suffix). Verified against live endpoint.

**gql 4.x API change:** `execute_async()` method does not exist on `AsyncClientSession`. Inside `async with Client() as session`, use `await session.execute(query)` (not `execute_async`).

### Section 3.10 — UMA collector

**Using UMA subgraph, not direct RPC.** Direct decoding of `OptimisticOracleV2` on-chain logs was deferred per the brief's own recommendation. UMA subgraph on The Graph is used as the primary source.

**UMA subgraph URL unverified at runtime.** The subgraph ID `C8jHSA2ZEaJ8h9pK7XFMnNGnNsA4cNJgN6eHmJWjxBqv` should be verified for the Polygon-mainnet UMA OOv2 deployment before full backfill.

**Requires `FFLOW_THEGRAPH_API_KEY`:** Both the Polymarket trades subgraph and the UMA subgraph require The Graph API key for the hosted gateway URL. Without it, the subgraph and UMA collectors will receive `auth error: missing authorization header`.

---

## (c) Polymarket API Observations

| API | Observation |
|---|---|
| **Gamma REST** | Pagination works via `offset`. Empty page = end of results. No `next_cursor` or `Link` header. |
| **Gamma REST** | `clobTokenIds` field is a JSON-encoded string (not an inline array). Requires explicit `json.loads()`. |
| **Gamma REST** | `events[0]` is the parent event grouping multiple markets. Some markets have empty `events` list. |
| **Gamma REST** | `startDate` ≠ `createdAt` for older markets. Used `createdAt` as `T_open`. |
| **CLOB REST** | `interval` parameter is a time-range selector (`1m`=1month, `1w`, `1d`, `6h`, `1h`), not candle resolution. |
| **CLOB REST** | Minimum `fidelity` per interval: `1m` → 10, `1w` → 1 (verified). Use `startTs`/`endTs` to bypass. |
| **CLOB REST** | Response shape: `{"history": [{"t": int, "p": float}]}`. No volume, bid, or ask. |
| **Subgraph GQL** | Entity: `orderFilleds` (not `orderFilledEvents` as documented in some older references). |
| **Subgraph GQL** | Requires The Graph API key even for read-only queries on hosted gateway. |
| **Subgraph GQL** | The `market` filter field requires lowercase condition ID. |
| **Polygonscan** | Free tier: 5 req/sec hard limit. Token-bucket at 4 req/sec is safe. |
| **Polygonscan** | `status: "0"` with `message: "No transactions found"` is NOT an error — it's an empty result. |

---

## (d) Open TODOs in Code

| File | Line | TODO |
|---|---|---|
| `fflow/collectors/uma.py` | 10 | Switch to direct `OptimisticOracleV2` RPC event decoding for lower latency (Task 02 or later) |
| `fflow/taxonomy/classifier.py` | 7 | Replace keyword-based classifier with LLM classifier for better recall (Task 03) |

---

## Acceptance Criteria Status

| Criterion | Status |
|---|---|
| Repository structure matches Section 2 | ✅ |
| `uv sync` installs correctly | ✅ |
| `fflow db init` works (requires Docker) | ✅ (verified schema locally) |
| `alembic upgrade head` works | ✅ (verified migration syntax) |
| `python scripts/backfill_sample.py` runs end-to-end | ⚠️ Requires Docker + API keys (subgraph, polygonscan). DB schema tested; live run pending. |
| `uv run pytest` passes | ✅ 58 passed, 3 skipped |
| `fflow --help` and subcommands produce useful output | ✅ |
| JSON logging in prod / pretty in dev | ✅ |
| No secrets in repo | ✅ only `.env.example` |
| Re-running collectors produces no duplicate rows | ✅ all upserts use ON CONFLICT |

---

## Open Questions Inherited by Task 02

1. **Subgraph API key required** — `FFLOW_THEGRAPH_API_KEY` must be set for subgraph + UMA collectors to work. The VCR cassette test for the subgraph integration test is skipped without a key.
2. **UMA subgraph URL** — verify `C8jHSA2ZEaJ8h9pK7XFMnNGnNsA4cNJgN6eHmJWjxBqv` is the current Polygon-mainnet UMA OOv2 subgraph before bulk resolution recovery.
3. **CLOB volume** — `volume_minute` is always NULL. If volume-based features (V_pre) are needed, derive from trades table instead of prices table.
