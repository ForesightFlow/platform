"""Generate JSONL fixture for the ForesightFlow coordination-experiment.

Phase 0: 50 markets — balanced across 6 categories, post-training-cutoff only.

Filters applied (all non-optional):
  1. Hard cutoff: resolvedAt >= HARD_CUTOFF (2025-09-15). Non-overridable invariant.
  2. Bucket exclusion: markets that belong to exclusive multi-outcome groups.
     Primary: raw_metadata['events'][0]['negRisk'] == true (Polymarket NegRisk flag).
     Secondary: event groups where >=3 siblings resolve and exactly 1 resolves YES
     (detected by grouping on events[0].id). Both forms tracked in eventGroupId /
     isBucketMarket output fields.
  3. Category balance: quota per category sampled independently; sibling substitution
     when a category is undersupplied.
  4. Calibration assertion: Brier(baseline, outcome) warning if > 0.18.

Baseline: last CLOB mid_price strictly >24h before resolvedAt; fallback to trade
VWAP from all trades >24h before resolvedAt. Markets with no baseline are dropped.

Category targets (Phase 0):
  crypto=8, politics=8, sports=8, economics=8, geopolitics=9, entertainment=9

Sibling pairs for substitution when quota cannot be met:
  politics <-> geopolitics
  crypto   <-> economics
  sports   <-> entertainment
"""

import argparse
import asyncio
import json
import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from fflow.db import AsyncSessionLocal

UTC = timezone.utc
HARD_CUTOFF = datetime(2025, 9, 15, tzinfo=UTC)

# ─── Category targets ─────────────────────────────────────────────────────────

PHASE0_TARGETS: dict[str, int] = {
    "crypto":        8,
    "politics":      8,
    "sports":        8,
    "economics":     8,
    "geopolitics":   9,
    "entertainment": 9,
}
PHASE0_TOTAL = sum(PHASE0_TARGETS.values())

SIBLING_PAIRS: list[tuple[str, str]] = [
    ("politics",      "geopolitics"),
    ("crypto",        "economics"),
    ("sports",        "entertainment"),
]

# ─── Category keyword mapping ─────────────────────────────────────────────────
# NOTE: order matters — checked top-to-bottom; SPORTS must precede GEOPOLITICS
# so "counter-strike" doesn't match the "strike" geopolitics keyword.

