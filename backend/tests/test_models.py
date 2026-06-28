from datetime import datetime, timezone, timedelta
from decimal import Decimal
from app.db.models import Agent, Position


def test_agent_persists_with_decimal_cash(db_session):
    agent = Agent(
        name="Alpha",
        instructions="compra basso vendi alto",
        duration_start=datetime.now(timezone.utc),
        duration_end=datetime.now(timezone.utc) + timedelta(days=7),
        cash_usd=Decimal("100"),
    )
    db_session.add(agent)
    db_session.commit()
    assert agent.id is not None
    assert agent.cash_usd == Decimal("100")


def test_position_links_to_agent(db_session):
    agent = Agent(
        name="Beta", duration_start=datetime.now(timezone.utc),
        duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"),
    )
    db_session.add(agent)
    db_session.commit()
    pos = Position(agent_id=agent.id, symbol="BTCUSDT",
                   quantity=Decimal("0.001"), avg_price=Decimal("50000"))
    db_session.add(pos)
    db_session.commit()
    assert pos in agent.positions
