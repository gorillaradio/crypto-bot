from dataclasses import dataclass
from datetime import datetime, timezone
import httpx
import feedparser


@dataclass
class FeedItem:
    source: str
    title: str
    url: str | None
    summary: str
    published_at: datetime


# (source label, feed url) — crypto-native, single source for v1. Macro arrives via these outlets.
DEFAULT_FEEDS: list[tuple[str, str]] = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("CryptoSlate", "https://cryptoslate.com/feed/"),
]


def _entry_time(entry) -> datetime | None:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if t is None:
        return None
    return datetime(*t[:6], tzinfo=timezone.utc)


def parse_feed(source: str, xml: str) -> list[FeedItem]:
    parsed = feedparser.parse(xml)
    out: list[FeedItem] = []
    for e in parsed.entries:
        when = _entry_time(e)
        if when is None:
            continue                                  # undated → cannot place in time, skip
        out.append(FeedItem(
            source=source,
            title=(e.get("title") or "").strip(),
            url=e.get("link"),
            summary=(e.get("summary") or "").strip(),
            published_at=when,
        ))
    return out


class RssFeedAdapter:
    def __init__(self, feeds: list[tuple[str, str]] = DEFAULT_FEEDS, timeout: int = 10):
        self.feeds = feeds
        self.timeout = timeout

    async def fetch(self) -> list[FeedItem]:
        items: list[FeedItem] = []
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            for source, url in self.feeds:
                try:
                    resp = await c.get(url)
                    resp.raise_for_status()
                except Exception:
                    continue                          # one dead feed never sinks the batch
                items.extend(parse_feed(source, resp.text))
        return items
