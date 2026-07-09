from datetime import datetime, timezone
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


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def execute_buy(session, agent: Agent, symbol: str, usd_amount: Decimal, ask: Decimal,
                cycle_id: str | None = None, rationale: str | None = None) -> Trade:
    notional = usd_amount
    fee = notional * settings.fee_rate
    total_cost = notional + fee
    if total_cost > agent.cash_usd:
        raise ValueError("cash insufficiente")
    quantity = notional / ask
    agent.cash_usd = agent.cash_usd - total_cost

    pos = _get_position(session, agent.id, symbol)
    is_new = pos is None
    if is_new:
        pos = Position(agent_id=agent.id, symbol=symbol, quantity=quantity, avg_price=ask,
                       opened_at=datetime.now(timezone.utc),
                       invested_usd=notional, realized_usd=Decimal("0"))
        session.add(pos)
    else:
        new_qty = pos.quantity + quantity
        pos.avg_price = (pos.avg_price * pos.quantity + ask * quantity) / new_qty
        pos.quantity = new_qty
        pos.invested_usd = (pos.invested_usd or Decimal("0")) + notional

    trade = Trade(agent_id=agent.id, symbol=symbol, side="BUY",
                  quantity=quantity, price=ask, fee=fee)
    session.add(trade)
    payload = {"side": "BUY", "symbol": symbol, "qty": str(quantity), "price": str(ask),
               "fee": str(fee), "usd_value": str(notional), "rationale": rationale,
               "position": "new" if is_new else "increase"}
    session.add(Event(agent_id=agent.id, kind="trade", cycle_id=cycle_id, payload=payload,
                      message=f"BUY {_fmt_qty(quantity)} {symbol} @ ${_fmt_price(ask)} (fee ${_fmt_price(fee)})"))
    session.commit()
    return trade


def execute_sell(session, agent: Agent, symbol: str, quantity: Decimal, bid: Decimal,
                 cycle_id: str | None = None, rationale: str | None = None) -> Trade:
    pos = _get_position(session, agent.id, symbol)
    if pos is None or quantity > pos.quantity:
        raise ValueError("quantità insufficiente")
    notional = quantity * bid
    fee = notional * settings.fee_rate
    agent.cash_usd = agent.cash_usd + (notional - fee)

    fraction = quantity / pos.quantity
    avg_cost = pos.avg_price
    realized_pct = (((bid - avg_cost) / avg_cost) * Decimal("100")) if avg_cost else Decimal("0")
    realized_usd = (bid - avg_cost) * quantity
    pos.realized_usd = (pos.realized_usd or Decimal("0")) + realized_usd

    payload = {"side": "SELL", "symbol": symbol, "qty": str(quantity), "price": str(bid),
               "fee": str(fee), "usd_value": str(notional), "rationale": rationale,
               "fraction": str(fraction), "avg_cost": str(avg_cost),
               "realized_pnl_pct": str(realized_pct), "realized_pnl_usd": str(realized_usd)}

    pos.quantity = pos.quantity - quantity
    if pos.quantity <= 0:
        now = datetime.now(timezone.utc)
        invested = pos.invested_usd or None
        total = pos.realized_usd
        payload["position_summary"] = {
            "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
            "closed_at": now.isoformat(),
            "held_minutes": (int((now - _as_utc(pos.opened_at)).total_seconds() // 60)
                             if pos.opened_at else None),
            "invested_usd": str(invested) if invested is not None else None,
            "realized_total_usd": str(total),
            "realized_total_pct": (str((total / invested) * Decimal("100"))
                                   if invested else None),
        }
        session.delete(pos)

    trade = Trade(agent_id=agent.id, symbol=symbol, side="SELL",
                  quantity=quantity, price=bid, fee=fee)
    session.add(trade)
    session.add(Event(agent_id=agent.id, kind="trade", cycle_id=cycle_id, payload=payload,
                      message=f"SELL {_fmt_qty(quantity)} {symbol} @ ${_fmt_price(bid)} (fee ${_fmt_price(fee)})"))
    session.commit()
    return trade
