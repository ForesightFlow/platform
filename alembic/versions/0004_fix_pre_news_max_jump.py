"""Fix pre_news_max_jump precision — USDC amount, not price

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "market_labels",
        "pre_news_max_jump",
        type_=sa.Numeric(20, 6),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "market_labels",
        "pre_news_max_jump",
        type_=sa.Numeric(8, 6),
        existing_nullable=True,
    )
