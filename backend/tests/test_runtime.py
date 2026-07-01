from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.db.models import Agent, Event, Position, EquitySnapshot, Trade, AgentMemory
from app.agents.runtime import run_heartbeat, run_decision, run_decision_guarded
from app.brain.context import CoinSnapshot, MemoryView
from app.brain.schema import Decision, Action


class FakeMarket:
    def __init__(self, price, book):
        self._price, self._book = price, book
    async def get_price(self, symbol): return self._price
    async def get_book_ticker(self, symbol): return self._book


class FakeMarketLLM:
    def __init__(self, snapshot, price, book):
        self._snap, self._price, self._book = snapshot, price, book
    async def get_universe_snapshot(self, symbols): return self._snap
    async def get_price(self, symbol): return self._price
    async def get_book_ticker(self, symbol): return self._book


class FakeMarketHB:
    """Market per l'heartbeat: prezzo unico per ogni simbolo + get_top_symbols."""
    def __init__(self, price, symbols=None):
        self._price, self._symbols = price, symbols or ["BTCUSDT"]
    async def get_price(self, symbol): return self._price
    async def get_top_symbols(self, quote, n): return self._symbols


def _agent(session, cash="100"):
    a = Agent(name="R", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal(cash))
    session.add(a); session.commit()
    return a


def _llm_agent(session):
    a = Agent(name="B", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("100"),
              model_provider="openrouter", model_name="deepseek/deepseek-v4-flash")
    session.add(a); session.commit()
    return a


def _armed_agent(session, stop="0.10", take="0.20"):
    a = Agent(name="H", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("0"), stop_loss=Decimal(stop), take_profit=Decimal(take))
    session.add(a); session.commit()
    return a


async def test_heartbeat_writes_equity_snapshot(db_session):
    agent = _agent(db_session, "100")
    market = FakeMarket(price=Decimal("100"), book=(Decimal("99"), Decimal("101")))
    await run_heartbeat(db_session, agent, market)
    snap = db_session.query(EquitySnapshot).filter_by(agent_id=agent.id).one()
    assert snap.equity_usd == Decimal("100")  # solo cash, nessuna posizione


async def test_heartbeat_within_band_saves_equity_no_trigger(db_session):
    agent = _armed_agent(db_session)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    market = FakeMarketHB(price=Decimal("105"))          # +5%, in banda
    calls = []
    async def fake_trigger(*a, **k): calls.append(1); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert calls == []
    snap = db_session.query(EquitySnapshot).filter_by(agent_id=agent.id).one()
    assert snap.equity_usd == Decimal("105")


async def test_heartbeat_fresh_breach_triggers_disarms_no_sell(db_session):
    agent = _armed_agent(db_session)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    market = FakeMarketHB(price=Decimal("85"))           # -15% → stop
    calls = []
    async def fake_trigger(session, agent, market, symbols, *, wake_reason=None):
        calls.append(wake_reason); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert len(calls) == 1 and "stop" in calls[0] and "BTCUSDT" in calls[0]
    assert db_session.query(Trade).filter_by(agent_id=agent.id).count() == 0   # nessuna vendita meccanica
    pos = db_session.query(Position).filter_by(agent_id=agent.id).one()
    assert pos.breach_armed is False


async def test_heartbeat_disarmed_breach_does_not_retrigger(db_session):
    agent = _armed_agent(db_session)
    p = Position(agent_id=agent.id, symbol="BTCUSDT", quantity=Decimal("1"), avg_price=Decimal("100"))
    p.breach_armed = False
    db_session.add(p); db_session.commit()
    market = FakeMarketHB(price=Decimal("85"))           # ancora oltre soglia, ma disarmata
    calls = []
    async def fake_trigger(*a, **k): calls.append(1); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert calls == []


async def test_heartbeat_rearms_when_back_in_band(db_session):
    agent = _armed_agent(db_session)
    p = Position(agent_id=agent.id, symbol="BTCUSDT", quantity=Decimal("1"), avg_price=Decimal("100"))
    p.breach_armed = False
    db_session.add(p); db_session.commit()
    market = FakeMarketHB(price=Decimal("100"))          # rientrata in banda
    async def fake_trigger(*a, **k): return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    db_session.refresh(p)
    assert p.breach_armed is True


