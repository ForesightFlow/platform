"""Stub for revisions 0003–0005 applied on task02h-phase3 (markets.resolution_type etc.)

These migrations were applied to the DB on task02h-phase3 but were not merged to the
current branch. This stub anchors the chain so 0006 can apply cleanly.
"""
from typing import Sequence, Union

revision: str = "0005"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass  # already applied on task02h-phase3


def downgrade() -> None:
    pass
