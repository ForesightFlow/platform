from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TZ = lambda: DateTime(timezone=True)  # noqa: E731 — each column needs its own instance


class Base(DeclarativeBase):
    pass


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # condition ID (0x...)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category_raw: Mapped[str | None] = mapped_column(String(500))
    category_fflow: Mapped[str | None] = mapped_column(String(100))
    created_at_chain: Mapped[datetime | None] = mapped_column(TZ())  # T_open
    end_date: Mapped[datetime | None] = mapped_column(TZ())
    resolved_at: Mapped[datetime | None] = mapped_column(TZ())  # T_resolve
    resolution_outcome: Mapped[int | None] = mapped_column(Integer)  # 0=NO, 1=YES
    resolution_evidence_url: Mapped[str | None] = mapped_column(Text)
    resolution_proposer: Mapped[str | None] = mapped_column(String(42))
    volume_total_usdc: Mapped[Any] = mapped_column(Numeric(20, 6), nullable=True)
    liquidity_usdc: Mapped[Any] = mapped_column(Numeric(20, 6), nullable=True)
    slug: Mapped[str | None] = mapped_column(String(500), unique=True)
    raw_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_refreshed_at: Mapped[datetime] = mapped_column(TZ(), nullable=False)

    __table_args__ = (
        Index("ix_markets_category_fflow", "category_fflow"),
        Index("ix_markets_resolved_at", "resolved_at"),
        Index("ix_markets_created_at_chain", "created_at_chain"),
    )


class Price(Base):
    __tablename__ = "prices"

    market_id: Mapped[str] = mapped_column(
        String, ForeignKey("markets.id"), primary_key=True
    )
    ts: Mapped[datetime] = mapped_column(TZ(), primary_key=True)  # minute-aligned UTC
    mid_price: Mapped[Any] = mapped_column(Numeric(8, 6), nullable=False)
    bid: Mapped[Any] = mapped_column(Numeric(8, 6), nullable=True)
    ask: Mapped[Any] = mapped_column(Numeric(8, 6), nullable=True)
    volume_minute: Mapped[Any] = mapped_column(Numeric(20, 6), nullable=True)

    __table_args__ = (Index("ix_prices_market_ts", "market_id", "ts"),)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String, ForeignKey("markets.id"), nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    log_index: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[datetime] = mapped_column(TZ(), nullable=False)
    taker_address: Mapped[str] = mapped_column(String(42), nullable=False)
    maker_address: Mapped[str | None] = mapped_column(String(42))
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # BUY or SELL
    outcome_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0=NO, 1=YES
    size_shares: Mapped[Any] = mapped_column(Numeric(20, 6), nullable=False)
    price: Mapped[Any] = mapped_column(Numeric(8, 6), nullable=False)
    notional_usdc: Mapped[Any] = mapped_column(Numeric(20, 6), nullable=False)
    raw_event: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("tx_hash", "log_index", name="uq_trades_tx_log"),
        Index("ix_trades_market_ts", "market_id", "ts"),
        Index("ix_trades_taker", "taker_address"),
        Index("ix_trades_maker", "maker_address"),
    )


class Wallet(Base):
    __tablename__ = "wallets"

    address: Mapped[str] = mapped_column(String(42), primary_key=True)  # lowercase hex
    first_seen_chain_at: Mapped[datetime | None] = mapped_column(TZ())
    first_seen_polymarket_at: Mapped[datetime | None] = mapped_column(TZ())
    funding_sources: Mapped[list | None] = mapped_column(JSONB)
    last_refreshed_at: Mapped[datetime] = mapped_column(TZ(), nullable=False)


class DataCollectionRun(Base):
    __tablename__ = "data_collection_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    collector: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[datetime] = mapped_column(TZ(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(TZ())
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # running|success|failed
    target: Mapped[str | None] = mapped_column(Text)
    n_records_written: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    run_metadata: Mapped[dict | None] = mapped_column(JSONB)
