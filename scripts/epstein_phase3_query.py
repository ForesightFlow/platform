"""Phase 3 of Task 02F: Epstein cluster deep dive queries."""
import asyncio
from sqlalchemy import text
from fflow.db import AsyncSessionLocal

EPSTEIN_IDS = [
    "0xec60889422584c30517308290d07b8e78251b77795a49fa19f210f5b0ef42594",  # AOC
    "0x913caf5e4e8a31944ca4fa888f3e51abf1e1203137d9c1507e4c076322b0dd94",  # Sanders
    "0xfa1543cdef36d55ef9126aaab6015c7c7ed5aa6a2bb5be355f5cacc2302c7374",  # Barak
]

LABEL_MAP = {
    "0xec60889422584c30517308290d07b8e78251b77795a49fa19f210f5b0ef42594": "AOC",
    "0x913caf5e4e8a31944ca4fa888f3e51abf1e1203137d9c1507e4c076322b0dd94": "Sanders",
    "0xfa1543cdef36d55ef9126aaab6015c7c7ed5aa6a2bb5be355f5cacc2302c7374": "Barak",
}

# p_resolve for each market (1=YES, 0=NO)
P_RESOLVE_MAP = {
    "0xec60889422584c30517308290d07b8e78251b77795a49fa19f210f5b0ef42594": 1,  # AOC YES
    "0x913caf5e4e8a31944ca4fa888f3e51abf1e1203137d9c1507e4c076322b0dd94": 1,  # Sanders YES
    "0xfa1543cdef36d55ef9126aaab6015c7c7ed5aa6a2bb5be355f5cacc2302c7374": 1,  # Barak YES
}


