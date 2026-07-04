"""brain due stadi columns

Revision ID: 49407193a9ac
Revises: 940cbbd9c670
Create Date: 2026-07-04 10:08:41.892558

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '49407193a9ac'
down_revision: Union[str, Sequence[str], None] = '940cbbd9c670'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agents",
        sa.Column("brain_version", sa.String(length=10), nullable=False, server_default="v1"))
    op.create_table(
        "market_briefs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cycle_id", sa.String(length=32), nullable=False),
        sa.Column("parsed_brief", sa.String(), nullable=True),
        sa.Column("system_prompt", sa.String(), nullable=False),
        sa.Column("user_prompt", sa.String(), nullable=False),
        sa.Column("raw_response", sa.String(), nullable=True),
        sa.Column("parse_status", sa.String(length=10), nullable=False),
        sa.Column("model_provider", sa.String(length=40), nullable=False),
        sa.Column("model_name", sa.String(length=80), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_market_briefs_cycle_id", "market_briefs", ["cycle_id"])
    op.create_index("ix_market_briefs_created_at", "market_briefs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_market_briefs_created_at", table_name="market_briefs")
    op.drop_index("ix_market_briefs_cycle_id", table_name="market_briefs")
    op.drop_table("market_briefs")
    op.drop_column("agents", "brain_version")
