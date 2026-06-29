from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api import routes
from app.db.models import Agent, EquitySnapshot, Agent as AgentModel, Position, Trade, Event, AgentMemory


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _client(db_session):
    app.dependency_overrides[routes.session_dep] = lambda: db_session
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
