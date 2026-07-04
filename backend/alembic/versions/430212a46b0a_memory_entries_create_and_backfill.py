"""memory_entries create and backfill

Revision ID: 430212a46b0a
Revises: 5adb80d611b1
Create Date: 2026-07-03 11:47:26.190982

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '430212a46b0a'
down_revision: Union[str, Sequence[str], None] = '5adb80d611b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("section", sa.String(length=40), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("cycle_id", sa.String(length=32), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_memory_entries_agent_id", "memory_entries", ["agent_id"])
    op.create_index("ix_memory_entries_cycle_id", "memory_entries", ["cycle_id"])
    op.create_index("ix_memory_entries_created_at", "memory_entries", ["created_at"])

    # Backfill: one entry per non-empty line of each existing agent_memory blob.
    memory = sa.table(
        "agent_memory",
        sa.column("agent_id", sa.Integer),
        sa.column("section", sa.String),
        sa.column("content", sa.String),
        sa.column("updated_at", sa.DateTime),
    )
    entries = sa.table(
        "memory_entries",
        sa.column("agent_id", sa.Integer),
        sa.column("section", sa.String),
        sa.column("content", sa.String),
        sa.column("cycle_id", sa.String),
        sa.column("active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
    )
    conn = op.get_bind()
    for row in conn.execute(sa.select(memory)):
        for line in (row.content or "").split("\n"):
            line = line.strip()
            if not line:
                continue
            conn.execute(entries.insert().values(
                agent_id=row.agent_id, section=row.section, content=line,
                cycle_id=None, active=True, created_at=row.updated_at))


def downgrade() -> None:
    op.drop_index("ix_memory_entries_created_at", table_name="memory_entries")
    op.drop_index("ix_memory_entries_cycle_id", table_name="memory_entries")
    op.drop_index("ix_memory_entries_agent_id", table_name="memory_entries")
    op.drop_table("memory_entries")
