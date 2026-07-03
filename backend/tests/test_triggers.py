from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.core.config import settings
from app.db.models import Agent, Position


def _agent(session):
    a = Agent(name="T", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("100"))
    session.add(a); session.commit()
    return a


def test_settings_have_trigger_knobs():
    assert settings.wake_budget_per_hour == 2
    assert settings.movement_threshold == Decimal("0.05")
    assert settings.movement_window_hours == 1


def test_new_columns_defaults(db_session):
    agent = _agent(db_session)
    assert agent.last_seen_observation_id is None
    pos = Position(agent_id=agent.id, symbol="BTCUSDT",
                   quantity=Decimal("1"), avg_price=Decimal("100"))
    db_session.add(pos); db_session.commit()
    assert pos.move_armed is True
