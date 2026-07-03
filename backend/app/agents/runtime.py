import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from uuid import uuid4
from app.core.config import settings
from app.db.models import EquitySnapshot, Event, DecisionRecord, BenchmarkBasis, BenchmarkSnapshot
from app.trading.engine import execute_buy, execute_sell
from app.agents.strategy import breached
from app.brain import evaluate as brain_decide_default
from app.brain.context import build_context
from app.brain import journal
from app.brain.memory import run_reflection_result, ClosedTrade
from app.brain.providers import make_adapter
from app.eval.benchmarks import compute_benchmark_equities


def universe_size(agent) -> int:
    return 100 if agent.universe == "TOP_100" else 50


async def build_agent_context(session, agent, market, symbols, *, wake_reason=None):
    """Costruisce il DecisionContext dai dati vivi (universo, posizioni, eventi recenti,
    memoria). Usata sia dal ciclo di decisione sia dal monitor dei prompt, così il monitor
    mostra esattamente ciò che la pipeline invierebbe."""
    universe = await market.get_universe_snapshot(symbols)

    holdings = []
    for pos in agent.positions:
        last = await market.get_price(pos.symbol)
        holdings.append((pos.symbol, pos.quantity, pos.avg_price, last))

    recent = [e.message for e in (
        session.query(Event).filter_by(agent_id=agent.id)
        .order_by(Event.timestamp.desc()).limit(10).all())]

    memory = journal.compact_view(session, agent.id)
    return build_context(instructions=agent.instructions, cash_usd=agent.cash_usd,
                         holdings=holdings, universe=universe, recent_events=recent,
                         memory=memory, wake_reason=wake_reason)


async def run_heartbeat(session, agent, market, *, trigger_decision=None) -> None:
    if trigger_decision is None:
        trigger_decision = run_decision_guarded
    positions_value = Decimal("0")
    breached_positions = []
    fresh = None                                  # (symbol, side, change_pct) del primo breach fresco
    for pos in list(agent.positions):
        last = await market.get_price(pos.symbol)
        positions_value += pos.quantity * last
        side = breached(pos.avg_price, last, agent.stop_loss, agent.take_profit)
        if side is None:
            if not pos.breach_armed:              # rientrata in banda → ri-arma
                pos.breach_armed = True
        else:
            breached_positions.append(pos)
            if pos.breach_armed and fresh is None:
                change_pct = (last - pos.avg_price) / pos.avg_price * Decimal("100")
                fresh = (pos.symbol, side, change_pct)
    equity = agent.cash_usd + positions_value
    session.add(EquitySnapshot(agent_id=agent.id, equity_usd=equity))
    session.commit()

    await record_benchmark_snapshot(session, agent, market)

    if fresh is None:
        return
    symbol, side, change_pct = fresh
    threshold = agent.stop_loss if side == "stop" else agent.take_profit
    label = "stop" if side == "stop" else "take-profit"
    wake_reason = (f"Risveglio fuori ciclo: {symbol} a {change_pct:+.2f}%, oltre la tua "
                   f"soglia di {label} {threshold * Decimal('100'):.2f}%. Rivaluta.")
    n = universe_size(agent)
    symbols = await market.get_top_symbols("USDT", n)
    triggered = await trigger_decision(session, agent, market, symbols, wake_reason=wake_reason)
    if triggered:
        for p in breached_positions:              # l'LLM ha visto l'intero portafoglio: disarma tutte
            p.breach_armed = False
        session.commit()


async def run_decision(session, agent, market, symbols, *, wake_reason=None,
                       brain_decide=brain_decide_default, reflect=run_reflection_result) -> None:
    cycle_id = uuid4().hex
    await _run_decision_llm(session, agent, market, symbols, brain_decide, reflect, cycle_id, wake_reason)


_agent_locks: dict[int, asyncio.Lock] = {}


def _agent_lock(agent_id: int) -> asyncio.Lock:
    lock = _agent_locks.get(agent_id)
    if lock is None:
        lock = asyncio.Lock()
        _agent_locks[agent_id] = lock
    return lock


async def run_decision_guarded(session, agent, market, symbols, *, wake_reason=None,
                               brain_decide=brain_decide_default, reflect=run_reflection_result) -> bool:
    """Esegue una decisione sotto il lock dell'agente. Se una decisione è già in corso per
    questo agente, salta e ritorna False (quella in corso copre la situazione)."""
    lock = _agent_lock(agent.id)
    if lock.locked():
        return False
    async with lock:
        await run_decision(session, agent, market, symbols, wake_reason=wake_reason,
                           brain_decide=brain_decide, reflect=reflect)
    return True


