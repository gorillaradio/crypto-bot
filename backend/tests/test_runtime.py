import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.db.models import (Agent, Event, Position, EquitySnapshot, Trade, MemoryEntry,
                           DecisionRecord, BenchmarkBasis, BenchmarkSnapshot)
from app.agents.runtime import run_heartbeat, run_decision, run_decision_guarded, universe_size
from app.brain.context import CoinSnapshot
from app.brain.memory import ReflectionResult, PolicyEdit
from app.brain.schema import Decision, Action, DecisionResult
from app.brain import journal
from app.brain.memory import MemoryUpdate, DistillationResult


class FakeMarket:
    def __init__(self, price, book):
        self._price, self._book = price, book
    async def get_price(self, symbol): return self._price
    async def get_book_ticker(self, symbol): return self._book
    async def get_top_symbols(self, quote, n): return ["BTCUSDT"]
    async def get_universe_snapshot(self, symbols):
        return [CoinSnapshot(s, self._price, Decimal("0")) for s in symbols]


class FakeMarketLLM:
    def __init__(self, snapshot, price, book):
        self._snap, self._price, self._book = snapshot, price, book
    async def get_universe_snapshot(self, symbols): return self._snap
    async def get_price(self, symbol): return self._price
    async def get_book_ticker(self, symbol): return self._book


class FakeMarketHB:
    """Market per l'heartbeat: prezzo unico per ogni simbolo + get_top_symbols + universo."""
    def __init__(self, price, symbols=None):
        self._price, self._symbols = price, symbols or ["BTCUSDT"]
    async def get_price(self, symbol): return self._price
    async def get_top_symbols(self, quote, n): return self._symbols
    async def get_universe_snapshot(self, symbols):
        return [CoinSnapshot(s, self._price, Decimal("0")) for s in symbols]


@pytest.fixture(autouse=True)
def _stub_brief_bootstrap(monkeypatch):
    """v2-only decision path: build_trader_context resolves a brief via get_or_bootstrap_brief,
    which cold-starts the analyst (needs get_top_symbols + a live adapter) when the fresh test DB
    has no brief. These decision-execution tests fake the trader decision and don't exercise the
    brief, so stub the resolver to a no-brief lookup (the trader renders brief-less)."""
    from app.agents import runtime as _runtime
    from app.brain.brief_store import BriefLookup
    from unittest.mock import AsyncMock
    monkeypatch.setattr(_runtime, "get_or_bootstrap_brief",
                        AsyncMock(return_value=BriefLookup(row=None, unavailable_reason=None, has_valid=False)))


def _agent(session, cash="100"):
    a = Agent(name="R", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal(cash), initial_capital_usd=Decimal(cash))
    session.add(a); session.commit()
    return a


def _llm_agent(session):
    a = Agent(name="B", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"),
              model_provider="openrouter", model_name="deepseek/deepseek-v4-flash")
    session.add(a); session.commit()
    return a


def _armed_agent(session, stop="0.10", take="0.20"):
    a = Agent(name="H", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("0"), initial_capital_usd=Decimal("0"), stop_loss=Decimal(stop), take_profit=Decimal(take))
    session.add(a); session.commit()
    return a


async def test_heartbeat_writes_equity_snapshot(db_session):
    agent = _agent(db_session, "100")
    market = FakeMarket(price=Decimal("100"), book=(Decimal("99"), Decimal("101")))
    await run_heartbeat(db_session, agent, market)
    snap = db_session.query(EquitySnapshot).filter_by(agent_id=agent.id).one()
    assert snap.equity_usd == Decimal("100")  # solo cash, nessuna posizione


async def test_heartbeat_equity_and_benchmark_share_timestamp(db_session):
    """Equity e benchmark dello stesso beat devono avere timestamp identico: il grafico
    li fonde per timestamp, se differiscono ogni serie resta a punti isolati e non si disegna."""
    agent = _agent(db_session, "100")
    market = FakeMarketHB(price=Decimal("100"))
    await run_heartbeat(db_session, agent, market)
    equity = db_session.query(EquitySnapshot).filter_by(agent_id=agent.id).one()
    benchmarks = db_session.query(BenchmarkSnapshot).filter_by(agent_id=agent.id).all()
    assert benchmarks, "il beat deve scrivere i benchmark"
    assert all(b.timestamp == equity.timestamp for b in benchmarks)


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
              duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("0"), initial_capital_usd=Decimal("0"))
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
                       brain_decide=lambda ctx, adapter: DecisionResult(decision))
    buys = db_session.query(Trade).filter_by(agent_id=agent.id, side="BUY").all()
    assert len(buys) == 1                            # only the valid $50 buy
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").one()
    assert "testing" in ev.message


