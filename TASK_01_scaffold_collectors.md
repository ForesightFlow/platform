# ForesightFlow — Claude Code Task 01: Scaffold + Collectors

**Project:** ForesightFlow
**Working name:** ForesightFlow
**Repo:** https://github.com/ForesightFlow
**Site:** https://foresightflow.xyz
**Author / lead:** Maksym Nechepurenko (Devnull FZCO)
**Companion document:** `CHARTER.md` (project charter, source of truth)
**Companion paper:** `foresightflow_draft_v0.2.pdf` (theoretical preprint)

---

## 0. How to read this document

This document is a self-contained brief for Claude Code (terminal mode) to implement **Task 01** of the ForesightFlow project. It is intended to be sufficient for Claude Code to do the task without needing access to chat history.

Read sections in order. Section 1 gives context. Section 2 gives the deliverable list. Section 3 gives implementation details for each module. Section 4 lists explicit acceptance criteria. Section 5 lists what is **out of scope** for this task.

When in doubt: prefer fewer lines of well-tested code over more lines of speculative code. Prefer real API calls in tests over mocks where the API is free and rate-limited gracefully (Polymarket's Gamma API qualifies).

---

## 1. Project context (one page)

### 1.1 What we are building

A real-time monitoring system that detects informed flow on Polymarket prediction markets, focusing on three categories where insider trading is plausible *a priori*:

1. **Military / geopolitical actions** (strikes, troop movements, treaty signings, prisoner exchanges)
2. **Corporate proprietary disclosures** (M&A, product launches, proprietary dataset releases like Google's Year-in-Search)
3. **Regulatory decisions** (FDA approvals, central bank rate decisions, court rulings)

We deliberately **do not** target sports, weather, or election polling — these serve as null-hypothesis controls only.

### 1.2 Two parallel deliverables

1. **Research paper** (already drafted at v0.2 — `foresightflow_draft_v0.2.pdf`)
2. **Production system** (this task is the first step of the system)

### 1.3 Task 01 scope

Set up the Python package `pmscope`, implement the data-source collectors (`pmscope.collectors`), and implement the storage schema. No analysis, no detection, no UI yet. Just: *read data from the world reliably and store it correctly*.

### 1.4 Key formal definitions (from the paper)

For a resolved market `M`:

- `T_open` = market creation timestamp
- `T_news` = first public mention of resolution-relevant info (recovered hierarchically: UMA proposer URL → GDELT → LLM-assisted)
- `T_resolve` = UMA Optimistic Oracle resolution timestamp
- `p(t)` = mid-price of YES outcome token at time `t`
- `ILS(M) = (p(T_news) - p(T_open)) / (p_resolve - p(T_open))`

Task 01 must capture all the data needed to compute `T_open`, `T_resolve`, full price history, full trade log, and UMA proposer evidence URLs. `T_news` recovery itself is **not** in scope for Task 01 (that's Task 02).

---

## 2. Deliverables

A working git repository with the following structure:

```
pmscope/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 0001_initial_schema.py
├── pmscope/
│   ├── __init__.py
│   ├── config.py
│   ├── models.py
│   ├── db.py
│   ├── logging.py
│   ├── collectors/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── gamma.py
│   │   ├── clob.py
│   │   ├── subgraph.py
│   │   ├── uma.py
│   │   └── polygonscan.py
│   ├── taxonomy/
│   │   ├── __init__.py
│   │   └── classifier.py
│   └── cli.py
├── scripts/
│   ├── init_db.sh
│   └── backfill_sample.py
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_gamma.py
    ├── test_clob.py
    ├── test_subgraph.py
    ├── test_uma.py
    ├── test_polygonscan.py
    ├── test_models.py
    └── test_taxonomy.py
```

Plus a Docker-based local development stack (Postgres + TimescaleDB).

---

## 3. Implementation details

### 3.1 Tech stack (locked decisions)

- **Python 3.12** (use modern syntax: `match`, `|` union types, `Self`)
- **Package manager:** `uv` (fast, deterministic). Alternative: `pip-tools`. Do not use poetry.
- **HTTP client:** `httpx` (async, supports HTTP/2, modern API)
- **GraphQL client:** `gql[httpx]` for the Polymarket subgraph
- **DB:** PostgreSQL 16 with TimescaleDB extension
- **ORM:** SQLAlchemy 2.0 (with the new `Mapped[...]` typed style)
- **Migrations:** Alembic
- **Validation:** Pydantic 2.x
- **Config:** `pydantic-settings`
- **CLI:** Typer
- **Logging:** `structlog` (JSON in prod, pretty-printed in dev)
- **Testing:** pytest, pytest-asyncio, pytest-vcr (record real API responses once, replay in CI)

### 3.2 Configuration (`pmscope/config.py`)

Use `pydantic-settings`. Read from environment variables and `.env`. All settings should have sensible defaults that work for local dev with the Docker stack.

```python
class Settings(BaseSettings):
    # Database
    db_url: str = "postgresql+asyncpg://pmscope:pmscope@localhost:5432/pmscope"

    # Polymarket
    gamma_api_url: str = "https://gamma-api.polymarket.com"
    clob_api_url: str = "https://clob.polymarket.com"

    # Polymarket subgraph (The Graph)
    # Will be set per-environment; user has API key
    subgraph_url: str = "https://api.thegraph.com/subgraphs/name/polymarket/matic-markets-2"
    thegraph_api_key: str | None = None

    # Polygonscan
    polygonscan_api_key: str | None = None
    polygonscan_url: str = "https://api.polygonscan.com/api"

    # UMA Optimistic Oracle (read via on-chain JSON-RPC; we use a public RPC by default)
    polygon_rpc_url: str = "https://polygon-rpc.com"

    # Rate limits / retries
    http_timeout_seconds: float = 30.0
    http_max_retries: int = 5
    http_backoff_base_seconds: float = 1.0

    # Logging
    log_level: str = "INFO"
    log_json: bool = False  # True in prod, False in dev

    model_config = SettingsConfigDict(env_prefix="PMSCOPE_", env_file=".env")
```

Provide `.env.example` with all variables documented and dummy values.

### 3.3 Database schema (`pmscope/models.py` + `alembic/versions/0001_initial_schema.py`)

Use SQLAlchemy 2.0 typed style. All time columns are `TIMESTAMPTZ` (UTC).

**Tables:**

#### `markets`
- `id` (str, PK) — Polymarket condition ID (`0x…`)
- `question` (str)
- `description` (text, nullable)
- `category_raw` (str) — from Gamma's `tags` field, comma-joined
- `category_pmscope` (str, nullable) — from our taxonomy classifier (filled later)
- `created_at_chain` (timestamptz) — market creation timestamp (this is `T_open`)
- `end_date` (timestamptz, nullable)
- `resolved_at` (timestamptz, nullable) — UMA resolution timestamp (this is `T_resolve`)
- `resolution_outcome` (int, nullable) — 0 = NO, 1 = YES, NULL = unresolved
- `resolution_evidence_url` (str, nullable) — UMA proposer evidence URL
- `resolution_proposer` (str, nullable) — wallet address of UMA proposer
- `volume_total_usdc` (numeric(20, 6), nullable)
- `liquidity_usdc` (numeric(20, 6), nullable)
- `slug` (str, nullable, unique) — Polymarket URL slug
- `raw_metadata` (jsonb) — full Gamma API response, stored verbatim
- `last_refreshed_at` (timestamptz)

Indexes: `category_pmscope`, `resolved_at`, `created_at_chain`.

#### `prices` (TimescaleDB hypertable)
- `market_id` (str, FK markets.id, part of PK)
- `ts` (timestamptz, part of PK) — minute granularity, UTC, snapped to minute
- `mid_price` (numeric(8, 6)) — YES-outcome mid in [0, 1]
- `bid` (numeric(8, 6), nullable)
- `ask` (numeric(8, 6), nullable)
- `volume_minute` (numeric(20, 6), nullable) — volume traded during this minute

Hypertable: `select create_hypertable('prices', 'ts', chunk_time_interval => interval '7 days')`.
Index: `(market_id, ts DESC)`.

#### `trades`
- `id` (bigserial PK)
- `market_id` (str, FK markets.id, indexed)
- `tx_hash` (str, indexed)
- `log_index` (int)
- `ts` (timestamptz, indexed)
- `taker_address` (str, indexed)
- `maker_address` (str, indexed, nullable)
- `side` (varchar(4)) — `'BUY'` or `'SELL'` (referring to YES outcome from taker's perspective)
- `outcome_index` (smallint) — 0 = NO token, 1 = YES token
- `size_shares` (numeric(20, 6))
- `price` (numeric(8, 6))
- `notional_usdc` (numeric(20, 6))
- `raw_event` (jsonb)

Unique: `(tx_hash, log_index)`.
Indexes: `(market_id, ts)`, `taker_address`, `maker_address`.

#### `wallets`
- `address` (str, PK) — lowercase hex
- `first_seen_chain_at` (timestamptz, nullable) — earliest on-chain transaction timestamp on Polygon
- `first_seen_polymarket_at` (timestamptz, nullable) — earliest known trade in `trades`
- `funding_sources` (jsonb, nullable) — list of `{counterparty, n_transfers, total_usdc}`, top 10
- `last_refreshed_at` (timestamptz)

#### `data_collection_runs`
- `id` (bigserial PK)
- `collector` (str) — e.g., `'gamma'`, `'clob_prices'`, `'subgraph_trades'`, etc.
- `started_at` (timestamptz)
- `finished_at` (timestamptz, nullable)
- `status` (str) — `'running'` | `'success'` | `'failed'`
- `target` (str, nullable) — e.g., a market_id, or a date range
- `n_records_written` (int, nullable)
- `error_message` (text, nullable)
- `metadata` (jsonb, nullable)

This table is for observability — every collector run inserts a row at start and updates it at end. Critical for diagnosing pipeline issues and computing freshness.

### 3.4 Database utilities (`pmscope/db.py`)

- Async SQLAlchemy engine + session maker.
- `async def get_session()` async generator for FastAPI dependency injection.
- A function `init_timescale_extensions()` that runs `CREATE EXTENSION IF NOT EXISTS timescaledb` and creates the hypertable for `prices` (idempotent).

### 3.5 Logging (`pmscope/logging.py`)

Configure structlog with two renderers based on `settings.log_json`:
- Dev: `ConsoleRenderer` with colors
- Prod: `JSONRenderer`

Standard processors: timestamp (UTC ISO), log level, logger name, exception traceback if any.

### 3.6 Base collector (`pmscope/collectors/base.py`)

```python
class BaseCollector(ABC):
    """
    Contract for all collectors.

    Every collector run:
      1. Inserts a row in data_collection_runs with status='running'.
      2. Performs its work.
      3. Updates the row with status='success' or 'failed' and counts.

    Collectors are idempotent: running the same collector with the same target
    twice should converge to the same DB state, not duplicate rows.
    """
    name: str  # set by subclass; matches data_collection_runs.collector

    async def run(self, target: str | None = None, **kwargs) -> CollectorResult:
        ...
```

`CollectorResult` is a Pydantic model with `n_written: int`, `started_at`, `finished_at`, `status`, optional `error`.

Provide a `RetryableHTTPClient` wrapper around httpx that:
- Retries on 5xx, 408, 429, and connection errors.
- Exponential backoff with jitter.
- Honors `Retry-After` on 429.
- Logs every retry at WARNING.
- Total retries capped by `settings.http_max_retries`.

### 3.7 Gamma collector (`pmscope/collectors/gamma.py`)

The Gamma API is the metadata source.

**Endpoints used:**
- `GET /markets?limit=...&offset=...&active=...&closed=...&tag=...`
- `GET /markets/{condition_id}`

**Pagination:** Gamma returns up to ~500 per page. Iterate with offset until empty page.

**Filtering for our scope:** the collector should accept a list of `category_keywords` (e.g., `["politics", "geopolitics", "regulation"]`) and only persist markets whose Polymarket tags match. Plus, accept a `since: datetime` parameter to limit by `created_at`.

**Persistence:** upsert into `markets` by `id`. Map fields:
- Polymarket `conditionId` → `markets.id`
- `question` → `question`
- `description` → `description`
- `tags` (list of strings) → `category_raw` (joined with `,`)
- `createdAt` → `created_at_chain`
- `endDate` → `end_date`
- `volume` → `volume_total_usdc`
- `liquidity` → `liquidity_usdc`
- `slug` → `slug`
- entire response → `raw_metadata`

`category_pmscope` is left NULL — taxonomy classifier fills it later.

**CLI command:** `pmscope collect gamma --since 2024-04-01 --categories politics,geopolitics,regulation`.

### 3.8 CLOB price-history collector (`pmscope/collectors/clob.py`)

Fetches one-minute OHLCV-style price history for a given market.

**Endpoint:** `GET /prices-history?market={token_id}&interval=1m&fidelity=1` (verify exact param names against current Polymarket CLOB docs at fetch time and adjust).

Note: the CLOB API needs the YES *token id*, not the condition ID. The token id is part of the Gamma metadata under `clobTokenIds` (a list — index 0 is NO, index 1 is YES). The collector should fetch the YES token id from `markets.raw_metadata` for each requested market.

**Persistence:** upsert into `prices` keyed on `(market_id, ts)`.

**API quirks:** the CLOB price-history endpoint may return many points; ingest in batches and use `INSERT ... ON CONFLICT DO UPDATE`.

**CLI command:** `pmscope collect clob --market 0x... [--start-ts ...] [--end-ts ...]`.

### 3.9 Subgraph trades collector (`pmscope/collectors/subgraph.py`)

Fetches the full historical trade log from the Polymarket subgraph.

**GraphQL query** (Claude Code: verify the exact entity name against the active subgraph schema; the entity is typically `orderFilledEvents` or `tradeEvents`):

```graphql
query Trades($market: ID!, $first: Int!, $skip: Int!) {
  orderFilledEvents(
    where: { market: $market }
    first: $first
    skip: $skip
    orderBy: timestamp
    orderDirection: asc
  ) {
    id
    timestamp
    transactionHash
    maker
    taker
    makerAssetId
    takerAssetId
    makerAmountFilled
    takerAmountFilled
    fee
  }
}
```

Pagination via `first` + `skip` (or cursor-based with `lastID` for entities >5000 — recommended). Use `gql[httpx]`. If `THEGRAPH_API_KEY` is set, attach as `Authorization: Bearer ...`.

**Trade direction inference:** in Polymarket CTF, a buy of the YES token is recorded as `takerAssetId` matching the YES token id from Gamma. Use `markets.raw_metadata.clobTokenIds[1]` as the YES token id for each market.

**Persistence:** insert into `trades` with `ON CONFLICT (tx_hash, log_index) DO NOTHING`. Compute:
- `side` = `'BUY'` if taker received YES, else `'SELL'`
- `size_shares` = the amount of YES token
- `price` = USDC paid / shares received

**Wallet seeding:** for every new trade, upsert the `taker_address` and `maker_address` into `wallets` with `first_seen_polymarket_at = trade.ts` (only if currently NULL or larger).

**CLI command:** `pmscope collect subgraph --market 0x... [--from-ts ...]`.

### 3.10 UMA Optimistic Oracle collector (`pmscope/collectors/uma.py`)

For each resolved market, recover:
- `resolved_at` (UMA proposal timestamp on-chain)
- `resolution_outcome` (0 or 1)
- `resolution_evidence_url` (extracted from UMA `ancillaryData` field — typically contains a URL after a `q:` prefix or in a JSON-encoded structure)
- `resolution_proposer` (address)

**Approach:** read UMA `OptimisticOracleV2` events on Polygon via JSON-RPC. The contract address on Polygon mainnet is `0xeE3Afe347D5C74317041E2618C49534dAf887c24`. Filter `ProposePrice` and `Settle` events by `requester` = Polymarket UMA Adapter address and by `identifier` = the well-known YES_OR_NO_QUERY identifier.

For Task 01, the simpler path is acceptable: query the **UMA subgraph** (also on The Graph) which exposes Optimistic Oracle requests directly. Whichever path is taken, the deliverable is the same: populate `markets.resolved_at`, `markets.resolution_outcome`, `markets.resolution_evidence_url`, `markets.resolution_proposer` for resolved markets.

**Ancillary data parsing:** `ancillaryData` is hex-encoded UTF-8. Decode, then look for `q:` followed by question text and embedded URLs. Extract any `http(s)://...` substring as a candidate `resolution_evidence_url`. If multiple URLs, pick the first non-Polymarket one.

**CLI command:** `pmscope collect uma --market 0x...` (single market) and `pmscope collect uma --all-resolved` (batch).

### 3.11 Polygonscan wallet collector (`pmscope/collectors/polygonscan.py`)

For wallets that appear in `trades`, fetch the on-chain context.

**Endpoint:** `GET https://api.polygonscan.com/api?module=account&action=txlist&address={addr}&startblock=0&endblock=99999999&sort=asc&apikey=...`

For each wallet:
- `first_seen_chain_at` = timestamp of first transaction.
- `funding_sources` = top 10 USDC-transfer counterparties by total USDC received. Use the `tokentx` action with USDC contract address `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` (Polygon PoS USDC).

**Rate limiting:** Polygonscan free tier is 5 req/sec. Implement a token-bucket limiter at 4 req/sec to be safe.

**Persistence:** upsert into `wallets`.

**CLI command:** `pmscope collect polygonscan --wallet 0x...` and `pmscope collect polygonscan --all-stale --max-age-days 30`.

### 3.12 Taxonomy classifier (`pmscope/taxonomy/classifier.py`)

A simple keyword-based classifier that assigns one of `{military_geopolitics, corporate_disclosure, regulatory_decision, other}` to each market based on `question`, `description`, and `category_raw`.

For Task 01, this is a **rule-based heuristic** (no LLM yet):
- `military_geopolitics`: keywords like `strike`, `troops`, `treaty`, `sanction`, `ceasefire`, `prisoner`, `embassy`, `nuclear`, `weapon`, `airstrike`, `military`, `Iran`, `Israel`, `Ukraine`, `Russia`, `China`, `Taiwan`, plus tag `geopolitics` or `politics`.
- `corporate_disclosure`: keywords like `launch`, `release`, `acquisition`, `merger`, `earnings`, `revenue`, `IPO`, `Google`, `OpenAI`, `Apple`, `Microsoft`, `Anthropic`, plus tag containing `business` / `tech`.
- `regulatory_decision`: keywords like `FDA`, `SEC`, `FCC`, `CFTC`, `approve`, `rate cut`, `rate hike`, `Fed`, `Federal Reserve`, `ruling`, `verdict`, `antitrust`.
- Otherwise: `other`.

Multiple categories possible — pick the highest-priority one in the order above. This is intentionally conservative; LLM upgrade is Task 03.

**CLI command:** `pmscope taxonomy classify --batch [--limit 1000]` (classifies markets where `category_pmscope IS NULL`).

### 3.13 CLI (`pmscope/cli.py`)

Use Typer with subcommands:

```
pmscope collect gamma --since DATE --categories COMMA_LIST
pmscope collect clob --market HEX [--start-ts ISO] [--end-ts ISO]
pmscope collect subgraph --market HEX [--from-ts ISO]
pmscope collect uma --market HEX | --all-resolved
pmscope collect polygonscan --wallet HEX | --all-stale [--max-age-days N]
pmscope taxonomy classify --batch [--limit N]
pmscope db init
pmscope db migrate
```

All commands should support `--dry-run` (compute work but don't write to DB).

### 3.14 Sample backfill script (`scripts/backfill_sample.py`)

A standalone script that runs the full pipeline against a small sample (≤ 20 markets) end-to-end. Used to validate that the data layer is functional before attempting full backfill.

The script:
1. Calls `gamma` collector for markets in last 90 days, all three categories.
2. Calls `clob` collector for each.
3. Calls `subgraph` collector for each.
4. Calls `uma` collector for resolved ones.
5. Picks 20 wallets with most trades and calls `polygonscan` collector.
6. Calls `taxonomy classify --batch`.
7. Prints a summary report: how many markets, prices, trades, wallets ingested.

### 3.15 Docker dev stack (`docker-compose.yml` at repo root)

Postgres + TimescaleDB:

```yaml
services:
  db:
    image: timescale/timescaledb:latest-pg16
    environment:
      POSTGRES_USER: pmscope
      POSTGRES_PASSWORD: pmscope
      POSTGRES_DB: pmscope
    ports:
      - "5432:5432"
    volumes:
      - pmscope_pgdata:/var/lib/postgresql/data
volumes:
  pmscope_pgdata:
```

`scripts/init_db.sh` should run `docker-compose up -d`, wait for healthy, and run `pmscope db init` and `alembic upgrade head`.

### 3.16 Tests

For each collector, three kinds of tests:

1. **Unit tests** for parsing and transformation logic, with synthetic input.
2. **Integration tests** with `pytest-vcr` cassettes (record once against real APIs, replay in CI). Cassettes go in `tests/cassettes/`.
3. **Schema tests** that the persistence layer round-trips data correctly.

Specifically:
- `test_gamma.py` — fetches one well-known market by id and asserts schema mapping.
- `test_clob.py` — fetches price history for one market and asserts that timestamps are minute-aligned, prices in [0, 1].
- `test_subgraph.py` — fetches first 5 trades for one market and asserts `side` inference is correct.
- `test_uma.py` — for one known resolved market, asserts that resolution_outcome, resolved_at, evidence_url are recovered.
- `test_polygonscan.py` — for one well-known wallet, asserts first_seen_chain_at is in the past and funding_sources non-empty.
- `test_taxonomy.py` — ten hand-crafted (question, expected_category) pairs.

CI: GitHub Actions running `uv run pytest` against the cassettes (no live APIs in CI).

### 3.17 README

Sections:
1. What is ForesightFlow (one paragraph)
2. Project structure
3. Local setup (`docker-compose up -d`, `uv sync`, `pmscope db init`, `python scripts/backfill_sample.py`)
4. Configuration via `.env`
5. CLI reference (auto-generated table from Typer)
6. License: MIT for code, CC-BY-4.0 for any future published datasets
7. Citation: link to `foresightflow_draft_v0.2.pdf`

---

## 4. Acceptance criteria

The task is **done** when **all** of the following hold:

1. Repository structure matches Section 2.
2. `docker-compose up -d && uv sync && pmscope db init && alembic upgrade head` succeeds on a clean machine.
3. `python scripts/backfill_sample.py` runs end-to-end against real APIs, ingests at least 10 markets across all three target categories, and exits cleanly.
4. After running the sample backfill, the following SQL queries return non-empty, sensible results:
   - `SELECT category_pmscope, COUNT(*) FROM markets GROUP BY 1;`
   - `SELECT COUNT(*) FROM prices;` (≥ 5000)
   - `SELECT COUNT(*) FROM trades;` (≥ 100)
   - `SELECT COUNT(*) FROM wallets;` (≥ 20)
   - `SELECT COUNT(*) FROM markets WHERE resolved_at IS NOT NULL;` (≥ 1)
5. `uv run pytest` passes locally (with cassettes), and CI passes.
6. `pmscope --help` and every subcommand `--help` produce useful output.
7. Logs are JSON in prod-config (`PMSCOPE_LOG_JSON=true`) and pretty in dev.
8. No secrets in the repo — only `.env.example`.
9. Re-running any collector twice produces no duplicate rows.

---

## 5. Out of scope for Task 01

Do **not** implement:

- T_news recovery (GDELT, LLM matching) — that's Task 02.
- ILS computation or any analytics — that's Task 02.
- Microstructure features (PIN, VPIN, VR, TS, Hawkes, kurtosis) — that's Task 04.
- Real-time WebSocket streaming — that's Task 05.
- Detector model training — that's Task 06.
- FastAPI server — that's Task 07.
- React frontend — that's Task 08.
- Telegram bot — that's Task 09.
- AWS deployment — that's Task 10.
- Any LLM-based code (LLM taxonomy classifier deferred to Task 03).

If something feels in-scope but isn't on the deliverables list, leave a TODO comment with a reference to this document and move on.

---

## 6. Working notes for Claude Code

- **Verify URLs and API behaviour at start.** Before writing the Gamma collector, do a `curl https://gamma-api.polymarket.com/markets?limit=1` and inspect the actual JSON shape. The schema documented above reflects current behaviour, but APIs evolve. If the live shape differs, prefer the live shape and update the brief accordingly with a note in the README.
- **Subgraph: confirm the right one.** There have been multiple Polymarket subgraphs over time. Verify against current Polymarket docs; the canonical one for trades is on The Graph network. With `THEGRAPH_API_KEY` set, use the gateway URL.
- **UMA collector is the most fiddly.** If on-chain log decoding via JSON-RPC turns out hairy, fall back to the UMA subgraph for Task 01 and leave a TODO to switch to direct RPC in Task 02.
- **Be honest about gaps.** Anywhere reality differs from this brief — e.g. an endpoint returns differently-shaped data — do the right thing and note it in `NOTES_FROM_IMPLEMENTATION.md` at the repo root. Don't silently hide deviations.
- **Time discipline.** All timestamps stored as `TIMESTAMPTZ` in UTC. All API timestamps converted to UTC at ingestion boundary. No naïve datetimes anywhere in the codebase.
- **Numeric discipline.** Use `numeric` (not `float`) for prices and amounts. Polymarket settles in USDC (6 decimals); Polymarket prices are bounded in [0, 1] and have 6 decimals of precision in practice.

---

## 7. Hand-off

When Task 01 is complete, the deliverable is:
- A pushed git repo at `https://github.com/ForesightFlow/pmscope` (or whichever name agreed)
- A green CI badge
- A short `IMPLEMENTATION_REPORT.md` at repo root summarizing: (a) anything that diverged from this brief, (b) any open questions for the next task.

Task 02 will pick up from this state and add T_news recovery + ILS computation.

---

*End of Task 01 brief. Document version: v0.1, 2026-04-25.*
