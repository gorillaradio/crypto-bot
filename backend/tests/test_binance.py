import httpx, respx
from decimal import Decimal
from app.market.binance import BinanceClient

BASE = "https://api.binance.com"


@respx.mock
async def test_get_book_ticker_returns_bid_ask():
    respx.get(f"{BASE}/api/v3/ticker/bookTicker").mock(
        return_value=httpx.Response(200, json={"bidPrice": "100.5", "askPrice": "100.7"})
    )
    client = BinanceClient()
    bid, ask = await client.get_book_ticker("BTCUSDT")
    assert bid == Decimal("100.5")
    assert ask == Decimal("100.7")


@respx.mock
async def test_get_top_symbols_sorted_by_volume_usdt_only():
    respx.get(f"{BASE}/api/v3/ticker/24hr").mock(
        return_value=httpx.Response(200, json=[
            {"symbol": "BTCUSDT", "quoteVolume": "500"},
            {"symbol": "ETHUSDT", "quoteVolume": "900"},
            {"symbol": "FOOBTC", "quoteVolume": "9999"},
        ])
    )
    client = BinanceClient()
    top = await client.get_top_symbols("USDT", 2)
    assert top == ["ETHUSDT", "BTCUSDT"]


@respx.mock
async def test_get_klines_returns_close_prices():
    respx.get(f"{BASE}/api/v3/klines").mock(
        return_value=httpx.Response(200, json=[
            [0, "1", "2", "0.5", "1.5", "10", 0, "0", 0, "0", "0", "0"],
            [0, "1", "2", "0.5", "2.5", "10", 0, "0", 0, "0", "0", "0"],
        ])
    )
    client = BinanceClient()
    closes = await client.get_klines("BTCUSDT", "1h", 2)
    assert closes == [Decimal("1.5"), Decimal("2.5")]
