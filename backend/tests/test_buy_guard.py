import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.db.models import Agent, DecisionRecord
from app.brain.schema import Decision, Action, DecisionResult
from app.brain.context import build_context
from app.agents import runtime
from app.agents.runtime import run_decision

pytestmark = pytest.mark.asyncio


def _agent(session):
    a = Agent(name="T", cash_usd=Decimal("1000"),
              model_name="deepseek/deepseek-v4-flash",
              duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1))
    session.add(a); session.commit()
    return a


class _MarketPx:
    async def get_price(self, symbol): return Decimal("100")
    async def get_book_ticker(self, symbol): return (Decimal("100"), Decimal("100"))


async def test_guard_uses_symbols_when_universe_empty(db_session, monkeypatch):
    """v2 ctx has an empty universe; the BUY guard must accept in-symbols and reject out-of-symbols."""
    agent = _agent(db_session)

    async def _fake_ctx(session, ag, market, symbols, *, wake_reason=None):
        return build_context(instructions="", cash_usd=ag.cash_usd, holdings=[], universe=[],
                             recent_events=[], brief=None, wake_reason=wake_reason)
    monkeypatch.setattr(runtime, "build_trader_context", _fake_ctx)

    def _brain(ctx, adapter):
        return DecisionResult(Decision(actions=[
            Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("10"), rationale="in"),
            Action(type="BUY", symbol="FAKEUSDT", usd_amount=Decimal("10"), rationale="out"),
        ], note="n"), "s", "u", "{}", "ok", 1)

    await run_decision(db_session, agent, _MarketPx(), ["BTCUSDT", "ETHUSDT"], brain_decide=_brain)
    rec = db_session.query(DecisionRecord).filter_by(kind="decision").first()
    assert rec is not None
    assert "1 operazioni" in db_session.query(runtime.Event).filter_by(kind="decision").first().message
    # BTCUSDT bought (in symbols), FAKEUSDT skipped (out of symbols)
    assert any(p.symbol == "BTCUSDT" for p in agent.positions)
    assert not any(p.symbol == "FAKEUSDT" for p in agent.positions)
