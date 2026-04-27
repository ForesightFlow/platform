"""ForesightFlow CLI — entry point: fflow"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated, Optional

import typer

from fflow.config import settings
from fflow.log import configure_logging, get_logger

app = typer.Typer(name="fflow", help="ForesightFlow data collection CLI")
collect_app = typer.Typer(help="Run data collectors")
taxonomy_app = typer.Typer(help="Market taxonomy operations")
db_app = typer.Typer(help="Database management")
news_app = typer.Typer(help="T_news recovery (3-tier hierarchy)")
score_app = typer.Typer(help="ILS scoring and label computation")

app.add_typer(collect_app, name="collect")
app.add_typer(taxonomy_app, name="taxonomy")
app.add_typer(db_app, name="db")
app.add_typer(news_app, name="news")
app.add_typer(score_app, name="score")


@app.callback()
def main_callback() -> None:
    configure_logging(settings.log_level, settings.log_json)


log = get_logger(__name__)


# ---------------------------------------------------------------------------
# collect gamma
# ---------------------------------------------------------------------------

@collect_app.command("gamma")
def collect_gamma(
    since: Annotated[Optional[str], typer.Option(help="ISO date, e.g. 2024-04-01")] = None,
    categories: Annotated[
        Optional[str], typer.Option(help="Comma-separated Polymarket tag names")
    ] = None,
    closed: Annotated[bool, typer.Option("--closed", help="Fetch historical resolved markets")] = False,
    end_date_min: Annotated[Optional[str], typer.Option(help="YYYY-MM-DD min end date (with --closed)")] = None,
    end_date_max: Annotated[Optional[str], typer.Option(help="YYYY-MM-DD max end date (with --closed)")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Fetch market metadata from Polymarket Gamma API.

    Normal mode: fetches active + recently closed markets ordered by createdAt.
    Historical mode (--closed): fetches resolved markets by end_date range.
    """
    from fflow.collectors.gamma import GammaCollector

    since_dt = _parse_date(since)
    cats = [c.strip() for c in categories.split(",")] if categories else []
    result = asyncio.run(GammaCollector().run(
        since=since_dt,
        categories=cats,
        closed=closed,
        end_date_min=end_date_min,
        end_date_max=end_date_max,
        dry_run=dry_run,
    ))
    typer.echo(f"gamma: {result.status}, n={result.n_written}")
    if result.error:
        typer.echo(f"error: {result.error}", err=True)
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# collect clob
# ---------------------------------------------------------------------------

