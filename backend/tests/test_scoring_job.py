from datetime import datetime, timezone, timedelta
from decimal import Decimal
from app.db.models import Agent, DecisionRecord, DecisionScore
from app.eval.scoring_job import score_matured_decisions


class FakePriceMarket:
    """get_price_at keyed by (symbol, ms) with a default fallback."""
    def __init__(self, prices, default=None):
        self._prices, self._default = prices, default
    async def get_price_at(self, symbol, ms):
        return self._prices.get((symbol, ms), self._default)


def _agent(session):
    a = Agent(name="S", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("100"))
    session.add(a); session.commit()
    return a


def _decision(session, agent_id, created_at, actions_json='{"actions":[{"type":"BUY","symbol":"BTCUSDT"}]}'):
    rec = DecisionRecord(agent_id=agent_id, cycle_id="c", kind="decision", trigger="schedule",
                         system_prompt="s", user_prompt="u", raw_response="r",
                         parsed_output=actions_json, parse_status="ok",
                         model_provider="openrouter", model_name="m", latency_ms=1)
    rec.created_at = created_at
    session.add(rec); session.commit()
    return rec


async def test_scores_matured_decision_for_both_windows(db_session):
    agent = _agent(db_session)
    made = datetime.now(timezone.utc) - timedelta(days=8)          # both 24h and 7d matured
    rec = _decision(db_session, agent.id, made)
    ms0 = int(made.timestamp() * 1000)
    market = FakePriceMarket({
        ("BTCUSDT", ms0): Decimal("100"),
        ("BTCUSDT", int((made + timedelta(hours=24)).timestamp() * 1000)): Decimal("110"),  # +10% at 24h
        ("BTCUSDT", int((made + timedelta(days=7)).timestamp() * 1000)): Decimal("90"),     # -10% at 7d
    })
    n = await score_matured_decisions(db_session, market, datetime.now(timezone.utc))
    assert n == 2
    by_win = {s.window: s for s in db_session.query(DecisionScore)
              .filter_by(decision_record_id=rec.id).all()}
    assert by_win["24h"].n_actions == 1 and by_win["24h"].n_hits == 1   # BUY into a rise
    assert by_win["7d"].n_hits == 0                                     # BUY into a fall


async def test_immature_decision_is_not_scored(db_session):
    agent = _agent(db_session)
    rec = _decision(db_session, agent.id, datetime.now(timezone.utc) - timedelta(hours=1))
    market = FakePriceMarket({}, default=Decimal("100"))
    n = await score_matured_decisions(db_session, market, datetime.now(timezone.utc))
    assert n == 0
    assert db_session.query(DecisionScore).count() == 0


async def test_already_scored_decision_is_not_rescored(db_session):
    agent = _agent(db_session)
    made = datetime.now(timezone.utc) - timedelta(days=8)
    rec = _decision(db_session, agent.id, made)
    market = FakePriceMarket({}, default=Decimal("100"))
    await score_matured_decisions(db_session, market, datetime.now(timezone.utc))
    n2 = await score_matured_decisions(db_session, market, datetime.now(timezone.utc))
    assert n2 == 0                                                     # idempotent
    assert db_session.query(DecisionScore).filter_by(decision_record_id=rec.id).count() == 2


async def test_reflection_and_failed_records_are_skipped(db_session):
    agent = _agent(db_session)
    made = datetime.now(timezone.utc) - timedelta(days=8)
    refl = _decision(db_session, agent.id, made)
    refl.kind = "reflection"
    failed = _decision(db_session, agent.id, made)
    failed.parse_status = "failed"
    db_session.commit()
    n = await score_matured_decisions(db_session, FakePriceMarket({}, default=Decimal("100")),
                                      datetime.now(timezone.utc))
    # only scorable kind="decision"/parse ok records count; neither of these qualifies
    assert db_session.query(DecisionScore).filter_by(decision_record_id=refl.id).count() == 0
    assert db_session.query(DecisionScore).filter_by(decision_record_id=failed.id).count() == 0


async def test_scoring_handles_naive_created_at_from_sqlite(db_session):
    """SQLite returns tz-NAIVE datetimes on round-trip; the job must treat them as UTC
    (via _as_utc) rather than raising TypeError. expire_all() forces a fresh DB load so
    created_at comes back naive — the exact condition _as_utc guards against."""
    agent = _agent(db_session)
    made = datetime.now(timezone.utc) - timedelta(days=8)
    rec = _decision(db_session, agent.id, made)
    db_session.expire_all()                        # drop identity-map cache → re-SELECT from SQLite
    reloaded = db_session.query(DecisionRecord).filter_by(id=rec.id).one()
    assert reloaded.created_at.tzinfo is None      # confirm the naive round-trip actually happens
    n = await score_matured_decisions(db_session, FakePriceMarket({}, default=Decimal("100")),
                                      datetime.now(timezone.utc))
    assert n == 2                                  # both windows scored, no TypeError from naive compare
