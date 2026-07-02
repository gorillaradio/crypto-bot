"""agent risk thresholds and position breach_armed

Revision ID: 139946be1c6f
Revises: f6a7b8c9d0e1
Create Date: 2026-07-01 09:36:56.081359

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '139946be1c6f'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("stop_loss", sa.Numeric(5, 4), nullable=True))
    op.add_column("agents", sa.Column("take_profit", sa.Numeric(5, 4), nullable=True))
    op.add_column("positions", sa.Column("breach_armed", sa.Boolean(),
                                          nullable=False, server_default=sa.true()))
    # preserva il comportamento di rischio degli agenti creati sotto il guardrail hardcoded
    op.execute("UPDATE agents SET stop_loss = 0.10, take_profit = 0.20")


def downgrade() -> None:
    op.drop_column("positions", "breach_armed")
    op.drop_column("agents", "take_profit")
    op.drop_column("agents", "stop_loss")
