import httpx, pytest, respx
from decimal import Decimal
from app.market.binance import BinanceClient, LifecycleMarketSnapshot

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


async def test_lifecycle_market_snapshot_fetches_quotes_and_hourly_closes(respx_mock):
    respx_mock.get(f"{BASE}/api/v3/ticker/24hr").mock(
        return_value=httpx.Response(200, json=[
            {"symbol": "BTCUSDT", "lastPrice": "110"},
            {"symbol": "ETHUSDT", "lastPrice": "90"},
        ])
    )
    respx_mock.get(
        f"{BASE}/api/v3/klines",
        params={"symbol": "BTCUSDT", "interval": "1h", "limit": "24"},
    ).mock(
        return_value=httpx.Response(200, json=[
            [0, "", "", "", "100"],
            [0, "", "", "", "110"],
        ])
    )
    respx_mock.get(
        f"{BASE}/api/v3/klines",
        params={"symbol": "ETHUSDT", "interval": "1h", "limit": "24"},
    ).mock(
        return_value=httpx.Response(200, json=[
            [0, "", "", "", "80"],
            [0, "", "", "", "90"],
        ])
    )

    snapshot = await BinanceClient().get_lifecycle_market_snapshot(
        ["BTCUSDT", "ETHUSDT", "BTCUSDT"]
    )

    assert snapshot.prices == {"BTCUSDT": Decimal("110"), "ETHUSDT": Decimal("90")}
    assert snapshot.series_24h["BTCUSDT"] == [Decimal("100"), Decimal("110")]
    assert snapshot.series_24h["ETHUSDT"] == [Decimal("80"), Decimal("90")]
    assert snapshot.as_of.tzinfo is not None
    assert len(respx_mock.calls) == 3


async def test_lifecycle_market_snapshot_keeps_last_known_value_after_provider_failure(
    respx_mock,
):
    respx_mock.get(f"{BASE}/api/v3/ticker/24hr").mock(
        side_effect=[
            httpx.Response(200, json=[{"symbol": "BTCUSDT", "lastPrice": "110"}]),
            httpx.Response(200, json=[{"symbol": "BTCUSDT", "lastPrice": "110"}]),
        ]
    )
    respx_mock.get(
        f"{BASE}/api/v3/klines",
        params={"symbol": "BTCUSDT", "interval": "1h", "limit": "24"},
    ).mock(
        side_effect=[
            httpx.Response(200, json=[[0, "", "", "", "110"]]),
            httpx.ConnectError("provider unavailable"),
        ]
    )
    client = BinanceClient()

    first = await client.get_lifecycle_market_snapshot(["BTCUSDT"])

    with pytest.raises(httpx.ConnectError):
        await client.get_lifecycle_market_snapshot(["BTCUSDT"])

    assert client.last_lifecycle_market_snapshot == first


async def test_lifecycle_market_snapshot_does_not_expose_mutable_cached_data(respx_mock):
    respx_mock.get(f"{BASE}/api/v3/ticker/24hr").mock(
        return_value=httpx.Response(
            200, json=[{"symbol": "BTCUSDT", "lastPrice": "110"}]
        )
    )
    respx_mock.get(
        f"{BASE}/api/v3/klines",
        params={"symbol": "BTCUSDT", "interval": "1h", "limit": "24"},
    ).mock(return_value=httpx.Response(200, json=[[0, "", "", "", "100"]]))
    client = BinanceClient()

    returned = await client.get_lifecycle_market_snapshot(["BTCUSDT"])
    returned.prices["BTCUSDT"] = Decimal("0")
    returned.series_24h["BTCUSDT"][0] = Decimal("0")

    cached = client.last_lifecycle_market_snapshot
    assert cached is not None
    assert cached.prices == {"BTCUSDT": Decimal("110")}
    assert cached.series_24h == {"BTCUSDT": [Decimal("100")]}

    cached.prices["BTCUSDT"] = Decimal("0")
    cached.series_24h["BTCUSDT"][0] = Decimal("0")

    assert client.last_lifecycle_market_snapshot == LifecycleMarketSnapshot(
        as_of=returned.as_of,
        prices={"BTCUSDT": Decimal("110")},
        series_24h={"BTCUSDT": [Decimal("100")]},
    )
