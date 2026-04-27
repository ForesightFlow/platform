"""Trade-based price series reconstruction.

Two public functions:
  reconstruct_price_series(market_id, session, granularity='1min') -> pd.DataFrame
  get_price_at(market_id, ts, session, tolerance_minutes=5) -> Decimal | None

The CLOB prices table is the primary source. When absent, fall back to
trade-derived VWAP aggregated into the same granularity.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fflow.log import get_logger

log = get_logger(__name__)

_SUPPORTED_GRANULARITIES = {"1min": "1 minute", "5min": "5 minutes", "1h": "1 hour"}
_LOOKUP_TOLERANCE = timedelta(minutes=5)


async def reconstruct_price_series(
    market_id: str,
    session: AsyncSession,
    granularity: str = "1min",
) -> pd.DataFrame:
    """Return a minute-resolution price DataFrame for market_id.

    Tries the CLOB prices table first. If that table has fewer than 2 rows for
    this market, falls back to trade-level VWAP aggregated at the requested
    granularity.

    Returns:
        DataFrame with columns:
            ts          — tz-aware UTC datetime, minute-aligned
            mid_price   — Decimal in [0, 1]
            volume_minute — Decimal (USDC notional in the bucket)
            source      — 'clob' | 'trade_vwap'

    Empty DataFrame if no data exists.
    """
    if granularity not in _SUPPORTED_GRANULARITIES:
        raise ValueError(f"Unsupported granularity {granularity!r}; use {list(_SUPPORTED_GRANULARITIES)}")

    # ── CLOB attempt ─────────────────────────────────────────────────────────
    clob_rows = (
        await session.execute(
            text(
                "SELECT ts, mid_price FROM prices "
                "WHERE market_id = :mid ORDER BY ts"
            ),
            {"mid": market_id},
        )
    ).fetchall()

    if len(clob_rows) >= 2:
        df = pd.DataFrame(
            [{"ts": r[0], "mid_price": Decimal(str(r[1])), "volume_minute": Decimal("0"), "source": "clob"}
             for r in clob_rows]
        )
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        log.debug("price_series_clob", market=market_id, rows=len(df))
        return df

    # ── Trade VWAP fallback ───────────────────────────────────────────────────
    pg_interval = _SUPPORTED_GRANULARITIES[granularity]
    rows = (
        await session.execute(
            text(
                f"""
                SELECT
                    date_trunc('minute', ts) AS bucket,
                    SUM(notional_usdc::numeric) AS notional,
                    SUM(size_shares::numeric)   AS shares
                FROM trades
                WHERE market_id = :mid
                GROUP BY bucket
                ORDER BY bucket
                """
            ),
            {"mid": market_id},
        )
    ).fetchall()

    if not rows:
        return pd.DataFrame(columns=["ts", "mid_price", "volume_minute", "source"])

    records = []
    for bucket, notional, shares in rows:
        if shares and float(shares) > 0:
            vwap = Decimal(str(notional)) / Decimal(str(shares))
            # clamp to [0, 1] — trades.price is already 0-1 but rounding edge cases
            vwap = max(Decimal("0"), min(Decimal("1"), vwap))
        else:
            vwap = None
        records.append({"ts": bucket, "mid_price": vwap, "volume_minute": Decimal(str(notional or 0)), "source": "trade_vwap"})

    df = pd.DataFrame(records).dropna(subset=["mid_price"])
    if df.empty:
        return df

    df["ts"] = pd.to_datetime(df["ts"], utc=True)

    # Forward-fill gaps: reindex to full minute range, ffill mid_price
    df = df.set_index("ts").sort_index()
    full_idx = pd.date_range(df.index[0], df.index[-1], freq="1min", tz=UTC)
    df = df.reindex(full_idx)
    df["mid_price"] = df["mid_price"].ffill()
    df["volume_minute"] = df["volume_minute"].fillna(Decimal("0"))
    df["source"] = df["source"].ffill()
    df = df.reset_index().rename(columns={"index": "ts"})

    log.debug("price_series_trade_vwap", market=market_id, rows=len(df))
    return df


async def get_price_at(
    market_id: str,
    ts: datetime,
    session: AsyncSession,
    tolerance_minutes: int = 5,
) -> tuple[Decimal | None, str]:
    """Return (price, source) at the given timestamp.

    Tries CLOB prices first; falls back to trade VWAP series. Returns
    (None, 'not_found') if no price within tolerance.
    """
    ts_utc = ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)
    ts_snapped = ts_utc.replace(second=0, microsecond=0)
    tol = timedelta(minutes=tolerance_minutes)

    # ── CLOB first ───────────────────────────────────────────────────────────
    row = (
        await session.execute(
            text(
                "SELECT mid_price, ts FROM prices "
                "WHERE market_id = :mid AND ts BETWEEN :lo AND :hi "
                "ORDER BY ABS(EXTRACT(EPOCH FROM (ts - :ts))) LIMIT 1"
            ),
            {
                "mid": market_id,
                "lo": ts_snapped - tol,
                "hi": ts_snapped + tol,
                "ts": ts_snapped,
            },
        )
    ).fetchone()

    if row is not None:
        try:
            return Decimal(str(row[0])), "clob"
        except InvalidOperation:
            pass

    # ── Trade VWAP fallback ───────────────────────────────────────────────────
    vwap_row = (
        await session.execute(
            text(
                """
                SELECT
                    SUM(notional_usdc::numeric) / NULLIF(SUM(size_shares::numeric), 0) AS vwap
                FROM trades
                WHERE market_id = :mid
                  AND ts BETWEEN :lo AND :hi
                """
            ),
            {
                "mid": market_id,
                "lo": ts_snapped - tol,
                "hi": ts_snapped + tol,
            },
        )
    ).fetchone()

    if vwap_row and vwap_row[0] is not None:
        price = max(Decimal("0"), min(Decimal("1"), Decimal(str(vwap_row[0]))))
        log.debug("get_price_at_trade_vwap", market=market_id, ts=ts_snapped, price=str(price))
        return price, "trade_vwap"

    log.debug("get_price_at_not_found", market=market_id, ts=ts_snapped)
    return None, "not_found"
