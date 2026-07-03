from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api import routes, auth
from app.db.models import Agent, EquitySnapshot, Agent as AgentModel, Position, Trade, Event, AgentMemory
from app.brain.context import CoinSnapshot


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _client(db_session):
    app.dependency_overrides[routes.session_dep] = lambda: db_session
    app.dependency_overrides[auth.require_admin] = lambda: "admin"
    app.dependency_overrides[auth.require_viewer_or_admin] = lambda: "admin"
    return TestClient(app)


def _mk(client, **over):
    """POST a valid agent payload; override any field via kwargs."""
    body = {"name": "A", "instructions": "", "duration_days": 7,
            "model_name": "deepseek/deepseek-v4-flash"}
    body.update(over)
    return client.post("/api/agents", json=body)


def test_create_agent_starts_with_initial_capital(db_session):
    client = _client(db_session)
    resp = _mk(client, name="Alpha", instructions="x")
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Alpha"
    assert Decimal(str(body["cash_usd"])) == Decimal("100")


def test_get_agent_equity_returns_curve(db_session):
    agent = Agent(name="B", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    db_session.add(EquitySnapshot(agent_id=agent.id, equity_usd=Decimal("105")))
    db_session.commit()
    client = _client(db_session)
    resp = client.get(f"/api/agents/{agent.id}/equity")
    assert resp.status_code == 200
    assert Decimal(resp.json()[0]["equity_usd"]) == Decimal("105")


def test_list_agents_returns_all(db_session):
    client = _client(db_session)
    _mk(client, name="X", duration_days=3)
    _mk(client, name="Y", duration_days=5)
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_agent_returns_404_for_missing(db_session):
    client = _client(db_session)
    resp = client.get("/api/agents/9999")
    assert resp.status_code == 404


def test_agent_detail_reports_equity_and_return(db_session):
    agent = Agent(name="R", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    db_session.add(EquitySnapshot(agent_id=agent.id, equity_usd=Decimal("110")))
    db_session.commit()
    client = _client(db_session)
    body = client.get(f"/api/agents/{agent.id}").json()
    assert Decimal(body["equity"]) == Decimal("110")
    assert Decimal(body["return_pct"]) == Decimal("10")  # (110-100)/100*100


def test_get_positions_returns_holdings_with_cost_basis(db_session):
    agent = Agent(name="P", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("0"))
    db_session.add(agent); db_session.commit()
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("0.5"), avg_price=Decimal("100")))
    db_session.commit()
    client = _client(db_session)
    rows = client.get(f"/api/agents/{agent.id}/positions").json()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTCUSDT"
    assert Decimal(rows[0]["cost_basis"]) == Decimal("50.0")


def test_create_agent_persists_model_and_default_provider(db_session):
    client = _client(db_session)
    resp = _mk(client, name="Brainy", instructions="buy low",
               model_name="deepseek/deepseek-v4-flash")
    assert resp.status_code == 201
    a = db_session.query(Agent).filter_by(name="Brainy").one()
    db_session.expire(a)                # force re-read from DB, bypass identity map
    assert a.model_provider == "openrouter"          # OpenRouter gateway default
    assert a.model_name == "deepseek/deepseek-v4-flash"


def test_create_agent_requires_model_name(db_session):
    client = _client(db_session)
    resp = client.post("/api/agents", json={
        "name": "NoModel", "duration_days": 7, "model_provider": "anthropic"})
    assert resp.status_code == 422


def test_create_agent_rejects_empty_model_name(db_session):
    client = _client(db_session)
    resp = _mk(client, name="Empty", model_name="")
    assert resp.status_code == 422


