import logging
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.core.config import settings
from app.db.base import get_session
from app.db.models import Agent
from app.market.binance import BinanceClient
from app.agents.runtime import (run_heartbeat, run_decision_guarded, universe_size,
                                 run_analyst_cycle)
from app.agents.learning import reflect_unlearned_scores
from app.eval.scoring_job import score_matured_decisions
from app.feeds.rss import RssFeedAdapter
from app.feeds.ingest import ingest_observations

_scheduler: AsyncIOScheduler | None = None
logger = logging.getLogger(__name__)


async def _heartbeat_tick():
    market = BinanceClient()
    with get_session() as session:
        for agent in session.query(Agent).filter_by(status="running").all():
            try:
                await run_heartbeat(session, agent, market)
            except Exception as exc:
                logger.error("heartbeat tick failed for agent %s: %s", agent.id, exc)
                session.rollback()


async def _decision_tick():
    market = BinanceClient()
    symbols_cache: dict[int, list[str]] = {}
    with get_session() as session:
        agents = session.query(Agent).filter_by(status="running").all()
        if agents:
            try:
                await run_analyst_cycle(session, market)
            except Exception as exc:
                logger.error("analyst cycle failed: %s", exc)
                session.rollback()
        for agent in agents:
            try:
                n = universe_size(agent)
                if n not in symbols_cache:
                    symbols_cache[n] = await market.get_top_symbols("USDT", n)
                await run_decision_guarded(session, agent, market, symbols_cache[n])
            except Exception as exc:
                logger.error("decision tick failed for agent %s: %s", agent.id, exc)
                session.rollback()


async def _scoring_tick():
    market = BinanceClient()
    now = datetime.now(timezone.utc)
    with get_session() as session:
        try:
            await score_matured_decisions(session, market, now)
        except Exception as exc:
            logger.error("scoring tick failed: %s", exc)
            session.rollback()


async def _learning_tick():
    with get_session() as session:
        try:
            await reflect_unlearned_scores(session)
        except Exception as exc:
            logger.error("learning tick failed: %s", exc)
            session.rollback()


async def _news_poll_tick():
    adapter = RssFeedAdapter()
    with get_session() as session:
        try:
            await ingest_observations(session, adapter)
        except Exception as exc:
            logger.error("news poll tick failed: %s", exc)
            session.rollback()


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(_heartbeat_tick, "interval", seconds=settings.heartbeat_seconds)
    _scheduler.add_job(_decision_tick, "interval", seconds=settings.decision_seconds)
    _scheduler.add_job(_scoring_tick, "interval", seconds=settings.scoring_seconds)
    _scheduler.add_job(_learning_tick, "interval", seconds=settings.scoring_seconds)
    _scheduler.add_job(_news_poll_tick, "interval", seconds=settings.news_poll_seconds)
    _scheduler.start()
    return _scheduler