_RAW_KEYWORDS: list[tuple[str, list[str]]] = [
    ("sports", [
        # Esports (must be first to avoid "strike" geopolitics match)
        "counter-strike", " cs:", "csgo", "cs2", "league of legends", " lol:",
        "valorant", "dota 2", "overwatch", "rainbow six", "esports", "esport",
        "blast open", "blast premier", "pgl ", "iem ", "esl pro league", "faze",
        "natus vincere", "vitality vs", "astralis", "liquid vs", "furia vs",
        # Cricket
        "ipl", " t20 ", "t20 world cup", "big bash", " bbl ", "pakistan super league",
        " psl ", "odi ", "test cricket", "cricket:",
        "indian premier league", "super giants", "kolkata knight",
        "rajasthan royals", "mumbai indians", "royal challengers",
        # Standard sports
        "nba", "nfl", "nhl", "mlb", "pga", "wimbledon", "ufc", "mma",
        "tennis", "soccer", "basketball", "baseball", "formula 1", " f1 ",
        "ncaa", "premier league", "champions league", "la liga", "bundesliga",
        "serie a", "ligue 1", "super bowl", "masters ", "olympics",
        "olympic games", "world series", "stanley cup", "nhl playoffs",
        "rebounds o/u", "assists o/u", "points o/u", "pts o/u",
        "eurobasket", "euro basket",
    ]),
    ("crypto", [
        "bitcoin", " btc ", "ethereum", " eth ", "crypto", "defi", "solana", " sol ",
        "usdt", "usdc", "binance", "coinbase", "nft ", "blockchain",
        "airdrop", " token ", "metamask", " sui ", "aptos", "avalanche",
        "ordinal", "inscription", "rune", "meme coin", "altcoin",
        "microstrategy bitcoin", "mstr bitcoin", "bitcoin purchase",
        "on-chain", "onchain", "layer 2", " l2 ", "staking",
        "polymarket us go live",  # crypto-adjacent
        "lighter market cap", "fdv",  # token launch
    ]),
    ("geopolitics", [
        "war ", "military ", "nato ", "missile", "invasion", "troops",
        "ukraine", "russia", "china ", "taiwan", "iran", "israel", "hamas",
        "hezbollah", "north korea", "sanctions", "ceasefire", "conflict",
        "hostage", "airstrike", "air strike", "blockade", "siege", "capture",
        "nuclear", "npt ", "strike iran", "strikes iran", "iran strike",
        "israel strikes", "israel x ", "us strikes", "us x iran",
        "iranian regime", "khamenei", "netanyahu", "maduro", "venezuela",
        "regime", "coup", "junta", "embassy", "ambassador",
    ]),
    ("economics", [
        "federal reserve", "interest rate", "inflation", "gdp", " cpi",
        "earnings", "quarterly earnings", "beat earnings", "beat revenue",
        "merger", "acquisition", " ipo ", "crude oil", "oil price",
        " s&p ", "nasdaq", "dow jones", "unemployment", "tariff",
        "trade deal", "trade war", "recession", "rate cut", "rate hike",
        "stock price", "shares", " o/u ", "over/under",
        "revenue hit", "market cap",
        "opendoor", "payroll data", "bls stop",
    ]),
    ("entertainment", [
        "oscars", "grammy", "emmy", "bafta", "golden globe", "eurovision",
        "mrbeast", "mr beast", "youtube", "netflix", "spotify",
        "box office", "billboard", "taylor swift", "kanye", "beyoncé",
        "drake", "travis scott", "ariana", "billie eilish",
        "google year in search", "year in search",
        "stranger things", "movie release", "album release", "song release",
        "sam altman", "most searched", "chatgpt #1", "gpt-5",
        "gpt ads", "openai", "anthropic", "llama",
        "robinhood say", "robinhood earnings call",  # earnings call word bingo
        "will kanye", "bully release",
    ]),
    ("politics", [
        "election", "president", "senate", "congress", "house vote",
        "governor", "mayor", "parliament", "prime minister", "chancellor",
        "referendum", "ballot", "campaign", "democrat", "republican",
        "conservative", "labour party", "liberal party",
        "executive order", "government shutdown", "supreme court",
        "secretary of", "department of ", "cabinet member",
        "filibuster", "impeach", "resign",
        "trump", "biden", "harris", "macron", "scholz", "sunak",
        "publicly insult", "trump insult", "eo ", "trump eo",
        "congress vote", "senate vote", "house pass",
        "howard lutnick", "elon musk pay", "gambling loss",
        "cap on gambling",
    ]),
]

# fflow taxonomy fallback
_FFLOW_MAP: dict[str, str] = {
    "military_geopolitics": "geopolitics",
    "regulatory_decision":  "politics",
    "corporate_disclosure": "economics",
}


def _map_category(category_fflow: str | None, category_raw: str | None, question: str) -> str:
    haystack = " " + " ".join(filter(None, [category_raw, question])).lower() + " "
    for label, keywords in _RAW_KEYWORDS:
        if any(kw in haystack for kw in keywords):
            return label
    if category_fflow and category_fflow in _FFLOW_MAP:
        return _FFLOW_MAP[category_fflow]
    return "politics"


# ─── SQL ─────────────────────────────────────────────────────────────────────

