import pytest
from decimal import Decimal
from app.brain.context import CoinSnapshot
from app.brain.analyst_schema import MarketBriefSchema, Highlight, AnalystResult
from app.agents.runtime import run_analyst_cycle, get_or_bootstrap_brief
from app.brain.brief_store import latest_valid_brief

pytestmark = pytest.mark.asyncio


class _Market:
    def __init__(self): self.top_calls = 0
    async def get_top_symbols(self, quote, n): self.top_calls += 1; return ["BTCUSDT", "ETHUSDT"]
    async def get_universe_snapshot(self, symbols):
        return [CoinSnapshot(s, Decimal("100"), Decimal("1")) for s in symbols]


def _fake_run(status="ok"):
    def run(ctx, adapter):
        brief = MarketBriefSchema(regime="risk-on",
                                  highlights=[Highlight(symbol="BTCUSDT", signal="bullish")])
        return AnalystResult(brief, "s", "u", "{}", status, 5)
    return run


async def test_run_analyst_cycle_persists_and_returns_row(db_session):
    row = await run_analyst_cycle(db_session, _Market(), run=_fake_run(), adapter=object())
    assert row is not None and "risk-on" in row.parsed_brief
    assert latest_valid_brief(db_session) is not None


async def test_run_analyst_cycle_failed_persists_but_returns_none(db_session):
    row = await run_analyst_cycle(db_session, _Market(), run=_fake_run("failed"), adapter=object())
    assert row is None                                   # unusable → caller must not use it
    assert latest_valid_brief(db_session) is None        # audit row exists but has NULL payload


async def test_get_or_bootstrap_reuses_existing(db_session):
    await run_analyst_cycle(db_session, _Market(), run=_fake_run(), adapter=object())
    calls = {"n": 0}
    async def _cycle(session, market): calls["n"] += 1; return None
    row = await get_or_bootstrap_brief(db_session, _Market(), run_cycle=_cycle)
    assert row is not None and calls["n"] == 0           # reused, no bootstrap


async def test_get_or_bootstrap_runs_cycle_when_empty(db_session):
    calls = {"n": 0}
    async def _cycle(session, market):
        calls["n"] += 1
        return await run_analyst_cycle(session, market, run=_fake_run(), adapter=object())
    row = await get_or_bootstrap_brief(db_session, _Market(), run_cycle=_cycle)
    assert row is not None and calls["n"] == 1


from datetime import datetime, timezone, timedelta
from app.db.models import Agent, Position
from app.agents.runtime import build_trader_context, run_analyst_cycle


def _agent(session):
    a = Agent(name="T", cash_usd=Decimal("100"),
              duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1))
    session.add(a); session.commit()
    return a


class _MarketPx(_Market):
    async def get_price(self, symbol): return Decimal("120")


async def test_trader_context_has_filtered_brief(db_session):
    await run_analyst_cycle(db_session, _Market(), run=_fake_run(), adapter=object())  # BTCUSDT highlight
    agent = _agent(db_session)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    ctx = await build_trader_context(db_session, agent, _MarketPx(), ["BTCUSDT", "ETHUSDT"])
    assert ctx.brief is not None and ctx.brief.regime == "risk-on"
    assert [h.symbol for h in ctx.brief.highlights] == ["BTCUSDT"]
    assert ctx.positions[0].last_price == Decimal("120")      # live-priced holding
