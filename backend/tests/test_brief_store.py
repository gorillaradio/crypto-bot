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


def test_latest_valid_none_when_empty(db_session):
    assert latest_valid_brief(db_session) is None


def test_filter_for_universe(db_session):
    row = persist_brief(db_session, "c1", _result())
    view = filter_brief_for(row, ["BTCUSDT", "ETHUSDT"])   # XRP not in universe
    assert view.regime == "risk-on" and view.key_news == ["Fed"]
    assert [h.symbol for h in view.highlights] == ["BTCUSDT"]   # XRP filtered out
    assert view.highlights[0].signal == "bullish" and view.as_of is not None
