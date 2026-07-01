from datetime import datetime, timezone, timedelta
from decimal import Decimal
from app.db.models import Agent, Position


def test_agent_model_fields_persist(db_session):
    a = Agent(name="L", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"),
              model_name="deepseek/deepseek-v4-flash")
    db_session.add(a); db_session.commit()
    db_session.refresh(a)               # read back from DB, not identity map
    assert a.model_provider == "openrouter"          # OpenRouter gateway default
    assert a.model_name == "deepseek/deepseek-v4-flash"


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


def test_agent_memory_unique_per_section(db_session):
    from app.db.models import AgentMemory
    import pytest
    from sqlalchemy.exc import IntegrityError
    agent = Agent(name="M", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    db_session.add(AgentMemory(agent_id=agent.id, section="coin_theses", content="BTC: bull"))
    db_session.commit()
    # a different section for the same agent is allowed
    db_session.add(AgentMemory(agent_id=agent.id, section="trade_lessons", content="sold too early"))
    db_session.commit()
    # a duplicate (agent, section) violates the unique constraint
    db_session.add(AgentMemory(agent_id=agent.id, section="coin_theses", content="BTC: bear"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def _mk_agent(session, **over):
    kw = dict(name="T", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("100"))
    kw.update(over)
    a = Agent(**kw)
    session.add(a); session.commit()
    return a


def test_agent_accepts_risk_thresholds(db_session):
    a = _mk_agent(db_session, stop_loss=Decimal("0.10"), take_profit=Decimal("0.20"))
    assert a.stop_loss == Decimal("0.10")
    assert a.take_profit == Decimal("0.20")


def test_agent_thresholds_default_none(db_session):
    a = _mk_agent(db_session)
    assert a.stop_loss is None and a.take_profit is None


def test_position_breach_armed_defaults_true(db_session):
    a = _mk_agent(db_session)
    p = Position(agent_id=a.id, symbol="BTCUSDT", quantity=Decimal("1"), avg_price=Decimal("100"))
    db_session.add(p); db_session.commit()
    assert p.breach_armed is True
