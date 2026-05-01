"""Build the polymarket-resolution-typology-v1 dataset.

Extracts all markets from the ForesightFlow DB with created_at_chain <=
2026-04-27T00:00:00Z (reproducibility cutoff), writes two parallel formats:
  datasets/polymarket-resolution-typology/data/typology-v1.jsonl.gz
  datasets/polymarket-resolution-typology/data/typology-v1.parquet

Usage:
    uv run python scripts/build_typology_dataset.py
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg

CUTOFF = datetime(2026, 4, 27, 0, 0, 0, tzinfo=timezone.utc)
OUT_DIR = Path(__file__).parent.parent / "datasets" / "polymarket-resolution-typology" / "data"
JSONL_GZ = OUT_DIR / "typology-v1.jsonl.gz"
PARQUET = OUT_DIR / "typology-v1.parquet"

# Load DB URL from settings
import os
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

DB_URL_ASYNC = os.environ.get("FFLOW_DB_URL", "postgresql+asyncpg://fflow:fflow@localhost:5432/fflow")
# Convert SQLAlchemy async URL to asyncpg DSN
DB_DSN = DB_URL_ASYNC.replace("postgresql+asyncpg://", "postgresql://")


QUERY = """
SELECT
    m.id                            AS market_id,
    m.question,
    m.description,
    m.category_fflow,
    m.resolution_type,
    m.resolution_outcome,
    m.volume_total_usdc::float8     AS volume_total_usdc,
    m.created_at_chain              AS created_at,
    m.end_date                      AS closed_at,
    m.resolved_at,
    COALESCE(tc.n_trades, 0)        AS n_trades_in_db
FROM markets m
LEFT JOIN (
    SELECT market_id, COUNT(*) AS n_trades
    FROM trades
    GROUP BY market_id
) tc ON tc.market_id = m.id
WHERE m.created_at_chain <= $1
   OR m.created_at_chain IS NULL
