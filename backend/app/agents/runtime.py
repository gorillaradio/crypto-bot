from decimal import Decimal, ROUND_DOWN
from uuid import uuid4
from app.core.config import settings
from app.db.models import EquitySnapshot, Event, AgentMemory
from app.trading.engine import execute_buy, execute_sell
from app.agents.strategy import guardrail_action
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


async def run_decision(session, agent, market, symbols, *,
                       brain_decide=brain_decide_default, reflect=run_reflection) -> None:
    cycle_id = uuid4().hex
    await _run_decision_llm(session, agent, market, symbols, brain_decide, reflect, cycle_id)


async def _run_decision_llm(session, agent, market, symbols, brain_decide, reflect, cycle_id: str) -> None:
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
        adapter = make_adapter(agent.model_provider, agent.model_name)
        decision = brain_decide(ctx, adapter)
    except Exception as exc:
        session.add(Event(agent_id=agent.id, kind="decision", cycle_id=cycle_id,
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
                # The fee is charged on top of the notional, so the most the agent
                # can actually spend is cash / (1 + fee_rate). Clamp the request down
                # to that (rounded down to the cash scale) so an all-in BUY executes
                # instead of erroring out in execute_buy when the fee tips it over cash.
                affordable = (agent.cash_usd / (Decimal("1") + settings.fee_rate)
                              ).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                if amount > affordable:
                    amount = affordable
                if amount < settings.min_trade_usd:
                    skipped += 1; continue
                _bid, ask = await market.get_book_ticker(action.symbol)
                execute_buy(session, agent, action.symbol, amount, ask, cycle_id=cycle_id)
                _append_rationale(session, agent, action.rationale, cycle_id)
                session.refresh(agent)
                held = {p.symbol: p for p in agent.positions}; actions += 1
            elif action.type == "SELL" and action.symbol in held:
                frac = action.fraction if action.fraction is not None else Decimal("1")
                qty = held[action.symbol].quantity * frac
                if qty <= 0:
                    skipped += 1; continue
                avg_cost = held[action.symbol].avg_price
                bid, _ask = await market.get_book_ticker(action.symbol)
                execute_sell(session, agent, action.symbol, qty, bid, cycle_id=cycle_id)
                realized = ((bid - avg_cost) / avg_cost * Decimal("100")) if avg_cost else Decimal("0")
                closed_trades.append(ClosedTrade(symbol=action.symbol, qty=qty, sell_price=bid,
                                                 avg_cost=avg_cost, realized_pnl_pct=realized))
                _append_rationale(session, agent, action.rationale, cycle_id)
                held = {p.symbol: p for p in agent.positions}; actions += 1
            else:
                skipped += 1
        except Exception:
            errors += 1
    note = decision.note or "(no note)"
    session.add(Event(agent_id=agent.id, kind="decision", cycle_id=cycle_id,
                      message=f"ciclo decisione (LLM): {note} — {actions} operazioni, {skipped} saltate, {errors} errori"))
    session.commit()

    if closed_trades:
        try:
            held_symbols = [p.symbol for p in agent.positions]
            new_mem = reflect(memory, closed_trades, held_symbols, agent.instructions, adapter)
            _persist_memory(session, agent.id, new_mem)
            session.add(Event(agent_id=agent.id, kind="reflection", cycle_id=cycle_id,
                              message="memoria aggiornata dopo trade chiuso"))
        except Exception as exc:
            session.add(Event(agent_id=agent.id, kind="reflection", cycle_id=cycle_id,
                              message=f"reflection: errore — {exc}"))
        session.commit()


def _append_rationale(session, agent, rationale: str, cycle_id: str | None = None) -> None:
    if rationale:
        session.add(Event(agent_id=agent.id, kind="reasoning", cycle_id=cycle_id, message=rationale))


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
