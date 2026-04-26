"""Labels schema: news_timestamps, market_labels, label_audit

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-26

Notes:
- markets.category_fflow already correct (no rename needed — corrected in 0001).
- market_labels denormalizes category_fflow from markets for fast filtering.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "news_timestamps",
        sa.Column("market_id", sa.String(), sa.ForeignKey("markets.id"), primary_key=True),
        sa.Column("t_news", TZ, nullable=False),
        sa.Column("tier", sa.SmallInteger(), nullable=False),          # 1=proposer URL, 2=GDELT, 3=LLM
        sa.Column("source_url", sa.Text()),
        sa.Column("source_publisher", sa.Text()),
        sa.Column("confidence", sa.Numeric(3, 2)),
        sa.Column("query_keywords", postgresql.ARRAY(sa.Text())),
        sa.Column("notes", sa.Text()),
        sa.Column("recovered_at", TZ, nullable=False),
        sa.Column(
            "recovered_by_run_id",
            sa.BigInteger(),
            sa.ForeignKey("data_collection_runs.id"),
        ),
    )
    op.create_index("ix_news_timestamps_tier", "news_timestamps", ["tier"])
    op.create_index("ix_news_timestamps_confidence", "news_timestamps", ["confidence"])

    op.create_table(
        "market_labels",
        sa.Column("market_id", sa.String(), sa.ForeignKey("markets.id"), primary_key=True),
        sa.Column("t_open", TZ, nullable=False),
        sa.Column("t_news", TZ, nullable=False),
        sa.Column("t_resolve", TZ, nullable=False),
        sa.Column("p_open", sa.Numeric(8, 6)),
        sa.Column("p_news", sa.Numeric(8, 6)),
        sa.Column("p_resolve", sa.SmallInteger()),                     # 0 or 1
        sa.Column("delta_pre", sa.Numeric(8, 6)),
        sa.Column("delta_total", sa.Numeric(8, 6)),
        sa.Column("ils", sa.Numeric(10, 6)),                           # NULL when |delta_total| < epsilon
        sa.Column("ils_30min", sa.Numeric(10, 6)),
        sa.Column("ils_2h", sa.Numeric(10, 6)),
        sa.Column("ils_6h", sa.Numeric(10, 6)),
        sa.Column("ils_24h", sa.Numeric(10, 6)),
        sa.Column("ils_7d", sa.Numeric(10, 6)),
        sa.Column("volume_pre_share", sa.Numeric(8, 6)),
        sa.Column("pre_news_max_jump", sa.Numeric(8, 6)),
        sa.Column("wallet_hhi_top10", sa.Numeric(8, 6)),
        sa.Column("time_to_news_top10", postgresql.JSONB()),           # [{wallet,t_trade,gap_seconds,size_shares}]
        sa.Column("n_trades_total", sa.Integer()),
        sa.Column("n_trades_pre_news", sa.Integer()),
        sa.Column("category_fflow", sa.String(100)),                   # denormalized from markets
        sa.Column("computed_at", TZ),
        sa.Column(
            "computed_by_run_id",
            sa.BigInteger(),
            sa.ForeignKey("data_collection_runs.id"),
        ),
        sa.Column(
            "flags",
            postgresql.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    op.create_index("ix_market_labels_category_fflow", "market_labels", ["category_fflow"])
    op.create_index("ix_market_labels_ils", "market_labels", ["ils"])
    op.create_index("ix_market_labels_volume_pre_share", "market_labels", ["volume_pre_share"])
    op.create_index("ix_market_labels_t_news", "market_labels", ["t_news"])

    op.create_table(
        "label_audit",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("details", postgresql.JSONB()),
        sa.Column("created_at", TZ, nullable=False),
    )
    op.create_index("ix_label_audit_market_id", "label_audit", ["market_id"])


def downgrade() -> None:
    op.drop_table("label_audit")
    op.drop_table("market_labels")
    op.drop_table("news_timestamps")