async def test_policy_violation_disclosure_does_not_block_valid_buy(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[
        Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("50"),
               rationale="override",
               policy_refs=["P999"], policy_alignment="violates",
               override_reason="fresh catalyst")
    ], note="buy anyway")

    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision))

    assert db_session.query(Trade).filter_by(agent_id=agent.id, side="BUY").count() == 1
    rec = db_session.query(DecisionRecord).filter_by(agent_id=agent.id, kind="decision").one()
    assert '"policy_refs":["P999"]' in rec.parsed_output
    assert '"policy_alignment":"violates"' in rec.parsed_output
    assert '"override_reason":"fresh catalyst"' in rec.parsed_output


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
                       brain_decide=lambda ctx, adapter: DecisionResult(decision))
    buys = db_session.query(Trade).filter_by(agent_id=agent.id, side="BUY").all()
    assert len(buys) == 1                            # the all-in executed
    pos = db_session.query(Position).filter_by(agent_id=agent.id, symbol="BTCUSDT").one()
    assert pos.quantity > 0
    assert agent.cash_usd >= Decimal("0")            # never overspends past cash
    assert agent.cash_usd < Decimal("1")             # spent (almost) all cash
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").one()
    assert "1 operazioni" in ev.message and "0 errori" in ev.message


async def test_llm_data_gathering_error_writes_event_no_trade(db_session):
    """If a market fetch raises while building the trader context, run_decision must not raise,
    must write a decision event recording the error, and must create zero Trade rows."""
    agent = _llm_agent(db_session)
    # held position is load-bearing: assemble_trader_context iterates positions and calls
    # get_price(pos.symbol), so the broken get_price below is what raises (the v2 path
    # doesn't fetch a universe). Without a position, get_price is never reached.
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()

    class FakeMarketLLMBroken:
        async def get_price(self, symbol):
            raise RuntimeError("network timeout")

    market = FakeMarketLLMBroken()
    await run_decision(db_session, agent, market, ["BTCUSDT"])
    trades = db_session.query(Trade).filter_by(agent_id=agent.id).all()
    assert len(trades) == 0
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").one()
    assert "errore" in ev.message
    assert "network timeout" in ev.message
    assert db_session.query(DecisionRecord).filter_by(agent_id=agent.id).count() == 0


async def test_llm_path_sells_held_fraction(db_session):
    agent = _llm_agent(db_session)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("2"))]
    market = FakeMarketLLM(snap, Decimal("120"), (Decimal("120"), Decimal("121")))
    decision = Decision(actions=[Action(type="SELL", symbol="BTCUSDT", fraction=Decimal("0.5"))], note="trim")
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision))
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
                       brain_decide=lambda ctx, adapter: DecisionResult(decision))
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
    def fake_reflect(memory, policy, closed, held_symbols, instructions, adapter):
        calls.append(closed)
        return ReflectionResult(MemoryUpdate(coin_theses=["BTC: took profit"], trade_lessons=["green exit"]))

    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision), reflect=fake_reflect)

    assert len(calls) == 1
    assert calls[0][0].symbol == "BTCUSDT"
    assert calls[0][0].realized_pnl_pct == Decimal("20")
    rows = journal.active_entries(db_session, agent.id, "coin_theses")
    assert [r.content for r in rows] == ["BTC: took profit"]
    assert [r.cycle_id for r in rows] == [rows[0].cycle_id] and rows[0].cycle_id is not None
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="reflection").one()
    assert "memoria" in ev.message.lower()


async def test_reflection_call_is_recorded(db_session):
    agent = _llm_agent(db_session)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("2"))]
    market = FakeMarketLLM(snap, Decimal("120"), (Decimal("120"), Decimal("121")))
    decision = Decision(actions=[Action(type="SELL", symbol="BTCUSDT", fraction=Decimal("1"))], note="exit")
    refl = ReflectionResult(MemoryUpdate(coin_theses=["BTC: booked"]),
                            system="RSYS", user="RUSR", raw='{"coin_theses":["BTC: booked"]}',
                            parse_status="ok", latency_ms=7)
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision),
                       reflect=lambda *a, **k: refl)
    recs = db_session.query(DecisionRecord).filter_by(agent_id=agent.id).all()
    assert sorted(r.kind for r in recs) == ["decision", "reflection"]
    rr = db_session.query(DecisionRecord).filter_by(agent_id=agent.id, kind="reflection").one()
    dd = db_session.query(DecisionRecord).filter_by(agent_id=agent.id, kind="decision").one()
    assert rr.parse_status == "ok" and rr.raw_response == '{"coin_theses":["BTC: booked"]}'
    assert rr.latency_ms == 7 and rr.trigger == "schedule"
    assert rr.system_prompt == "RSYS" and rr.user_prompt == "RUSR"
    assert rr.cycle_id == dd.cycle_id             # decision + reflection share the cycle


