"""drop agent_memory

Revision ID: 945d65d0ab6f
Revises: 430212a46b0a
Create Date: 2026-07-03 12:17:55.493184

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '945d65d0ab6f'
down_revision: Union[str, Sequence[str], None] = '430212a46b0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("agent_memory")


def downgrade() -> None:
    op.create_table(
        "agent_memory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("section", sa.String(length=40), nullable=False),
        sa.Column("content", sa.String(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "section", name="uq_agent_memory_section"),
    )
    entries = sa.table(
        "memory_entries",
        sa.column("agent_id", sa.Integer),
        sa.column("section", sa.String),
        sa.column("content", sa.String),
        sa.column("active", sa.Boolean),
        sa.column("id", sa.Integer),
    )
    memory = sa.table(
        "agent_memory",
        sa.column("agent_id", sa.Integer),
        sa.column("section", sa.String),
        sa.column("content", sa.String),
    )
    conn = op.get_bind()
    grouped: dict = {}
    for row in conn.execute(sa.select(entries).where(entries.c.active == True).order_by(entries.c.id)):  # noqa: E712
        grouped.setdefault((row.agent_id, row.section), []).append(row.content)
    for (agent_id, section), lines in grouped.items():
        conn.execute(memory.insert().values(agent_id=agent_id, section=section, content="\n".join(lines)))
