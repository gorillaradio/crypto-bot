"""backfill event payloads + position lifecycle from history

Revision ID: c4d5e6f7a8b9
Revises: a1f2e3d4c5b6
Create Date: 2026-07-09
"""
import sqlalchemy as sa
from alembic import op

from app.db.event_backfill import payload_for, fold_rationales, replay_positions

revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "a1f2e3d4c5b6"
branch_labels = None
depends_on = None

events = sa.table("events",
                  sa.column("id", sa.Integer), sa.column("kind", sa.String),
                  sa.column("message", sa.String), sa.column("cycle_id", sa.String),
                  sa.column("payload", sa.JSON))
positions = sa.table("positions",
                     sa.column("id", sa.Integer), sa.column("agent_id", sa.Integer),
                     sa.column("symbol", sa.String),
                     sa.column("opened_at", sa.DateTime(timezone=True)),
                     sa.column("invested_usd", sa.Numeric),
                     sa.column("realized_usd", sa.Numeric))


def upgrade() -> None:
    conn = op.get_bind()

    # 1) payload da message, per tutti gli eventi senza payload
    rows = conn.execute(sa.select(events.c.id, events.c.kind, events.c.message,
                                  events.c.cycle_id)
                        .where(events.c.payload.is_(None))
                        .order_by(events.c.id)).fetchall()
    parsed = [(r.id, r.kind, r.cycle_id, payload_for(r.kind, r.message)) for r in rows]
    for eid, _kind, _cyc, payload in parsed:
        conn.execute(events.update().where(events.c.id == eid).values(payload=payload))

    # 2) rationale dei reasoning dentro il trade che li precede (stesso ciclo)
    for eid, payload in fold_rationales(parsed).items():
        conn.execute(events.update().where(events.c.id == eid).values(payload=payload))

    # 3) vita delle posizioni aperte, rigiocata dallo storico trades
    trades = [t for t in
              conn.execute(sa.select(sa.table("trades",
                  sa.column("id", sa.Integer), sa.column("agent_id", sa.Integer),
                  sa.column("symbol", sa.String), sa.column("side", sa.String),
                  sa.column("quantity", sa.Numeric), sa.column("price", sa.Numeric),
                  sa.column("timestamp", sa.DateTime(timezone=True))))).fetchall()]
    life = replay_positions(trades)
    for row in conn.execute(sa.select(positions.c.id, positions.c.agent_id,
                                      positions.c.symbol)).fetchall():
        info = life.get((row.agent_id, row.symbol))
        if info:
            conn.execute(positions.update().where(positions.c.id == row.id).values(
                opened_at=info["opened_at"], invested_usd=info["invested_usd"],
                realized_usd=info["realized_usd"]))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(events.update().values(payload=None))
    conn.execute(positions.update().values(opened_at=None, invested_usd=0, realized_usd=0))
