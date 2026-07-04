from datetime import datetime, timezone
import json
from app.db.models import Observation
from app.feeds.rss import FeedItem
from app.feeds.ingest import ingest_observations


class FakeAdapter:
    def __init__(self, items): self._items = items
    async def fetch(self): return list(self._items)


def _item(title, url, summary="", src="CoinDesk", h=10):
    return FeedItem(source=src, title=title, url=url, summary=summary,
                    published_at=datetime(2026, 7, 3, h, 0, tzinfo=timezone.utc))


async def test_ingest_inserts_and_tags_symbols(db_session):
    adapter = FakeAdapter([
        _item("Bitcoin ETF sees record inflows", "https://a/1"),
        _item("Fed holds rates, crypto slips", "https://a/2"),      # market-wide → no symbol
    ])
    n = await ingest_observations(db_session, adapter)
    assert n == 2
    btc = db_session.query(Observation).filter_by(url="https://a/1").one()
    assert json.loads(btc.symbols_json) == ["BTC"] and btc.kind == "news"
    macro = db_session.query(Observation).filter_by(url="https://a/2").one()
    assert json.loads(macro.symbols_json) == []                     # kept as market-wide


async def test_ingest_is_idempotent_across_repolls(db_session):
    adapter = FakeAdapter([_item("Solana upgrade", "https://a/9")])
    assert await ingest_observations(db_session, adapter) == 1
    assert await ingest_observations(db_session, adapter) == 0       # same url → deduped
    assert db_session.query(Observation).count() == 1


async def test_ingest_dedups_within_one_batch(db_session):
    adapter = FakeAdapter([_item("Same", "https://a/x"), _item("Same", "https://a/x")])
    assert await ingest_observations(db_session, adapter) == 1
    assert db_session.query(Observation).count() == 1


async def test_ingest_hashes_on_source_title_when_url_missing(db_session):
    adapter = FakeAdapter([_item("Untitled link", None), _item("Untitled link", None)])
    assert await ingest_observations(db_session, adapter) == 1       # identical source+title → one row