async def test_reflection_can_add_self_policy_on_sell(db_session):
    agent = _llm_agent(db_session)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("2"))]
    market = FakeMarketLLM(snap, Decimal("120"), (Decimal("120"), Decimal("121")))
    decision = Decision(actions=[Action(type="SELL", symbol="BTCUSDT", fraction=Decimal("1"))], note="exit")

    def fake_reflect(memory, policy, closed, held_symbols, instructions, adapter):
        return ReflectionResult(MemoryUpdate(policy_edits=[
            PolicyEdit(op="add", text="Wait for fresh evidence before re-entry.", reason="Churn hurt.")
        ]))

    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision),
                       reflect=fake_reflect)

    rows = journal.active_entries(db_session, agent.id, "self_policy")
    assert [r.content for r in rows] == ["Wait for fresh evidence before re-entry."]


async def test_invalid_policy_edit_leaves_reflection_memory_unchanged(db_session):
    agent = _llm_agent(db_session)
    journal.append_entries(db_session, agent.id, "coin_theses", ["BTC: keep"])
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("2"))]
    market = FakeMarketLLM(snap, Decimal("120"), (Decimal("120"), Decimal("121")))
    decision = Decision(actions=[Action(type="SELL", symbol="BTCUSDT", fraction=Decimal("1"))], note="exit")

    def fake_reflect(memory, policy, closed, held_symbols, instructions, adapter):
        return ReflectionResult(MemoryUpdate(
            coin_theses=["BTC: should not apply"],
            policy_edits=[PolicyEdit(op="retire", policy_ref="P999", reason="bad ref")],
        ))

    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision),
                       reflect=fake_reflect)

    assert [r.content for r in journal.active_entries(db_session, agent.id, "coin_theses")] == ["BTC: keep"]
    assert journal.active_entries(db_session, agent.id, "self_policy") == []
    ev = (db_session.query(Event)
          .filter_by(agent_id=agent.id, kind="reflection")
          .order_by(Event.id.desc())
          .first())
    assert "errore" in ev.message.lower() or "invalid" in ev.message.lower()
    rec = db_session.query(DecisionRecord).filter_by(agent_id=agent.id, kind="reflection").one()
    assert rec.parse_status == "failed"
    assert rec.parsed_output is None


async def test_decision_events_share_one_cycle_id(db_session):
    """Every event a single run_decision emits (decision summary, trade)
    must carry the same non-null cycle_id so the frontend can group them."""
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[
        Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("50"), rationale="dip"),
    ], note="in")
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision))
    events = db_session.query(Event).filter_by(agent_id=agent.id).all()
    kinds = {e.kind for e in events}
    assert {"decision", "trade"} <= kinds   # both present
    cycle_ids = {e.cycle_id for e in events}
    assert len(cycle_ids) == 1 and None not in cycle_ids  # exactly one, non-null


async def test_two_cycles_get_distinct_cycle_ids(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[], note="hold")
    for _ in range(2):
        await run_decision(db_session, agent, market, ["BTCUSDT"],
                           brain_decide=lambda ctx, adapter: DecisionResult(decision))
    ids = [e.cycle_id for e in db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").all()]
    assert len(ids) == 2 and ids[0] != ids[1]


async def test_no_reflection_when_no_sell(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("50"))], note="in")
    calls = []
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision),
                       reflect=lambda *a, **k: calls.append(1) or ReflectionResult(MemoryUpdate()))
    assert calls == []
    assert db_session.query(MemoryEntry).filter_by(agent_id=agent.id).count() == 0


async def test_run_decision_passes_wake_reason_and_marks_event(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    captured = {}

    def capture(ctx, adapter):
        captured["wake"] = ctx.wake_reason
        return DecisionResult(Decision(actions=[], note="held"))

    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       wake_reason="BTCUSDT -12% oltre stop", brain_decide=capture)
    assert captured["wake"] == "BTCUSDT -12% oltre stop"
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").one()
    assert "fuori ciclo" in ev.message


async def test_reflection_failure_is_isolated(db_session):
    agent = _llm_agent(db_session)
    journal.append_entries(db_session, agent.id, "coin_theses", ["BTC: keep"])
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("2"))]
    market = FakeMarketLLM(snap, Decimal("120"), (Decimal("120"), Decimal("121")))
    decision = Decision(actions=[Action(type="SELL", symbol="BTCUSDT", fraction=Decimal("1"))], note="exit")

    def boom(*a, **k):
        raise RuntimeError("provider down")

    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision), reflect=boom)

    # existing memory untouched
    rows = journal.active_entries(db_session, agent.id, "coin_theses")
    assert [r.content for r in rows] == ["BTC: keep"]
    # error logged as a reflection event, loop did not crash (the SELL still executed)
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="reflection").one()
    assert "errore" in ev.message and "provider down" in ev.message
    assert db_session.query(Trade).filter_by(agent_id=agent.id, side="SELL").count() == 1