_CANDIDATES_SQL = """
WITH bucket_event_ids AS (
  -- Secondary bucket detection: non-negRisk event groups with >=3 siblings, exactly 1 YES
  SELECT (raw_metadata -> 'events' -> 0 ->> 'id') AS event_id
  FROM markets
  WHERE resolved_at >= :resolved_after
    AND resolution_outcome IN (0, 1)
    AND volume_total_usdc >= :min_vol
    AND (raw_metadata -> 'events' -> 0 ->> 'negRisk')::boolean IS DISTINCT FROM true
    AND EXISTS (SELECT 1 FROM trades t WHERE t.market_id = markets.id)
  GROUP BY (raw_metadata -> 'events' -> 0 ->> 'id')
  HAVING COUNT(*) >= 3
     AND SUM(CASE WHEN resolution_outcome = 1 THEN 1 ELSE 0 END) = 1
)
SELECT
  m.id,
  m.question,
  m.category_fflow,
  m.category_raw,
  m.volume_total_usdc,
  m.resolved_at,
  m.resolution_outcome,
  (m.raw_metadata -> 'events' -> 0 ->> 'id') AS event_group_id,
  COALESCE((m.raw_metadata -> 'events' -> 0 ->> 'negRisk')::boolean, false) AS is_neg_risk,
  CASE
    WHEN COALESCE((m.raw_metadata -> 'events' -> 0 ->> 'negRisk')::boolean, false) THEN true
    WHEN (m.raw_metadata -> 'events' -> 0 ->> 'id') IN (SELECT event_id FROM bucket_event_ids) THEN true
    ELSE false
  END AS is_bucket_market
FROM markets m
WHERE m.resolved_at >= :resolved_after
  AND m.resolution_outcome IN (0, 1)
  AND m.volume_total_usdc >= :min_vol
  AND EXISTS (SELECT 1 FROM trades t WHERE t.market_id = m.id)
ORDER BY m.volume_total_usdc DESC
"""

_CLOB_SQL = """
SELECT mid_price FROM prices
WHERE market_id = :mid AND ts < :cutoff
ORDER BY ts DESC LIMIT 1
"""

_VWAP_SQL = """
SELECT SUM(size_shares::numeric * price::numeric) / NULLIF(SUM(size_shares::numeric), 0),
       COUNT(*)
FROM trades
WHERE market_id = :mid AND ts < :cutoff
"""

_ALL_TRADES_SQL = "SELECT COUNT(*) FROM trades WHERE market_id = :mid"


async def _baseline(session, market_id: str, cutoff: datetime) -> tuple[float | None, str, int]:
    r = await session.execute(text(_CLOB_SQL), {"mid": market_id, "cutoff": cutoff})
    row = r.fetchone()
    if row and row[0] is not None:
        return float(row[0]), "clob_mid", -1

    r = await session.execute(text(_VWAP_SQL), {"mid": market_id, "cutoff": cutoff})
    row = r.fetchone()
    if row and row[0] is not None:
        return float(row[0]), "trade_vwap", int(row[1])
    return None, "none", 0


async def _total_trades(session, market_id: str) -> int:
    r = await session.execute(text(_ALL_TRADES_SQL), {"mid": market_id})
    return r.scalar() or 0


# ─── Main ─────────────────────────────────────────────────────────────────────

