import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
from app.db.models import Agent
from app.scheduler import jobs

pytestmark = pytest.mark.asyncio


def _agent(session, brain_version):
    a = Agent(name="T", brain_version=brain_version, status="running", cash_usd=Decimal("100"),
              model_name="m", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1))
    session.add(a); session.commit()
    return a


class _FakeMarket:
    """Stands in for BinanceClient() in the per-agent loop path."""
    def __init__(self):
        self.get_top_symbols = AsyncMock(return_value=["BTCUSDT"])


async def test_analyst_runs_once_when_v2_present(db_session, monkeypatch):
    _agent(db_session, "v1"); _agent(db_session, "v2")
    monkeypatch.setattr(jobs, "get_session", lambda: _ctxmgr(db_session))
    monkeypatch.setattr(jobs, "BinanceClient", lambda: _FakeMarket())
    monkeypatch.setattr(jobs, "run_decision_guarded", AsyncMock(return_value=True))
    monkeypatch.setattr(jobs, "universe_size", lambda a: 100)
    cycle = AsyncMock(return_value=None)
    monkeypatch.setattr(jobs, "run_analyst_cycle", cycle)
    await jobs._decision_tick()
    cycle.assert_awaited_once()


async def test_analyst_skipped_when_all_v1(db_session, monkeypatch):
    _agent(db_session, "v1")
    monkeypatch.setattr(jobs, "get_session", lambda: _ctxmgr(db_session))
    monkeypatch.setattr(jobs, "BinanceClient", lambda: _FakeMarket())
    monkeypatch.setattr(jobs, "run_decision_guarded", AsyncMock(return_value=True))
    monkeypatch.setattr(jobs, "universe_size", lambda a: 100)
    cycle = AsyncMock(return_value=None)
    monkeypatch.setattr(jobs, "run_analyst_cycle", cycle)
    await jobs._decision_tick()
    cycle.assert_not_awaited()


class _ctxmgr:
    def __init__(self, s): self.s = s
    def __enter__(self): return self.s
    def __exit__(self, *a): return False
