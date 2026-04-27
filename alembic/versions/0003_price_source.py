"""Add price_source column to market_labels

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "market_labels",
        sa.Column("price_source", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("market_labels", "price_source")
