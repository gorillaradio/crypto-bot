"""event payload + position lifecycle columns

Revision ID: a1f2e3d4c5b6
Revises: 7b8c9d0e1f2a
Create Date: 2026-07-09
"""
import sqlalchemy as sa
from alembic import op

revision: str = "a1f2e3d4c5b6"
down_revision: str | None = "7b8c9d0e1f2a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("payload", sa.JSON(), nullable=True))
    op.add_column("positions", sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("positions", sa.Column("invested_usd", sa.Numeric(20, 8),
                                         nullable=False, server_default="0"))
    op.add_column("positions", sa.Column("realized_usd", sa.Numeric(20, 8),
                                         nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("positions", "realized_usd")
    op.drop_column("positions", "invested_usd")
    op.drop_column("positions", "opened_at")
    op.drop_column("events", "payload")
