from decimal import Decimal
from app.core.config import settings
from app.db.models import Agent, Position, Trade, Event


def _trim(s: str) -> str:
    return (s.rstrip("0").rstrip(".")) if "." in s else s


def _fmt_qty(d: Decimal) -> str:
    step = Decimal("0.0001") if abs(d) >= 1 else Decimal("0.00000001")
    return _trim(f"{d.quantize(step):f}")


def _fmt_price(d: Decimal) -> str:
    return _trim(f"{d:f}")


def _get_position(session, agent_id, symbol):
    return session.query(Position).filter_by(agent_id=agent_id, symbol=symbol).first()


def execute_buy(session, agent: Agent, symbol: str, usd_amount: Decimal, ask: Decimal,
                cycle_id: str | None = None) -> Trade:
    notional = usd_amount
    fee = notional * settings.fee_rate
    total_cost = notional + fee
    if total_cost > agent.cash_usd:
        raise ValueError("cash insufficiente")
    quantity = notional / ask
    agent.cash_usd = agent.cash_usd - total_cost

    pos = _get_position(session, agent.id, symbol)
    if pos is None:
        pos = Position(agent_id=agent.id, symbol=symbol, quantity=quantity, avg_price=ask)
        session.add(pos)
    else:
        new_qty = pos.quantity + quantity
        pos.avg_price = (pos.avg_price * pos.quantity + ask * quantity) / new_qty
        pos.quantity = new_qty

    trade = Trade(agent_id=agent.id, symbol=symbol, side="BUY",
                  quantity=quantity, price=ask, fee=fee)
    session.add(trade)
    session.add(Event(agent_id=agent.id, kind="trade", cycle_id=cycle_id,
                      message=f"BUY {_fmt_qty(quantity)} {symbol} @ ${_fmt_price(ask)} (fee ${_fmt_price(fee)})"))
    session.commit()
    return trade


def execute_sell(session, agent: Agent, symbol: str, quantity: Decimal, bid: Decimal,
                 cycle_id: str | None = None) -> Trade:
    pos = _get_position(session, agent.id, symbol)
    if pos is None or quantity > pos.quantity:
        raise ValueError("quantità insufficiente")
    notional = quantity * bid
    fee = notional * settings.fee_rate
    agent.cash_usd = agent.cash_usd + (notional - fee)

    pos.quantity = pos.quantity - quantity
    if pos.quantity <= 0:
        session.delete(pos)

    trade = Trade(agent_id=agent.id, symbol=symbol, side="SELL",
                  quantity=quantity, price=bid, fee=fee)
    session.add(trade)
    session.add(Event(agent_id=agent.id, kind="trade", cycle_id=cycle_id,
                      message=f"SELL {_fmt_qty(quantity)} {symbol} @ ${_fmt_price(bid)} (fee ${_fmt_price(fee)})"))
    session.commit()
    return trade
