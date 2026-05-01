from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fflow.config import settings
from fflow.log import get_logger

log = get_logger(__name__)

engine = create_async_engine(settings.db_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_timescale_extensions(session: AsyncSession) -> None:
    from sqlalchemy import text

    await session.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))
    await session.commit()
    log.info("timescaledb_extension_created")

    # Create hypertable for prices (idempotent via migrate_data=false)
    await session.execute(
        text(
            "SELECT create_hypertable('prices', 'ts', "
            "chunk_time_interval => INTERVAL '7 days', "
            "if_not_exists => TRUE)"
        )
    )
    await session.commit()
    log.info("prices_hypertable_ready")