async def test_heartbeat_no_thresholds_never_triggers(db_session):
    a = Agent(name="Blind", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("0"))
    db_session.add(a); db_session.commit()
    db_session.add(Position(agent_id=a.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    market = FakeMarketHB(price=Decimal("50"))           # -50%, ma soglie None
    calls = []
    async def fake_trigger(*a, **k): calls.append(1); return True
    await run_heartbeat(db_session, a, market, trigger_decision=fake_trigger)
    assert calls == []


async def test_heartbeat_armed_position_triggers_despite_other_disarmed(db_session):
    agent = _armed_agent(db_session)
    p1 = Position(agent_id=agent.id, symbol="AAAUSDT", quantity=Decimal("1"), avg_price=Decimal("100"))
    p1.breach_armed = False                              # già svegliato per questa
    p2 = Position(agent_id=agent.id, symbol="BBBUSDT", quantity=Decimal("1"), avg_price=Decimal("100"))
    db_session.add_all([p1, p2]); db_session.commit()
    market = FakeMarketHB(price=Decimal("85"), symbols=["AAAUSDT", "BBBUSDT"])  # entrambe -15%
    calls = []
    async def fake_trigger(session, agent, market, symbols, *, wake_reason=None):
        calls.append(wake_reason); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert len(calls) == 1 and "BBBUSDT" in calls[0]     # la posizione armata sveglia
    db_session.refresh(p1); db_session.refresh(p2)
    assert p1.breach_armed is False and p2.breach_armed is False  # entrambe disarmate al risveglio


async def test_llm_path_executes_buy_with_guardrails(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[
        Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("50"), rationale="dip"),
        Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("2"), rationale="too small"),   # < min_trade
        Action(type="BUY", symbol="NOTINUNIVERSE", usd_amount=Decimal("10"), rationale="x"),     # not in universe
    ], note="testing")
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: decision)
    buys = db_session.query(Trade).filter_by(agent_id=agent.id, side="BUY").all()
    assert len(buys) == 1                            # only the valid $50 buy
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").one()
    assert "testing" in ev.message


async def test_llm_all_in_buy_clamps_for_fee_and_executes(db_session):
    """An all-in BUY (usd_amount == cash) must succeed, not error out: the runtime
    clamps the requested spend to cash/(1+fee_rate) so the fee fits on top, opening
    a position. Without the clamp, execute_buy raises 'cash insufficiente'."""
    agent = _llm_agent(db_session)                   # cash 100
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[
        Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("100"), rationale="all-in"),
    ], note="fomo")
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: decision)
    buys = db_session.query(Trade).filter_by(agent_id=agent.id, side="BUY").all()
    assert len(buys) == 1                            # the all-in executed
    pos = db_session.query(Position).filter_by(agent_id=agent.id, symbol="BTCUSDT").one()
    assert pos.quantity > 0
    assert agent.cash_usd >= Decimal("0")            # never overspends past cash
    assert agent.cash_usd < Decimal("1")             # spent (almost) all cash
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").one()
    assert "1 operazioni" in ev.message and "0 errori" in ev.message


async def test_llm_data_gathering_error_writes_event_no_trade(db_session):
    """If get_universe_snapshot raises, run_decision must not raise, must write a decision
    event recording the error, and must create zero Trade rows."""
    agent = _llm_agent(db_session)

    class FakeMarketLLMBroken:
        async def get_universe_snapshot(self, symbols):
            raise RuntimeError("network timeout")

    market = FakeMarketLLMBroken()
    await run_decision(db_session, agent, market, ["BTCUSDT"])
    trades = db_session.query(Trade).filter_by(agent_id=agent.id).all()
    assert len(trades) == 0
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").one()
    assert "errore" in ev.message
    assert "network timeout" in ev.message


async def test_llm_path_sells_held_fraction(db_session):
    agent = _llm_agent(db_session)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("2"))]
    market = FakeMarketLLM(snap, Decimal("120"), (Decimal("120"), Decimal("121")))
    decision = Decision(actions=[Action(type="SELL", symbol="BTCUSDT", fraction=Decimal("0.5"))], note="trim")
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: decision)
    pos = db_session.query(Position).filter_by(agent_id=agent.id, symbol="BTCUSDT").one()
    assert pos.quantity == Decimal("0.5")


