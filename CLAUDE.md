# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ForesightFlow** (`fflow` Python package) is a real-time monitoring system that detects informed trading flows on Polymarket prediction markets. The primary deliverable is a data-collection pipeline (Task 01), with analysis, detection, API, and frontend in subsequent tasks.

Naming convention: brand = **ForesightFlow**, import name = `fflow` (like numpy/NumPy).

See `CHARTER.md` for the full project charter and `TASK_01_scaffold_collectors.md` for the current task spec.

## Tech Stack (locked)

- **Python 3.12** — use modern syntax: `match`, `|` union types, `Self`
- **Package manager:** `uv` (not poetry, not pip directly)
- **HTTP:** `httpx` (async, HTTP/2)
- **GraphQL:** `gql[httpx]` for Polymarket subgraph
- **Database:** PostgreSQL 16 + TimescaleDB extension
- **ORM:** SQLAlchemy 2.0 with `Mapped[...]` typed style
- **Migrations:** Alembic
- **Validation/config:** Pydantic 2.x + pydantic-settings (`env_prefix="FFLOW_"`)
- **CLI:** Typer (entry point: `fflow`)
- **Logging:** structlog (JSON in prod when `FFLOW_LOG_JSON=true`, pretty in dev)
- **Testing:** pytest + pytest-asyncio + pytest-vcr (cassettes in `tests/cassettes/`)

## Common Commands

```bash
# Local dev stack
docker-compose up -d                          # Start Postgres + TimescaleDB
uv sync                                       # Install dependencies
fflow db init                                 # Create schema + TimescaleDB extension
alembic upgrade head                          # Run migrations

# Testing
uv run pytest                                 # All tests (uses VCR cassettes, no live API)
uv run pytest tests/test_gamma.py -k test_name  # Single test

# Collectors (CLI)
fflow collect gamma --since 2024-04-01 --categories politics,geopolitics,regulation
fflow collect clob --market 0x... [--start-ts ISO] [--end-ts ISO]
fflow collect subgraph --market 0x... [--from-ts ISO]
fflow collect uma --market 0x... | --all-resolved
fflow collect polygonscan --wallet 0x... | --all-stale [--max-age-days N]
fflow taxonomy classify --batch [--limit N]

# End-to-end validation
python scripts/backfill_sample.py
```

All `fflow collect *` commands support `--dry-run`.

## Architecture

The `fflow` package is structured as:

```
fflow/collectors/   — One module per data source; all inherit BaseCollector
fflow/taxonomy/     — Rule-based keyword classifier (no LLM in Task 01)
fflow/models.py     — SQLAlchemy 2.0 ORM: markets, prices, trades, wallets, data_collection_runs
fflow/db.py         — Async engine, session factory, TimescaleDB init
fflow/config.py     — pydantic-settings Settings class
fflow/cli.py        — Typer CLI wiring all subcommands
```

**Data flow:** Collectors fetch from external APIs → upsert into Postgres → taxonomy classifier fills `markets.category_fflow` → CLI orchestrates.

**Data sources:**
| Collector | Source | What it provides |
|---|---|---|
| `gamma.py` | Polymarket Gamma API | Market metadata, tags, volume (T_open) |
| `clob.py` | Polymarket CLOB API | 1-minute OHLCV price history |
| `subgraph.py` | The Graph (Polymarket subgraph) | Full historical trade log |
| `uma.py` | UMA Optimistic Oracle | Resolution timestamps (T_resolve), outcome, evidence URL |
| `polygonscan.py` | Polygonscan API | Wallet on-chain history, funding sources |

## Critical Conventions

**Idempotency:** Every collector uses `INSERT ... ON CONFLICT DO UPDATE/DO NOTHING`. Running twice must produce identical DB state, never duplicates.

**Collector contract:** Every run (1) inserts a `data_collection_runs` row with `status='running'`, (2) does work, (3) updates to `status='success'` or `'failed'` with counts.

**Time discipline:** All timestamps are `TIMESTAMPTZ` in UTC. Convert all API timestamps at the ingestion boundary. Zero naïve datetimes.

**Numeric discipline:** Prices and USDC amounts use SQL `numeric` type (not `float`). YES-outcome prices are in `[0, 1]` with 6-decimal precision.

**Async-first:** All I/O uses async (`httpx`, `sqlalchemy[asyncio]`).

**Retry logic:** `RetryableHTTPClient` (in `base.py`) retries on 5xx, 408, 429, connection errors with exponential backoff + jitter; honors `Retry-After`; capped at `settings.http_max_retries`.

**Rate limits:** Polygonscan free tier allows 5 req/sec — implement token-bucket at 4 req/sec.

## Database Schema Notes

- `markets.id` = Polymarket condition ID (`0x...` hex string, PK)
- `markets.category_fflow` starts as NULL; taxonomy classifier fills it
- `prices` is a TimescaleDB hypertable partitioned on `ts` (7-day chunks); minute-aligned UTC timestamps
- `trades` unique constraint on `(tx_hash, log_index)`
- `wallets.address` = lowercase hex
- CLOB YES token id lives in `markets.raw_metadata['clobTokenIds'][1]` (index 1 = YES, 0 = NO)
- DB name and user: `fflow` (see docker-compose)

## Testing Strategy

- **Unit tests:** parsing/transformation with synthetic input
- **Integration tests:** pytest-vcr cassettes in `tests/cassettes/` — record real API responses once, replay in CI (no live API calls in CI)
- **Schema tests:** ORM round-trips

## Implementation Notes (from Task 01 brief)

- Before writing a collector, `curl` the live endpoint to verify current JSON shape — update if it differs from the spec
- Polymarket has had multiple subgraphs; verify the canonical one for trades on The Graph; attach `Authorization: Bearer $FFLOW_THEGRAPH_API_KEY` when set
- UMA collector: if on-chain JSON-RPC log decoding is complex, use the UMA subgraph as fallback and leave a TODO
- Document any deviations from the spec in `NOTES_FROM_IMPLEMENTATION.md` at repo root

## Task Roadmap (do not implement beyond current task)

| Task | Scope |
|---|---|
| 01 (current) | Scaffold + collectors + storage schema |
| 02 | T_news recovery (GDELT, LLM-assisted) + ILS computation |
| 03 | LLM taxonomy classifier upgrade |
| 04 | Microstructure features (PIN, VPIN, Kyle's lambda) |
| 05 | Real-time WebSocket streaming |
| 06 | Detector model training |
| 07 | FastAPI server |
| 08 | React frontend |
| 09 | Telegram bot |
| 10 | AWS deployment |
