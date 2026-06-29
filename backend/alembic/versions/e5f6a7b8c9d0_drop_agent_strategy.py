"""drop agent strategy column"""
from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("agents", "strategy")


def downgrade():
    op.add_column("agents", sa.Column("strategy", sa.String(length=20),
                                      nullable=False, server_default="llm"))
