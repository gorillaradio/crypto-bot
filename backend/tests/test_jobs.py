from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import app.scheduler.jobs as jobs
from app.db.models import Agent


def _agent(session, name, universe):
    now = datetime.now(timezone.utc)
    a = Agent(name=name, duration_start=now, duration_end=now + timedelta(days=7),
              cash_usd=Decimal("100"), universe=universe, status="running")
    session.add(a)
    session.commit()
    return a


async def test_decision_tick_uses_per_agent_universe(db_session, monkeypatch):
    _agent(db_session, "small", "TOP_50")
    _agent(db_session, "big", "TOP_100")

    fetched: dict[int, int] = {}
    passed: dict[str, list[str]] = {}

    class FakeMarket:
        async def get_top_symbols(self, quote="USDT", n=100):
            fetched[n] = fetched.get(n, 0) + 1
            return [f"SYM{n}"]

    async def fake_run_decision_guarded(session, agent, market, symbols, **kw):
        passed[agent.name] = symbols

    @contextmanager
    def fake_get_session():
        yield db_session

    monkeypatch.setattr(jobs, "BinanceClient", lambda: FakeMarket())
    monkeypatch.setattr(jobs, "run_decision_guarded", fake_run_decision_guarded)
    monkeypatch.setattr(jobs, "get_session", fake_get_session)

    await jobs._decision_tick()

    assert passed["small"] == ["SYM50"]
    assert passed["big"] == ["SYM100"]
    assert fetched == {50: 1, 100: 1}  # one fetch per distinct size, not per agent
