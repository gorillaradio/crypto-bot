"""agents.initial_capital_usd

Revision ID: b1c2d3e4f5a6
Revises: c4d5e6f7a8b9
Create Date: 2026-07-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("initial_capital_usd", sa.Numeric(20, 8), nullable=True))
    # benchmark_basis.initial_capital è il capitale vero con cui l'agente è partito,
    # congelato al primo heartbeat. Per gli agenti che non ci sono mai arrivati,
    # 100 è l'unico valore che settings.initial_capital_usd abbia mai avuto.
    op.execute("""
        UPDATE agents a
           SET initial_capital_usd = COALESCE(
               (SELECT b.initial_capital FROM benchmark_basis b WHERE b.agent_id = a.id),
               100)
         WHERE a.initial_capital_usd IS NULL
    """)
    op.alter_column("agents", "initial_capital_usd", nullable=False)


def downgrade() -> None:
    op.drop_column("agents", "initial_capital_usd")