async def test_guarded_runs_when_free(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    ran = await run_decision_guarded(db_session, agent, market, ["BTCUSDT"],
                                     brain_decide=lambda ctx, adapter: DecisionResult(Decision(actions=[], note="ok")))
    assert ran is True


async def test_guarded_skips_when_locked(db_session):
    from app.agents.runtime import _agent_lock
    agent = _llm_agent(db_session)
    market = FakeMarketLLM([], Decimal("100"), (Decimal("99"), Decimal("101")))
    lock = _agent_lock(agent.id)
    await lock.acquire()
    try:
        ran = await run_decision_guarded(db_session, agent, market, ["BTCUSDT"],
                                         brain_decide=lambda ctx, adapter: DecisionResult(Decision(actions=[], note="x")))
        assert ran is False
    finally:
        lock.release()


async def test_run_decision_writes_decision_record(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    result = DecisionResult(Decision(actions=[], note="hold"),
                            system="SYS", user="USR", raw='{"actions":[],"note":"hold"}',
                            parse_status="ok", latency_ms=42)
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: result)
    rec = db_session.query(DecisionRecord).filter_by(agent_id=agent.id).one()
    assert rec.kind == "decision" and rec.trigger == "schedule"
    assert rec.parse_status == "ok"
    assert rec.raw_response == '{"actions":[],"note":"hold"}'
    assert rec.system_prompt == "SYS" and rec.user_prompt == "USR"
    assert rec.model_provider == "openrouter"
    assert rec.model_name == "deepseek/deepseek-v4-flash"
    assert rec.latency_ms == 42
    assert rec.cycle_id is not None
    assert '"note":"hold"' in rec.parsed_output      # parsed Decision serialized


async def test_decision_record_trigger_is_breach_on_wake(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       wake_reason="BTCUSDT -12% oltre stop",
                       brain_decide=lambda ctx, adapter: DecisionResult(Decision(actions=[], note="held")))
    rec = db_session.query(DecisionRecord).filter_by(agent_id=agent.id).one()
    assert rec.trigger == "breach"


async def test_decision_record_shares_cycle_id_with_events(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[Action(type="BUY", symbol="BTCUSDT",
                                        usd_amount=Decimal("50"), rationale="dip")], note="in")
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision))
    rec = db_session.query(DecisionRecord).filter_by(agent_id=agent.id).one()
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").one()
    assert rec.cycle_id == ev.cycle_id and rec.cycle_id is not None


def test_universe_size_maps_universe_field():
    class A: universe = "TOP_100"
    class B: universe = "TOP_50"
    assert universe_size(A()) == 100
    assert universe_size(B()) == 50


async def test_heartbeat_writes_benchmark_snapshots_and_basis(db_session):
    agent = _agent(db_session, "100")
    market = FakeMarketHB(price=Decimal("100"), symbols=["BTCUSDT", "ETHUSDT"])
    await run_heartbeat(db_session, agent, market)
    basis = db_session.query(BenchmarkBasis).filter_by(agent_id=agent.id).one()
    assert basis.initial_capital == Decimal("100")
    kinds = sorted(r.kind for r in
                   db_session.query(BenchmarkSnapshot).filter_by(agent_id=agent.id).all())
    assert kinds == ["equal_weight", "hodl_btc", "random_p10", "random_p50", "random_p90"]
    # at the first heartbeat every benchmark equals the initial capital (start == now prices)
    for r in db_session.query(BenchmarkSnapshot).filter_by(agent_id=agent.id).all():
        assert r.equity_usd == Decimal("100")


async def test_benchmark_snapshots_of_one_beat_share_timestamp(db_session):
    agent = _agent(db_session, "100")
    await run_heartbeat(db_session, agent, FakeMarketHB(price=Decimal("100")))
    rows = db_session.query(BenchmarkSnapshot).filter_by(agent_id=agent.id).all()
    assert len(rows) == 5
    assert len({r.timestamp for r in rows}) == 1     # one beat → one shared timestamp


async def test_heartbeat_basis_frozen_across_beats(db_session):
    agent = _agent(db_session, "100")
    await run_heartbeat(db_session, agent, FakeMarketHB(price=Decimal("100")))   # freezes basis at 100
    await run_heartbeat(db_session, agent, FakeMarketHB(price=Decimal("200")))   # BTC doubled
    assert db_session.query(BenchmarkBasis).filter_by(agent_id=agent.id).count() == 1   # frozen once
    hodl = (db_session.query(BenchmarkSnapshot)
            .filter_by(agent_id=agent.id, kind="hodl_btc")
            .order_by(BenchmarkSnapshot.id.desc()).first())
    assert hodl.equity_usd == Decimal("200")     # 100 * 200/100


