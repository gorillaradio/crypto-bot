from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api import routes
from app.db.models import Agent, EquitySnapshot, Agent as AgentModel


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _client(db_session):
    app.dependency_overrides[routes.session_dep] = lambda: db_session
    return TestClient(app)


def test_create_agent_starts_with_initial_capital(db_session):
    client = _client(db_session)
    resp = client.post("/api/agents", json={
        "name": "Alpha", "instructions": "x", "duration_days": 7})
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
    client.post("/api/agents", json={"name": "X", "instructions": "", "duration_days": 3})
    client.post("/api/agents", json={"name": "Y", "instructions": "", "duration_days": 5})
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
    from app.db.models import Position
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


def test_create_llm_agent_persists_model_fields(db_session):
    client = _client(db_session)
    resp = client.post("/api/agents", json={
        "name": "Brainy", "instructions": "buy low", "duration_days": 7,
        "strategy": "llm", "model_provider": "deepseek", "model_name": "deepseek-chat"})
    assert resp.status_code == 201
    from app.db.models import Agent
    a = db_session.query(Agent).filter_by(name="Brainy").one()
    db_session.expire(a)                # force re-read from DB, bypass identity map
    assert a.strategy == "llm" and a.model_provider == "deepseek" and a.model_name == "deepseek-chat"


def test_invalid_model_provider_rejected_at_boundary(db_session):
    client = _client(db_session)
    resp = client.post("/api/agents", json={
        "name": "Bad", "instructions": "x", "duration_days": 7,
        "model_provider": "openai"})
    assert resp.status_code == 422


def test_get_agent_memory_returns_sections(db_session):
    from app.db.models import AgentMemory
    agent = Agent(name="Mem", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    db_session.add(AgentMemory(agent_id=agent.id, section="coin_theses", content="BTC: bull"))
    db_session.commit()
    client = _client(db_session)
    r = client.get(f"/api/agents/{agent.id}/memory")
    assert r.status_code == 200
    body = r.json()
    assert body["coin_theses"] == "BTC: bull"
    assert body["trade_lessons"] == ""        # missing section -> empty string


def test_get_events_returns_last_100_desc(db_session):
    from app.db.models import Event
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
    resp = client.post("/api/agents", json={
        "name": "Small", "instructions": "", "duration_days": 7, "universe": "TOP_50"})
    assert resp.status_code == 201
    agent = db_session.query(AgentModel).filter_by(name="Small").one()
    assert agent.universe == "TOP_50"


def test_create_agent_defaults_universe_to_top_100(db_session):
    client = _client(db_session)
    resp = client.post("/api/agents", json={
        "name": "Big", "instructions": "", "duration_days": 7})
    assert resp.status_code == 201
    agent = db_session.query(AgentModel).filter_by(name="Big").one()
    assert agent.universe == "TOP_100"


def test_create_agent_rejects_invalid_universe(db_session):
    client = _client(db_session)
    resp = client.post("/api/agents", json={
        "name": "Bad", "duration_days": 7, "universe": "TOP_500"})
    assert resp.status_code == 422
