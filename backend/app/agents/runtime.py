from decimal import Decimal
from app.db.models import EquitySnapshot, Event
from app.trading.engine import execute_buy, execute_sell
from app.agents.strategy import decide_signal, guardrail_action


async def run_heartbeat(session, agent, market) -> None:
    equity = agent.cash_usd
    for pos in list(agent.positions):
        last = await market.get_price(pos.symbol)
        if guardrail_action(pos.avg_price, last) == "SELL":
            bid, _ask = await market.get_book_ticker(pos.symbol)
            execute_sell(session, agent, pos.symbol, pos.quantity, bid)
        else:
            equity += pos.quantity * last
    session.add(EquitySnapshot(agent_id=agent.id, equity_usd=equity))
    session.commit()


async def run_decision(session, agent, market, symbols, buy_usd: Decimal) -> None:
    held = {p.symbol: p for p in agent.positions}
    actions = 0
    for symbol in symbols:
        closes = await market.get_klines(symbol, "1h", 50)
        signal = decide_signal(closes)
        if signal == "BUY" and agent.cash_usd >= buy_usd:
            _bid, ask = await market.get_book_ticker(symbol)
            execute_buy(session, agent, symbol, buy_usd, ask)
            actions += 1
        elif signal == "SELL" and symbol in held:
            bid, _ask = await market.get_book_ticker(symbol)
            execute_sell(session, agent, symbol, held[symbol].quantity, bid)
            actions += 1
    session.add(Event(agent_id=agent.id, kind="decision",
                      message=f"ciclo decisione: {actions} operazioni su {len(symbols)} simboli"))
    session.commit()
