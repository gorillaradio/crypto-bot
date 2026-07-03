"""trigger engine columns

Revision ID: 940cbbd9c670
Revises: 6c4cc097ac38
Create Date: 2026-07-03 23:57:14.738658

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '940cbbd9c670'
down_revision: Union[str, Sequence[str], None] = '6c4cc097ac38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("positions",
        sa.Column("move_armed", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("agents",
        sa.Column("last_seen_observation_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "last_seen_observation_id")
    op.drop_column("positions", "move_armed")