ORDER BY m.created_at_chain ASC NULLS LAST
"""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat().replace("+00:00", "Z")


async def main() -> None:
    import asyncpg as apg

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Connecting to DB …")
    conn = await apg.connect(DB_DSN)

    print(f"Running extraction query (cutoff: {CUTOFF.isoformat()}) …")
    t0 = time.monotonic()
    rows = await conn.fetch(QUERY, CUTOFF)
    await conn.close()
    elapsed = time.monotonic() - t0
    print(f"Fetched {len(rows):,} rows in {elapsed:.1f}s")

    if elapsed > 600:
        print("ERROR: query took >10 minutes — stopping")
        sys.exit(1)

    # ── Write JSONL.GZ ─────────────────────────────────────────────────────
    print("Writing JSONL.GZ …")
    with gzip.open(JSONL_GZ, "wt", encoding="utf-8", compresslevel=6) as gz:
        for row in rows:
            record = {
                "market_id": row["market_id"],
                "question": row["question"],
                "description": row["description"],
                "category_fflow": row["category_fflow"],
                "resolution_type": row["resolution_type"],
                "resolution_outcome": row["resolution_outcome"],
                "volume_total_usdc": row["volume_total_usdc"],
                "created_at": iso(row["created_at"]),
                "closed_at": iso(row["closed_at"]),
                "resolved_at": iso(row["resolved_at"]),
                "n_trades_in_db": row["n_trades_in_db"],
            }
            gz.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"  {JSONL_GZ.stat().st_size / 1_048_576:.1f} MB")

    # ── Write Parquet ───────────────────────────────────────────────────────
    print("Writing Parquet …")
    schema = pa.schema([
        pa.field("market_id", pa.string(), nullable=False),
        pa.field("question", pa.string(), nullable=False),
        pa.field("description", pa.string(), nullable=True),
        pa.field("category_fflow", pa.string(), nullable=False),
        pa.field("resolution_type", pa.string(), nullable=False),
        pa.field("resolution_outcome", pa.int8(), nullable=True),
        pa.field("volume_total_usdc", pa.float64(), nullable=True),
        pa.field("created_at", pa.string(), nullable=True),
        pa.field("closed_at", pa.string(), nullable=True),
        pa.field("resolved_at", pa.string(), nullable=True),
        pa.field("n_trades_in_db", pa.int32(), nullable=False),
    ])

    arrays = {
        "market_id": pa.array([r["market_id"] for r in rows], type=pa.string()),
        "question": pa.array([r["question"] for r in rows], type=pa.string()),
        "description": pa.array([r["description"] for r in rows], type=pa.string()),
        "category_fflow": pa.array([r["category_fflow"] for r in rows], type=pa.string()),
        "resolution_type": pa.array([r["resolution_type"] for r in rows], type=pa.string()),
        "resolution_outcome": pa.array([r["resolution_outcome"] for r in rows], type=pa.int8()),
        "volume_total_usdc": pa.array([r["volume_total_usdc"] for r in rows], type=pa.float64()),
        "created_at": pa.array([iso(r["created_at"]) for r in rows], type=pa.string()),
        "closed_at": pa.array([iso(r["closed_at"]) for r in rows], type=pa.string()),
        "resolved_at": pa.array([iso(r["resolved_at"]) for r in rows], type=pa.string()),
        "n_trades_in_db": pa.array([r["n_trades_in_db"] for r in rows], type=pa.int32()),
    }
    table = pa.table(arrays, schema=schema)
    pq.write_table(table, PARQUET, compression="snappy")
    print(f"  {PARQUET.stat().st_size / 1_048_576:.1f} MB")

    # ── Verification counts ─────────────────────────────────────────────────
    print("\n── Verification counts ──")
    total = len(rows)
    by_type = {}
    by_cat = {}
    for r in rows:
        rt = r["resolution_type"] or "null"
        by_type[rt] = by_type.get(rt, 0) + 1
        cat = r["category_fflow"] or "null"
        by_cat[cat] = by_cat.get(cat, 0) + 1

    print(f"Total records: {total:,}")
    print("By resolution_type:")
    for k, v in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {k:<25} {v:>8,}  ({100*v/total:.1f}%)")
    print("By category_fflow:")
    for k, v in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"  {k:<25} {v:>8,}  ({100*v/total:.1f}%)")

    # File sizes
    jsonlgz_size = JSONL_GZ.stat().st_size
    parquet_size = PARQUET.stat().st_size
    print(f"\nFile sizes:")
    print(f"  typology-v1.jsonl.gz   {jsonlgz_size:>12,} bytes  ({jsonlgz_size/1_048_576:.1f} MB)")
    print(f"  typology-v1.parquet    {parquet_size:>12,} bytes  ({parquet_size/1_048_576:.1f} MB)")

    # Sanity checks vs expected
    print("\n── Sanity checks ──")
    checks = [
        (total == 911237, f"total records: {total} (expected 911,237)"),
        (by_type.get("deadline_resolved", 0) > 55000, f"deadline_resolved: {by_type.get('deadline_resolved',0):,}"),
        (by_type.get("event_resolved", 0) > 900, f"event_resolved: {by_type.get('event_resolved',0):,}"),
        (by_type.get("unclassifiable", 0) > 850000, f"unclassifiable: {by_type.get('unclassifiable',0):,}"),
        (by_cat.get("corporate_disclosure", 0) > 18000, f"corporate_disclosure: {by_cat.get('corporate_disclosure',0):,}"),
    ]
    all_ok = True
    for ok, msg in checks:
        status = "OK  " if ok else "FAIL"
        print(f"  [{status}] {msg}")
        if not ok:
            all_ok = False

    if not all_ok:
        print("\nWARNING: One or more sanity checks failed. Review before publishing.")
        sys.exit(1)

    # ── Compute manifest hashes ─────────────────────────────────────────────
    print("\n── SHA-256 hashes ──")
    jsonlgz_sha = sha256_file(JSONL_GZ)
    parquet_sha = sha256_file(PARQUET)
    print(f"  jsonl.gz   {jsonlgz_sha}")
    print(f"  parquet    {parquet_sha}")

    manifest = {
        "version": "1.0",
        "tag": "polymarket-resolution-typology-v1",
        "released": "2026-04-28",
        "cutoff": "2026-04-27T00:00:00Z",
        "files": {
            "data/typology-v1.jsonl.gz": {
                "sha256": jsonlgz_sha,
                "size_bytes": jsonlgz_size,
                "n_lines": total,
            },
            "data/typology-v1.parquet": {
                "sha256": parquet_sha,
                "size_bytes": parquet_size,
                "n_rows": total,
            },
        },
        "counts": {
            "total": total,
            "by_resolution_type": by_type,
            "by_category_fflow": by_cat,
        },
    }
    manifest_path = JSONL_GZ.parent.parent / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\nMANIFEST.json written to {manifest_path}")
    print("\nExtraction complete.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
