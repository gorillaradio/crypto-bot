"""share links table"""
from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "share_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_share_links_token", "share_links", ["token"], unique=True)


def downgrade():
    op.drop_index("ix_share_links_token", table_name="share_links")
    op.drop_table("share_links")