async def generate(
    resolved_after: datetime,
    min_vol: float,
    output_path: str,
    rng_seed: int,
) -> None:
    rng = random.Random(rng_seed)

    # ── Load all candidates ──────────────────────────────────────────────────
    print("Loading candidates…", file=sys.stderr)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(_CANDIDATES_SQL),
            {"resolved_after": resolved_after, "min_vol": min_vol},
        )
        rows = result.fetchall()
    print(f"  Raw rows: {len(rows)}", file=sys.stderr)

    # ── Categorise + filter ──────────────────────────────────────────────────
    clean: list[dict] = []
    bucket_excluded = 0
    for row in rows:
        (mid, question, cat_fflow, cat_raw, volume,
         resolved_at, outcome, event_group_id, is_neg_risk, is_bucket) = row

        if resolved_at is None:
            continue
        if is_bucket:
            bucket_excluded += 1
            continue

        exp_cat = _map_category(cat_fflow, cat_raw, question)
        clean.append({
            "_id": mid,
            "_question": question,
            "_cat_fflow": cat_fflow,
            "_volume": float(volume),
            "_resolved_at": resolved_at,
            "_outcome": outcome,
            "_event_group_id": event_group_id,
            "_is_bucket": is_bucket,
            "_exp_cat": exp_cat,
        })

    print(
        f"  After bucket exclusion: {len(clean)}  (excluded {bucket_excluded})",
        file=sys.stderr,
    )

    # ── Shuffle then group by category ──────────────────────────────────────
    rng.shuffle(clean)
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for m in clean:
        by_cat[m["_exp_cat"]].append(m)
    for cat, items in by_cat.items():
        print(f"  Pool {cat}: {len(items)}", file=sys.stderr)

    # ── Per-category sampling with baseline check ────────────────────────────
    targets = dict(PHASE0_TARGETS)
    sampled: dict[str, list[dict]] = defaultdict(list)
    substitutions: list[str] = []

    # Sibling map (bidirectional)
    sibling: dict[str, str] = {}
    for a, b in SIBLING_PAIRS:
        sibling[a] = b
        sibling[b] = a

    async with AsyncSessionLocal() as session:
        for cat, quota in targets.items():
            candidates = list(by_cat.get(cat, []))
            filled = await _fill_quota(session, candidates, quota)
            sampled[cat].extend(filled)

            shortfall = quota - len(filled)
            if shortfall > 0:
                sib = sibling.get(cat)
                if sib:
                    sib_pool = [m for m in by_cat.get(sib, [])
                                if m not in sampled[sib]]
                    sib_filled = await _fill_quota(session, sib_pool, shortfall)
                    sampled[cat].extend(sib_filled)
                    if sib_filled:
                        msg = (f"{cat}: {shortfall} slot(s) filled from {sib} "
                               f"(only {len(filled)}/{quota} in primary pool)")
                        substitutions.append(msg)
                        print(f"  SUBSTITUTION: {msg}", file=sys.stderr)

    # ── Flatten + final assertion ────────────────────────────────────────────
    all_records = []
    for cat, items in sampled.items():
        all_records.extend(items)

    # Hard cutoff assertion
    violations = [r for r in all_records if r["_resolved_at"] < HARD_CUTOFF]
    if violations:
        print("ASSERTION FAILED: pre-cutoff records in fixture:", file=sys.stderr)
        for v in violations:
            print(f"  {v['_id']} resolvedAt={v['_resolved_at']}", file=sys.stderr)
        sys.exit(1)

    # Bucket assertion
    bucket_emitted = [r for r in all_records if r["_is_bucket"]]
    if bucket_emitted:
        print("ASSERTION FAILED: bucket markets emitted:", file=sys.stderr)
        for b in bucket_emitted:
            print(f"  {b['_id']} question={b['_question'][:60]}", file=sys.stderr)
        sys.exit(1)

    # ── Calibration check ────────────────────────────────────────────────────
    _print_calibration(all_records)

    # ── Write output ─────────────────────────────────────────────────────────
    import os
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

    with open(output_path, "w") as fh:
        for r in all_records:
            record = {
                "marketId":          r["_id"],
                "question":          r["_question"],
                "category":          r["_exp_cat"],
                "categoryFflow":     r["_cat_fflow"],
                "resolutionOutcome": r["_outcome"],
                "resolvedAt":        r["_resolved_at"].isoformat(),
                "baselineDate":      r["_baseline_date"].isoformat(),
                "baselineMidPrice":  round(r["_baseline_price"], 6),
                "baselineSource":    r["_baseline_source"],
                "volumeUsdc":        r["_volume"],
                "tradeCount":        r["_trade_count"],
                "ilsScore":          None,
                "eventGroupId":      r["_event_group_id"],
                "isBucketMarket":    r["_is_bucket"],
            }
            fh.write(json.dumps(record) + "\n")

    # ── Validation output ────────────────────────────────────────────────────
    _print_validation(all_records, substitutions)


