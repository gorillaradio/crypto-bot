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


_AGENT = {"name": "A", "instructions": "", "duration_days": 7,
          "model_name": "deepseek/deepseek-v4-flash"}


def test_writes_require_admin(client, db_session):
    assert client.post("/api/agents", json=_AGENT).status_code == 401
    db_session.add(ShareLink(token="v1")); db_session.commit()
    client.post("/api/auth/viewer", json={"token": "v1"})
    assert client.post("/api/agents", json=_AGENT).status_code == 401   # viewer cannot write
    client.post("/api/auth/login", json={"password": "secret"})
    assert client.post("/api/agents", json=_AGENT).status_code == 201   # admin can


def test_reads_require_a_session(client, db_session):
    assert client.get("/api/agents").status_code == 401
    db_session.add(ShareLink(token="v2")); db_session.commit()
    client.post("/api/auth/viewer", json={"token": "v2"})
    assert client.get("/api/agents").status_code == 200                 # viewer can read


def test_decisions_require_a_session(client, db_session):
    assert client.get("/api/agents/1/decisions").status_code == 401
    db_session.add(ShareLink(token="v3")); db_session.commit()
    client.post("/api/auth/viewer", json={"token": "v3"})
    assert client.get("/api/agents/1/decisions").status_code == 200   # viewer can read


def test_benchmarks_require_a_session(client, db_session):
    assert client.get("/api/agents/1/benchmarks").status_code == 401
    db_session.add(ShareLink(token="v4")); db_session.commit()
    client.post("/api/auth/viewer", json={"token": "v4"})
    assert client.get("/api/agents/1/benchmarks").status_code == 200   # viewer can read


def test_open_lifecycles_reject_anonymous_and_revoked_viewer(client, db_session):
    assert client.get("/api/agents/1/lifecycles/open").status_code == 401
    link = ShareLink(token="life-viewer")
    db_session.add(link); db_session.commit()
    client.post("/api/auth/viewer", json={"token": link.token})
    assert client.get("/api/agents/1/lifecycles/open").status_code == 404
    db_session.delete(link); db_session.commit()
    assert client.get("/api/agents/1/lifecycles/open").status_code == 401


def test_lifecycle_collection_rejects_anonymous_and_revoked_viewer(client, db_session):
    assert client.get("/api/agents/1/lifecycles").status_code == 401
    link = ShareLink(token="collection-viewer")
    db_session.add(link); db_session.commit()
    client.post("/api/auth/viewer", json={"token": link.token})
    assert client.get("/api/agents/1/lifecycles").status_code == 404
    db_session.delete(link); db_session.commit()
    assert client.get("/api/agents/1/lifecycles").status_code == 401


def test_share_links_are_admin_only(client):
    assert client.get("/api/share-links").status_code == 401
    client.post("/api/auth/login", json={"password": "secret"})
    created = client.post("/api/share-links", json={"label": "amici"})
    assert created.status_code == 201
    body = created.json()
    assert body["url"].endswith("#" + body["token"])
    assert any(l["token"] == body["token"] for l in client.get("/api/share-links").json())


def test_revoke_blocks_viewer_immediately(db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "secret")
    app.dependency_overrides[auth.session_dep] = lambda: db_session
    admin = TestClient(app, base_url="https://testserver")
    viewer = TestClient(app, base_url="https://testserver")
    admin.post("/api/auth/login", json={"password": "secret"})
    link = admin.post("/api/share-links", json={}).json()
    viewer.post("/api/auth/viewer", json={"token": link["token"]})
    assert viewer.get("/api/agents").status_code == 200
    assert admin.delete(f"/api/share-links/{link['id']}").status_code == 204
    assert viewer.get("/api/agents").status_code == 401                 # revoke is immediate
    assert viewer.get("/api/auth/me").json() == {"role": None}


def test_delete_missing_share_link_404(client):
    client.post("/api/auth/login", json={"password": "secret"})
    assert client.delete("/api/share-links/9999").status_code == 404


def test_metrics_require_a_session(client, db_session):
    assert client.get("/api/agents/1/metrics").status_code == 401
    assert client.get("/api/metrics/by-model").status_code == 401
    db_session.add(ShareLink(token="v5")); db_session.commit()
    client.post("/api/auth/viewer", json={"token": "v5"})
    assert client.get("/api/agents/1/metrics").status_code == 200
    assert client.get("/api/metrics/by-model").status_code == 200


def test_memory_journal_requires_a_session(client, db_session):
    assert client.get("/api/agents/1/memory/journal").status_code == 401
    db_session.add(ShareLink(token="v6")); db_session.commit()
    client.post("/api/auth/viewer", json={"token": "v6"})
    assert client.get("/api/agents/1/memory/journal").status_code == 200   # viewer can read


def test_no_policy_mutation_endpoint_exists():
    # Le policy sono solo LLM-authored: nessun endpoint HTTP deve mutarle.
    # Verifica diretta sulle route (indipendente dall'ambiente): un POST nudo
    # colpirebbe il catch-all StaticFiles della SPA e darebbe 405, non 404.
    mutators = {"POST", "PUT", "PATCH", "DELETE"}
    assert not any(
        "memory/policy" in getattr(r, "path", "")
        and (getattr(r, "methods", None) or set()) & mutators
        for r in app.routes
    )
