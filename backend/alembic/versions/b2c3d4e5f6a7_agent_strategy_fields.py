"""agent strategy fields"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "4fe169988067"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agents", sa.Column("strategy", sa.String(length=20), nullable=False, server_default="llm"))
    op.add_column("agents", sa.Column("model_provider", sa.String(length=40), nullable=True))
    op.add_column("agents", sa.Column("model_name", sa.String(length=80), nullable=True))


def downgrade():
    op.drop_column("agents", "model_name")
    op.drop_column("agents", "model_provider")
    op.drop_column("agents", "strategy")