@collect_app.command("clob")
def collect_clob(
    market: Annotated[str, typer.Option(help="Market condition ID (0x...)")],
    start_ts: Annotated[Optional[str], typer.Option(help="ISO datetime")] = None,
    end_ts: Annotated[Optional[str], typer.Option(help="ISO datetime")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Fetch 1-minute price history from CLOB API."""
    from fflow.collectors.clob import ClobCollector

    result = asyncio.run(
        ClobCollector().run(
            market_id=market,
            start_ts=_parse_dt(start_ts),
            end_ts=_parse_dt(end_ts),
            dry_run=dry_run,
        )
    )
    typer.echo(f"clob: {result.status}, n={result.n_written}")
    if result.error:
        typer.echo(f"error: {result.error}", err=True)
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# collect subgraph
# ---------------------------------------------------------------------------

@collect_app.command("subgraph")
def collect_subgraph(
    market: Annotated[Optional[str], typer.Option(help="Market condition ID (0x...)")] = None,
    from_ts: Annotated[Optional[str], typer.Option(help="ISO datetime")] = None,
    all_resolved: Annotated[bool, typer.Option("--all-resolved", help="Run for all resolved markets")] = False,
    min_volume: Annotated[float, typer.Option(help="Min volume_total_usdc filter (batch only)")] = 50000.0,
    max_volume: Annotated[Optional[float], typer.Option(help="Max volume_total_usdc filter (batch only)")] = None,
    limit: Annotated[Optional[int], typer.Option(help="Max markets to process in batch mode")] = None,
    categories: Annotated[Optional[str], typer.Option(help="Comma-separated category_fflow filter (batch only)")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Fetch full trade log from Polymarket subgraph."""
    from fflow.collectors.subgraph import SubgraphCollector

    if not market and not all_resolved:
        typer.echo("Provide --market or --all-resolved", err=True)
        raise typer.Exit(1)

    if all_resolved:
        cats = [c.strip() for c in categories.split(",")] if categories else None
        asyncio.run(_subgraph_batch(min_volume=min_volume, max_volume=max_volume, limit=limit, categories=cats, dry_run=dry_run))
    else:
        result = asyncio.run(
            SubgraphCollector().run(
                market_id=market,
                from_ts=_parse_dt(from_ts),
                dry_run=dry_run,
            )
        )
        typer.echo(f"subgraph: {result.status}, n={result.n_written}")
        if result.error:
            typer.echo(f"error: {result.error}", err=True)
            raise typer.Exit(1)


def _load_resume_set(progress_path: "pathlib.Path") -> "set[str]":
    """Return set of market_ids already successfully processed (status == 'ok')."""
    import json
    done: set[str] = set()
    if not progress_path.exists():
        return done
    with open(progress_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("status") == "ok":
                    done.add(rec["market_id"])
            except (json.JSONDecodeError, KeyError):
                pass
    return done


def _write_progress(
    path: "pathlib.Path",
    market_id: str,
    status: str,
    trades_count: int,
    wallets_count: int,
    duration_ms: int,
) -> None:
    import json
    entry = {
        "market_id": market_id,
        "status": status,
        "trades_count": trades_count,
        "wallets_count": wallets_count,
        "duration_ms": duration_ms,
        "ts": datetime.now(UTC).isoformat(),
    }
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


async def _subgraph_batch(
    min_volume: float,
    dry_run: bool,
    max_volume: float | None = None,
    limit: int | None = None,
    categories: list[str] | None = None,
) -> None:
    import pathlib
    import time
    from fflow.collectors.subgraph import SubgraphCollector
    from fflow.db import AsyncSessionLocal
    from fflow.models import Market, Trade
    from sqlalchemy import select, func

    progress_path = pathlib.Path("logs/batch_progress.jsonl")
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    resume_set = _load_resume_set(progress_path)
    if resume_set:
        log.info("subgraph_batch_resume", already_done=len(resume_set))
        typer.echo(f"resuming: {len(resume_set)} markets already completed in checkpoint")

    async with AsyncSessionLocal() as session:
        stmt = (
            select(Market.id, Market.volume_total_usdc, Market.resolved_at)
            .where(Market.resolved_at.isnot(None))
            .where(Market.volume_total_usdc >= min_volume)
            .order_by(Market.volume_total_usdc.desc())
        )
        if max_volume:
            stmt = stmt.where(Market.volume_total_usdc <= max_volume)
        if categories:
            stmt = stmt.where(Market.category_fflow.in_(categories))
        if limit:
            stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).all()

    total = len(rows)
    log.info("subgraph_batch_start", total=total, min_volume=min_volume, max_volume=max_volume, limit=limit, categories=categories)
    if max_volume:
        typer.echo(f"subgraph batch: {total} markets vol=[${min_volume:,.0f}, ${max_volume:,.0f}]")
    else:
        typer.echo(f"subgraph batch: {total} markets vol>=${min_volume:,.0f}" + (f" (limit={limit})" if limit else "") + (f" categories={categories}" if categories else ""))

    collector = SubgraphCollector()
    stale_cutoff = datetime.now(UTC) - timedelta(days=1)
    ok = fail = skipped = already_done = 0

    for mid, vol, resolved_at in rows:
        # Resume: skip markets already in checkpoint with status=ok
        if mid in resume_set:
            already_done += 1
            continue

        # Idempotency: skip markets resolved >1 day ago that already have trades in DB
        resolved_is_old = resolved_at and resolved_at < stale_cutoff
        if resolved_is_old and not dry_run:
            async with AsyncSessionLocal() as session:
                existing = await session.scalar(
                    select(func.count()).select_from(Trade).where(Trade.market_id == mid)
                )
            if existing and existing > 0:
                already_done += 1
                log.info("subgraph_skip_already_collected", market=mid, existing_trades=existing)
                _write_progress(progress_path, mid, "ok", existing, 0, 0)
                continue

        t0 = time.monotonic()
        try:
            r = await collector.run(market_id=mid, dry_run=dry_run)
            duration_ms = int((time.monotonic() - t0) * 1000)
            if r.n_written and r.n_written > 0:
                ok += 1
                _write_progress(progress_path, mid, "ok", r.n_written, r.n_wallets, duration_ms)
            else:
                skipped += 1
                _write_progress(progress_path, mid, "skipped", 0, 0, duration_ms)
            log.info("subgraph_batch_market", market=mid, vol=float(vol or 0),
                     status=r.status, n=r.n_written, wallets=r.n_wallets, ms=duration_ms)
        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            fail += 1
            log.error("subgraph_batch_error", market=mid, error=str(exc))
            _write_progress(progress_path, mid, "failed", 0, 0, duration_ms)

    typer.echo(f"subgraph batch done: ok={ok} skipped(0 trades)={skipped} already_done={already_done} fail={fail}")


# ---------------------------------------------------------------------------
# collect uma
# ---------------------------------------------------------------------------

@collect_app.command("uma")
def collect_uma(
    market: Annotated[Optional[str], typer.Option(help="Market condition ID")] = None,
    all_resolved: Annotated[bool, typer.Option("--all-resolved")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Fetch UMA resolution data for markets."""
    from fflow.collectors.uma import UmaCollector

    if not market and not all_resolved:
        typer.echo("Provide --market or --all-resolved", err=True)
        raise typer.Exit(1)

    result = asyncio.run(
        UmaCollector().run(market_id=market, all_resolved=all_resolved, dry_run=dry_run)
    )
    typer.echo(f"uma: {result.status}, n={result.n_written}")
    if result.error:
        typer.echo(f"error: {result.error}", err=True)
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# collect polygonscan
# ---------------------------------------------------------------------------

@collect_app.command("polygonscan")
def collect_polygonscan(
    wallet: Annotated[Optional[str], typer.Option(help="Wallet address (0x...)")] = None,
    all_stale: Annotated[bool, typer.Option("--all-stale")] = False,
    max_age_days: Annotated[int, typer.Option(help="Staleness threshold in days")] = 30,
    min_trades: Annotated[int, typer.Option(help="Only refresh wallets with at least N trades")] = 0,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Fetch on-chain wallet data from Polygonscan."""
    from fflow.collectors.polygonscan import PolygonscanCollector

    if not wallet and not all_stale:
        typer.echo("Provide --wallet or --all-stale", err=True)
        raise typer.Exit(1)

    result = asyncio.run(
        PolygonscanCollector().run(
            wallet=wallet,
            all_stale=all_stale,
            max_age_days=max_age_days,
            min_trades=min_trades,
            dry_run=dry_run,
        )
    )
    typer.echo(f"polygonscan: {result.status}, n={result.n_written}")
    if result.error:
        typer.echo(f"error: {result.error}", err=True)
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# taxonomy classify
# ---------------------------------------------------------------------------

@taxonomy_app.command("classify")
def taxonomy_classify(
    batch: Annotated[bool, typer.Option("--batch")] = False,
    limit: Annotated[int, typer.Option(help="Max markets to classify")] = 1000,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Classify markets where category_fflow is NULL."""
    from fflow.taxonomy.classifier import classify_batch

    n = asyncio.run(classify_batch(limit=limit, dry_run=dry_run))
    typer.echo(f"classify: classified {n} markets")


# ---------------------------------------------------------------------------
# db commands
# ---------------------------------------------------------------------------

@db_app.command("init")
def db_init() -> None:
    """Create schema and initialize TimescaleDB."""
    from fflow.db import AsyncSessionLocal, engine, init_timescale_extensions
    from fflow.models import Base

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSessionLocal() as session:
            await init_timescale_extensions(session)

    asyncio.run(_init())
    typer.echo("db init: done")


@db_app.command("migrate")
def db_migrate() -> None:
    """Run Alembic migrations."""
    import subprocess
    subprocess.run(["alembic", "upgrade", "head"], check=True)


# ---------------------------------------------------------------------------
# news commands
# ---------------------------------------------------------------------------

@news_app.command("tier1")
def news_tier1(
    market: Annotated[str, typer.Option(help="Market condition ID (0x...)")],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Tier 1: extract T_news from UMA proposer evidence URL."""
    from fflow.db import AsyncSessionLocal
    from fflow.models import Market, NewsTimestamp
    from fflow.news.proposer_url import fetch_proposer_timestamp
    from sqlalchemy import select

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            mkt = await session.get(Market, market)
            if mkt is None:
                typer.echo(f"Market not found: {market}", err=True)
                raise typer.Exit(1)
            url = mkt.resolution_evidence_url
            if not url:
                typer.echo("No resolution_evidence_url on this market.")
                raise typer.Exit(1)

            result = await fetch_proposer_timestamp(url)
            if result is None:
                typer.echo("No timestamp extracted from proposer URL.")
                raise typer.Exit(1)

            typer.echo(f"t_news={result.t_news.isoformat()} confidence={result.confidence}")
            if dry_run:
                return

            row = NewsTimestamp(
                market_id=market,
                t_news=result.t_news,
                tier=1,
                source_url=result.source_url,
                confidence=result.confidence,
                recovered_at=datetime.now(UTC),
            )
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            stmt = (
                pg_insert(NewsTimestamp)
                .values(
                    market_id=market,
                    t_news=result.t_news,
                    tier=1,
                    source_url=result.source_url,
                    confidence=result.confidence,
                    recovered_at=datetime.now(UTC),
                )
                .on_conflict_do_update(
                    index_elements=["market_id"],
                    set_={"t_news": result.t_news, "tier": 1,
                          "source_url": result.source_url,
                          "confidence": result.confidence},
                )
            )
            await session.execute(stmt)
            await session.commit()
            typer.echo("Saved.")

    asyncio.run(_run())


@news_app.command("tier2")
def news_tier2(
    market: Annotated[str, typer.Option(help="Market condition ID (0x...)")],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Tier 2: search GDELT BigQuery for T_news. Requires GCP credentials."""
    from fflow.db import AsyncSessionLocal
    from fflow.models import Market, NewsTimestamp
    from fflow.news.gdelt import search_gdelt

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            mkt = await session.get(Market, market)
            if mkt is None:
                typer.echo(f"Market not found: {market}", err=True)
                raise typer.Exit(1)

            result = await search_gdelt(
                question=mkt.question,
                t_resolve=mkt.resolved_at or datetime.now(UTC),
                t_open=mkt.created_at_chain,
                dry_run=dry_run,
            )
            if result is None:
                typer.echo("No GDELT result (GCP not configured or no match).")
                raise typer.Exit(1)

            typer.echo(f"t_news={result.t_news.isoformat()} confidence={result.confidence}")
            typer.echo(f"source={result.source_url}")
            if dry_run:
                return

            from sqlalchemy.dialects.postgresql import insert as pg_insert
            stmt = (
                pg_insert(NewsTimestamp)
                .values(
                    market_id=market,
                    t_news=result.t_news,
                    tier=2,
                    source_url=result.source_url,
                    source_publisher=result.source_publisher,
                    confidence=result.confidence,
                    query_keywords=result.query_keywords,
                    recovered_at=datetime.now(UTC),
                )
                .on_conflict_do_update(
                    index_elements=["market_id"],
                    set_={"t_news": result.t_news, "tier": 2,
                          "source_url": result.source_url,
                          "confidence": result.confidence},
                )
            )
            await session.execute(stmt)
            await session.commit()
            typer.echo("Saved.")

    asyncio.run(_run())


@news_app.command("tier3")
def news_tier3(
    market: Annotated[str, typer.Option(help="Market condition ID (0x...)")],
    confirm: Annotated[bool, typer.Option("--confirm", help="Acknowledge LLM API cost")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Tier 3: use Claude LLM to extract T_news. Requires --confirm."""
    from fflow.db import AsyncSessionLocal
    from fflow.models import Market, NewsTimestamp
    from fflow.news.llm_match import llm_extract_date

    if not confirm and not dry_run:
        typer.echo("Pass --confirm to acknowledge LLM API cost (~$0.01-0.05 per call).")
        raise typer.Exit(1)

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            mkt = await session.get(Market, market)
            if mkt is None:
                typer.echo(f"Market not found: {market}", err=True)
                raise typer.Exit(1)

            result = await llm_extract_date(
                question=mkt.question,
                description=mkt.description,
                api_key=settings.anthropic_api_key,
                confirmed=confirm,
            )
            if result is None:
                typer.echo("LLM returned no date.")
                raise typer.Exit(1)

            typer.echo(f"t_news={result.t_news.isoformat()} confidence={result.confidence}")
            typer.echo(f"notes={result.notes}")
            if dry_run:
                return

            from sqlalchemy.dialects.postgresql import insert as pg_insert
            stmt = (
                pg_insert(NewsTimestamp)
                .values(
                    market_id=market,
                    t_news=result.t_news,
                    tier=3,
                    confidence=result.confidence,
                    notes=result.notes,
                    recovered_at=datetime.now(UTC),
                )
                .on_conflict_do_update(
                    index_elements=["market_id"],
                    set_={"t_news": result.t_news, "tier": 3,
                          "confidence": result.confidence},
                )
            )
            await session.execute(stmt)
            await session.commit()
            typer.echo("Saved.")

    asyncio.run(_run())


@news_app.command("suggest-validation-set")
def news_suggest_validation_set(
    limit: Annotated[int, typer.Option(help="Max markets to return")] = 20,
) -> None:
    """Suggest markets for manual T_news validation (high-signal categories)."""
    from fflow.db import AsyncSessionLocal
    from fflow.models import Market
    from sqlalchemy import or_, select

    # Keywords that tend to have clear, verifiable news events
    SIGNAL_KEYWORDS = [
        "iran", "venezuela", "maduro", "taylor swift",
        "openai", "fda approval", "rate cut", "year in search",
        "election", "resign", "arrest", "launch",
    ]

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            conditions = [
                Market.question.ilike(f"%{kw}%") for kw in SIGNAL_KEYWORDS
            ]
            stmt = (
                select(Market.id, Market.question, Market.category_fflow,
                       Market.resolution_outcome)
                .where(Market.resolution_outcome.isnot(None))
                .where(or_(*conditions))
                .limit(limit)
            )
            rows = (await session.execute(stmt)).all()

        if not rows:
            typer.echo("No matching markets found.")
            return

        typer.echo(f"{'ID':<45} {'Outcome':<8} {'Category':<25} Question")
        typer.echo("-" * 120)
        for r in rows:
            q = (r.question or "")[:60]
            cat = (r.category_fflow or "")[:24]
            typer.echo(f"{r.id:<45} {str(r.resolution_outcome):<8} {cat:<25} {q}")

    asyncio.run(_run())


@news_app.command("tier1-batch")
def news_tier1_batch(
    limit: Annotated[int, typer.Option(help="Max markets to process")] = 500,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Batch Tier 1: extract T_news from resolution_evidence_url for all eligible markets."""
    from fflow.db import AsyncSessionLocal
    from fflow.models import Market, NewsTimestamp
    from fflow.news.proposer_url import fetch_proposer_timestamp
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            already_done_sq = select(NewsTimestamp.market_id).where(NewsTimestamp.tier == 1)
            stmt = (
                select(Market.id, Market.resolution_evidence_url)
                .where(Market.resolution_evidence_url.isnot(None))
                .where(Market.id.notin_(already_done_sq))
                .limit(limit)
            )
            rows = (await session.execute(stmt)).all()

        typer.echo(f"tier1-batch: {len(rows)} markets to process")
        ok = skip = fail = 0
        for market_id, url in rows:
            try:
                result = await fetch_proposer_timestamp(url)
            except Exception as exc:
                fail += 1
                log.warning("tier1_batch_error", market=market_id, error=str(exc))
                continue

            if result is None:
                skip += 1
                continue

            if not dry_run:
                async with AsyncSessionLocal() as session:
                    stmt = (
                        pg_insert(NewsTimestamp)
                        .values(
                            market_id=market_id,
                            t_news=result.t_news,
                            tier=1,
                            source_url=result.source_url,
                            confidence=result.confidence,
                            recovered_at=datetime.now(UTC),
                        )
                        .on_conflict_do_update(
                            index_elements=["market_id"],
                            set_={
                                "t_news": result.t_news,
                                "tier": 1,
                                "source_url": result.source_url,
                                "confidence": result.confidence,
                            },
                        )
                    )
                    await session.execute(stmt)
                    await session.commit()
            ok += 1
            if ok % 50 == 0:
                typer.echo(f"  progress: ok={ok} skip={skip} fail={fail}")

        typer.echo(f"tier1-batch done: ok={ok} skip={skip} fail={fail}")

    asyncio.run(_run())


@news_app.command("seed-proxy")
def news_seed_proxy(
    market_ids: Annotated[Optional[str], typer.Option(help="Comma-separated market IDs")] = None,
    category: Annotated[Optional[str], typer.Option(help="Seed all markets in this category_fflow")] = None,
    offset_days: Annotated[int, typer.Option(help="Days before end_date for proxy T_news")] = 1,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Seed synthetic T_news proxy from end_date - offset_days (tier=2, confidence=0.50).

    Used for markets resolved by Polymarket admin (no UMA evidence URL) where
    the outcome was publicly knowable close to end_date.
    """
    from fflow.db import AsyncSessionLocal
    from fflow.models import Market, NewsTimestamp
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    async def _run() -> None:
        if market_ids:
            ids = [m.strip() for m in market_ids.split(",") if m.strip()]
        elif category:
            async with AsyncSessionLocal() as session:
                rows = (
                    await session.execute(
                        select(Market.id).where(Market.category_fflow == category)
                        .where(Market.end_date.isnot(None))
                        .where(Market.resolved_at.isnot(None))
                    )
                ).scalars().all()
            ids = list(rows)
        else:
            typer.echo("Provide --market-ids or --category", err=True)
            raise typer.Exit(1)

        typer.echo(f"seed-proxy: {len(ids)} markets, offset={offset_days}d")
        ok = skip = 0
        async with AsyncSessionLocal() as session:
            for mid in ids:
                mkt = await session.get(Market, mid)
                if mkt is None or mkt.end_date is None:
                    skip += 1
                    continue

                t_news = mkt.end_date - timedelta(days=offset_days)
                notes = f"proxy:end_date-{offset_days}d"

                if not dry_run:
                    stmt = (
                        pg_insert(NewsTimestamp)
                        .values(
                            market_id=mid,
                            t_news=t_news,
                            tier=2,
                            source_url=None,
                            confidence=0.50,
                            notes=notes,
                            recovered_at=datetime.now(UTC),
                        )
                        .on_conflict_do_update(
                            index_elements=["market_id"],
                            set_={
                                "t_news": t_news,
                                "tier": 2,
                                "confidence": 0.50,
                                "notes": notes,
                            },
                        )
                    )
                    await session.execute(stmt)
                else:
                    typer.echo(f"  [dry-run] {mid[:12]}…  t_news={t_news.isoformat()}")
                ok += 1

            if not dry_run:
                await session.commit()

        typer.echo(f"seed-proxy done: ok={ok} skip={skip}")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# score commands
# ---------------------------------------------------------------------------

@score_app.command("market")
def score_market(
    market: Annotated[str, typer.Option(help="Market condition ID (0x...)")],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Compute ILS label for a single market and persist to market_labels."""
    from fflow.db import AsyncSessionLocal
    from fflow.scoring.pipeline import compute_market_label

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            label = await compute_market_label(session, market, dry_run=dry_run)
            if label is None:
                typer.echo("Label not computed (missing data or prerequisites).")
                raise typer.Exit(1)
            typer.echo(f"ILS={label.ils}  flags={label.flags}")
            if dry_run:
                typer.echo("[dry-run] not persisted")

    asyncio.run(_run())


@score_app.command("classify-types")
def score_classify_types(
    min_volume: Annotated[float, typer.Option(help="Min volume_total_usdc")] = 50000.0,
    categories: Annotated[Optional[str], typer.Option(help="Comma-separated category_fflow filter")] = None,
    limit: Annotated[Optional[int], typer.Option(help="Max markets to classify")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Classify resolution_type for all resolved markets with sufficient volume."""
    from sqlalchemy import select, update

    from fflow.db import AsyncSessionLocal
    from fflow.models import Market
    from fflow.scoring.resolution_type import classify_from_text

    cats = [c.strip() for c in categories.split(",")] if categories else None

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            stmt = (
                select(
                    Market.id,
                    Market.question,
                    Market.resolution_outcome,
                )
                .where(Market.resolution_outcome.isnot(None))
                .where(Market.volume_total_usdc >= min_volume)
            )
            if cats:
                stmt = stmt.where(Market.category_fflow.in_(cats))
            if limit:
                stmt = stmt.limit(limit)
            rows = (await session.execute(stmt)).all()

        typer.echo(f"classify-types: {len(rows)} markets to classify")
        counts: dict[str, int] = {}
        ok = 0

        for batch_start in range(0, len(rows), 500):
            batch = rows[batch_start : batch_start + 500]
            async with AsyncSessionLocal() as session:
                for mid, question, outcome in batch:
                    rt = classify_from_text(question=question, resolution_outcome=outcome, last_price=None)
                    counts[rt] = counts.get(rt, 0) + 1
                    if not dry_run:
                        await session.execute(
                            update(Market).where(Market.id == mid).values(resolution_type=rt)
                        )
                        ok += 1
                if not dry_run:
                    await session.commit()

        typer.echo("Distribution: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        if dry_run:
            typer.echo("[dry-run] no writes")
        else:
            typer.echo(f"classify-types done: {ok} updated")

    asyncio.run(_run())


@score_app.command("batch")
def score_batch(
    limit: Annotated[int, typer.Option(help="Max markets to score")] = 500,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Compute ILS labels for all markets that have a NewsTimestamp but no label."""
    from fflow.db import AsyncSessionLocal
    from fflow.models import MarketLabel, NewsTimestamp
    from fflow.scoring.pipeline import compute_market_label
    from sqlalchemy import select

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            # Markets with news but no label yet
            labelled = select(MarketLabel.market_id)
            stmt = (
                select(NewsTimestamp.market_id)
                .where(NewsTimestamp.market_id.notin_(labelled))
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()

        n_ok = n_fail = 0
        for market_id in rows:
            async with AsyncSessionLocal() as session:
                label = await compute_market_label(session, market_id, dry_run=dry_run)
                if label:
                    n_ok += 1
                else:
                    n_fail += 1

        typer.echo(f"batch: ok={n_ok} skipped={n_fail}")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