async def test_heartbeat_benchmark_failure_does_not_break_equity(db_session):
    agent = _agent(db_session, "100")

    class BrokenUniverse:
        async def get_price(self, symbol): return Decimal("100")
        async def get_top_symbols(self, quote, n): return ["BTCUSDT"]
        async def get_universe_snapshot(self, symbols): raise RuntimeError("ticker down")

    await run_heartbeat(db_session, agent, BrokenUniverse())
    # equity snapshot still written, benchmark rows absent, no exception bubbled up
    assert db_session.query(EquitySnapshot).filter_by(agent_id=agent.id).one().equity_usd == Decimal("100")
    assert db_session.query(BenchmarkSnapshot).filter_by(agent_id=agent.id).count() == 0


async def test_heartbeat_breach_still_triggers_when_benchmark_fails(db_session):
    """Benchmark recording rolls back on a broken market (expiring ORM state); the
    breach logic that follows must still fire and disarm the position."""
    agent = _armed_agent(db_session)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()

    class BreachMarketBrokenBench:
        async def get_price(self, symbol): return Decimal("85")          # -15% → stop breach
        async def get_top_symbols(self, quote, n): return ["BTCUSDT"]
        async def get_universe_snapshot(self, symbols): raise RuntimeError("ticker down")

    calls = []
    async def fake_trigger(session, agent, market, symbols, *, wake_reason=None):
        calls.append(wake_reason); return True

    await run_heartbeat(db_session, agent, BreachMarketBrokenBench(), trigger_decision=fake_trigger)
    assert len(calls) == 1 and "stop" in calls[0]        # breach fired despite benchmark failure
    pos = db_session.query(Position).filter_by(agent_id=agent.id).one()
    assert pos.breach_armed is False                     # disarmed after trigger
    assert db_session.query(EquitySnapshot).filter_by(agent_id=agent.id).count() == 1
    assert db_session.query(BenchmarkSnapshot).filter_by(agent_id=agent.id).count() == 0


async def test_heartbeat_second_beat_benchmark_failure_keeps_basis(db_session):
    """A later beat whose benchmark valuation fails rolls back only that beat's work;
    the basis frozen on the first beat stays intact."""
    agent = _agent(db_session, "100")
    await run_heartbeat(db_session, agent, FakeMarketHB(price=Decimal("100")))   # beat 1 freezes basis
    assert db_session.query(BenchmarkBasis).filter_by(agent_id=agent.id).count() == 1
    snaps_before = db_session.query(BenchmarkSnapshot).filter_by(agent_id=agent.id).count()

    class BrokenSecondBeat:
        async def get_price(self, symbol): return Decimal("100")
        async def get_top_symbols(self, quote, n): return ["BTCUSDT"]
        async def get_universe_snapshot(self, symbols): raise RuntimeError("ticker down")

    await run_heartbeat(db_session, agent, BrokenSecondBeat())                   # beat 2 benchmark fails
    assert db_session.query(BenchmarkBasis).filter_by(agent_id=agent.id).count() == 1          # basis intact
    assert db_session.query(BenchmarkSnapshot).filter_by(agent_id=agent.id).count() == snaps_before


def _sell_setup(db_session):
    """An agent holding BTCUSDT with a FakeMarketLLM that sells it (→ triggers reflection)."""
    agent = _llm_agent(db_session)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("2"))]
    market = FakeMarketLLM(snap, Decimal("120"), (Decimal("120"), Decimal("121")))
    decision = Decision(actions=[Action(type="SELL", symbol="BTCUSDT", fraction=Decimal("1"))], note="exit")
    return agent, market, decision


async def test_distillation_runs_when_section_over_cap(db_session):
    agent, market, decision = _sell_setup(db_session)
    cap = journal.SECTION_CAPS["strategy_notes"]                 # 5
    journal.append_entries(db_session, agent.id, "strategy_notes", [f"note{i}" for i in range(cap)])
    db_session.commit()

    # reflection adds one strategy note → 6 active > cap 5 → distillation fires for that section
    def fake_reflect(*a, **k):
        return ReflectionResult(MemoryUpdate(strategy_notes=["note-new"]))
    seen = {}
    def fake_distill(section, entries, cap_, instructions, adapter):
        seen[section] = list(entries)
        return DistillationResult(["merged"], parse_status="ok")

    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision),
                       reflect=fake_reflect, distill=fake_distill)

    assert "strategy_notes" in seen and len(seen["strategy_notes"]) == 6      # saw all active before compaction
    active = journal.active_entries(db_session, agent.id, "strategy_notes")
    assert [r.content for r in active] == ["merged"]                          # compacted set is now active
    assert db_session.query(MemoryEntry).filter_by(agent_id=agent.id, section="strategy_notes",
                                                   active=False).count() == 6  # old ones superseded, kept
    rec = db_session.query(DecisionRecord).filter_by(agent_id=agent.id, kind="distillation").one()
    assert rec.parse_status == "ok" and rec.cycle_id is not None
    ev = [e for e in db_session.query(Event).filter_by(agent_id=agent.id, kind="reflection").all()
          if "distillata" in e.message]
    assert len(ev) == 1 and "strategy_notes" in ev[0].message


