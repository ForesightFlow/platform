"""Wallet-level features: HHI concentration and time-to-news signals."""

from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from fflow.models import Trade


async def compute_wallet_features(
    session: AsyncSession,
    market_id: str,
    t_news: datetime,
    p_resolve: int,
) -> dict:
    """Compute wallet concentration and early-mover features.

    Returns a dict with:
        wallet_hhi_top10:     Herfindahl-Hirschman Index of notional volume
                              across the top-10 wallets pre-news (0–1 scale)
        time_to_news_top10:   list of dicts [{address, minutes_before_news,
                              notional_usdc}] for the 10 largest pre-news
                              traders, sorted by notional descending
    """
    # Only count trades aligned with the resolution side
    # (YES trades when p_resolve=1, NO trades when p_resolve=0)
    side = "BUY" if p_resolve == 1 else "SELL"

    pre_trades_q = (
        sa.select(
            Trade.taker_address,
            sa.func.sum(Trade.notional_usdc).label("notional"),
            sa.func.min(Trade.ts).label("first_trade_ts"),
        )
        .where(Trade.market_id == market_id)
        .where(Trade.ts < t_news)
        .where(Trade.side == side)
        .where(Trade.outcome_index == p_resolve)
        .group_by(Trade.taker_address)
        .order_by(sa.desc("notional"))
    )

    rows = (await session.execute(pre_trades_q)).all()

    if not rows:
        return {
            "wallet_hhi_top10": None,
            "time_to_news_top10": None,
        }

    top10 = rows[:10]
    top10_notionals = [Decimal(str(r.notional)) for r in top10]
    total_top10 = sum(top10_notionals)

    hhi: Decimal | None = None
    if total_top10 > 0:
        shares = [n / total_top10 for n in top10_notionals]
        hhi = sum(s * s for s in shares).quantize(Decimal("0.000001"))

    time_to_news = []
    for r in top10:
        delta = t_news - r.first_trade_ts
        minutes_before = delta.total_seconds() / 60
        time_to_news.append(
            {
                "address": r.taker_address,
                "minutes_before_news": round(minutes_before, 1),
                "notional_usdc": float(r.notional),
            }
        )

    return {
        "wallet_hhi_top10": hhi,
        "time_to_news_top10": time_to_news if time_to_news else None,
    }
