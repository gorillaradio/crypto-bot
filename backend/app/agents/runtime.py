from decimal import Decimal
from app.core.config import settings
from app.db.models import EquitySnapshot, Event, AgentMemory
from app.trading.engine import execute_buy, execute_sell
from app.agents.strategy import decide_signal, guardrail_action
from app.brain import decide as brain_decide_default
from app.brain.context import build_context, MemoryView
from app.brain.memory import run_reflection, ClosedTrade
from app.brain.providers import make_adapter


async def run_heartbeat(session, agent, market) -> None:
    positions_value = Decimal("0")
    for pos in list(agent.positions):
        last = await market.get_price(pos.symbol)
        if guardrail_action(pos.avg_price, last) == "SELL":
            bid, _ask = await market.get_book_ticker(pos.symbol)
            execute_sell(session, agent, pos.symbol, pos.quantity, bid)
        else:
            positions_value += pos.quantity * last
    equity = agent.cash_usd + positions_value
    session.add(EquitySnapshot(agent_id=agent.id, equity_usd=equity))
    session.commit()


async def run_decision(session, agent, market, symbols, buy_usd: Decimal, *,
                       brain_decide=brain_decide_default, reflect=run_reflection) -> None:
    if agent.strategy == "sma":
        await _run_decision_sma(session, agent, market, symbols, buy_usd)
    else:
        await _run_decision_llm(session, agent, market, symbols, brain_decide, reflect)


async def _run_decision_sma(session, agent, market, symbols, buy_usd: Decimal) -> None:
    held = {p.symbol: p for p in agent.positions}
    actions = errors = 0
    for symbol in symbols:
        try:
            closes = await market.get_klines(symbol, "1h", 50)
            signal = decide_signal(closes)
            if signal == "BUY" and agent.cash_usd >= buy_usd:
                _bid, ask = await market.get_book_ticker(symbol)
                execute_buy(session, agent, symbol, buy_usd, ask); actions += 1
            elif signal == "SELL" and symbol in held:
                bid, _ask = await market.get_book_ticker(symbol)
                execute_sell(session, agent, symbol, held[symbol].quantity, bid); actions += 1
        except Exception:
            errors += 1
    session.add(Event(agent_id=agent.id, kind="decision",
                      message=f"ciclo decisione (SMA): {actions} operazioni su {len(symbols)} simboli, {errors} errori"))
    session.commit()


async def _run_decision_llm(session, agent, market, symbols, brain_decide, reflect) -> None:
    try:
        universe = await market.get_universe_snapshot(symbols)
        universe_symbols = {c.symbol for c in universe}

        holdings = []
        for pos in agent.positions:
            last = await market.get_price(pos.symbol)
            holdings.append((pos.symbol, pos.quantity, pos.avg_price, last))

        recent = [e.message for e in (
            session.query(Event).filter_by(agent_id=agent.id)
            .order_by(Event.timestamp.desc()).limit(10).all())]

        mem_rows = {r.section: r.content for r in
                    session.query(AgentMemory).filter_by(agent_id=agent.id).all()}
        memory = MemoryView(
            coin_theses=mem_rows.get("coin_theses", ""),
            trade_lessons=mem_rows.get("trade_lessons", ""),
            strategy_notes=mem_rows.get("strategy_notes", ""),
        )
        ctx = build_context(instructions=agent.instructions, cash_usd=agent.cash_usd,
                            holdings=holdings, universe=universe, recent_events=recent,
                            memory=memory)
        adapter = make_adapter(agent.model_provider or "anthropic", agent.model_name or "")
        decision = brain_decide(ctx, adapter)
    except Exception as exc:
        session.add(Event(agent_id=agent.id, kind="decision",
                          message=f"ciclo decisione (LLM): errore — {exc}"))
        session.commit()
        return

    held = {p.symbol: p for p in agent.positions}
    actions = skipped = errors = 0
    closed_trades: list[ClosedTrade] = []
    for action in decision.actions:
        try:
            if action.type == "BUY" and action.symbol in universe_symbols:
                amount = action.usd_amount or settings.decision_buy_default_usd
                if amount < settings.min_trade_usd or amount > agent.cash_usd:
                    skipped += 1; continue
                _bid, ask = await market.get_book_ticker(action.symbol)
                execute_buy(session, agent, action.symbol, amount, ask)
                _append_rationale(session, agent, action.rationale)
                session.refresh(agent)
                held = {p.symbol: p for p in agent.positions}; actions += 1
            elif action.type == "SELL" and action.symbol in held:
                frac = action.fraction if action.fraction is not None else Decimal("1")
                qty = held[action.symbol].quantity * frac
                if qty <= 0:
                    skipped += 1; continue
                avg_cost = held[action.symbol].avg_price
                bid, _ask = await market.get_book_ticker(action.symbol)
                execute_sell(session, agent, action.symbol, qty, bid)
                realized = ((bid - avg_cost) / avg_cost * Decimal("100")) if avg_cost else Decimal("0")
                closed_trades.append(ClosedTrade(symbol=action.symbol, qty=qty, sell_price=bid,
                                                 avg_cost=avg_cost, realized_pnl_pct=realized))
                _append_rationale(session, agent, action.rationale)
                held = {p.symbol: p for p in agent.positions}; actions += 1
            else:
                skipped += 1
        except Exception:
            errors += 1
    note = decision.note or "(no note)"
    session.add(Event(agent_id=agent.id, kind="decision",
                      message=f"ciclo decisione (LLM): {note} — {actions} operazioni, {skipped} saltate, {errors} errori"))
    session.commit()

    if closed_trades:
        try:
            held_symbols = [p.symbol for p in agent.positions]
            new_mem = reflect(memory, closed_trades, held_symbols, agent.instructions, adapter)
            _persist_memory(session, agent.id, new_mem)
            session.add(Event(agent_id=agent.id, kind="reflection",
                              message="memoria aggiornata dopo trade chiuso"))
        except Exception as exc:
            session.add(Event(agent_id=agent.id, kind="reflection",
                              message=f"reflection: errore — {exc}"))
        session.commit()


def _append_rationale(session, agent, rationale: str) -> None:
    if rationale:
        session.add(Event(agent_id=agent.id, kind="reasoning", message=rationale))


def _persist_memory(session, agent_id, mem: MemoryView) -> None:
    for section, content in (("coin_theses", mem.coin_theses),
                             ("trade_lessons", mem.trade_lessons),
                             ("strategy_notes", mem.strategy_notes)):
        row = (session.query(AgentMemory)
               .filter_by(agent_id=agent_id, section=section).first())
        if row is None:
            session.add(AgentMemory(agent_id=agent_id, section=section, content=content))
        else:
            row.content = content
