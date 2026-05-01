"""Volume and jump features derived from the Trade table."""

from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from fflow.models import Trade


async def compute_volume_features(
    session: AsyncSession,
    market_id: str,
    t_news: datetime,
    t_resolve: datetime,
) -> dict:
    """Compute volume-based features for a market.

    Returns a dict with:
        volume_pre_share:    fraction of total volume traded before t_news
        pre_news_max_jump:   largest single-trade notional in pre-news window (USDC)
        n_trades_total:      total number of trades in [t_open, t_resolve]
        n_trades_pre_news:   number of trades strictly before t_news
    """
    total_q = (
        sa.select(
            sa.func.count().label("n"),
            sa.func.coalesce(sa.func.sum(Trade.notional_usdc), 0).label("vol"),
        )
        .where(Trade.market_id == market_id)
        .where(Trade.ts <= t_resolve)
    )
    pre_q = (
        sa.select(
            sa.func.count().label("n"),
            sa.func.coalesce(sa.func.sum(Trade.notional_usdc), 0).label("vol"),
            sa.func.coalesce(sa.func.max(Trade.notional_usdc), 0).label("max_jump"),
        )
        .where(Trade.market_id == market_id)
        .where(Trade.ts < t_news)
    )

    total_row = (await session.execute(total_q)).one()
    pre_row = (await session.execute(pre_q)).one()

    n_total = int(total_row.n)
    n_pre = int(pre_row.n)
    vol_total = Decimal(str(total_row.vol))
    vol_pre = Decimal(str(pre_row.vol))
    max_jump = Decimal(str(pre_row.max_jump))

    volume_pre_share: Decimal | None = None
    if vol_total > 0:
        volume_pre_share = (vol_pre / vol_total).quantize(Decimal("0.000001"))

    return {
        "volume_pre_share": volume_pre_share,
        "pre_news_max_jump": max_jump if n_pre > 0 else None,
        "n_trades_total": n_total,
        "n_trades_pre_news": n_pre,
    }
