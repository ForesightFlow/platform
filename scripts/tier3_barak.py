"""Task 02F Phase 4 — LLM Tier 3 on Barak Epstein market.

T_news recovery method:
  1. Primary: web-search-verified date (most accurate for Dec 2025 events outside
     model training window). Source: CNN/Al Jazeera/Times of Israel, all dated
     2025-12-18 — House Democrats on Oversight Committee released 68 Epstein estate
     photos including Barak photo, "a day before DOJ deadline."
  2. Fallback: would use fflow news tier3 --market <id> --confirm if API key set.

T_news = 2025-12-18T18:00:00Z
  Rationale: Release occurred during US afternoon (EST) on Thursday Dec 18.
  Multiple outlets (CNN, Al Jazeera, NBC, ABC) published Dec 18. Using 18:00 UTC
  (1pm ET) as a conservative estimate; actual release may have been ~3-5pm ET.
  Second release (DOJ main batch) was Dec 19. Barak photo first appeared Dec 18.

Stores as tier=3, confidence=0.90 (web-verified multi-source, date certain ±1 day).

Then recomputes ILS for Barak at the new T_news and compares to proxy ILS.
"""

import asyncio
import json
import logging
import pathlib
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from fflow.db import AsyncSessionLocal
from fflow.models import NewsTimestamp
from fflow.scoring.ils import compute_ils, PriceLookupError
from fflow.scoring.price_series import reconstruct_price_series

BARAK_ID = "0xfa1543cdef36d55ef9126aaab6015c7c7ed5aa6a2bb5be355f5cacc2302c7374"

# Web-search-derived T_news
T_NEWS_LLM = datetime(2025, 12, 18, 18, 0, 0, tzinfo=UTC)
T_NEWS_SOURCE = (
    "web_search:2025-12-18 — House Oversight Committee (Dems) released 68 Epstein estate photos "
    "including Barak photo (CNN, Al Jazeera, Times of Israel, NBC, ABC all dated 2025-12-18). "
    "DOJ main release was Dec 19. Barak first public mention: Dec 18 photo release."
)
T_NEWS_CONFIDENCE = 0.90  # multi-source, date certain; time within ±4h

LOG_PATH = pathlib.Path("logs/tier3_barak.log")


def setup_log() -> logging.Logger:
    LOG_PATH.parent.mkdir(exist_ok=True)
    logger = logging.getLogger("tier3_barak")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(LOG_PATH, mode="w")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


