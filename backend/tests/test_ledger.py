from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.db.models import Agent, Position, Trade
from app.trading.engine import execute_buy, execute_sell
from app.trading.ledger import rebuild_agent_state, verify_agent_state


def _agent(session, cash="200"):
    agent = Agent(
        name="Ledger", duration_start=datetime.now(timezone.utc),
        duration_end=datetime.now(timezone.utc), cash_usd=Decimal(cash),
        initial_capital_usd=Decimal(cash),
    )
    session.add(agent)
    session.commit()
    return agent


def test_rebuild_matches_cash_and_open_projection_after_partial_sell(db_session):
    agent = _agent(db_session)
    execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"), cycle_id="c1")
    execute_sell(db_session, agent, "BTCUSDT", Decimal("0.4"), Decimal("120"), cycle_id="c2")

    rebuilt = rebuild_agent_state(db_session, agent.id)
    position = db_session.query(Position).one()

    assert rebuilt.cash_usd == Decimal("147.852")
    assert rebuilt.positions[position.lifecycle_id].quantity == Decimal("0.6")
    assert rebuilt.positions[position.lifecycle_id].avg_price == Decimal("100")
    assert rebuilt.positions[position.lifecycle_id].realized_usd == Decimal("8")
    assert verify_agent_state(db_session, agent.id) == []


def test_verify_reports_projection_divergence(db_session):
    agent = _agent(db_session)
    execute_buy(db_session, agent, "ETHUSDT", Decimal("50"), Decimal("50"), cycle_id="c1")
    db_session.query(Position).one().quantity = Decimal("9")
    db_session.commit()

    assert "ETHUSDT quantity" in verify_agent_state(db_session, agent.id)


def test_canonical_trade_cannot_be_updated_or_deleted(db_session):
    agent = _agent(db_session)
    trade = execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), Decimal("100"), cycle_id="c1")

    trade.price = Decimal("999")
    with pytest.raises(ValueError, match="append-only"):
        db_session.commit()
    db_session.rollback()
    db_session.refresh(trade)
    assert trade.price == Decimal("100")

    db_session.delete(trade)
    with pytest.raises(ValueError, match="append-only"):
        db_session.commit()
    db_session.rollback()
