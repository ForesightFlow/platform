"""End-to-end label computation pipeline for a single market."""

from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from fflow.models import LabelAudit, Market, MarketLabel, NewsTimestamp, Price
from fflow.scoring.ils import PriceLookupError, compute_ils
from fflow.scoring.price_series import reconstruct_price_series
from fflow.scoring.volume import compute_volume_features
from fflow.scoring.wallet_features import compute_wallet_features

log = structlog.get_logger()


class LabelingError(Exception):
    pass


async def compute_market_label(
    session: AsyncSession,
    market_id: str,
    *,
    price_source: str = "auto",
    dry_run: bool = False,
) -> MarketLabel | None:
    """Compute and upsert a MarketLabel for market_id.

    Requires:
        - market exists with resolution_outcome, created_at_chain, resolved_at
        - at least one NewsTimestamp row exists

    Returns the MarketLabel (unsaved if dry_run=True), or None if prerequisites
    are not met (logs the reason).
    """
    logger = log.bind(market_id=market_id)

    # Load market
    market = await session.get(Market, market_id)
    if market is None:
        logger.warning("market_not_found")
        return None

    if market.resolution_outcome is None:
        logger.info("skipping_unresolved_market")
        return None

    t_open = market.created_at_chain
    t_resolve = market.resolved_at
    p_resolve = market.resolution_outcome

    if t_open is None or t_resolve is None:
        logger.warning("missing_timestamps", t_open=t_open, t_resolve=t_resolve)
        return None

    # Load best available T_news (lowest tier = highest confidence)
    news_row = (
        await session.execute(
            select(NewsTimestamp)
            .where(NewsTimestamp.market_id == market_id)
            .order_by(NewsTimestamp.tier, NewsTimestamp.confidence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if news_row is None:
        logger.info("no_news_timestamp")
        return None

    t_news = news_row.t_news

    # T_news must not predate T_open (market didn't exist yet → ILS undefined)
    if t_news < t_open:
        logger.warning("t_news_predates_t_open", t_news=str(t_news), t_open=str(t_open))
        return None

    # Load price series — CLOB first, trade VWAP fallback (price_source='auto')
    if price_source in ("auto", "clob"):
        prices = await reconstruct_price_series(market_id, session, granularity="1min")
        # If CLOB-only was requested but no data, fail
        if price_source == "clob" and (prices.empty or prices["source"].iloc[0] != "clob"):
            logger.warning("no_clob_price_data")
            return None
    elif price_source == "trade_vwap":
        # Force trade VWAP by temporarily clearing CLOB result check
        from sqlalchemy import text as _sa_text
        trade_rows = (await session.execute(
            _sa_text("""
                SELECT date_trunc('minute', ts) AS bucket,
                       SUM(notional_usdc::numeric)/NULLIF(SUM(size_shares::numeric),0) AS vwap,
                       SUM(notional_usdc::numeric) AS vol
                FROM trades WHERE market_id = :mid GROUP BY bucket ORDER BY bucket
            """), {"mid": market_id}
        )).fetchall()
        if not trade_rows:
            logger.warning("no_trade_data")
            return None
        import pandas as pd
        prices = pd.DataFrame([
            {"ts": r[0], "mid_price": r[1], "volume_minute": r[2], "source": "trade_vwap"}
            for r in trade_rows if r[1] is not None
        ])
        prices["ts"] = pd.to_datetime(prices["ts"], utc=True)
    else:
        raise ValueError(f"Unknown price_source {price_source!r}")

    if prices.empty:
        logger.warning("no_price_data")
        return None

    actual_price_source = prices["source"].iloc[0] if "source" in prices.columns else "unknown"

    import pandas as pd
    # If t_open predates the first trade by more than 5 min, snap t_open to the first
    # available trade timestamp so p_open reflects the first observable price.
    first_ts = prices["ts"].min()
    if hasattr(first_ts, "to_pydatetime"):
        first_ts = first_ts.to_pydatetime()
    from datetime import timedelta
    if (first_ts - t_open).total_seconds() > 300:
        logger.info(
            "t_open_snapped_to_first_trade",
            original_t_open=str(t_open),
            snapped_to=str(first_ts),
        )
        t_open = first_ts

    # Compute ILS
    try:
        ils_bundle = compute_ils(
            prices=prices,
            t_open=t_open,
            t_news=t_news,
            t_resolve=t_resolve,
            p_resolve=p_resolve,
        )
    except PriceLookupError as exc:
        logger.warning("price_lookup_failed", error=str(exc))
        return None

    # Compute volume features
    vol = await compute_volume_features(session, market_id, t_news, t_resolve)

    # Compute wallet features
    wallet = await compute_wallet_features(session, market_id, t_news, p_resolve)

    computed_at = datetime.now(UTC)

    label_data = {
        "market_id": market_id,
        "t_open": t_open,
        "t_news": t_news,
        "t_resolve": t_resolve,
        "p_open": ils_bundle.p_open,
        "p_news": ils_bundle.p_news,
        "p_resolve": p_resolve,
        "delta_pre": ils_bundle.delta_pre,
        "delta_total": ils_bundle.delta_total,
        "ils": ils_bundle.ils,
        "ils_30min": ils_bundle.ils_30min,
        "ils_2h": ils_bundle.ils_2h,
        "ils_6h": ils_bundle.ils_6h,
        "ils_24h": ils_bundle.ils_24h,
        "ils_7d": ils_bundle.ils_7d,
        "volume_pre_share": vol["volume_pre_share"],
        "pre_news_max_jump": vol["pre_news_max_jump"],
        "n_trades_total": vol["n_trades_total"],
        "n_trades_pre_news": vol["n_trades_pre_news"],
        "wallet_hhi_top10": wallet["wallet_hhi_top10"],
        "time_to_news_top10": wallet["time_to_news_top10"],
        "category_fflow": market.category_fflow,
        "price_source": actual_price_source,
        "computed_at": computed_at,
        "flags": ils_bundle.flags,
    }

    label = MarketLabel(**label_data)

    if dry_run:
        logger.info("dry_run_label_computed", ils=str(ils_bundle.ils))
        return label

    # Upsert label
    stmt = (
        insert(MarketLabel)
        .values(**label_data)
        .on_conflict_do_update(
            index_elements=["market_id"],
            set_={k: v for k, v in label_data.items() if k != "market_id"},
        )
    )
    await session.execute(stmt)

    # Append audit record
    audit = LabelAudit(
        market_id=market_id,
        event_type="label_computed",
        details={
            "ils": str(ils_bundle.ils),
            "flags": ils_bundle.flags,
            "t_news_tier": news_row.tier,
        },
        created_at=computed_at,
    )
    session.add(audit)
    await session.commit()

    logger.info(
        "label_written",
        ils=str(ils_bundle.ils),
        flags=ils_bundle.flags,
        t_news_tier=news_row.tier,
    )
    return label
