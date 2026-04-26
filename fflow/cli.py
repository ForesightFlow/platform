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

app.add_typer(collect_app, name="collect")
app.add_typer(taxonomy_app, name="taxonomy")
app.add_typer(db_app, name="db")


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
