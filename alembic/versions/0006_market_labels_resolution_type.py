"""Add resolution_type to market_labels (denormalized from markets)

markets.resolution_type was added in migration 0005 (applied on task02h-phase3).
This migration adds the matching denormalized column to market_labels.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "market_labels",
        sa.Column("resolution_type", sa.String(30), nullable=True),
    )
    op.create_index(
        "ix_market_labels_resolution_type", "market_labels", ["resolution_type"]
    )


def downgrade() -> None:
    op.drop_index("ix_market_labels_resolution_type", table_name="market_labels")
    op.drop_column("market_labels", "resolution_type")
