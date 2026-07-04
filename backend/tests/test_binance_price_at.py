import pytest
from decimal import Decimal
from app.market.binance import BinanceClient


class StubClient(BinanceClient):
    def __init__(self, rows):
        super().__init__()
        self._rows = rows
        self.last_params = None
    async def _get(self, path, params):
        self.last_params = params
        return self._rows


async def test_get_price_at_returns_close_of_first_candle():
    # a kline row: [openTime, open, high, low, close, ...]
    c = StubClient([[1000, "10", "12", "9", "11", "…"]])
    price = await c.get_price_at("BTCUSDT", 1000)
    assert price == Decimal("11")                       # index 4 = close
    assert c.last_params["startTime"] == 1000 and c.last_params["limit"] == 1


async def test_get_price_at_returns_none_when_empty():
    c = StubClient([])
    assert await c.get_price_at("BTCUSDT", 1000) is None
