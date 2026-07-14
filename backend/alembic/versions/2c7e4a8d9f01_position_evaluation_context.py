"""add position evaluation context

Revision ID: 2c7e4a8d9f01
Revises: 1a2b3c4d5e6f
"""
from alembic import op
import sqlalchemy as sa

revision = "2c7e4a8d9f01"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("position_evaluations", sa.Column("policy_refs", sa.JSON(), nullable=True))
    op.add_column("position_evaluations", sa.Column("policy_alignment", sa.String(length=16), nullable=True))
    op.add_column("position_evaluations", sa.Column("override_reason", sa.String(), nullable=True))


def downgrade():
    op.drop_column("position_evaluations", "override_reason")
    op.drop_column("position_evaluations", "policy_alignment")
    op.drop_column("position_evaluations", "policy_refs")
