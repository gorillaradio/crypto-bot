from decimal import Decimal
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.core.config import settings
from app.db.base import get_session
from app.db.models import Agent
from app.market.binance import BinanceClient
from app.agents.runtime import run_heartbeat, run_decision

_scheduler: AsyncIOScheduler | None = None


async def _heartbeat_tick():
    market = BinanceClient()
    with get_session() as session:
        for agent in session.query(Agent).filter_by(status="running").all():
            await run_heartbeat(session, agent, market)


async def _decision_tick():
    market = BinanceClient()
    n = 100 if settings.universe_default == "TOP_100" else 50
    symbols = await market.get_top_symbols("USDT", n)
    with get_session() as session:
        for agent in session.query(Agent).filter_by(status="running").all():
            buy_usd = settings.initial_capital_usd / Decimal("10")
            await run_decision(session, agent, market, symbols, buy_usd)


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(_heartbeat_tick, "interval", seconds=settings.heartbeat_seconds)
    _scheduler.add_job(_decision_tick, "interval", seconds=settings.decision_seconds)
    _scheduler.start()
    return _scheduler
