from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api import routes
from app.db.models import Agent, EquitySnapshot


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
