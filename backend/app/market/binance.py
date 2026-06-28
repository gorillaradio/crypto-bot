from decimal import Decimal
import httpx

BASE_URL = "https://api.binance.com"


class BinanceClient:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url

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

    async def get_top_symbols(self, quote: str = "USDT", n: int = 100) -> list[str]:
        data = await self._get("/api/v3/ticker/24hr", {})
        usdt = [
            d for d in data
            if d["symbol"].endswith(quote)
            and not d["symbol"][: -len(quote)].endswith(("UP", "DOWN"))
        ]
        usdt.sort(key=lambda d: Decimal(d["quoteVolume"]), reverse=True)
        return [d["symbol"] for d in usdt[:n]]
