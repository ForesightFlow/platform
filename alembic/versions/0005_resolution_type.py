"""Add resolution_type column to markets

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "markets",
        sa.Column("resolution_type", sa.String(50), nullable=True),
    )
    op.create_index("ix_markets_resolution_type", "markets", ["resolution_type"])


def downgrade() -> None:
    op.drop_index("ix_markets_resolution_type", table_name="markets")
    op.drop_column("markets", "resolution_type")