async def main():
    async with AsyncSessionLocal() as session:

        # 1. Market labels summary
        rows = (await session.execute(text("""
            SELECT
                m.id, m.question, ml.ils, ml.p_open, ml.p_news, ml.p_resolve,
                ml.t_open, ml.t_news, ml.t_resolve,
                m.volume_total_usdc, m.resolved_at, m.resolution_outcome,
                ml.wallet_hhi_top10
            FROM market_labels ml
            JOIN markets m ON m.id = ml.market_id
            WHERE m.id = ANY(:ids)
        """), {"ids": EPSTEIN_IDS})).mappings().all()

        print("=== MARKET LABELS SUMMARY ===")
        label_data = {}
        for r in rows:
            mid = r["id"]
            label_data[mid] = dict(r)
            print(f"\n--- {LABEL_MAP[mid]} ---")
            print(f"  question: {r['question'][:80]}")
            print(f"  ILS={r['ils']:.3f}  p_open={r['p_open']:.3f}  p_news={r['p_news']:.3f}  p_resolve={r['p_resolve']:.0f}")
            print(f"  t_open={str(r['t_open'])[:19]}  t_news={str(r['t_news'])[:19]}  t_resolve={str(r['t_resolve'])[:19]}")
            print(f"  volume=${r['volume_total_usdc']:.0f}  wallet_hhi_top10={r['wallet_hhi_top10']}")

        # 2. Daily price trajectories (YES price = 1 - mid_price because outcome_index=1 is NO token)
        rows2 = (await session.execute(text("""
            SELECT
                p.market_id,
                DATE_TRUNC('day', p.ts) as day,
                AVG(p.mid_price) as avg_mid,
                COUNT(*) as n_points
            FROM prices p
            WHERE p.market_id = ANY(:ids)
            GROUP BY p.market_id, DATE_TRUNC('day', p.ts)
            ORDER BY p.market_id, day
        """), {"ids": EPSTEIN_IDS})).mappings().all()

        print("\n\n=== DAILY PRICE TRAJECTORY ===")
        cur = None
        for r in rows2:
            mid = r["market_id"]
            if mid != cur:
                cur = mid
                ld = label_data.get(mid, {})
                print(f"\n--- {LABEL_MAP[mid]} (t_news={str(ld.get('t_news','?'))[:10]}, resolved={str(ld.get('t_resolve','?'))[:10]}) ---")
            yes = 1.0 - float(r["avg_mid"])
            print(f"  {str(r['day'])[:10]}: YES={yes:.3f}  (n_minutes={r['n_points']})")

        # 3. Top-10 wallets by pre-news notional per market (resolution-aligned trades)
        print("\n\n=== TOP-10 WALLETS BY PRE-NEWS NOTIONAL ===")
        for mid in EPSTEIN_IDS:
            ld = label_data.get(mid, {})
            t_news = ld.get("t_news")
            p_resolve = int(ld.get("p_resolve", 1))
            side = "BUY" if p_resolve == 1 else "SELL"

            rows3 = (await session.execute(text("""
                SELECT
                    t.taker_address,
                    SUM(t.notional_usdc) as total_notional,
                    COUNT(*) as n_trades,
                    MIN(t.ts) as first_trade,
                    AVG(1.0 - t.price) as avg_yes_price,
                    w.first_seen_chain_at,
                    w.first_seen_polymarket_at,
                    (SELECT COUNT(DISTINCT t2.market_id) FROM trades t2 WHERE t2.taker_address = t.taker_address) as total_markets
                FROM trades t
                LEFT JOIN wallets w ON w.address = t.taker_address
                WHERE t.market_id = :mid
                  AND t.ts < :t_news
                  AND t.side = :side
                  AND t.outcome_index = :outcome_index
                GROUP BY t.taker_address, w.first_seen_chain_at, w.first_seen_polymarket_at
                ORDER BY SUM(t.notional_usdc) DESC
                LIMIT 10
            """), {"mid": mid, "t_news": t_news, "side": side, "outcome_index": p_resolve})).mappings().all()

            total_vol = sum(float(r["total_notional"]) for r in rows3)
            t_news_str = str(t_news)[:19] if t_news else "N/A"
            print(f"\n--- {LABEL_MAP[mid]} (t_news={t_news_str}, side={side}, total pre-news vol=${total_vol:.0f}) ---")
            for i, r in enumerate(rows3, 1):
                share = 100 * float(r["total_notional"]) / total_vol if total_vol else 0
                mins = None
                if t_news and r["first_trade"]:
                    mins = (t_news - r["first_trade"]).total_seconds() / 60
                mins_str = f"{mins:.0f}min" if mins is not None else "N/A"
                print(f"  #{i}: {r['taker_address'][:14]}... "
                      f"vol=${r['total_notional']:.0f} ({share:.1f}%) "
                      f"trades={r['n_trades']} avg_yes={r['avg_yes_price']:.3f} "
                      f"first_trade={str(r['first_trade'])[:16]} ({mins_str} before) "
                      f"total_mkts={r['total_markets']} "
                      f"poly_since={str(r['first_seen_polymarket_at'])[:10] if r['first_seen_polymarket_at'] else 'unk'}")

        # 4. Bottom-10 wallets (by pre-news notional — smallest traders)
        print("\n\n=== BOTTOM-10 WALLETS (smallest pre-news) ===")
        for mid in EPSTEIN_IDS:
            ld = label_data.get(mid, {})
            t_news = ld.get("t_news")
            p_resolve = int(ld.get("p_resolve", 1))
            side = "BUY" if p_resolve == 1 else "SELL"

            rows4 = (await session.execute(text("""
                SELECT
                    t.taker_address,
                    SUM(t.notional_usdc) as total_notional,
                    COUNT(*) as n_trades,
                    MIN(t.ts) as first_trade,
                    (SELECT COUNT(DISTINCT t2.market_id) FROM trades t2 WHERE t2.taker_address = t.taker_address) as total_markets
                FROM trades t
                WHERE t.market_id = :mid
                  AND t.ts < :t_news
                  AND t.side = :side
                  AND t.outcome_index = :outcome_index
                GROUP BY t.taker_address
                ORDER BY SUM(t.notional_usdc) ASC
                LIMIT 10
            """), {"mid": mid, "t_news": t_news, "side": side, "outcome_index": p_resolve})).mappings().all()

            print(f"\n--- {LABEL_MAP[mid]} bottom-10 ---")
            for i, r in enumerate(rows4, 1):
                mins = None
                if t_news and r["first_trade"]:
                    mins = (t_news - r["first_trade"]).total_seconds() / 60
                mins_str = f"{mins:.0f}min" if mins is not None else "N/A"
                print(f"  #{i}: {r['taker_address'][:14]}... "
                      f"vol=${r['total_notional']:.0f} "
                      f"trades={r['n_trades']} "
                      f"first_trade={str(r['first_trade'])[:16]} ({mins_str} before) "
                      f"total_mkts={r['total_markets']}")

        # 5. Cross-market wallet overlap
        rows5 = (await session.execute(text("""
            SELECT
                t.taker_address,
                COUNT(DISTINCT t.market_id) as n_epstein_markets,
                SUM(t.notional_usdc) as total_vol,
                MIN(t.ts) as earliest_trade,
                w.first_seen_chain_at,
                w.first_seen_polymarket_at,
                (SELECT COUNT(DISTINCT t2.market_id) FROM trades t2 WHERE t2.taker_address = t.taker_address) as total_markets,
                ARRAY_AGG(DISTINCT t.market_id) as market_ids
            FROM trades t
            LEFT JOIN wallets w ON w.address = t.taker_address
            WHERE t.market_id = ANY(:ids)
            GROUP BY t.taker_address, w.first_seen_chain_at, w.first_seen_polymarket_at
            HAVING COUNT(DISTINCT t.market_id) >= 2
            ORDER BY COUNT(DISTINCT t.market_id) DESC, SUM(t.notional_usdc) DESC
        """), {"ids": EPSTEIN_IDS})).mappings().all()

        print("\n\n=== CROSS-MARKET WALLETS (in 2+ Epstein markets) ===")
        for r in rows5:
            market_labels = [LABEL_MAP[m] for m in r["market_ids"] if m in LABEL_MAP]
            print(f"  {r['taker_address'][:16]}... "
                  f"n_epstein={r['n_epstein_markets']} ({'+'.join(market_labels)}) "
                  f"vol=${r['total_vol']:.0f} "
                  f"earliest={str(r['earliest_trade'])[:16]} "
                  f"chain_since={str(r['first_seen_chain_at'])[:10] if r['first_seen_chain_at'] else 'unk'} "
                  f"poly_since={str(r['first_seen_polymarket_at'])[:10] if r['first_seen_polymarket_at'] else 'unk'} "
                  f"total_mkts={r['total_markets']}")


if __name__ == "__main__":
    asyncio.run(main())
