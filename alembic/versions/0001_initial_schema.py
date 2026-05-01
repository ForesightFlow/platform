"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

TZ = sa.DateTime(timezone=True)

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")

    op.create_table(
        "markets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("category_raw", sa.String(500)),
        sa.Column("category_fflow", sa.String(100)),
        sa.Column("created_at_chain", sa.DateTime(timezone=True)),
        sa.Column("end_date", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_outcome", sa.Integer()),
        sa.Column("resolution_evidence_url", sa.Text()),
        sa.Column("resolution_proposer", sa.String(42)),
        sa.Column("volume_total_usdc", sa.Numeric(20, 6)),
        sa.Column("liquidity_usdc", sa.Numeric(20, 6)),
        sa.Column("slug", sa.String(500), unique=True),
        sa.Column("raw_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_markets_category_fflow", "markets", ["category_fflow"])
    op.create_index("ix_markets_resolved_at", "markets", ["resolved_at"])
    op.create_index("ix_markets_created_at_chain", "markets", ["created_at_chain"])

    op.create_table(
        "wallets",
        sa.Column("address", sa.String(42), primary_key=True),
        sa.Column("first_seen_chain_at", sa.DateTime(timezone=True)),
        sa.Column("first_seen_polymarket_at", sa.DateTime(timezone=True)),
        sa.Column("funding_sources", postgresql.JSONB()),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "prices",
        sa.Column("market_id", sa.String(), sa.ForeignKey("markets.id"), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("mid_price", sa.Numeric(8, 6), nullable=False),
        sa.Column("bid", sa.Numeric(8, 6)),
        sa.Column("ask", sa.Numeric(8, 6)),
        sa.Column("volume_minute", sa.Numeric(20, 6)),
    )
    op.create_index("ix_prices_market_ts", "prices", ["market_id", "ts"])
    op.execute(
        "SELECT create_hypertable('prices', 'ts', "
        "chunk_time_interval => INTERVAL '7 days', "
        "if_not_exists => TRUE)"
    )

    op.create_table(
        "trades",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.String(), sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("tx_hash", sa.String(66), nullable=False),
        sa.Column("log_index", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("taker_address", sa.String(42), nullable=False),
        sa.Column("maker_address", sa.String(42)),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("outcome_index", sa.SmallInteger(), nullable=False),
        sa.Column("size_shares", sa.Numeric(20, 6), nullable=False),
        sa.Column("price", sa.Numeric(8, 6), nullable=False),
        sa.Column("notional_usdc", sa.Numeric(20, 6), nullable=False),
        sa.Column("raw_event", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("tx_hash", "log_index", name="uq_trades_tx_log"),
    )
    op.create_index("ix_trades_market_ts", "trades", ["market_id", "ts"])
    op.create_index("ix_trades_taker", "trades", ["taker_address"])
    op.create_index("ix_trades_maker", "trades", ["maker_address"])

    op.create_table(
        "data_collection_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("collector", sa.String(50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("target", sa.Text()),
        sa.Column("n_records_written", sa.Integer()),
        sa.Column("error_message", sa.Text()),
        sa.Column("run_metadata", postgresql.JSONB()),
    )


def downgrade() -> None:
    op.drop_table("data_collection_runs")
    op.drop_table("trades")
    op.drop_table("prices")
    op.drop_table("wallets")
    op.drop_table("markets")
