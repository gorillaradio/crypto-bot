from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from sqlalchemy.exc import IntegrityError
from app.db.models import Agent, Position


def test_agent_model_fields_persist(db_session):
    a = Agent(name="L", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"),
              initial_capital_usd=Decimal("100"),
              model_name="deepseek/deepseek-v4-flash")
    db_session.add(a); db_session.commit()
    db_session.refresh(a)               # read back from DB, not identity map
    assert a.model_provider == "openrouter"          # OpenRouter gateway default
    assert a.model_name == "deepseek/deepseek-v4-flash"


def test_agent_persists_with_decimal_cash(db_session):
    agent = Agent(
        name="Alpha",
        instructions="compra basso vendi alto",
        duration_start=datetime.now(timezone.utc),
        duration_end=datetime.now(timezone.utc) + timedelta(days=7),
        cash_usd=Decimal("100"),
        initial_capital_usd=Decimal("100"),
    )
    db_session.add(agent)
    db_session.commit()
    assert agent.id is not None
    assert agent.cash_usd == Decimal("100")


def test_position_links_to_agent(db_session):
    agent = Agent(
        name="Beta", duration_start=datetime.now(timezone.utc),
        duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"),
        initial_capital_usd=Decimal("100"),
    )
    db_session.add(agent)
    db_session.commit()
    pos = Position(agent_id=agent.id, symbol="BTCUSDT",
                   quantity=Decimal("0.001"), avg_price=Decimal("50000"))
    db_session.add(pos)
    db_session.commit()
    assert pos in agent.positions


