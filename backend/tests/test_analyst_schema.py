from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.core.config import settings
from app.db.models import Agent, MarketBrief


def _agent(session, **kw):
    a = Agent(name="T", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("100"), **kw)
    session.add(a); session.commit()
    return a


def test_brain_v2_settings_present():
    assert settings.analyst_model == "deepseek/deepseek-v4-pro"
    assert settings.brief_max_highlights == 15
    assert settings.analyst_news_limit == 30


def test_agent_brain_version_defaults_v1(db_session):
    assert _agent(db_session).brain_version == "v1"


def test_agent_brain_version_can_be_v2(db_session):
    assert _agent(db_session, brain_version="v2").brain_version == "v2"


def test_market_brief_insert_and_nullable_payload(db_session):
    b = MarketBrief(cycle_id="c1", parsed_brief=None, system_prompt="s", user_prompt="u",
                    raw_response=None, parse_status="failed",
                    model_provider="openrouter", model_name="deepseek/deepseek-v4-pro",
                    latency_ms=12)
    db_session.add(b); db_session.commit()
    assert b.id is not None and b.parsed_brief is None and b.created_at is not None
