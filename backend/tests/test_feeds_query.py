from datetime import datetime, timezone
import json
from app.db.models import Observation
from app.feeds.query import recent_observations_for


def _obs(session, title, symbols, h, url):
    session.add(Observation(source="CoinDesk", kind="news", title=title, url=url,
                            symbols_json=json.dumps(symbols), dedup_hash=url,
                            published_at=datetime(2026, 7, 3, h, 0, tzinfo=timezone.utc)))
    session.commit()


def test_returns_universe_matches_and_market_wide_only(db_session):
    _obs(db_session, "BTC news", ["BTC"], 12, "u/1")
    _obs(db_session, "ETH news", ["ETH"], 11, "u/2")       # not in universe → excluded
    _obs(db_session, "Macro news", [], 10, "u/3")          # market-wide → included
    out = recent_observations_for(db_session, ["BTCUSDT"])
    titles = [o.title for o in out]
    assert "BTC news" in titles and "Macro news" in titles
    assert "ETH news" not in titles


def test_orders_newest_first_and_limits(db_session):
    for i in range(15):
        _obs(db_session, f"n{i}", ["BTC"], 8, f"u/{i}")     # same hour; id desc breaks ties
    out = recent_observations_for(db_session, ["BTCUSDT"], limit=5)
    assert len(out) == 5
    assert out[0].title == "n14"                            # most-recently inserted first
