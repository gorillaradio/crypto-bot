"""add lifecycle ledger identity

Revision ID: 1a2b3c4d5e6f
Revises: b1c2d3e4f5a6
"""
from alembic import op
import sqlalchemy as sa


revision = "1a2b3c4d5e6f"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "position_lifecycles",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("opening_cycle_id", sa.String(length=32), nullable=True),
        sa.Column("last_cycle_id", sa.String(length=32), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("agent_id", "symbol", "opening_cycle_id", "last_cycle_id", "opened_at", "closed_at"):
        op.create_index(f"ix_position_lifecycles_{column}", "position_lifecycles", [column])
    op.add_column("positions", sa.Column("lifecycle_id", sa.String(length=32), nullable=True))
    op.create_foreign_key("fk_positions_lifecycle_id", "positions", "position_lifecycles", ["lifecycle_id"], ["id"])
    op.create_index("ix_positions_lifecycle_id", "positions", ["lifecycle_id"], unique=True)
    op.add_column("trades", sa.Column("lifecycle_id", sa.String(length=32), nullable=True))
    op.add_column("trades", sa.Column("cycle_id", sa.String(length=32), nullable=True))
    op.create_foreign_key("fk_trades_lifecycle_id", "trades", "position_lifecycles", ["lifecycle_id"], ["id"])
    op.create_index("ix_trades_lifecycle_id", "trades", ["lifecycle_id"])
    op.create_index("ix_trades_cycle_id", "trades", ["cycle_id"])
    op.create_table(
        "position_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("lifecycle_id", sa.String(length=32), sa.ForeignKey("position_lifecycles.id"), nullable=False),
        sa.Column("cycle_id", sa.String(length=32), nullable=True),
        sa.Column("action", sa.String(length=8), nullable=False),
        sa.Column("rationale", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("agent_id", "lifecycle_id", "cycle_id", "timestamp"):
        op.create_index(f"ix_position_evaluations_{column}", "position_evaluations", [column])


def downgrade():
    op.drop_table("position_evaluations")
    op.drop_index("ix_trades_cycle_id", table_name="trades")
    op.drop_index("ix_trades_lifecycle_id", table_name="trades")
    op.drop_constraint("fk_trades_lifecycle_id", "trades", type_="foreignkey")
    op.drop_column("trades", "cycle_id")
    op.drop_column("trades", "lifecycle_id")
    op.drop_index("ix_positions_lifecycle_id", table_name="positions")
    op.drop_constraint("fk_positions_lifecycle_id", "positions", type_="foreignkey")
    op.drop_column("positions", "lifecycle_id")
    op.drop_table("position_lifecycles")