async def test_distillation_skipped_when_under_cap(db_session):
    agent, market, decision = _sell_setup(db_session)
    def fake_reflect(*a, **k):
        return ReflectionResult(MemoryUpdate(strategy_notes=["just one"]))
    calls = []
    def fake_distill(*a, **k):
        calls.append(1); return DistillationResult(["x"], parse_status="ok")
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision),
                       reflect=fake_reflect, distill=fake_distill)
    assert calls == []                                                        # 1 entry, never over cap
    assert db_session.query(DecisionRecord).filter_by(agent_id=agent.id, kind="distillation").count() == 0


async def test_distillation_failure_leaves_entries_and_records_failed(db_session):
    agent, market, decision = _sell_setup(db_session)
    cap = journal.SECTION_CAPS["strategy_notes"]
    journal.append_entries(db_session, agent.id, "strategy_notes", [f"note{i}" for i in range(cap)])
    db_session.commit()
    def fake_reflect(*a, **k):
        return ReflectionResult(MemoryUpdate(strategy_notes=["note-new"]))
    def boom_distill(section, entries, cap_, instructions, adapter):
        return DistillationResult(list(entries), parse_status="failed")       # keep originals
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision),
                       reflect=fake_reflect, distill=boom_distill)
    active = journal.active_entries(db_session, agent.id, "strategy_notes")
    assert len(active) == cap + 1                                             # nothing superseded on failure
    rec = db_session.query(DecisionRecord).filter_by(agent_id=agent.id, kind="distillation").one()
    assert rec.parse_status == "failed" and rec.parsed_output is None