async def _run_decision_llm(session, agent, market, symbols, brain_decide, reflect, cycle_id: str, wake_reason=None) -> None:
    try:
        ctx = await build_agent_context(session, agent, market, symbols, wake_reason=wake_reason)
        universe_symbols = {c.symbol for c in ctx.universe}
        adapter = make_adapter(agent.model_provider, agent.model_name)
        result = brain_decide(ctx, adapter)
    except Exception as exc:
        session.add(Event(agent_id=agent.id, kind="decision", cycle_id=cycle_id,
                          message=f"ciclo decisione (LLM): errore — {exc}"))
        session.commit()
        return

    decision = result.decision
    trigger = "breach" if wake_reason else "schedule"

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
    kind_label = "ciclo decisione fuori ciclo (LLM)" if wake_reason else "ciclo decisione (LLM)"
    _record_llm_call(session, agent, cycle_id, "decision", trigger,
                     system=result.system, user=result.user, raw=result.raw,
                     parsed_output=decision.model_dump_json(),
                     parse_status=result.parse_status, latency_ms=result.latency_ms)
    session.add(Event(agent_id=agent.id, kind="decision", cycle_id=cycle_id,
                      message=f"{kind_label}: {note} — {actions} operazioni, {skipped} saltate, {errors} errori"))
    session.commit()

    if closed_trades:
        try:
            held_symbols = [p.symbol for p in agent.positions]
            rr = reflect(ctx.memory, closed_trades, held_symbols, agent.instructions, adapter)
            _record_llm_call(session, agent, cycle_id, "reflection", trigger,
                             system=rr.system, user=rr.user, raw=rr.raw,
                             parsed_output=(rr.entries.model_dump_json()
                                            if rr.parse_status == "ok" else None),
                             parse_status=rr.parse_status, latency_ms=rr.latency_ms)
            if rr.parse_status == "ok":
                for section in journal.SECTIONS:
                    journal.append_entries(session, agent.id, section,
                                           getattr(rr.entries, section), cycle_id=cycle_id)
                session.add(Event(agent_id=agent.id, kind="reflection", cycle_id=cycle_id,
                                  message="memoria aggiornata dopo trade chiuso"))
            else:
                session.add(Event(agent_id=agent.id, kind="reflection", cycle_id=cycle_id,
                                  message="reflection: risposta non valida, memoria invariata"))
        except Exception as exc:
            session.add(Event(agent_id=agent.id, kind="reflection", cycle_id=cycle_id,
                              message=f"reflection: errore — {exc}"))
        session.commit()


def _append_rationale(session, agent, rationale: str, cycle_id: str | None = None) -> None:
    if rationale:
        session.add(Event(agent_id=agent.id, kind="reasoning", cycle_id=cycle_id, message=rationale))


def _record_llm_call(session, agent, cycle_id, kind, trigger, *,
                     system, user, raw, parsed_output, parse_status, latency_ms) -> None:
    session.add(DecisionRecord(
        agent_id=agent.id, cycle_id=cycle_id, kind=kind, trigger=trigger,
        system_prompt=system, user_prompt=user, raw_response=raw,
        parsed_output=parsed_output, parse_status=parse_status,
        model_provider=agent.model_provider, model_name=agent.model_name,
        latency_ms=latency_ms))


async def record_benchmark_snapshot(session, agent, market) -> None:
    """Write the ghost-benchmark equities for this beat. Self-isolating: on any error
    it rolls back its own work and returns — benchmarks are telemetry, never a reason
    to break the heartbeat."""
    try:
        basis = session.query(BenchmarkBasis).filter_by(agent_id=agent.id).first()
        if basis is None:
            symbols = await market.get_top_symbols("USDT", universe_size(agent))
            snap = await market.get_universe_snapshot(symbols)
            start_prices = {c.symbol: c.price for c in snap}
            basis = BenchmarkBasis(
                agent_id=agent.id,
                universe_json=json.dumps(symbols),
                start_prices_json=json.dumps({s: str(p) for s, p in start_prices.items()}),
                initial_capital=settings.initial_capital_usd)
            session.add(basis)
            now_prices = start_prices
            universe = symbols
        else:
            universe = json.loads(basis.universe_json)
            start_prices = {s: Decimal(p) for s, p in json.loads(basis.start_prices_json).items()}
            snap = await market.get_universe_snapshot(universe)
            now_prices = {c.symbol: c.price for c in snap}
        equities = compute_benchmark_equities(
            initial=basis.initial_capital, universe=universe,
            start_prices=start_prices, now_prices=now_prices, seed=agent.id)
        ts = datetime.now(timezone.utc)
        for kind, equity in equities.items():
            session.add(BenchmarkSnapshot(agent_id=agent.id, kind=kind, equity_usd=equity, timestamp=ts))
        session.commit()
    except Exception:
        session.rollback()
