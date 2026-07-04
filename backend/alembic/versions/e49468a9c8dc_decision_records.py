"""decision records

Revision ID: e49468a9c8dc
Revises: 139946be1c6f
Create Date: 2026-07-02 20:17:18.545158

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e49468a9c8dc'
down_revision: Union[str, Sequence[str], None] = '139946be1c6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "decision_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("cycle_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("system_prompt", sa.String(), nullable=False),
        sa.Column("user_prompt", sa.String(), nullable=False),
        sa.Column("raw_response", sa.String(), nullable=True),
        sa.Column("parsed_output", sa.String(), nullable=True),
        sa.Column("parse_status", sa.String(length=10), nullable=False),
        sa.Column("model_provider", sa.String(length=40), nullable=False),
        sa.Column("model_name", sa.String(length=80), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_decision_records_agent_id", "decision_records", ["agent_id"])
    op.create_index("ix_decision_records_cycle_id", "decision_records", ["cycle_id"])
    op.create_index("ix_decision_records_created_at", "decision_records", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_decision_records_created_at", table_name="decision_records")
    op.drop_index("ix_decision_records_cycle_id", table_name="decision_records")
    op.drop_index("ix_decision_records_agent_id", table_name="decision_records")
    op.drop_table("decision_records")
