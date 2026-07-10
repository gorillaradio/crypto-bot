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


def test_partial_sell_keeps_position(db_session):
    agent = _agent(db_session, "0")
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1.0"), avg_price=Decimal("100")))
    db_session.commit()
    # vende 0.4 al bid 200 → nozionale 80, fee = 80 * 0.001 = 0.08, cash += 79.92
    execute_sell(db_session, agent, "BTCUSDT", Decimal("0.4"), bid=Decimal("200"))
    assert agent.cash_usd == Decimal("79.92")
    pos = db_session.query(Position).filter_by(agent_id=agent.id, symbol="BTCUSDT").one()
    assert pos.quantity == Decimal("0.6")


def test_sell_raises_if_not_enough_quantity(db_session):
    agent = _agent(db_session, "0")
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("0.1"), avg_price=Decimal("100")))
    db_session.commit()
    with pytest.raises(ValueError):
        execute_sell(db_session, agent, "BTCUSDT", Decimal("0.5"), bid=Decimal("200"))


# --- payload strutturato e ciclo di vita posizione (spec 2026-07-09) ---
from app.db.models import Event


def test_buy_writes_structured_payload_and_opens_lifecycle(db_session):
    agent = _agent(db_session, "100")
    execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), ask=Decimal("100"),
                cycle_id="c1", rationale="momentum")
    ev = db_session.query(Event).filter_by(kind="trade").one()
    p = ev.payload
    assert p["side"] == "BUY" and p["symbol"] == "BTCUSDT"
    assert p["usd_value"] == "50" and p["rationale"] == "momentum"
    assert p["position"] == "new"
    pos = db_session.query(Position).one()
    assert pos.opened_at is not None
    assert pos.invested_usd == Decimal("50")
    assert pos.realized_usd == Decimal("0")


def test_rebuy_marks_increase_and_accumulates_invested(db_session):
    agent = _agent(db_session, "200")
    execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), ask=Decimal("100"))
    first_opened = db_session.query(Position).one().opened_at
    execute_buy(db_session, agent, "BTCUSDT", Decimal("30"), ask=Decimal("120"))
    pos = db_session.query(Position).one()
    assert pos.invested_usd == Decimal("80")
    assert pos.opened_at == first_opened          # il riacquisto non riapre la vita
    last = db_session.query(Event).filter_by(kind="trade").order_by(Event.id.desc()).first()
    assert last.payload["position"] == "increase"


def test_partial_sell_payload_has_fraction_and_realized(db_session):
    agent = _agent(db_session, "100")
    execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), ask=Decimal("100"))
    execute_sell(db_session, agent, "BTCUSDT", Decimal("0.25"), bid=Decimal("120"),
                 rationale="take profit")
    ev = db_session.query(Event).filter_by(kind="trade").order_by(Event.id.desc()).first()
    p = ev.payload
    assert p["side"] == "SELL"
    assert Decimal(p["fraction"]) == Decimal("0.5")            # 0.25 di 0.5
    assert Decimal(p["realized_pnl_pct"]) == Decimal("20")     # (120-100)/100
    assert Decimal(p["realized_pnl_usd"]) == Decimal("5")      # 20 * 0.25
    assert "position_summary" not in p                          # parziale: niente biografia
    pos = db_session.query(Position).one()
    assert pos.realized_usd == Decimal("5")


def test_full_close_payload_carries_position_summary(db_session):
    agent = _agent(db_session, "100")
    execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), ask=Decimal("100"))
    execute_sell(db_session, agent, "BTCUSDT", Decimal("0.25"), bid=Decimal("120"))
    execute_sell(db_session, agent, "BTCUSDT", Decimal("0.25"), bid=Decimal("140"))
    ev = db_session.query(Event).filter_by(kind="trade").order_by(Event.id.desc()).first()
    s = ev.payload["position_summary"]
    assert s["opened_at"] is not None and s["closed_at"] is not None
    assert s["held_minutes"] >= 0
    assert Decimal(s["invested_usd"]) == Decimal("50")
    # vita intera: +5 (prima parziale) +10 (chiusura) = 15 → 30% dell'investito
    assert Decimal(s["realized_total_usd"]) == Decimal("15")
    assert Decimal(s["realized_total_pct"]) == Decimal("30")
    assert db_session.query(Position).first() is None
