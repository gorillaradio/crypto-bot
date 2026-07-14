from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import httpx
from app.brain.context import CoinSnapshot

BASE_URL = "https://api.binance.com"


@dataclass(frozen=True)
class LifecycleMarketSnapshot:
    as_of: datetime
    prices: dict[str, Decimal]
    series_24h: dict[str, list[Decimal]]


def _copy_lifecycle_market_snapshot(
    snapshot: LifecycleMarketSnapshot,
) -> LifecycleMarketSnapshot:
    return LifecycleMarketSnapshot(
        as_of=snapshot.as_of,
        prices=dict(snapshot.prices),
        series_24h={symbol: list(series) for symbol, series in snapshot.series_24h.items()},
    )


class BinanceClient:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self._last_lifecycle_market_snapshot: LifecycleMarketSnapshot | None = None

    @property
    def last_lifecycle_market_snapshot(self) -> LifecycleMarketSnapshot | None:
        if self._last_lifecycle_market_snapshot is None:
            return None
        return _copy_lifecycle_market_snapshot(self._last_lifecycle_market_snapshot)

    async def _get(self, path: str, params: dict) -> object:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10) as c:
            resp = await c.get(path, params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_price(self, symbol: str) -> Decimal:
        data = await self._get("/api/v3/ticker/price", {"symbol": symbol})
        return Decimal(data["price"])

    async def get_book_ticker(self, symbol: str) -> tuple[Decimal, Decimal]:
        data = await self._get("/api/v3/ticker/bookTicker", {"symbol": symbol})
        return Decimal(data["bidPrice"]), Decimal(data["askPrice"])

    async def get_klines(self, symbol: str, interval: str, limit: int) -> list[Decimal]:
        data = await self._get(
            "/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit}
        )
        return [Decimal(row[4]) for row in data]  # index 4 = close

    async def get_price_at(self, symbol: str, ms: int) -> Decimal | None:
        data = await self._get(
            "/api/v3/klines",
            {"symbol": symbol, "interval": "1h", "startTime": ms, "limit": 1},
        )
        if not data:
            return None
        return Decimal(data[0][4])  # index 4 = close

    async def get_top_symbols(self, quote: str = "USDT", n: int = 100) -> list[str]:
        data = await self._get("/api/v3/ticker/24hr", {})
        usdt = [
            d for d in data
            if d["symbol"].endswith(quote)
            and not d["symbol"][: -len(quote)].endswith(("UP", "DOWN"))
        ]
        usdt.sort(key=lambda d: Decimal(d["quoteVolume"]), reverse=True)
        return [d["symbol"] for d in usdt[:n]]

    async def get_universe_snapshot(self, symbols: list[str]) -> list[CoinSnapshot]:
        data = await self._get("/api/v3/ticker/24hr", {})
        by_symbol = {d["symbol"]: d for d in data}
        out = []
        for s in symbols:
            d = by_symbol.get(s)
            if d is None:
                continue
            out.append(CoinSnapshot(symbol=s, price=Decimal(d["lastPrice"]),
                                    pct_24h=Decimal(d["priceChangePercent"])))
        return out

    async def get_lifecycle_market_snapshot(
        self, symbols: list[str], series_symbols: list[str] | None = None,
    ) -> LifecycleMarketSnapshot:
        distinct_symbols = list(dict.fromkeys(symbols))
        distinct_series_symbols = (
            distinct_symbols if series_symbols is None
            else [symbol for symbol in dict.fromkeys(series_symbols) if symbol in distinct_symbols]
        )
        data = await self._get("/api/v3/ticker/24hr", {})
        by_symbol = {d["symbol"]: d for d in data}
        prices = {
            symbol: Decimal(by_symbol[symbol]["lastPrice"])
            for symbol in distinct_symbols
        }
        series_24h = {
            symbol: await self.get_klines(symbol, "1h", 24)
            for symbol in distinct_series_symbols
        }
        snapshot = LifecycleMarketSnapshot(
            as_of=datetime.now(timezone.utc),
            prices=prices,
            series_24h=series_24h,
        )
        self._last_lifecycle_market_snapshot = _copy_lifecycle_market_snapshot(snapshot)
        return snapshot
