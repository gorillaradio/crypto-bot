"""observations

Revision ID: 6c4cc097ac38
Revises: 945d65d0ab6f
Create Date: 2026-07-03 17:59:12.790774

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6c4cc097ac38'
down_revision: Union[str, Sequence[str], None] = '945d65d0ab6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("symbols_json", sa.String(), nullable=False),
        sa.Column("dedup_hash", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_observations_dedup_hash", "observations", ["dedup_hash"], unique=True)
    op.create_index("ix_observations_published_at", "observations", ["published_at"])
    op.create_index("ix_observations_created_at", "observations", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_observations_created_at", table_name="observations")
    op.drop_index("ix_observations_published_at", table_name="observations")
    op.drop_index("ix_observations_dedup_hash", table_name="observations")
    op.drop_table("observations")