def _mk_agent(session, **over):
    kw = dict(name="T", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"))
    kw.update(over)
    a = Agent(**kw)
    session.add(a); session.commit()
    return a


def test_agent_accepts_risk_thresholds(db_session):
    a = _mk_agent(db_session, stop_loss=Decimal("0.10"), take_profit=Decimal("0.20"))
    assert a.stop_loss == Decimal("0.10")
    assert a.take_profit == Decimal("0.20")


def test_agent_thresholds_default_none(db_session):
    a = _mk_agent(db_session)
    assert a.stop_loss is None and a.take_profit is None


def test_position_breach_armed_defaults_true(db_session):
    a = _mk_agent(db_session)
    p = Position(agent_id=a.id, symbol="BTCUSDT", quantity=Decimal("1"), avg_price=Decimal("100"))
    db_session.add(p); db_session.commit()
    assert p.breach_armed is True


def test_decision_record_persists_with_defaults(db_session):
    from app.db.models import DecisionRecord
    a = _mk_agent(db_session)
    rec = DecisionRecord(agent_id=a.id, cycle_id="cyc1", kind="decision", trigger="schedule",
                         system_prompt="sys", user_prompt="usr", raw_response="raw",
                         parsed_output='{"actions":[]}', parse_status="ok",
                         model_provider="openrouter", model_name="m", latency_ms=123)
    db_session.add(rec); db_session.commit(); db_session.refresh(rec)
    assert rec.id is not None
    assert rec.created_at is not None            # Python-side default applied on insert
    assert rec.raw_response == "raw"


def test_decision_record_allows_null_raw_parsed_and_model(db_session):
    from app.db.models import DecisionRecord
    a = _mk_agent(db_session)
    rec = DecisionRecord(agent_id=a.id, cycle_id="cyc2", kind="reflection", trigger="breach",
                         system_prompt="s", user_prompt="u", raw_response=None,
                         parsed_output=None, parse_status="failed",
                         model_provider="openrouter", model_name=None, latency_ms=0)
    db_session.add(rec); db_session.commit()
    assert rec.raw_response is None and rec.parsed_output is None and rec.model_name is None


def test_benchmark_basis_persists(db_session):
    from app.db.models import BenchmarkBasis
    a = _mk_agent(db_session)
    row = BenchmarkBasis(agent_id=a.id, universe_json='["BTCUSDT"]',
                         start_prices_json='{"BTCUSDT": "100"}', initial_capital=Decimal("100"))
    db_session.add(row); db_session.commit(); db_session.refresh(row)
    assert row.id is not None and row.created_at is not None


def test_benchmark_snapshot_persists(db_session):
    from app.db.models import BenchmarkSnapshot
    a = _mk_agent(db_session)
    row = BenchmarkSnapshot(agent_id=a.id, kind="hodl_btc", equity_usd=Decimal("123.45"))
    db_session.add(row); db_session.commit(); db_session.refresh(row)
    assert row.id is not None and row.timestamp is not None
    assert row.kind == "hodl_btc"


def test_decision_score_persists_with_null_return(db_session):
    from app.db.models import DecisionRecord, DecisionScore
    a = _mk_agent(db_session)
    rec = DecisionRecord(agent_id=a.id, cycle_id="c", kind="decision", trigger="schedule",
                         system_prompt="s", user_prompt="u", raw_response="r",
                         parsed_output='{"actions":[]}', parse_status="ok",
                         model_provider="openrouter", model_name="m", latency_ms=1)
    db_session.add(rec); db_session.commit()
    score = DecisionScore(decision_record_id=rec.id, window="24h", n_actions=0, n_hits=0,
                          avg_return_pct=None)
    db_session.add(score); db_session.commit(); db_session.refresh(score)
    assert score.id is not None and score.avg_return_pct is None


def test_decision_score_reflected_at_defaults_to_none(db_session):
    from app.db.models import DecisionRecord, DecisionScore
    a = _mk_agent(db_session)
    rec = DecisionRecord(agent_id=a.id, cycle_id="c", kind="decision", trigger="schedule",
                         system_prompt="s", user_prompt="u", raw_response="r",
                         parsed_output='{"actions":[]}', parse_status="ok",
                         model_provider="openrouter", model_name="m", latency_ms=1)
    db_session.add(rec); db_session.commit()

    score = DecisionScore(decision_record_id=rec.id, window="24h", n_actions=0, n_hits=0,
                          avg_return_pct=None)
    db_session.add(score); db_session.commit()

    assert score.reflected_at is None


def test_decision_score_reflected_at_can_be_set(db_session):
    from app.db.models import DecisionRecord, DecisionScore
    a = _mk_agent(db_session)
    rec = DecisionRecord(agent_id=a.id, cycle_id="c", kind="decision", trigger="schedule",
                         system_prompt="s", user_prompt="u", raw_response="r",
                         parsed_output='{"actions":[]}', parse_status="ok",
                         model_provider="openrouter", model_name="m", latency_ms=1)
    db_session.add(rec); db_session.commit()

    now = datetime.now(timezone.utc)
    score = DecisionScore(decision_record_id=rec.id, window="24h", n_actions=0, n_hits=0,
                          avg_return_pct=None, reflected_at=now)
    db_session.add(score); db_session.commit()

    assert score.reflected_at == now


def test_decision_score_unique_per_record_and_window(db_session):
    import pytest
    from sqlalchemy.exc import IntegrityError
    from app.db.models import DecisionRecord, DecisionScore
    a = _mk_agent(db_session)
    rec = DecisionRecord(agent_id=a.id, cycle_id="c", kind="decision", trigger="schedule",
                         system_prompt="s", user_prompt="u", raw_response="r",
                         parsed_output='{"actions":[]}', parse_status="ok",
                         model_provider="openrouter", model_name="m", latency_ms=1)
    db_session.add(rec); db_session.commit()
    db_session.add(DecisionScore(decision_record_id=rec.id, window="24h", n_actions=1, n_hits=1))
    db_session.commit()
    db_session.add(DecisionScore(decision_record_id=rec.id, window="24h", n_actions=2, n_hits=0))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_settings_exposes_market_brief_max_age_minutes():
    from app.core.config import settings

    assert settings.market_brief_max_age_minutes == 120


def test_memory_entry_persists_with_defaults(db_session):
    from app.db.models import MemoryEntry
    agent = Agent(name="J", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"),
                  initial_capital_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    row = MemoryEntry(agent_id=agent.id, section="coin_theses", content="BTC: bull")
    db_session.add(row); db_session.commit(); db_session.refresh(row)
    assert row.id is not None and row.created_at is not None
    assert row.active is True                       # default active
    assert row.cycle_id is None                     # nullable


def test_memory_entry_allows_many_rows_per_section(db_session):
    from app.db.models import MemoryEntry
    agent = Agent(name="J2", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"),
                  initial_capital_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    db_session.add_all([
        MemoryEntry(agent_id=agent.id, section="coin_theses", content="BTC: bull", cycle_id="c1"),
        MemoryEntry(agent_id=agent.id, section="coin_theses", content="ETH: flat", cycle_id="c1"),
    ])
    db_session.commit()                              # no unique constraint → both persist
    assert db_session.query(MemoryEntry).filter_by(agent_id=agent.id, section="coin_theses").count() == 2


def test_observation_persists_with_defaults(db_session):
    from app.db.models import Observation
    obs = Observation(source="CoinDesk", title="Bitcoin ETF sees record inflows",
                      url="https://x/1", dedup_hash="h1",
                      published_at=datetime(2026, 7, 3, 10, 30, tzinfo=timezone.utc))
    db_session.add(obs); db_session.commit(); db_session.refresh(obs)
    assert obs.id is not None and obs.created_at is not None
    assert obs.kind == "news"            # default kind
    assert obs.symbols_json == "[]"      # default: market-wide until tagged


def test_observation_dedup_hash_is_unique(db_session):
    from app.db.models import Observation
    import pytest
    from sqlalchemy.exc import IntegrityError
    now = datetime(2026, 7, 3, 10, 30, tzinfo=timezone.utc)
    db_session.add(Observation(source="CoinDesk", title="a", dedup_hash="dup", published_at=now))
    db_session.commit()
    db_session.add(Observation(source="Cointelegraph", title="b", dedup_hash="dup", published_at=now))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_agent_requires_initial_capital(db_session):
    """Nessun default: chi crea un Agent dichiara con quanto parte."""
    agent = Agent(
        name="NoCapital",
        duration_start=datetime.now(timezone.utc),
        duration_end=datetime.now(timezone.utc) + timedelta(days=1),
        cash_usd=Decimal("100"),
    )
    db_session.add(agent)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_agent_persists_initial_capital(db_session):
    agent = Agent(
        name="WithCapital",
        duration_start=datetime.now(timezone.utc),
        duration_end=datetime.now(timezone.utc) + timedelta(days=1),
        cash_usd=Decimal("100"),
        initial_capital_usd=Decimal("100"),
    )
    db_session.add(agent); db_session.commit()
    assert agent.initial_capital_usd == Decimal("100")


def test_lifecycle_trade_and_evaluation_persist_canonical_identity(db_session):
    from app.db.models import PositionEvaluation, PositionLifecycle, Trade

    agent = _mk_agent(db_session)
    lifecycle = PositionLifecycle(
        id="life-1", agent_id=agent.id, symbol="BTCUSDT", opening_cycle_id="cycle-1"
    )
    db_session.add(lifecycle)
    db_session.flush()
    trade = Trade(
        agent_id=agent.id, lifecycle_id=lifecycle.id, cycle_id="cycle-1",
        symbol="BTCUSDT", side="BUY", quantity=Decimal("0.5"),
        price=Decimal("100"), fee=Decimal("0.05"),
    )
    evaluation = PositionEvaluation(
        agent_id=agent.id, lifecycle_id=lifecycle.id, cycle_id="cycle-1",
        action="BUY", rationale="momentum",
    )
    db_session.add_all([trade, evaluation])
    db_session.commit()

    assert trade.lifecycle_id == "life-1"
    assert trade.cycle_id == "cycle-1"
    assert evaluation.lifecycle_id == trade.lifecycle_id
    assert lifecycle.closed_at is None


def test_position_evaluation_persists_policy_context(db_session):
    from app.db.models import PositionEvaluation, PositionLifecycle

    agent = _mk_agent(db_session)
    lifecycle = PositionLifecycle(
        id="life-policy", agent_id=agent.id, symbol="BTCUSDT",
        opening_cycle_id="cycle-policy",
    )
    db_session.add(lifecycle)
    db_session.flush()
    db_session.add(PositionEvaluation(
        agent_id=agent.id, lifecycle_id=lifecycle.id, cycle_id="cycle-policy",
        action="HOLD", rationale="wait for confirmation",
        policy_refs=["P001", "P004"], policy_alignment="follows",
        override_reason="",
    ))
    db_session.commit()

    saved = db_session.query(PositionEvaluation).one()
    assert saved.policy_refs == ["P001", "P004"]
    assert saved.policy_alignment == "follows"
    assert saved.override_reason == ""


def test_position_can_reference_current_lifecycle(db_session):
    from app.db.models import PositionLifecycle

    agent = _mk_agent(db_session)
    lifecycle = PositionLifecycle(
        id="life-open", agent_id=agent.id, symbol="ETHUSDT", opening_cycle_id="cycle-open"
    )
    db_session.add(lifecycle)
    db_session.flush()
    position = Position(
        agent_id=agent.id, lifecycle_id=lifecycle.id, symbol="ETHUSDT",
        quantity=Decimal("1"), avg_price=Decimal("50"),
    )
    db_session.add(position)
    db_session.commit()

    assert position.lifecycle_id == lifecycle.id
