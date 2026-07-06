from app.brain.analyst_schema import MarketBriefSchema, Highlight, AnalystResult
from app.brain.brief_store import persist_brief, latest_valid_brief, filter_brief_for


def _result(regime="risk-on", parse_status="ok"):
    brief = MarketBriefSchema(regime=regime, key_news=["Fed"], highlights=[
        Highlight(symbol="BTCUSDT", snapshot="$60000", signal="bullish", note="etf"),
        Highlight(symbol="XRPUSDT", snapshot="$0.5", signal="bearish", note="suit")])
    return AnalystResult(brief, system="s", user="u", raw="{}", parse_status=parse_status, latency_ms=7)


def test_persist_ok_writes_payload_and_audit(db_session):
    row = persist_brief(db_session, "c1", _result())
    assert row.id is not None and row.parse_status == "ok"
    assert row.parsed_brief and "risk-on" in row.parsed_brief
    assert row.model_provider == "openrouter" and row.system_prompt == "s"


def test_persist_failed_stores_null_payload(db_session):
    row = persist_brief(db_session, "c2", _result(parse_status="failed"))
    assert row.parsed_brief is None


def test_latest_valid_skips_failed_and_returns_newest(db_session):
    persist_brief(db_session, "c1", _result(regime="old"))
    persist_brief(db_session, "c2", _result(parse_status="failed"))   # newer but unusable
    latest = latest_valid_brief(db_session)
    assert latest is not None and "old" in latest.parsed_brief         # skips the failed one


def test_latest_valid_returns_newest_among_two_valid(db_session):
    persist_brief(db_session, "c1", _result(regime="older"))
    persist_brief(db_session, "c2", _result(regime="newer"))   # both valid (parse ok)
    latest = latest_valid_brief(db_session)
    # newest of two VALID rows must win — this fails if order_by were removed
    # (SQLite .first() without ORDER BY returns the oldest/first-inserted row)
    assert latest is not None and "newer" in latest.parsed_brief


def test_latest_valid_none_when_empty(db_session):
    assert latest_valid_brief(db_session) is None


def test_filter_for_universe(db_session):
    row = persist_brief(db_session, "c1", _result())
    view = filter_brief_for(row, ["BTCUSDT", "ETHUSDT"])   # XRP not in universe
    assert view.regime == "risk-on" and view.key_news == ["Fed"]
    assert [h.symbol for h in view.highlights] == ["BTCUSDT"]   # XRP filtered out
    assert view.highlights[0].signal == "bullish" and view.as_of is not None


def test_brief_lookup_returns_fresh_valid_brief(db_session):
    from datetime import datetime, timezone, timedelta
    from app.brain.brief_store import brief_lookup_for_prompt

    row = persist_brief(db_session, "fresh", _result(regime="fresh"))
    row.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db_session.commit()

    lookup = brief_lookup_for_prompt(db_session, now=datetime.now(timezone.utc))

    assert lookup.row == row
    assert lookup.unavailable_reason is None
    assert lookup.has_valid is True


def test_brief_lookup_treats_stale_valid_brief_as_unavailable(db_session):
    from datetime import datetime, timezone, timedelta
    from app.brain.brief_store import brief_lookup_for_prompt

    row = persist_brief(db_session, "stale", _result(regime="stale"))
    row.created_at = datetime.now(timezone.utc) - timedelta(minutes=124)
    db_session.commit()

    lookup = brief_lookup_for_prompt(db_session, now=datetime.now(timezone.utc))

    assert lookup.row is None
    assert lookup.has_valid is True
    assert "stale by 124m" in lookup.unavailable_reason


def test_brief_lookup_ignores_failed_rows_for_freshness(db_session):
    from datetime import datetime, timezone
    from app.db.models import MarketBrief
    from app.brain.brief_store import brief_lookup_for_prompt

    db_session.add(MarketBrief(cycle_id="bad", parsed_brief=None,
                               system_prompt="s", user_prompt="u", raw_response=None,
                               parse_status="failed", model_provider="openrouter",
                               model_name="m", latency_ms=1,
                               created_at=datetime.now(timezone.utc)))
    db_session.commit()

    lookup = brief_lookup_for_prompt(db_session, now=datetime.now(timezone.utc))

    assert lookup.row is None
    assert lookup.has_valid is False
    assert lookup.unavailable_reason is None
