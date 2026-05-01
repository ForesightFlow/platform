# ForesightFlow

Real-time detection of informed trading flows in Polymarket prediction markets.

ForesightFlow collects microstructure data across three market categories — military/geopolitical events, corporate disclosures, and regulatory decisions — and computes information leakage signatures to surface markets where informed traders may have acted before public announcements.

## Local Setup

```bash
# Start Postgres + TimescaleDB
docker-compose up -d

# Install dependencies
uv sync

# Initialize database
fflow db init
alembic upgrade head

# Run end-to-end validation
python scripts/backfill_sample.py
```

Or use the convenience script:

```bash
bash scripts/init_db.sh
```

## Configuration

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

Key variables:

| Variable | Description |
|---|---|
| `FFLOW_DB_URL` | Postgres async connection string |
| `FFLOW_THEGRAPH_API_KEY` | The Graph API key (for subgraph access) |
| `FFLOW_POLYGONSCAN_API_KEY` | Polygonscan free API key |
| `FFLOW_LOG_JSON` | Set `true` in production for JSON logging |

## CLI Reference

```
fflow collect gamma --since 2024-04-01 --categories politics,geopolitics,regulation
fflow collect clob --market 0x... [--start-ts ISO] [--end-ts ISO]
fflow collect subgraph --market 0x... [--from-ts ISO]
fflow collect uma --market 0x... | --all-resolved
fflow collect polygonscan --wallet 0x... | --all-stale [--max-age-days N]
fflow taxonomy classify --batch [--limit N]
fflow db init
fflow db migrate
```

All `collect` commands support `--dry-run`.

## Running Tests

```bash
uv run pytest                          # all tests (uses VCR cassettes)
uv run pytest tests/test_taxonomy.py   # single module
uv run pytest --vcr-record=new_episodes tests/test_gamma.py  # record cassettes
```

## Architecture

See `CHARTER.md` for the full project charter and `CLAUDE.md` for implementation guidance.

Data flow: **Collectors** → PostgreSQL + TimescaleDB → **Taxonomy Classifier** → **CLI**

| Collector | Source | Data |
|---|---|---|
| `gamma` | Polymarket Gamma API | Market metadata, T_open |
| `clob` | Polymarket CLOB API | 1-minute price history |
| `subgraph` | The Graph | Full trade log |
| `uma` | UMA Optimistic Oracle | Resolution timestamps, T_resolve |
| `polygonscan` | Polygonscan | Wallet on-chain history |

## License

Code: MIT. Future published datasets: CC-BY-4.0.

## Citation

Nechepurenko M. (2026). *ForesightFlow: Real-Time Detection of Informed Trading in Decentralized Prediction Markets.* Preprint: `foresightflow_draft_v0.2.pdf`.

---

## Cite this work

If you use this code, please cite the papers it implements:

### ForesightFlow: An Information Leakage Score Framework for Prediction Markets

```bibtex
@misc{nechepurenko2026ils-framework,
  title  = {ForesightFlow: An Information Leakage Score Framework for Prediction Markets},
  author = {Nechepurenko, Maksym},
  year   = {2026},
  url    = {https://papers.ssrn.com/abstract=6687361},
  note   = {SSRN Working Paper 6687361}
}
```

Full preprint: <https://foresightflow.org/publications/foresightflow-ils-framework>.

### Empirical Evaluation of Deadline-Resolved Information Leakage on Documented Polymarket Insider Cases

```bibtex
@misc{nechepurenko2026deadline-leakage,
  title  = {Empirical Evaluation of Deadline-Resolved Information Leakage on Documented Polymarket Insider Cases},
  author = {Nechepurenko, Maksym},
  year   = {2026},
  url    = {https://papers.ssrn.com/abstract=6687398},
  note   = {SSRN Working Paper 6687398}
}
```

Full preprint: <https://foresightflow.org/publications/deadline-resolved-information-leakage>.

### Per-Market Information Leakage and Order-Flow Skill

```bibtex
@misc{nechepurenko2026permarket-skill,
  title  = {Per-Market Information Leakage and Order-Flow Skill: Two Methodological Lenses on Informed Trading in Decentralized Prediction Markets},
  author = {Nechepurenko, Maksym},
  year   = {2026},
  url    = {https://papers.ssrn.com/abstract=6687418},
  note   = {SSRN Working Paper 6687418}
}
```

Full preprint: <https://foresightflow.org/publications/per-market-information-leakage>.

### ForesightFlow: Real-Time Detection of Informed Trading in Decentralized Prediction Markets

```bibtex
@misc{nechepurenko2026realtime-detection,
  title  = {ForesightFlow: Real-Time Detection of Informed Trading in Decentralized Prediction Markets},
  author = {Nechepurenko, Maksym},
  year   = {2026},
  url    = {https://papers.ssrn.com/abstract=6687441},
  note   = {SSRN Working Paper 6687441}
}
```

Full preprint: <https://foresightflow.org/publications/foresightflow-realtime-detection>.
