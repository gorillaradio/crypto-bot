import pytest
from decimal import Decimal
from datetime import datetime, timezone
from app.db.models import Agent, Position, Trade
from app.trading.engine import execute_buy, execute_sell


def _agent(session, cash="100"):
    a = Agent(name="T", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc), cash_usd=Decimal(cash))
    session.add(a); session.commit()
    return a


def test_buy_spends_cash_with_fee_and_creates_position(db_session):
    agent = _agent(db_session, "100")
    # compra 50 USD di BTC all'ask 100 → qty lorda 0.5, fee 0.1% sul nozionale
    trade = execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), ask=Decimal("100"))
    # nozionale 50, fee = 50 * 0.001 = 0.05, cash = 100 - 50 - 0.05
    assert agent.cash_usd == Decimal("49.95")
    assert trade.side == "BUY"
    assert trade.fee == Decimal("0.05")
    pos = db_session.query(Position).filter_by(agent_id=agent.id, symbol="BTCUSDT").one()
    assert pos.quantity == Decimal("0.5")
    assert pos.avg_price == Decimal("100")


def test_buy_raises_if_insufficient_cash(db_session):
    agent = _agent(db_session, "10")
    with pytest.raises(ValueError):
        execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), ask=Decimal("100"))


def test_sell_credits_cash_with_fee_and_reduces_position(db_session):
    agent = _agent(db_session, "0")
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("0.5"), avg_price=Decimal("100")))
    db_session.commit()
    # vende 0.5 al bid 200 → nozionale 100, fee 0.1
    trade = execute_sell(db_session, agent, "BTCUSDT", Decimal("0.5"), bid=Decimal("200"))
    assert agent.cash_usd == Decimal("99.9")  # 100 - fee 0.1
    assert trade.side == "SELL"
    remaining = db_session.query(Position).filter_by(agent_id=agent.id, symbol="BTCUSDT").first()
    assert remaining is None  # posizione azzerata → rimossa


def test_sell_raises_if_not_enough_quantity(db_session):
    agent = _agent(db_session, "0")
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("0.1"), avg_price=Decimal("100")))
    db_session.commit()
    with pytest.raises(ValueError):
        execute_sell(db_session, agent, "BTCUSDT", Decimal("0.5"), bid=Decimal("200"))