async def test_run_decision_explicit_trigger_wins(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    await run_decision(db_session, agent, market, ["BTCUSDT"], wake_reason="x moved 6%",
                       trigger="movement",
                       brain_decide=lambda ctx, adapter: DecisionResult(Decision(actions=[], note="h")))
    rec = db_session.query(DecisionRecord).filter_by(agent_id=agent.id).one()
    assert rec.trigger == "movement"


async def test_run_decision_guarded_forwards_trigger(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    ran = await run_decision_guarded(db_session, agent, market, ["BTCUSDT"], wake_reason="n",
                                     trigger="news",
                                     brain_decide=lambda ctx, adapter: DecisionResult(Decision(actions=[], note="h")))
    assert ran is True
    rec = db_session.query(DecisionRecord).filter_by(agent_id=agent.id).one()
    assert rec.trigger == "news"


class FakeMarketMove:
    """Heartbeat market with klines: price flat for equity, klines drive the 1h move."""
    def __init__(self, price, closes, symbols=None):
        self._price, self._closes, self._symbols = price, closes, symbols or ["BTCUSDT"]
    async def get_price(self, symbol): return self._price
    async def get_top_symbols(self, quote, n): return self._symbols
    async def get_universe_snapshot(self, symbols):
        return [CoinSnapshot(s, self._price, Decimal("0")) for s in symbols]
    async def get_klines(self, symbol, interval, limit):
        return list(self._closes)                       # [old, ..., now]


def _move_agent(db_session):
    """Agent with thresholds disabled (no breach) holding BTCUSDT."""
    a = Agent(name="M", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("0"), initial_capital_usd=Decimal("0"))
    db_session.add(a); db_session.commit()
    db_session.add(Position(agent_id=a.id, symbol="BTCUSDT", quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    return a


async def test_movement_fresh_triggers_and_disarms(db_session):
    agent = _move_agent(db_session)
    market = FakeMarketMove(price=Decimal("100"), closes=[Decimal("100"), Decimal("107")])  # +7%
    calls = []
    async def fake_trigger(session, agent, market, symbols, *, wake_reason=None, trigger=None):
        calls.append((wake_reason, trigger)); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert len(calls) == 1 and calls[0][1] == "movement" and "BTCUSDT" in calls[0][0]
    pos = db_session.query(Position).filter_by(agent_id=agent.id).one()
    assert pos.move_armed is False
    assert db_session.query(Trade).filter_by(agent_id=agent.id).count() == 0


async def test_movement_within_band_does_not_trigger(db_session):
    agent = _move_agent(db_session)
    market = FakeMarketMove(price=Decimal("100"), closes=[Decimal("100"), Decimal("103")])  # +3% < 5%
    calls = []
    async def fake_trigger(*a, **k): calls.append(1); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert calls == []


async def test_movement_disarmed_does_not_retrigger_then_rearms(db_session):
    agent = _move_agent(db_session)
    pos = db_session.query(Position).filter_by(agent_id=agent.id).one()
    pos.move_armed = False; db_session.commit()
    spiking = FakeMarketMove(price=Decimal("100"), closes=[Decimal("100"), Decimal("107")])  # still +7%
    async def fake_trigger(*a, **k): return True
    await run_heartbeat(db_session, agent, spiking, trigger_decision=fake_trigger)
    db_session.refresh(pos); assert pos.move_armed is False            # stays disarmed while spiking
    calm = FakeMarketMove(price=Decimal("100"), closes=[Decimal("100"), Decimal("101")])     # +1%
    await run_heartbeat(db_session, agent, calm, trigger_decision=fake_trigger)
    db_session.refresh(pos); assert pos.move_armed is True             # re-armed when back in band


async def test_breach_takes_priority_over_movement(db_session):
    agent = _armed_agent(db_session)                                   # stop 0.10 / take 0.20
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT", quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    market = FakeMarketMove(price=Decimal("85"), closes=[Decimal("100"), Decimal("85")])  # -15%: breach AND move
    calls = []
    async def fake_trigger(session, agent, market, symbols, *, wake_reason=None, trigger=None):
        calls.append((wake_reason, trigger)); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert len(calls) == 1 and calls[0][1] is None and "stop" in calls[0][0]   # breach path (no trigger kwarg)
    pos = db_session.query(Position).filter_by(agent_id=agent.id).one()
    assert pos.breach_armed is False and pos.move_armed is False        # both disarmed by the one review


async def test_movement_suppressed_when_budget_exhausted(db_session):
    from app.db.models import DecisionRecord
    agent = _move_agent(db_session)
    for _ in range(2):                                                  # 2 recent movement wakes = budget
        r = DecisionRecord(agent_id=agent.id, cycle_id="c", kind="decision", trigger="movement",
                           system_prompt="s", user_prompt="u", raw_response="r", parsed_output="{}",
                           parse_status="ok", model_provider="openrouter", model_name="m", latency_ms=1)
        db_session.add(r)
    db_session.commit()
    market = FakeMarketMove(price=Decimal("100"), closes=[Decimal("100"), Decimal("108")])  # +8%
    calls = []
    async def fake_trigger(*a, **k): calls.append(1); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert calls == []                                                  # deferred
    pos = db_session.query(Position).filter_by(agent_id=agent.id).one()
    assert pos.move_armed is True                                       # NOT disarmed → retries next beat


async def test_movement_klines_error_isolated(db_session):
    """A market without get_klines (or one that raises) must not break the beat; movement skipped."""
    agent = _move_agent(db_session)
    market = FakeMarketHB(price=Decimal("100"))                         # has no get_klines
    calls = []
    async def fake_trigger(*a, **k): calls.append(1); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert calls == []
    assert db_session.query(EquitySnapshot).filter_by(agent_id=agent.id).count() == 1  # beat completed


def _news_agent_holding_btc(db_session):
    import json as _json
    from app.db.models import Observation
    a = Agent(name="N", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("0"), initial_capital_usd=Decimal("0"))
    db_session.add(a); db_session.commit()
    db_session.add(Position(agent_id=a.id, symbol="BTCUSDT", quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.add(Observation(source="CoinDesk", kind="news", title="Bitcoin ETF approved", url="u1",
                               symbols_json=_json.dumps(["BTC"]), dedup_hash="u1",
                               published_at=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc)))
    db_session.commit()
    return a


async def test_news_fresh_triggers_news_wake(db_session):
    agent = _news_agent_holding_btc(db_session)
    market = FakeMarketMove(price=Decimal("100"), closes=[Decimal("100"), Decimal("101")])  # calm price
    calls = []
    async def fake_trigger(session, agent, market, symbols, *, wake_reason=None, trigger=None):
        calls.append((wake_reason, trigger)); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert len(calls) == 1 and calls[0][1] == "news" and "Bitcoin ETF approved" in calls[0][0]


async def test_news_suppressed_when_budget_exhausted(db_session):
    from app.db.models import DecisionRecord
    agent = _news_agent_holding_btc(db_session)
    for _ in range(2):
        db_session.add(DecisionRecord(agent_id=agent.id, cycle_id="c", kind="decision", trigger="news",
                       system_prompt="s", user_prompt="u", raw_response="r", parsed_output="{}",
                       parse_status="ok", model_provider="openrouter", model_name="m", latency_ms=1))
    db_session.commit()
    market = FakeMarketMove(price=Decimal("100"), closes=[Decimal("100"), Decimal("101")])
    calls = []
    async def fake_trigger(*a, **k): calls.append(1); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert calls == []                                             # deferred; watermark untouched


async def test_movement_takes_priority_over_news(db_session):
    agent = _news_agent_holding_btc(db_session)                    # holds BTC + has fresh BTC news
    market = FakeMarketMove(price=Decimal("100"), closes=[Decimal("100"), Decimal("108")])  # +8% move too
    calls = []
    async def fake_trigger(session, agent, market, symbols, *, wake_reason=None, trigger=None):
        calls.append(trigger); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert calls == ["movement"]                                   # movement chosen over news


async def test_news_wake_advances_watermark_to_triggering_obs_not_global_max(db_session):
    import json as _json
    from app.db.models import Observation
    agent = _news_agent_holding_btc(db_session)          # holds BTC + one BTC obs (id 1)
    o2 = Observation(source="CoinDesk", kind="news", title="Bitcoin hits high", url="u2",
                     symbols_json=_json.dumps(["BTC"]), dedup_hash="u2",
                     published_at=datetime(2026, 7, 3, 11, 0, tzinfo=timezone.utc))
    o3 = Observation(source="CoinDesk", kind="news", title="Ethereum news", url="u3",
                     symbols_json=_json.dumps(["ETH"]), dedup_hash="u3",   # NOT held, newer → must be skipped
                     published_at=datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc))
    db_session.add_all([o2, o3]); db_session.commit()
    market = FakeMarketMove(price=Decimal("100"), closes=[Decimal("100"), Decimal("101")])  # calm → news only
    async def fake_trigger(session, agent, market, symbols, *, wake_reason=None, trigger=None):
        return True                                       # simulate the decision ran
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert agent.last_seen_observation_id == o2.id        # advanced to the triggering HELD obs...
    assert agent.last_seen_observation_id != o3.id        # ...NOT the global max (unheld ETH), which is the fix


async def test_breach_wake_does_not_advance_news_watermark(db_session):
    import json as _json
    from app.db.models import Observation
    agent = _armed_agent(db_session)                     # stop/take set, cash 0
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT", quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.add(Observation(source="CoinDesk", kind="news", title="BTC news", url="ux",
                               symbols_json=_json.dumps(["BTC"]), dedup_hash="ux",
                               published_at=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc)))
    db_session.commit()
    market = FakeMarketMove(price=Decimal("85"), closes=[Decimal("100"), Decimal("85")])  # -15% → breach fires (priority)
    async def fake_trigger(session, agent, market, symbols, *, wake_reason=None, trigger=None):
        return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert agent.last_seen_observation_id is None         # a breach wake must NOT advance the news bookmark


# --- payload strutturati su decision/reflection (spec 2026-07-09) ---

async def test_decision_event_payload_records_skip_reasons(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[
        Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("50"), rationale="ok buy"),
        Action(type="BUY", symbol="DOGEUSDT", usd_amount=Decimal("50"), rationale="x"),   # fuori universo
        Action(type="SELL", symbol="ETHUSDT", rationale="x"),                              # mai posseduta
    ], note="testing skips")
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision))
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").one()
    p = ev.payload
    assert p["status"] == "ok" and p["note"] == "testing skips"
    assert p["executed"] == 1 and p["errors"] == 0
    assert p["skipped_count"] == 2
    reasons = {(s["type"], s["symbol"]): s["reason"] for s in p["skipped"]}
    assert reasons[("BUY", "DOGEUSDT")] == "coin fuori universo"
    assert reasons[("SELL", "ETHUSDT")] == "posizione inesistente"


async def test_trade_rationale_lives_in_trade_payload_no_reasoning_events(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[
        Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("50"), rationale="momentum play"),
    ], note="buy")
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision))
    trade_ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="trade").one()
    assert trade_ev.payload["rationale"] == "momentum play"
    assert db_session.query(Event).filter_by(agent_id=agent.id, kind="reasoning").count() == 0


async def test_decision_error_event_payload(db_session, monkeypatch):
    agent = _llm_agent(db_session)
    market = FakeMarketLLM([], Decimal("100"), (Decimal("99"), Decimal("101")))
    def boom(ctx, adapter): raise RuntimeError("LLM timeout")
    await run_decision(db_session, agent, market, ["BTCUSDT"], brain_decide=boom)
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").one()
    assert ev.payload["status"] == "error"
    assert "LLM timeout" in ev.payload["detail"]