def test_get_agent_memory_returns_sections(db_session):
    from app.brain import journal
    agent = Agent(name="Mem", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    journal.append_entries(db_session, agent.id, "coin_theses", ["BTC: bull"])
    db_session.commit()
    client = _client(db_session)
    r = client.get(f"/api/agents/{agent.id}/memory")
    assert r.status_code == 200
    body = r.json()
    assert body["coin_theses"] == "BTC: bull"
    assert body["trade_lessons"] == ""


def test_get_events_returns_last_100_desc(db_session):
    agent = Agent(name="C", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    for i in range(5):
        db_session.add(Event(agent_id=agent.id, kind="info", message=f"msg {i}"))
    db_session.commit()
    client = _client(db_session)
    resp = client.get(f"/api/agents/{agent.id}/events")
    assert resp.status_code == 200
    assert len(resp.json()) == 5


def test_create_agent_persists_chosen_universe(db_session):
    client = _client(db_session)
    resp = _mk(client, name="Small", universe="TOP_50")
    assert resp.status_code == 201
    agent = db_session.query(AgentModel).filter_by(name="Small").one()
    assert agent.universe == "TOP_50"


def test_create_agent_defaults_universe_to_top_100(db_session):
    client = _client(db_session)
    resp = _mk(client, name="Big")
    assert resp.status_code == 201
    agent = db_session.query(AgentModel).filter_by(name="Big").one()
    assert agent.universe == "TOP_100"


def test_create_agent_rejects_invalid_universe(db_session):
    client = _client(db_session)
    resp = _mk(client, name="Bad", universe="TOP_500")
    assert resp.status_code == 422


def test_patch_agent_renames(db_session):
    client = _client(db_session)
    created = _mk(client, name="Old").json()
    resp = client.patch(f"/api/agents/{created['id']}", json={"name": "New"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"
    assert db_session.get(AgentModel, created["id"]).name == "New"


def test_patch_agent_404_when_missing(db_session):
    client = _client(db_session)
    resp = client.patch("/api/agents/9999", json={"name": "X"})
    assert resp.status_code == 404


def test_delete_agent_removes_agent_and_children(db_session):
    client = _client(db_session)
    created = _mk(client, name="Doomed").json()
    aid = created["id"]
    db_session.add_all([
        Position(agent_id=aid, symbol="BTCUSDT", quantity=Decimal("1"), avg_price=Decimal("100")),
        Trade(agent_id=aid, symbol="BTCUSDT", side="BUY", quantity=Decimal("1"),
              price=Decimal("100"), fee=Decimal("0.1")),
        EquitySnapshot(agent_id=aid, equity_usd=Decimal("100")),
        Event(agent_id=aid, kind="decision", message="hi"),
        AgentMemory(agent_id=aid, section="coin_theses", content="BTC: bull"),
    ])
    db_session.commit()

    resp = client.delete(f"/api/agents/{aid}")
    assert resp.status_code == 204
    assert db_session.get(AgentModel, aid) is None
    assert db_session.query(Position).filter_by(agent_id=aid).count() == 0
    assert db_session.query(Trade).filter_by(agent_id=aid).count() == 0
    assert db_session.query(EquitySnapshot).filter_by(agent_id=aid).count() == 0
    assert db_session.query(Event).filter_by(agent_id=aid).count() == 0
    assert db_session.query(AgentMemory).filter_by(agent_id=aid).count() == 0


def test_delete_agent_404_when_missing(db_session):
    client = _client(db_session)
    resp = client.delete("/api/agents/9999")
    assert resp.status_code == 404


def test_create_agent_persists_thresholds(db_session):
    client = _client(db_session)
    resp = _mk(client, name="Risk", stop_loss=0.15, take_profit=0.30)
    assert resp.status_code == 201
    a = db_session.query(Agent).filter_by(name="Risk").one()
    # float→Decimal può introdurre imprecisione; in Postgres Numeric(5,4) arrotonda. Tolleranza:
    assert a.stop_loss is not None and abs(a.stop_loss - Decimal("0.15")) < Decimal("0.0005")
    assert a.take_profit is not None and abs(a.take_profit - Decimal("0.30")) < Decimal("0.0005")


def test_create_agent_thresholds_optional(db_session):
    client = _client(db_session)
    resp = _mk(client, name="NoRisk")
    assert resp.status_code == 201
    a = db_session.query(Agent).filter_by(name="NoRisk").one()
    assert a.stop_loss is None and a.take_profit is None


def test_create_agent_rejects_stop_loss_ge_1(db_session):
    client = _client(db_session)
    resp = _mk(client, name="Bad", stop_loss=1.5)
    assert resp.status_code == 422


def test_create_agent_rejects_nonpositive_take_profit(db_session):
    client = _client(db_session)
    resp = _mk(client, name="Bad2", take_profit=0)
    assert resp.status_code == 422


class FakeMarketPreview:
    def __init__(self, snapshot, price, symbols=None):
        self._snap, self._price, self._symbols = snapshot, price, symbols or ["BTCUSDT"]
    async def get_top_symbols(self, quote, n): return self._symbols
    async def get_universe_snapshot(self, symbols): return self._snap
    async def get_price(self, symbol): return self._price


def _use_fake_market(snapshot=None, price=Decimal("120")):
    snap = snapshot if snapshot is not None else [CoinSnapshot("BTCUSDT", price, Decimal("1"))]
    app.dependency_overrides[routes.market_dep] = lambda: FakeMarketPreview(snap, price)


def test_get_prompt_returns_three_prompts(db_session):
    agent = Agent(name="P", instructions="compra basso",
                  duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"), model_name="deepseek/deepseek-v4-flash")
    db_session.add(agent); db_session.commit()
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    client = _client(db_session)
    _use_fake_market()
    resp = client.get(f"/api/agents/{agent.id}/prompt")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"decision", "reflection", "retry"}
    assert "compra basso" in body["decision"]["system"]
    assert "BTCUSDT" in body["decision"]["user"]


def test_get_prompt_404_when_missing(db_session):
    client = _client(db_session)
    _use_fake_market()
    resp = client.get("/api/agents/999/prompt")
    assert resp.status_code == 404


class FailingMarketPreview:
    async def get_top_symbols(self, quote, n): raise RuntimeError("binance down")
    async def get_universe_snapshot(self, symbols): raise RuntimeError("binance down")
    async def get_price(self, symbol): raise RuntimeError("binance down")


def test_get_prompt_502_when_market_fails(db_session):
    agent = Agent(name="P", instructions="compra basso",
                  duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"), model_name="deepseek/deepseek-v4-flash")
    db_session.add(agent); db_session.commit()
    client = _client(db_session)
    app.dependency_overrides[routes.market_dep] = lambda: FailingMarketPreview()
    resp = client.get(f"/api/agents/{agent.id}/prompt")
    assert resp.status_code == 502


def test_get_decisions_returns_records_newest_first(db_session):
    from app.db.models import DecisionRecord
    agent = Agent(name="D", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    db_session.add_all([
        DecisionRecord(agent_id=agent.id, cycle_id="c1", kind="decision", trigger="schedule",
                       system_prompt="s1", user_prompt="u1", raw_response="r1",
                       parsed_output='{"actions":[]}', parse_status="ok",
                       model_provider="openrouter", model_name="m", latency_ms=10),
        DecisionRecord(agent_id=agent.id, cycle_id="c2", kind="reflection", trigger="schedule",
                       system_prompt="s2", user_prompt="u2", raw_response=None,
                       parsed_output=None, parse_status="failed",
                       model_provider="openrouter", model_name="m", latency_ms=5),
    ])
    db_session.commit()
    client = _client(db_session)
    resp = client.get(f"/api/agents/{agent.id}/decisions")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["cycle_id"] == "c2"            # newest (higher id) first
    assert body[0]["parse_status"] == "failed"
    assert body[0]["raw_response"] is None
    assert body[1]["kind"] == "decision" and body[1]["latency_ms"] == 10


def test_get_decisions_empty_for_unknown_agent(db_session):
    client = _client(db_session)
    resp = client.get("/api/agents/9999/decisions")
    assert resp.status_code == 200 and resp.json() == []


def test_delete_agent_removes_decision_records(db_session):
    from app.db.models import DecisionRecord
    client = _client(db_session)
    aid = _mk(client, name="DoomedRec").json()["id"]
    db_session.add(DecisionRecord(agent_id=aid, cycle_id="c1", kind="decision", trigger="schedule",
                                  system_prompt="s", user_prompt="u", raw_response="r",
                                  parsed_output=None, parse_status="ok",
                                  model_provider="openrouter", model_name="m", latency_ms=1))
    db_session.commit()
    assert client.delete(f"/api/agents/{aid}").status_code == 204
    assert db_session.query(DecisionRecord).filter_by(agent_id=aid).count() == 0


def test_delete_agent_removes_decision_scores(db_session):
    from app.db.models import DecisionRecord, DecisionScore
    client = _client(db_session)
    aid = _mk(client, name="DoomedScore").json()["id"]
    rec = DecisionRecord(agent_id=aid, cycle_id="c", kind="decision", trigger="schedule",
                         system_prompt="s", user_prompt="u", raw_response="r",
                         parsed_output='{"actions":[]}', parse_status="ok",
                         model_provider="openrouter", model_name="m", latency_ms=1)
    db_session.add(rec); db_session.commit()
    db_session.add(DecisionScore(decision_record_id=rec.id, window="24h", n_actions=0, n_hits=0))
    db_session.commit()
    assert client.delete(f"/api/agents/{aid}").status_code == 204
    assert db_session.query(DecisionScore).filter_by(decision_record_id=rec.id).count() == 0


def test_get_benchmarks_returns_points_oldest_first(db_session):
    from app.db.models import BenchmarkSnapshot
    agent = Agent(name="Bm", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    db_session.add_all([
        BenchmarkSnapshot(agent_id=agent.id, kind="hodl_btc", equity_usd=Decimal("100")),
        BenchmarkSnapshot(agent_id=agent.id, kind="equal_weight", equity_usd=Decimal("101")),
    ])
    db_session.commit()
    client = _client(db_session)
    resp = client.get(f"/api/agents/{agent.id}/benchmarks")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert {p["kind"] for p in body} == {"hodl_btc", "equal_weight"}
    assert Decimal(body[0]["equity_usd"]) == Decimal("100")   # id-ascending (oldest first)


def test_get_benchmarks_empty_for_unknown_agent(db_session):
    client = _client(db_session)
    resp = client.get("/api/agents/9999/benchmarks")
    assert resp.status_code == 200 and resp.json() == []


def test_delete_agent_removes_benchmark_rows(db_session):
    from app.db.models import BenchmarkBasis, BenchmarkSnapshot
    client = _client(db_session)
    aid = _mk(client, name="DoomedBm").json()["id"]
    db_session.add(BenchmarkBasis(agent_id=aid, universe_json="[]", start_prices_json="{}",
                                  initial_capital=Decimal("100")))
    db_session.add(BenchmarkSnapshot(agent_id=aid, kind="hodl_btc", equity_usd=Decimal("100")))
    db_session.commit()
    assert client.delete(f"/api/agents/{aid}").status_code == 204
    assert db_session.query(BenchmarkBasis).filter_by(agent_id=aid).count() == 0
    assert db_session.query(BenchmarkSnapshot).filter_by(agent_id=aid).count() == 0


def _decision_with_score(db_session, agent_id, model_name, window, n_actions, n_hits):
    from app.db.models import DecisionRecord, DecisionScore
    rec = DecisionRecord(agent_id=agent_id, cycle_id="c", kind="decision", trigger="schedule",
                         system_prompt="s", user_prompt="u", raw_response="r",
                         parsed_output='{"actions":[]}', parse_status="ok",
                         model_provider="openrouter", model_name=model_name, latency_ms=1)
    db_session.add(rec); db_session.commit()
    db_session.add(DecisionScore(decision_record_id=rec.id, window=window,
                                 n_actions=n_actions, n_hits=n_hits))
    db_session.commit()
    return rec


def test_agent_metrics_reports_return_drawdown_and_hitrate(db_session):
    from app.db.models import EquitySnapshot, BenchmarkSnapshot
    agent = Agent(name="Mx", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    for v in ("100", "120", "90"):
        db_session.add(EquitySnapshot(agent_id=agent.id, equity_usd=Decimal(v)))
    db_session.add(BenchmarkSnapshot(agent_id=agent.id, kind="hodl_btc", equity_usd=Decimal("100")))
    db_session.add(BenchmarkSnapshot(agent_id=agent.id, kind="hodl_btc", equity_usd=Decimal("110")))
    db_session.commit()
    _decision_with_score(db_session, agent.id, "deepseek/x", "24h", 4, 3)
    client = _client(db_session)
    body = client.get(f"/api/agents/{agent.id}/metrics").json()
    assert Decimal(body["return_pct"]) == Decimal("-10")            # 100 → 90
    assert Decimal(body["max_drawdown_pct"]) == Decimal("25")       # 120 → 90
    assert Decimal(body["hit_rate_24h"]) == Decimal("75")
    assert body["hit_rate_7d"] is None                             # no 7d scores
    assert Decimal(body["benchmarks"]["hodl_btc"]["return_pct"]) == Decimal("10")


def test_agent_metrics_unknown_agent_is_all_zero(db_session):
    client = _client(db_session)
    body = client.get("/api/agents/9999/metrics").json()
    assert Decimal(body["return_pct"]) == Decimal("0")
    assert body["benchmarks"] == {} and body["hit_rate_24h"] is None


def test_model_metrics_aggregates_hitrate_by_model(db_session):
    client = _client(db_session)
    aid = _mk(client, name="MdlA").json()["id"]
    _decision_with_score(db_session, aid, "deepseek/x", "24h", 2, 2)
    _decision_with_score(db_session, aid, "deepseek/x", "24h", 2, 1)
    _decision_with_score(db_session, aid, "glm/y", "24h", 1, 0)
    body = client.get("/api/metrics/by-model").json()
    by_model = {m["model_name"]: m for m in body}
    assert Decimal(by_model["deepseek/x"]["hit_rate_24h"]) == Decimal("75")   # 3 hits / 4 actions
    assert Decimal(by_model["glm/y"]["hit_rate_24h"]) == Decimal("0")