async def _fill_quota(session, candidates: list[dict], quota: int) -> list[dict]:
    """Try candidates in order until we have `quota` with valid baselines."""
    filled = []
    for m in candidates:
        if len(filled) >= quota:
            break
        resolved_at = m["_resolved_at"]
        cutoff = resolved_at - timedelta(hours=24)
        price, source, n_pre = await _baseline(session, m["_id"], cutoff)
        if price is None:
            continue
        total_trades = await _total_trades(session, m["_id"])
        m["_baseline_price"] = price
        m["_baseline_source"] = source
        m["_baseline_date"] = cutoff
        m["_trade_count"] = total_trades
        filled.append(m)
    return filled


def _print_calibration(records: list[dict]) -> None:
    if not records:
        return
    import statistics
    prices = [r["_baseline_price"] for r in records]
    outcomes = [r["_outcome"] for r in records]
    brier = statistics.mean((p - o) ** 2 for p, o in zip(prices, outcomes))

    bins: dict[int, list] = defaultdict(list)
    for p, o in zip(prices, outcomes):
        b = min(int(p * 10), 9)
        bins[b].append((p, o))

    print(f"\nCalibration check: Brier={brier:.4f}", file=sys.stderr)
    for i in range(10):
        if i in bins:
            avg_p = sum(x[0] for x in bins[i]) / len(bins[i])
            yes_r = sum(x[1] for x in bins[i]) / len(bins[i])
            print(
                f"  [{i/10:.1f},{(i+1)/10:.1f}): n={len(bins[i])} avg_p={avg_p:.3f} yes_rate={yes_r:.3f}",
                file=sys.stderr,
            )
    if brier > 0.18:
        print(f"  [WARN] Brier={brier:.4f} exceeds 0.18 threshold!", file=sys.stderr)
    for i, bucket in bins.items():
        if len(bucket) >= 5:
            avg_p = sum(x[0] for x in bucket) / len(bucket)
            yes_r = sum(x[1] for x in bucket) / len(bucket)
            if abs(avg_p - yes_r) > 0.4:
                print(
                    f"  [WARN] Bin [{i/10:.1f},{(i+1)/10:.1f}) miscalibrated: "
                    f"|avg_p({avg_p:.3f}) - yes_rate({yes_r:.3f})| > 0.4",
                    file=sys.stderr,
                )


