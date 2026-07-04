"""drop agents.brain_version

Revision ID: c89a7674625e
Revises: 49407193a9ac
Create Date: 2026-07-04 15:19:04.731051

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c89a7674625e'
down_revision: Union[str, Sequence[str], None] = '49407193a9ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("agents", "brain_version")


def downgrade() -> None:
    op.add_column("agents",
        sa.Column("brain_version", sa.String(length=10), nullable=False, server_default="v2"))
