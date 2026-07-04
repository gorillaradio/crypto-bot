from datetime import datetime, timezone, timedelta
from decimal import Decimal
import app.scheduler.jobs as jobs
from app.db.models import Agent, DecisionRecord, DecisionScore


def _running_agent(session):
    a = Agent(name="Run", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("100"), status="running")
    session.add(a); session.commit()
    return a


async def test_scoring_tick_scores_matured_decisions(db_session, monkeypatch):
    agent = _running_agent(db_session)
    rec = DecisionRecord(agent_id=agent.id, cycle_id="c", kind="decision", trigger="schedule",
                         system_prompt="s", user_prompt="u", raw_response="r",
                         parsed_output='{"actions":[{"type":"BUY","symbol":"BTCUSDT"}]}',
                         parse_status="ok", model_provider="openrouter", model_name="m", latency_ms=1)
    rec.created_at = datetime.now(timezone.utc) - timedelta(days=8)
    db_session.add(rec); db_session.commit()

    # session factory used by the tick → our in-memory session
    monkeypatch.setattr(jobs, "get_session", lambda: _CtxSession(db_session))

    class FakeMarket:
        async def get_price_at(self, symbol, ms): return Decimal("100")
    monkeypatch.setattr(jobs, "BinanceClient", lambda: FakeMarket())

    await jobs._scoring_tick()
    assert db_session.query(DecisionScore).filter_by(decision_record_id=rec.id).count() == 2


class _CtxSession:
    """Minimal context-manager wrapper so `with get_session() as s:` yields our test session."""
    def __init__(self, s): self._s = s
    def __enter__(self): return self._s
    def __exit__(self, *a): return False


async def test_news_poll_tick_ingests_observations(db_session, monkeypatch):
    from app.db.models import Observation
    from app.feeds.rss import FeedItem

    class FakeAdapter:
        async def fetch(self):
            return [FeedItem(source="CoinDesk", title="Bitcoin rallies", url="https://n/1",
                             summary="", published_at=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc))]

    monkeypatch.setattr(jobs, "get_session", lambda: _CtxSession(db_session))
    monkeypatch.setattr(jobs, "RssFeedAdapter", lambda: FakeAdapter())

    await jobs._news_poll_tick()
    obs = db_session.query(Observation).one()
    assert obs.title == "Bitcoin rallies" and obs.source == "CoinDesk"


async def test_news_poll_tick_survives_ingest_error(db_session, monkeypatch):
    from app.db.models import Observation

    class BrokenAdapter:
        async def fetch(self): raise RuntimeError("feeds down")

    monkeypatch.setattr(jobs, "get_session", lambda: _CtxSession(db_session))
    monkeypatch.setattr(jobs, "RssFeedAdapter", lambda: BrokenAdapter())

    await jobs._news_poll_tick()                       # must NOT raise
    assert db_session.query(Observation).count() == 0
