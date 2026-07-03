from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.core.config import settings
from app.db.models import Agent, Position


def _agent(session):
    a = Agent(name="T", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("100"))
    session.add(a); session.commit()
    return a


def test_settings_have_trigger_knobs():
    assert settings.wake_budget_per_hour == 2
    assert settings.movement_threshold == Decimal("0.05")
    assert settings.movement_window_hours == 1


def test_new_columns_defaults(db_session):
    agent = _agent(db_session)
    assert agent.last_seen_observation_id is None
    pos = Position(agent_id=agent.id, symbol="BTCUSDT",
                   quantity=Decimal("1"), avg_price=Decimal("100"))
    db_session.add(pos); db_session.commit()
    assert pos.move_armed is True


from app.agents.triggers import movement_change


def test_movement_change_up():
    assert movement_change(Decimal("100"), Decimal("108")) == Decimal("0.08")


def test_movement_change_down_is_signed():
    assert movement_change(Decimal("100"), Decimal("93")) == Decimal("-0.07")


def test_movement_change_flat():
    assert movement_change(Decimal("100"), Decimal("100")) == Decimal("0")


def test_movement_change_zero_first_guards():
    assert movement_change(Decimal("0"), Decimal("50")) == Decimal("0")


from app.db.models import DecisionRecord
from app.agents.triggers import count_recent_event_wakes


def _rec(session, agent_id, trigger, kind="decision", age_minutes=1):
    r = DecisionRecord(agent_id=agent_id, cycle_id="c", kind=kind, trigger=trigger,
                       system_prompt="s", user_prompt="u", raw_response="r",
                       parsed_output="{}", parse_status="ok",
                       model_provider="openrouter", model_name="m", latency_ms=1)
    r.created_at = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    session.add(r); session.commit()
    return r


def test_budget_counts_only_movement_and_news_decisions(db_session):
    agent = _agent(db_session)
    _rec(db_session, agent.id, "movement")
    _rec(db_session, agent.id, "news")
    _rec(db_session, agent.id, "breach")                        # exempt trigger
    _rec(db_session, agent.id, "schedule")                     # exempt trigger
    _rec(db_session, agent.id, "movement", kind="reflection")  # not a decision
    assert count_recent_event_wakes(db_session, agent.id) == 2


def test_budget_excludes_records_older_than_one_hour(db_session):
    agent = _agent(db_session)
    _rec(db_session, agent.id, "movement", age_minutes=59)
    _rec(db_session, agent.id, "news", age_minutes=120)        # 2h ago → excluded
    assert count_recent_event_wakes(db_session, agent.id) == 1


def test_budget_is_per_agent(db_session):
    a1, a2 = _agent(db_session), _agent(db_session)
    _rec(db_session, a1.id, "movement")
    assert count_recent_event_wakes(db_session, a2.id) == 0
