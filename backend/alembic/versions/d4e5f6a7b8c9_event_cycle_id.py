"""event cycle_id"""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("cycle_id", sa.String(length=32), nullable=True))
    op.create_index("ix_events_cycle_id", "events", ["cycle_id"])


def downgrade():
    op.drop_index("ix_events_cycle_id", table_name="events")
    op.drop_column("events", "cycle_id")
