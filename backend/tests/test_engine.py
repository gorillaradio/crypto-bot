import pytest
from decimal import Decimal
from datetime import datetime, timezone
from app.db.models import Agent, Position, PositionEvaluation, PositionLifecycle, Trade
from app.trading.engine import execute_buy, execute_sell


def _agent(session, cash="100"):
    a = Agent(name="T", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc), cash_usd=Decimal(cash), initial_capital_usd=Decimal(cash))
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
    assert trade.lifecycle_id is not None
    assert trade.cycle_id is not None
    pos = db_session.query(Position).filter_by(agent_id=agent.id, symbol="BTCUSDT").one()
    assert pos.quantity == Decimal("0.5")
    assert pos.avg_price == Decimal("100")
    evaluation = db_session.query(PositionEvaluation).one()
    assert (evaluation.policy_refs, evaluation.policy_alignment, evaluation.override_reason) == (
        [], "unrelated", "",
    )


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_trade_evaluation_persists_full_policy_context(db_session, side):
    agent = _agent(db_session, "300")
    if side == "SELL":
        execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"), cycle_id="open")
        trade = execute_sell(
            db_session, agent, "BTCUSDT", Decimal("0.5"), Decimal("120"),
            cycle_id="decision", rationale="trim risk", policy_refs=["P002"],
            policy_alignment="violates", override_reason="volatility spike",
        )
    else:
        trade = execute_buy(
            db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"),
            cycle_id="decision", rationale="breakout", policy_refs=["P001"],
            policy_alignment="follows", override_reason="",
        )

    evaluation = (db_session.query(PositionEvaluation)
                  .filter_by(lifecycle_id=trade.lifecycle_id, cycle_id="decision").one())
    assert evaluation.rationale in {"breakout", "trim risk"}
    assert evaluation.policy_refs == (["P001"] if side == "BUY" else ["P002"])
    assert evaluation.policy_alignment == ("follows" if side == "BUY" else "violates")
    assert evaluation.override_reason == ("" if side == "BUY" else "volatility spike")


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


def test_trades_keep_one_lifecycle_until_close_then_open_a_second_life(db_session):
    agent = _agent(db_session, "300")

    first = execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), Decimal("100"), cycle_id="c1")
    increase = execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), Decimal("100"), cycle_id="c2")
    partial = execute_sell(db_session, agent, "BTCUSDT", Decimal("0.4"), Decimal("120"), cycle_id="c3")
    close = execute_sell(db_session, agent, "BTCUSDT", Decimal("0.6"), Decimal("130"), cycle_id="c4")
    second = execute_buy(db_session, agent, "BTCUSDT", Decimal("40"), Decimal("80"), cycle_id="c5")

    assert {first.lifecycle_id, increase.lifecycle_id, partial.lifecycle_id, close.lifecycle_id} == {
        first.lifecycle_id
    }
    assert first.lifecycle_id is not None
    assert second.lifecycle_id != first.lifecycle_id
    assert [t.cycle_id for t in (first, increase, partial, close, second)] == ["c1", "c2", "c3", "c4", "c5"]
    lifecycles = db_session.query(PositionLifecycle).order_by(PositionLifecycle.opened_at).all()
    assert lifecycles[0].closed_at is not None
    assert lifecycles[1].closed_at is None
    assert db_session.query(Position).one().lifecycle_id == second.lifecycle_id


def test_buy_rolls_back_trade_evaluation_and_projection_together(db_session):
    from sqlalchemy import event

    agent = _agent(db_session, "100")

    def fail_evaluation(_mapper, _connection, _target):
        raise RuntimeError("evaluation unavailable")

    event.listen(PositionEvaluation, "before_insert", fail_evaluation)
    try:
        with pytest.raises(RuntimeError, match="evaluation unavailable"):
            execute_buy(
                db_session, agent, "BTCUSDT", Decimal("50"), Decimal("100"),
                cycle_id="atomic", rationale="test",
            )
    finally:
        event.remove(PositionEvaluation, "before_insert", fail_evaluation)

    assert db_session.query(Trade).count() == 0
    assert db_session.query(PositionEvaluation).count() == 0
    assert db_session.query(Position).count() == 0
    assert db_session.query(PositionLifecycle).count() == 0
    db_session.refresh(agent)
    assert agent.cash_usd == Decimal("100")


def test_sell_rolls_back_trade_evaluation_and_projection_together(db_session):
    from sqlalchemy import event

    agent = _agent(db_session, "200")
    execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"), cycle_id="open")
    position = db_session.query(Position).one()
    cash_before = agent.cash_usd

    def fail_evaluation(_mapper, _connection, target):
        if target.action == "SELL":
            raise RuntimeError("sell evaluation unavailable")

    event.listen(PositionEvaluation, "before_insert", fail_evaluation)
    try:
        with pytest.raises(RuntimeError, match="sell evaluation unavailable"):
            execute_sell(
                db_session, agent, "BTCUSDT", Decimal("0.4"), Decimal("120"),
                cycle_id="partial", rationale="trim",
            )
    finally:
        event.remove(PositionEvaluation, "before_insert", fail_evaluation)

    db_session.refresh(agent)
    db_session.refresh(position)
    assert agent.cash_usd == cash_before
    assert position.quantity == Decimal("1")
    assert db_session.query(Trade).count() == 1
    assert db_session.query(PositionEvaluation).count() == 1