async def run():
    log = setup_log()
    log.info("=== Task 02F Phase 4 — LLM Tier 3 on Barak (web-verified T_news) ===")
    log.info(f"market_id: {BARAK_ID}")
    log.info(f"T_news (LLM-derived): {T_NEWS_LLM.isoformat()}")
    log.info(f"Source: {T_NEWS_SOURCE}")
    log.info(f"Confidence: {T_NEWS_CONFIDENCE}")

    async with AsyncSessionLocal() as session:
        # ── 1. Get market data ──────────────────────────────────────────────
        row = (await session.execute(text("""
            SELECT m.id, m.question, m.created_at_chain as t_open_raw, m.resolved_at,
                   m.resolution_outcome, ml.t_open, ml.t_news as t_news_proxy,
                   ml.p_open, ml.p_news as p_news_proxy, ml.p_resolve,
                   ml.ils as ils_proxy, ml.wallet_hhi_top10
            FROM market_labels ml
            JOIN markets m ON m.id = ml.market_id
            WHERE m.id = :mid
        """), {"mid": BARAK_ID})).mappings().first()

        if row is None:
            log.error("Market not found in market_labels")
            return

        log.info(f"question: {row['question']}")
        log.info(f"t_open: {row['t_open']}")
        log.info(f"resolved_at: {row['resolved_at']}")
        log.info(f"Proxy T_news: {row['t_news_proxy']}")
        log.info(f"Proxy ILS: {row['ils_proxy']:.4f}")
        log.info(f"Proxy p_open={row['p_open']:.3f} p_news={row['p_news_proxy']:.3f} p_resolve={row['p_resolve']:.0f}")

        t_open = row["t_open"]
        t_resolve = row["resolved_at"]
        p_resolve = float(row["resolution_outcome"])

        # ── 2. Store T_news (tier=3) ────────────────────────────────────────
        log.info("Storing tier=3 news_timestamp...")
        stmt = (
            pg_insert(NewsTimestamp)
            .values(
                market_id=BARAK_ID,
                t_news=T_NEWS_LLM,
                tier=3,
                confidence=T_NEWS_CONFIDENCE,
                notes=T_NEWS_SOURCE,
                recovered_at=datetime.now(UTC),
            )
            .on_conflict_do_update(
                index_elements=["market_id"],
                set_={
                    "t_news": T_NEWS_LLM,
                    "tier": 3,
                    "confidence": T_NEWS_CONFIDENCE,
                    "notes": T_NEWS_SOURCE,
                    "recovered_at": datetime.now(UTC),
                },
            )
        )
        await session.execute(stmt)
        await session.commit()
        log.info("tier=3 timestamp saved.")

        # ── 3. Recompute ILS at T_news_llm ─────────────────────────────────
        log.info("Reconstructing price series...")
        prices = await reconstruct_price_series(BARAK_ID, session, granularity="1min")
        if prices.empty:
            log.error("No price series found")
            return
        log.info(f"Price series: {len(prices)} rows, {prices['ts'].min()} → {prices['ts'].max()}")

        # Snap t_open to first trade if needed
        first_ts = prices["ts"].min()
        if hasattr(first_ts, "to_pydatetime"):
            first_ts = first_ts.to_pydatetime()
        if (first_ts - t_open).total_seconds() > 300:
            t_open = first_ts
            log.info(f"t_open snapped to first trade: {t_open}")

        # Compute ILS at LLM T_news
        log.info(f"Computing ILS at T_news_llm = {T_NEWS_LLM}")
        try:
            bundle_llm = compute_ils(
                prices=prices,
                t_open=t_open,
                t_news=T_NEWS_LLM,
                t_resolve=t_resolve,
                p_resolve=p_resolve,
            )
            ils_llm = float(bundle_llm.ils) if bundle_llm.ils is not None else None
            p_news_llm = float(bundle_llm.p_news) if bundle_llm.p_news is not None else None
            p_open_llm = float(bundle_llm.p_open) if bundle_llm.p_open is not None else None
        except PriceLookupError as e:
            log.error(f"ILS compute error: {e}")
            ils_llm = None
            p_news_llm = None
            p_open_llm = None

        # Compute ILS at proxy T_news (for comparison)
        t_news_proxy = row["t_news_proxy"]
        log.info(f"Computing ILS at T_news_proxy = {t_news_proxy}")
        try:
            bundle_proxy = compute_ils(
                prices=prices,
                t_open=t_open,
                t_news=t_news_proxy,
                t_resolve=t_resolve,
                p_resolve=p_resolve,
            )
            ils_proxy_recomputed = float(bundle_proxy.ils) if bundle_proxy.ils is not None else None
            p_news_proxy_recomputed = float(bundle_proxy.p_news) if bundle_proxy.p_news is not None else None
        except PriceLookupError as e:
            log.error(f"Proxy ILS compute error: {e}")
            ils_proxy_recomputed = None
            p_news_proxy_recomputed = None

        log.info("=== ILS COMPARISON ===")
        log.info(f"Proxy T_news (resolved_at-24h): {t_news_proxy}")
        log.info(f"  p_news_proxy = {p_news_proxy_recomputed:.4f}" if p_news_proxy_recomputed else "  p_news_proxy = N/A")
        log.info(f"  ILS_proxy = {ils_proxy_recomputed:.4f}" if ils_proxy_recomputed else "  ILS_proxy = N/A")
        log.info(f"LLM T_news (Dec 18 2025): {T_NEWS_LLM}")
        log.info(f"  p_news_llm = {p_news_llm:.4f}" if p_news_llm else "  p_news_llm = N/A")
        log.info(f"  ILS_llm = {ils_llm:.4f}" if ils_llm else "  ILS_llm = N/A")
        if ils_llm is not None and ils_proxy_recomputed is not None:
            delta = ils_llm - ils_proxy_recomputed
            log.info(f"  ΔILS = {delta:+.4f} ({'more' if delta > 0 else 'less'} signal with LLM T_news)")

        # ── 4. Wallet timing analysis with new T_news ────────────────────────
        log.info("=== WALLET TIMING WITH LLM T_NEWS ===")
        wallet_rows = (await session.execute(text("""
            SELECT
                t.taker_address,
                SUM(t.notional_usdc) as total_vol,
                COUNT(*) as n_trades,
                MIN(t.ts) as first_trade,
                AVG(t.price) as avg_yes_price,
                (SELECT COUNT(DISTINCT t2.market_id) FROM trades t2
                 WHERE t2.taker_address = t.taker_address) as total_markets
            FROM trades t
            WHERE t.market_id = :mid
              AND t.side = 'BUY'
              AND t.outcome_index = 1
            GROUP BY t.taker_address
            ORDER BY SUM(t.notional_usdc) DESC
            LIMIT 15
        """), {"mid": BARAK_ID})).mappings().all()

        results = []
        for r in wallet_rows:
            first = r["first_trade"]
            mins_before_proxy = (t_news_proxy - first).total_seconds() / 60 if first else None
            mins_before_llm = (T_NEWS_LLM - first).total_seconds() / 60 if first else None
            pre_proxy = mins_before_proxy is not None and mins_before_proxy > 0
            pre_llm = mins_before_llm is not None and mins_before_llm > 0
            timing_label = (
                "PRE_BOTH" if (pre_llm and pre_proxy) else
                "PRE_PROXY_ONLY" if (pre_proxy and not pre_llm) else
                "POST_BOTH"
            )
            results.append({
                "wallet": r["taker_address"],
                "vol": float(r["total_vol"]),
                "n_trades": r["n_trades"],
                "first_trade": str(first)[:16] if first else None,
                "avg_yes_price": float(r["avg_yes_price"]) if r["avg_yes_price"] else None,
                "mins_before_proxy": round(mins_before_proxy) if mins_before_proxy else None,
                "mins_before_llm": round(mins_before_llm) if mins_before_llm else None,
                "timing": timing_label,
                "total_markets": r["total_markets"],
            })
            log.info(
                f"  {r['taker_address'][:14]}... "
                f"vol=${float(r['total_vol']):.0f} "
                f"first={str(first)[:16]} "
                f"proxy_lead={round(mins_before_proxy) if mins_before_proxy else 'N/A'}min "
                f"llm_lead={round(mins_before_llm) if mins_before_llm else 'N/A'}min "
                f"timing={timing_label}"
            )

        # Save results to JSON for report
        output = {
            "generated_at": datetime.now(UTC).isoformat(),
            "market_id": BARAK_ID,
            "t_news_proxy": str(t_news_proxy),
            "t_news_llm": T_NEWS_LLM.isoformat(),
            "ils_proxy": ils_proxy_recomputed,
            "ils_llm": ils_llm,
            "p_open": p_open_llm,
            "p_news_proxy": p_news_proxy_recomputed,
            "p_news_llm": p_news_llm,
            "p_resolve": p_resolve,
            "wallets": results,
        }
        out_path = pathlib.Path("/tmp/tier3_barak_results.json")
        out_path.write_text(json.dumps(output, indent=2, default=str))
        log.info(f"Results saved to {out_path}")
        log.info("=== Phase 4 complete ===")
        return output


if __name__ == "__main__":
    asyncio.run(run())
