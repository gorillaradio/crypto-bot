import httpx, respx
from datetime import timezone
from app.feeds.rss import parse_feed, RssFeedAdapter, FeedItem

RSS_A = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>CoinDesk</title>
<item><title>Bitcoin ETF sees record inflows</title><link>https://a/1</link>
<pubDate>Fri, 03 Jul 2026 10:30:00 +0000</pubDate><description>BTC up</description></item>
<item><title>Solana network upgrade goes live</title><link>https://a/2</link>
<pubDate>Fri, 03 Jul 2026 09:00:00 +0000</pubDate><description>SOL news</description></item>
</channel></rss>"""

RSS_NO_DATE = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>X</title>
<item><title>No date here</title><link>https://a/3</link></item>
</channel></rss>"""


def test_parse_feed_extracts_items():
    items = parse_feed("CoinDesk", RSS_A)
    assert [i.title for i in items] == ["Bitcoin ETF sees record inflows",
                                        "Solana network upgrade goes live"]
    assert items[0].source == "CoinDesk" and items[0].url == "https://a/1"
    assert items[0].published_at.tzinfo is not None
    assert items[0].published_at.astimezone(timezone.utc).hour == 10


def test_parse_feed_skips_undated_items():
    assert parse_feed("X", RSS_NO_DATE) == []


@respx.mock
async def test_fetch_aggregates_all_feeds():
    respx.get("https://feed-a/").mock(return_value=httpx.Response(200, text=RSS_A))
    respx.get("https://feed-b/").mock(return_value=httpx.Response(200, text=RSS_A))
    adapter = RssFeedAdapter(feeds=[("A", "https://feed-a/"), ("B", "https://feed-b/")])
    items = await adapter.fetch()
    assert len(items) == 4                      # 2 per feed
    assert {i.source for i in items} == {"A", "B"}


@respx.mock
async def test_fetch_skips_a_broken_feed():
    respx.get("https://ok/").mock(return_value=httpx.Response(200, text=RSS_A))
    respx.get("https://down/").mock(return_value=httpx.Response(503))
    adapter = RssFeedAdapter(feeds=[("OK", "https://ok/"), ("DOWN", "https://down/")])
    items = await adapter.fetch()
    assert len(items) == 2 and {i.source for i in items} == {"OK"}   # broken feed skipped, other survives
