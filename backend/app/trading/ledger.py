from dataclasses import dataclass
from decimal import Decimal

from app.db.models import Agent, Position, Trade


@dataclass(frozen=True)
class LedgerPosition:
    symbol: str
    quantity: Decimal
    avg_price: Decimal
    invested_usd: Decimal
    realized_usd: Decimal


@dataclass(frozen=True)
class AgentLedgerState:
    cash_usd: Decimal
    positions: dict[str, LedgerPosition]


def rebuild_agent_state(session, agent_id: int) -> AgentLedgerState:
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise ValueError("agent not found")
    cash = agent.initial_capital_usd
    positions: dict[str, LedgerPosition] = {}
    trades = (
        session.query(Trade)
        .filter(Trade.agent_id == agent_id, Trade.lifecycle_id.is_not(None))
        .order_by(Trade.timestamp.asc(), Trade.id.asc())
        .all()
    )
    for trade in trades:
        current = positions.get(trade.lifecycle_id)
        if trade.side == "BUY":
            previous_qty = current.quantity if current else Decimal("0")
            previous_cost = (current.avg_price * previous_qty) if current else Decimal("0")
            quantity = previous_qty + trade.quantity
            positions[trade.lifecycle_id] = LedgerPosition(
                symbol=trade.symbol,
                quantity=quantity,
                avg_price=(previous_cost + trade.price * trade.quantity) / quantity,
                invested_usd=(current.invested_usd if current else Decimal("0")) + trade.price * trade.quantity,
                realized_usd=current.realized_usd if current else Decimal("0"),
            )
            cash -= trade.price * trade.quantity + trade.fee
        elif trade.side == "SELL" and current is not None:
            quantity = current.quantity - trade.quantity
            realized = current.realized_usd + (trade.price - current.avg_price) * trade.quantity
            cash += trade.price * trade.quantity - trade.fee
            if quantity <= 0:
                positions.pop(trade.lifecycle_id)
            else:
                positions[trade.lifecycle_id] = LedgerPosition(
                    symbol=current.symbol, quantity=quantity, avg_price=current.avg_price,
                    invested_usd=current.invested_usd, realized_usd=realized,
                )
    return AgentLedgerState(cash_usd=cash, positions=positions)


def verify_agent_state(session, agent_id: int) -> list[str]:
    agent = session.get(Agent, agent_id)
    if agent is None:
        return ["agent missing"]
    rebuilt = rebuild_agent_state(session, agent_id)
    errors = []
    if agent.cash_usd != rebuilt.cash_usd:
        errors.append("cash_usd")
    projected = {p.lifecycle_id: p for p in session.query(Position).filter_by(agent_id=agent_id).all()
                 if p.lifecycle_id is not None}
    if set(projected) != set(rebuilt.positions):
        errors.append("position lifecycles")
    for lifecycle_id in set(projected) & set(rebuilt.positions):
        position = projected[lifecycle_id]
        ledger = rebuilt.positions[lifecycle_id]
        if position.quantity != ledger.quantity:
            errors.append(f"{position.symbol} quantity")
        if position.avg_price != ledger.avg_price:
            errors.append(f"{position.symbol} avg_price")
        if (position.invested_usd or Decimal("0")) != ledger.invested_usd:
            errors.append(f"{position.symbol} invested_usd")
        if (position.realized_usd or Decimal("0")) != ledger.realized_usd:
            errors.append(f"{position.symbol} realized_usd")
    return errors
