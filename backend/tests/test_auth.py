import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api import auth
from app.core.config import settings
from app.db.models import ShareLink


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "secret")
    app.dependency_overrides[auth.session_dep] = lambda: db_session
    # https base_url so the Secure session cookie is sent back across requests
    return TestClient(app, base_url="https://testserver")


def test_me_is_anonymous_without_session(client):
    assert client.get("/api/auth/me").json() == {"role": None}


def test_login_correct_password_then_me_is_admin(client):
    r = client.post("/api/auth/login", json={"password": "secret"})
    assert r.status_code == 200
    assert r.json() == {"role": "admin"}
    assert client.get("/api/auth/me").json() == {"role": "admin"}


def test_login_wrong_password_401(client):
    assert client.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    assert client.get("/api/auth/me").json() == {"role": None}


def test_login_disabled_when_admin_password_empty(db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "")
    app.dependency_overrides[auth.session_dep] = lambda: db_session
    c = TestClient(app, base_url="https://testserver")
    assert c.post("/api/auth/login", json={"password": ""}).status_code == 401


def test_logout_clears_session(client):
    client.post("/api/auth/login", json={"password": "secret"})
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").json() == {"role": None}


def test_viewer_exchange_valid_token(client, db_session):
    db_session.add(ShareLink(label="amici", token="tok-abc"))
    db_session.commit()
    r = client.post("/api/auth/viewer", json={"token": "tok-abc"})
    assert r.status_code == 200
    assert r.json() == {"role": "viewer"}
    assert client.get("/api/auth/me").json() == {"role": "viewer"}


def test_viewer_exchange_invalid_token_401(client):
    assert client.post("/api/auth/viewer", json={"token": "ghost"}).status_code == 401
    assert client.get("/api/auth/me").json() == {"role": None}
