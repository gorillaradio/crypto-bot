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
            {"symbol": "BTCUPUSDT", "quoteVolume": "9999"},
        ])
    )
    client = BinanceClient()
    top = await client.get_top_symbols("USDT", 2)
    assert top == ["ETHUSDT", "BTCUSDT"]
    assert "BTCUPUSDT" not in top


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


@respx.mock
async def test_get_universe_snapshot_filters_and_parses():
    respx.get(f"{BASE}/api/v3/ticker/24hr").mock(
        return_value=httpx.Response(200, json=[
            {"symbol": "BTCUSDT", "lastPrice": "60000.0", "priceChangePercent": "2.5"},
            {"symbol": "ETHUSDT", "lastPrice": "3000.0", "priceChangePercent": "-1.0"},
            {"symbol": "JUNKUSDT", "lastPrice": "1.0", "priceChangePercent": "0"},
        ])
    )
    from app.brain.context import CoinSnapshot
    snap = await BinanceClient().get_universe_snapshot(["ETHUSDT", "BTCUSDT"])
    assert [c.symbol for c in snap] == ["ETHUSDT", "BTCUSDT"]   # order preserved
    assert snap[1].price == Decimal("60000.0")
    assert snap[1].pct_24h == Decimal("2.5")
    assert isinstance(snap[0], CoinSnapshot)
