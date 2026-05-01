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
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Fetch market metadata from Polymarket Gamma API."""
    from fflow.collectors.gamma import GammaCollector

    since_dt = _parse_date(since)
    cats = [c.strip() for c in categories.split(",")] if categories else []
    result = asyncio.run(GammaCollector().run(since=since_dt, categories=cats, dry_run=dry_run))
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
    market: Annotated[str, typer.Option(help="Market condition ID (0x...)")],
    from_ts: Annotated[Optional[str], typer.Option(help="ISO datetime")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Fetch full trade log from Polymarket subgraph."""
    from fflow.collectors.subgraph import SubgraphCollector

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


@taxonomy_app.command("classify-type")
def taxonomy_classify_type(
    limit: Annotated[int, typer.Option(help="Max markets to classify per run")] = 10_000,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    force: Annotated[bool, typer.Option("--force", help="Re-classify already-classified markets (fixes stale classifications)")] = False,
) -> None:
    """Populate resolution_type (deadline_resolved / unclassifiable) for markets where NULL.

    Logs WARNING for any market where the deadline pattern matched only in the
    description field — these are candidates for manual review.
    Use --force to re-run on already-classified markets (fixes stale values from old classifier).
    """
    from fflow.taxonomy.classifier import classify_type_batch

    counts = asyncio.run(classify_type_batch(limit=limit, dry_run=dry_run, force=force))
    if not counts:
        typer.echo("classify-type: nothing to classify")
        return
    total = sum(counts.values())
    parts = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    typer.echo(f"classify-type: {total} markets classified ({parts})")


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
    """Tier 3: use Claude LLM + web search to extract T_news or T_event.

    Dispatches by resolution_type (paper §7.2):
      deadline_resolved YES → T_event recovery ("when did the event happen?")
      deadline_resolved NO  → skipped (no event occurred; T_resolve is authoritative)
      event_resolved / unclassifiable → T_news recovery ("when did news first break?")

    Requires --confirm to acknowledge LLM API cost (~$0.05-0.20 per call with web search).
    """
    from fflow.db import AsyncSessionLocal
    from fflow.models import Market, NewsTimestamp
    from fflow.news.llm_match import llm_extract_date

    if not confirm and not dry_run:
        typer.echo("Pass --confirm to acknowledge LLM API cost (~$0.05-0.20 with web search).")
        raise typer.Exit(1)

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            mkt = await session.get(Market, market)
            if mkt is None:
                typer.echo(f"Market not found: {market}", err=True)
                raise typer.Exit(1)

            # Route by resolution_type + outcome (paper §7.2)
            is_deadline = mkt.resolution_type == "deadline_resolved"
            is_yes = mkt.resolution_outcome == 1

            if is_deadline and not is_yes:
                typer.echo(
                    "deadline_resolved NO market — T_resolve is authoritative; "
                    "no T_event recovery needed. Skipping."
                )
                return

            recovery_mode = "t_event" if is_deadline else "t_news"
            typer.echo(
                f"resolution_type={mkt.resolution_type} outcome={mkt.resolution_outcome} "
                f"→ recovery_mode={recovery_mode}"
            )

            result = await llm_extract_date(
                question=mkt.question,
                description=mkt.description,
                api_key=settings.anthropic_api_key,
                confirmed=confirm,
                recovery_mode=recovery_mode,
            )
            if result is None:
                typer.echo("LLM returned no date.")
                raise typer.Exit(1)

            label = "t_event" if recovery_mode == "t_event" else "t_news"
            typer.echo(f"{label}={result.t_news.isoformat()} confidence={result.confidence}")
            typer.echo(f"sources={', '.join(result.sources) or 'none'}")
            typer.echo(f"notes={result.notes}")
            if dry_run:
                return

            from sqlalchemy.dialects.postgresql import insert as pg_insert
            notes_full = (
                f"[{recovery_mode}] sources={', '.join(result.sources) or 'none'}. {result.notes}"
            )
            stmt = (
                pg_insert(NewsTimestamp)
                .values(
                    market_id=market,
                    t_news=result.t_news,
                    tier=3,
                    confidence=result.confidence,
                    notes=notes_full,
                    recovered_at=datetime.now(UTC),
                )
                .on_conflict_do_update(
                    index_elements=["market_id"],
                    set_={"t_news": result.t_news, "tier": 3,
                          "confidence": result.confidence, "notes": notes_full},
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


@score_app.command("batch")
def score_batch(
    limit: Annotated[int, typer.Option(help="Max markets to score")] = 500,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Compute ILS labels for unlabeled markets.

    Includes two candidate pools:
      1. deadline_resolved markets with price data (no T_news required)
      2. Markets with a NewsTimestamp (standard path)
    """
    from fflow.db import AsyncSessionLocal
    from fflow.models import Market, MarketLabel, NewsTimestamp, Price
    from fflow.scoring.pipeline import compute_market_label
    from sqlalchemy import select, union

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            labelled = select(MarketLabel.market_id)

            # Pool 1: deadline_resolved with prices, not yet labelled
            deadline_q = (
                select(Market.id)
                .where(Market.resolution_type == "deadline_resolved")
                .where(Market.resolved_at.isnot(None))
                .where(Market.resolution_outcome.isnot(None))
                .where(
                    Market.id.in_(
                        select(Price.market_id).distinct()
                    )
                )
                .where(Market.id.notin_(labelled))
                .limit(limit)
            )

            # Pool 2: markets with NewsTimestamp, not yet labelled
            news_q = (
                select(NewsTimestamp.market_id)
                .where(NewsTimestamp.market_id.notin_(labelled))
                .limit(limit)
            )

            deadline_ids = (await session.execute(deadline_q)).scalars().all()
            news_ids = (await session.execute(news_q)).scalars().all()

        # Deduplicate across pools
        all_ids = list(dict.fromkeys(list(deadline_ids) + list(news_ids)))[:limit]

        n_ok = n_fail = 0
        for market_id in all_ids:
            async with AsyncSessionLocal() as session:
                label = await compute_market_label(session, market_id, dry_run=dry_run)
                if label:
                    n_ok += 1
                else:
                    n_fail += 1

        typer.echo(f"batch: ok={n_ok} skipped={n_fail} (deadline_candidates={len(deadline_ids)}, news_candidates={len(news_ids)})")

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
