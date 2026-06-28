from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.db.models import Agent, Event, Position, EquitySnapshot, Trade
from app.agents.runtime import run_heartbeat, run_decision


class FakeMarket:
    def __init__(self, price, book, closes):
        self._price, self._book, self._closes = price, book, closes
    async def get_price(self, symbol): return self._price
    async def get_book_ticker(self, symbol): return self._book
    async def get_klines(self, symbol, interval, limit): return self._closes


class FakeMarketPartialError:
    """Returns closes for known symbols; raises RuntimeError for others."""
    def __init__(self, closes_by_symbol, book):
        self._closes_by_symbol = closes_by_symbol
        self._book = book

    async def get_price(self, symbol): return Decimal("100")
    async def get_book_ticker(self, symbol): return self._book
    async def get_klines(self, symbol, interval, limit):
        if symbol not in self._closes_by_symbol:
            raise RuntimeError(f"network error for {symbol}")
        return self._closes_by_symbol[symbol]


def _agent(session, cash="100"):
    a = Agent(name="R", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal(cash))
    session.add(a); session.commit()
    return a


async def test_heartbeat_writes_equity_snapshot(db_session):
    agent = _agent(db_session, "100")
    market = FakeMarket(price=Decimal("100"), book=(Decimal("99"), Decimal("101")), closes=[])
    await run_heartbeat(db_session, agent, market)
    snap = db_session.query(EquitySnapshot).filter_by(agent_id=agent.id).one()
    assert snap.equity_usd == Decimal("100")  # solo cash, nessuna posizione


async def test_heartbeat_sells_on_stop_loss(db_session):
    agent = _agent(db_session, "0")
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    # last price 80 → -20% → stop loss → vende al bid 80
    market = FakeMarket(price=Decimal("80"), book=(Decimal("80"), Decimal("81")), closes=[])
    await run_heartbeat(db_session, agent, market)
    trades = db_session.query(Trade).filter_by(agent_id=agent.id, side="SELL").all()
    assert len(trades) == 1


async def test_heartbeat_equity_includes_sell_proceeds(db_session):
    agent = _agent(db_session, "0")
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    # last price 80 → -20% → stop loss → sells at bid 80, fee 0.1% → cash = 79.92
    market = FakeMarket(price=Decimal("80"), book=(Decimal("80"), Decimal("81")), closes=[])
    await run_heartbeat(db_session, agent, market)
    snap = db_session.query(EquitySnapshot).filter_by(agent_id=agent.id).one()
    assert snap.equity_usd == Decimal("79.92")


async def test_decision_buys_on_bullish_signal(db_session):
    agent = _agent(db_session, "100")
    closes = [Decimal("10")] * 19 + [Decimal("5"), Decimal("100")]
    market = FakeMarket(price=Decimal("100"), book=(Decimal("99"), Decimal("101")), closes=closes)
    await run_decision(db_session, agent, market, symbols=["BTCUSDT"], buy_usd=Decimal("50"))
    buys = db_session.query(Trade).filter_by(agent_id=agent.id, side="BUY").all()
    assert len(buys) == 1


async def test_decision_error_isolation_skips_bad_symbol(db_session):
    """A symbol that raises on get_klines is skipped; the good symbol still trades."""
    agent = _agent(db_session, "200")
    bullish_closes = [Decimal("10")] * 19 + [Decimal("5"), Decimal("100")]
    market = FakeMarketPartialError(
        closes_by_symbol={"ETHUSDT": bullish_closes},
        book=(Decimal("99"), Decimal("101")),
    )
    await run_decision(
        db_session, agent, market,
        symbols=["BADUSDT", "ETHUSDT"],
        buy_usd=Decimal("50"),
    )
    buys = db_session.query(Trade).filter_by(agent_id=agent.id, side="BUY").all()
    assert len(buys) == 1
    assert buys[0].symbol == "ETHUSDT"
    event = db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").one()
    assert event is not None
    assert "1 errori" in event.message
