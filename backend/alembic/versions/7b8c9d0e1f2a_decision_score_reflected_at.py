"""decision score reflected_at

Revision ID: 7b8c9d0e1f2a
Revises: c89a7674625e
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7b8c9d0e1f2a"
down_revision: Union[str, Sequence[str], None] = "c89a7674625e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("decision_scores",
                  sa.Column("reflected_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("decision_scores", "reflected_at")