def _print_validation(records: list[dict], substitutions: list[str]) -> None:
    import statistics
    if not records:
        print("=== Fixture validation ===\nNo records!", flush=True)
        return

    dates = [r["_resolved_at"] for r in records]
    pre_cutoff = sum(1 for d in dates if d < HARD_CUTOFF)
    bucket_emitted = sum(1 for r in records if r["_is_bucket"])

    cat_counts = defaultdict(int)
    for r in records:
        cat_counts[r["_exp_cat"]] += 1

    yes_count = sum(1 for r in records if r["_outcome"] == 1)
    no_count = len(records) - yes_count

    src_counts = defaultdict(int)
    for r in records:
        src_counts[r["_baseline_source"]] += 1

    prices = [r["_baseline_price"] for r in records]
    outcomes = [r["_outcome"] for r in records]
    brier = statistics.mean((p - o) ** 2 for p, o in zip(prices, outcomes))

    bins: dict[int, list] = defaultdict(list)
    for p, o in zip(prices, outcomes):
        b = min(int(p * 10), 9)
        bins[b].append((p, o))

    volumes = [r["_volume"] for r in records]
    ils_count = sum(1 for r in records if r.get("ilsScore") is not None)

    print("=== Fixture validation ===")
    print(f"Total records: {len(records)}")
    print(f"Date range: {min(dates).strftime('%Y-%m-%d')} -> {max(dates).strftime('%Y-%m-%d')}")
    print(f"Pre-cutoff records: {pre_cutoff}  (assertion: must be 0)")
    print(f"Bucket markets emitted: {bucket_emitted}  (assertion: must be 0)")
    print()
    print("Category distribution:")
    for cat, target in PHASE0_TARGETS.items():
        n = cat_counts.get(cat, 0)
        print(f"  {cat}: {n} (target {target})")
    print(f"Substitutions made: {', '.join(substitutions) if substitutions else 'none'}")
    print()
    print("Outcome balance:")
    pct_yes = yes_count * 100 / len(records)
    print(f"  YES (1): {yes_count}  ({pct_yes:.0f}%)")
    print(f"  NO  (0): {no_count}  ({100-pct_yes:.0f}%)")
    if not (30 <= pct_yes <= 70):
        print(f"  [WARN] YES rate {pct_yes:.0f}% outside 30-70% target range")
    print()
    print("Baseline source breakdown:")
    for src in ("clob_mid", "trade_vwap"):
        print(f"  {src}: {src_counts.get(src, 0)}")
    print()
    print("Baseline calibration check:")
    brier_warn = " [WARN: exceeds 0.18]" if brier > 0.18 else ""
    print(f"  Brier(baseline, outcome): {brier:.4f}   [target: 0.10-0.20]{brier_warn}")
    print("  Bin breakdown:")
    for i in range(10):
        lo, hi = i / 10, (i + 1) / 10
        if i in bins:
            b = bins[i]
            avg_p = sum(x[0] for x in b) / len(b)
            yes_r = sum(x[1] for x in b) / len(b)
            flag = ""
            if len(b) >= 5 and abs(avg_p - yes_r) > 0.4:
                flag = "  [WARN: miscalibrated]"
            print(
                f"    [{lo:.1f}, {hi:.1f}): n={len(b):2d}"
                f"  avg_baseline={avg_p:.3f}  yes_rate={yes_r:.3f}{flag}"
            )
        else:
            print(f"    [{lo:.1f}, {hi:.1f}): n= 0")
    print()
    print(f"Volume USDC: "
          f"min={int(min(volumes)):,}, "
          f"median={int(sorted(volumes)[len(volumes)//2]):,}, "
          f"max={int(max(volumes)):,}")
    print(f"Records with ilsScore: {ils_count}")

    if pre_cutoff > 0 or bucket_emitted > 0:
        sys.exit(1)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--resolved-after",
        default="2025-09-15",
        help="ISO date — must be >= 2025-09-15 (experimental cutoff invariant). "
             "Default: 2025-09-15",
    )
    p.add_argument(
        "--min-vol",
        type=float,
        default=50_000,
        help="Minimum volume_total_usdc. Default: 50000",
    )
    p.add_argument(
        "--output",
        default="data/fixture_phase0.jsonl",
        help="Output JSONL path. Default: data/fixture_phase0.jsonl",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for reproducible sampling. Default: 42",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    resolved_after = datetime.fromisoformat(args.resolved_after).replace(tzinfo=UTC)

    # Hard cutoff validation — reject anything earlier than invariant
    if resolved_after < HARD_CUTOFF:
        print(
            f"ERROR: --resolved-after {args.resolved_after} is earlier than the "
            f"experimental invariant cutoff {HARD_CUTOFF.date()}. "
            f"The LLM training cutoff is August 2025; markets resolving before "
            f"2025-09-15 may be in training data. This flag cannot be set earlier.",
            file=sys.stderr,
        )
        sys.exit(1)

    asyncio.run(
        generate(
            resolved_after=resolved_after,
            min_vol=args.min_vol,
            output_path=args.output,
            rng_seed=args.seed,
        )
    )


if __name__ == "__main__":
    main()
