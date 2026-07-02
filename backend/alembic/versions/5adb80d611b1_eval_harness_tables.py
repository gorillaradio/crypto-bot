"""eval harness tables

Revision ID: 5adb80d611b1
Revises: e49468a9c8dc
Create Date: 2026-07-03 00:27:07.241636

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5adb80d611b1'
down_revision: Union[str, Sequence[str], None] = 'e49468a9c8dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "benchmark_basis",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("universe_json", sa.String(), nullable=False),
        sa.Column("start_prices_json", sa.String(), nullable=False),
        sa.Column("initial_capital", sa.Numeric(20, 8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_benchmark_basis_agent_id", "benchmark_basis", ["agent_id"], unique=True)

    op.create_table(
        "benchmark_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("equity_usd", sa.Numeric(20, 8), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_benchmark_snapshots_agent_id", "benchmark_snapshots", ["agent_id"])
    op.create_index("ix_benchmark_snapshots_timestamp", "benchmark_snapshots", ["timestamp"])

    op.create_table(
        "decision_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_record_id", sa.Integer(), sa.ForeignKey("decision_records.id"), nullable=False),
        sa.Column("window", sa.String(length=8), nullable=False),
        sa.Column("n_actions", sa.Integer(), nullable=False),
        sa.Column("n_hits", sa.Integer(), nullable=False),
        sa.Column("avg_return_pct", sa.Numeric(12, 4), nullable=True),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("decision_record_id", "window", name="uq_decision_score_window"),
    )
    op.create_index("ix_decision_scores_decision_record_id", "decision_scores", ["decision_record_id"])


def downgrade() -> None:
    op.drop_index("ix_decision_scores_decision_record_id", table_name="decision_scores")
    op.drop_table("decision_scores")
    op.drop_index("ix_benchmark_snapshots_timestamp", table_name="benchmark_snapshots")
    op.drop_index("ix_benchmark_snapshots_agent_id", table_name="benchmark_snapshots")
    op.drop_table("benchmark_snapshots")
    op.drop_index("ix_benchmark_basis_agent_id", table_name="benchmark_basis")
    op.drop_table("benchmark_basis")