async def test_llm_buy_then_sell_same_symbol_same_cycle(db_session):
    """After a BUY, held must be rebuilt so a subsequent SELL of the same symbol
    in the same cycle is not silently skipped (Fix 2)."""
    agent = _llm_agent(db_session)
    # agent starts with no position in NEWUSDT
    snap = [CoinSnapshot("NEWUSDT", Decimal("50"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("50"), (Decimal("50"), Decimal("51")))
    decision = Decision(actions=[
        Action(type="BUY",  symbol="NEWUSDT", usd_amount=Decimal("50"), rationale="open"),
        Action(type="SELL", symbol="NEWUSDT", fraction=Decimal("1"),    rationale="close"),
    ], note="buy-then-sell")
    await run_decision(db_session, agent, market, ["NEWUSDT"],
                       brain_decide=lambda ctx, adapter: decision)
    # Both the BUY and the SELL should have executed
    buys  = db_session.query(Trade).filter_by(agent_id=agent.id, side="BUY").all()
    sells = db_session.query(Trade).filter_by(agent_id=agent.id, side="SELL").all()
    assert len(buys)  == 1, "BUY should have executed"
    assert len(sells) == 1, "SELL should have executed (held must be rebuilt after BUY)"
    # Position should be gone (fully closed)
    pos = db_session.query(Position).filter_by(agent_id=agent.id, symbol="NEWUSDT").first()
    assert pos is None or pos.quantity == Decimal("0")


async def test_reflection_runs_once_on_sell_and_persists(db_session):
    agent = _llm_agent(db_session)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("2"))]
    market = FakeMarketLLM(snap, Decimal("120"), (Decimal("120"), Decimal("121")))
    decision = Decision(actions=[Action(type="SELL", symbol="BTCUSDT", fraction=Decimal("1"))], note="exit")

    calls = []
    def fake_reflect(memory, closed, held_symbols, instructions, adapter):
        calls.append(closed)
        return MemoryView(coin_theses="BTC: took profit", trade_lessons="green exit")

    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: decision, reflect=fake_reflect)

    assert len(calls) == 1                       # exactly one reflection call
    assert calls[0][0].symbol == "BTCUSDT"
    assert calls[0][0].realized_pnl_pct == Decimal("20")   # (120-100)/100*100
    row = db_session.query(AgentMemory).filter_by(agent_id=agent.id, section="coin_theses").one()
    assert row.content == "BTC: took profit"
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="reflection").one()
    assert "memoria" in ev.message.lower()


async def test_decision_events_share_one_cycle_id(db_session):
    """Every event a single run_decision emits (decision summary, reasoning, trade)
    must carry the same non-null cycle_id so the frontend can group them."""
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[
        Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("50"), rationale="dip"),
    ], note="in")
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: decision)
    events = db_session.query(Event).filter_by(agent_id=agent.id).all()
    kinds = {e.kind for e in events}
    assert {"decision", "reasoning", "trade"} <= kinds   # all three present
    cycle_ids = {e.cycle_id for e in events}
    assert len(cycle_ids) == 1 and None not in cycle_ids  # exactly one, non-null


async def test_two_cycles_get_distinct_cycle_ids(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[], note="hold")
    for _ in range(2):
        await run_decision(db_session, agent, market, ["BTCUSDT"],
                           brain_decide=lambda ctx, adapter: decision)
    ids = [e.cycle_id for e in db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").all()]
    assert len(ids) == 2 and ids[0] != ids[1]


async def test_no_reflection_when_no_sell(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("50"))], note="in")
    calls = []
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: decision,
                       reflect=lambda *a, **k: calls.append(1) or MemoryView())
    assert calls == []
    assert db_session.query(AgentMemory).filter_by(agent_id=agent.id).count() == 0


async def test_run_decision_passes_wake_reason_and_marks_event(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    captured = {}

    def capture(ctx, adapter):
        captured["wake"] = ctx.wake_reason
        return Decision(actions=[], note="held")

    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       wake_reason="BTCUSDT -12% oltre stop", brain_decide=capture)
    assert captured["wake"] == "BTCUSDT -12% oltre stop"
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").one()
    assert "fuori ciclo" in ev.message


async def test_reflection_failure_is_isolated(db_session):
    agent = _llm_agent(db_session)
    db_session.add(AgentMemory(agent_id=agent.id, section="coin_theses", content="BTC: keep"))
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("2"))]
    market = FakeMarketLLM(snap, Decimal("120"), (Decimal("120"), Decimal("121")))
    decision = Decision(actions=[Action(type="SELL", symbol="BTCUSDT", fraction=Decimal("1"))], note="exit")

    def boom(*a, **k):
        raise RuntimeError("provider down")

    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: decision, reflect=boom)

    # existing memory untouched
    row = db_session.query(AgentMemory).filter_by(agent_id=agent.id, section="coin_theses").one()
    assert row.content == "BTC: keep"
    # error logged as a reflection event, loop did not crash (the SELL still executed)
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="reflection").one()
    assert "errore" in ev.message and "provider down" in ev.message
    assert db_session.query(Trade).filter_by(agent_id=agent.id, side="SELL").count() == 1


async def test_guarded_runs_when_free(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    ran = await run_decision_guarded(db_session, agent, market, ["BTCUSDT"],
                                     brain_decide=lambda ctx, adapter: Decision(actions=[], note="ok"))
    assert ran is True


async def test_guarded_skips_when_locked(db_session):
    from app.agents.runtime import _agent_lock
    agent = _llm_agent(db_session)
    market = FakeMarketLLM([], Decimal("100"), (Decimal("99"), Decimal("101")))
    lock = _agent_lock(agent.id)
    await lock.acquire()
    try:
        ran = await run_decision_guarded(db_session, agent, market, ["BTCUSDT"],
                                         brain_decide=lambda ctx, adapter: Decision(actions=[], note="x"))
        assert ran is False
    finally:
        lock.release()
