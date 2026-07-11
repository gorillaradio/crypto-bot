from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.core.config import settings
from app.db.models import Agent, MarketBrief


def _agent(session, **kw):
    a = Agent(name="T", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"), **kw)
    session.add(a); session.commit()
    return a


def test_brain_v2_settings_present():
    assert settings.analyst_model == "deepseek/deepseek-v4-pro"
    assert settings.brief_max_highlights == 15
    assert settings.analyst_news_limit == 30


def test_market_brief_insert_and_nullable_payload(db_session):
    b = MarketBrief(cycle_id="c1", parsed_brief=None, system_prompt="s", user_prompt="u",
                    raw_response=None, parse_status="failed",
                    model_provider="openrouter", model_name="deepseek/deepseek-v4-pro",
                    latency_ms=12)
    db_session.add(b); db_session.commit()
    assert b.id is not None and b.parsed_brief is None and b.created_at is not None


from app.brain.analyst_schema import Highlight, MarketBriefSchema


def test_parses_full_brief():
    raw = ('{"regime":"risk-on, BTC leads","highlights":'
           '[{"symbol":"SOLUSDT","snapshot":"$182 (+9.4% 24h)","signal":"bullish","note":"momentum"}],'
           '"key_news":["Fed holds rates"]}')
    b = MarketBriefSchema.model_validate_json(raw)
    assert b.regime.startswith("risk-on")
    assert b.highlights[0].symbol == "SOLUSDT" and b.highlights[0].signal == "bullish"
    assert b.key_news == ["Fed holds rates"]


def test_defaults_empty():
    b = MarketBriefSchema.model_validate_json("{}")
    assert b.regime == "" and b.highlights == [] and b.key_news == []


def test_signal_rejects_unknown():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Highlight.model_validate({"symbol": "BTCUSDT", "signal": "moon"})
