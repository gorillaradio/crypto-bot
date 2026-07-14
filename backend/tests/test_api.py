from datetime import datetime, timezone, timedelta
from decimal import Decimal
import base64
import json
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api import routes, auth
from app.db.models import Agent, EquitySnapshot, Agent as AgentModel, Position, PositionLifecycle, Trade, Event, MemoryEntry
from app.trading.engine import execute_buy, execute_sell
from app.brain.context import CoinSnapshot
from app.market.binance import LifecycleMarketSnapshot


@pytest.fixture(autouse=True)
def _clear_overrides():
    app.dependency_overrides[routes.lifecycle_market_dep] = lambda: LifecycleMarketFake(
        LifecycleMarketSnapshot(
            as_of=datetime(2026, 7, 14, 10, tzinfo=timezone.utc),
            prices={}, series_24h={},
        )
    )
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
                  cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"))
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
                  cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"))
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
                  cash_usd=Decimal("0"), initial_capital_usd=Decimal("0"))
    db_session.add(agent); db_session.commit()
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("0.5"), avg_price=Decimal("100")))
    db_session.commit()
    client = _client(db_session)
    _use_fake_market()                       # endpoint ora async + market_dep → stub, niente rete
    rows = client.get(f"/api/agents/{agent.id}/positions").json()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTCUSDT"
    assert Decimal(rows[0]["cost_basis"]) == Decimal("50.0")


def test_get_positions_includes_live_pnl(db_session):
    agent = Agent(name="P", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("0"), initial_capital_usd=Decimal("0"))
    db_session.add(agent); db_session.commit()
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("2"), avg_price=Decimal("100")))
    db_session.commit()
    client = _client(db_session)
    _use_fake_market([CoinSnapshot("BTCUSDT", Decimal("150"), Decimal("1"))])
    row = client.get(f"/api/agents/{agent.id}/positions").json()[0]
    assert Decimal(row["last_price"]) == Decimal("150")
    assert Decimal(row["unrealized_pnl_pct"]) == Decimal("50")     # (150-100)/100*100
    assert Decimal(row["market_value"]) == Decimal("300")          # 2*150


def test_get_positions_pnl_none_when_symbol_missing(db_session):
    agent = Agent(name="P", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("0"), initial_capital_usd=Decimal("0"))
    db_session.add(agent); db_session.commit()
    db_session.add(Position(agent_id=agent.id, symbol="GONEUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    client = _client(db_session)
    _use_fake_market([CoinSnapshot("BTCUSDT", Decimal("150"), Decimal("1"))])  # snapshot senza GONEUSDT
    row = client.get(f"/api/agents/{agent.id}/positions").json()[0]
    assert row["last_price"] is None
    assert row["unrealized_pnl_pct"] is None
    assert row["market_value"] is None
    assert Decimal(row["cost_basis"]) == Decimal("100")


def test_get_positions_degrades_to_cost_only_when_market_fails(db_session):
    agent = Agent(name="P", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("0"), initial_capital_usd=Decimal("0"))
    db_session.add(agent); db_session.commit()
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    client = _client(db_session)
    app.dependency_overrides[routes.market_dep] = lambda: FailingMarketPreview()
    resp = client.get(f"/api/agents/{agent.id}/positions")
    assert resp.status_code == 200                    # NON 502: le posizioni sono un pannello centrale
    row = resp.json()[0]
    assert row["last_price"] is None
    assert Decimal(row["cost_basis"]) == Decimal("100")


def test_get_open_lifecycles_uses_canonical_ledger_and_returns_net_result(db_session):
    agent = Agent(name="Ledger API", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("200"), initial_capital_usd=Decimal("200"))
    db_session.add(agent); db_session.commit()
    execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"),
                cycle_id="open-cycle", rationale="open")
    execute_sell(db_session, agent, "BTCUSDT", Decimal("0.4"), Decimal("120"),
                 cycle_id="partial-cycle", rationale="trim")
    # Un payload evento volutamente falso non deve essere una fonte del riepilogo.
    event = db_session.query(Event).filter_by(kind="trade").order_by(Event.id.desc()).first()
    event.payload = {**event.payload, "position_summary": {"realized_total_usd": "999999"}}
    db_session.commit()
    client = _client(db_session)
    _use_fake_market([CoinSnapshot("BTCUSDT", Decimal("110"), Decimal("1"))])

    response = client.get(f"/api/agents/{agent.id}/lifecycles/open")

    assert response.status_code == 200
    row = response.json()[0]
    assert row["lifecycle_id"]
    assert row["cycle_id"] == "partial-cycle"
    assert row["status"] == "open"
    assert Decimal(row["quantity"]) == Decimal("0.6")
    assert Decimal(row["exposure_usd"]) == Decimal("66")
    assert Decimal(row["fees_usd"]) == Decimal("0.148")
    assert Decimal(row["net_result_usd"]) == Decimal("13.852")
    assert Decimal(row["net_result_pct"]) == Decimal("13.852")
    assert row["evaluation"]["action"] == "SELL"
    assert row["evaluation"]["rationale"] == "trim"


def test_get_open_lifecycles_returns_404_for_missing_agent(db_session):
    client = _client(db_session)
    assert client.get("/api/agents/999/lifecycles/open").status_code == 404


def _lifecycle_agent(db_session):
    agent = Agent(name="Lifecycle collection", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("1000"), initial_capital_usd=Decimal("1000"))
    db_session.add(agent); db_session.commit()
    return agent


class LifecycleMarketFake:
    def __init__(self, snapshot: LifecycleMarketSnapshot):
        self._snapshot = snapshot
        self._last_snapshot = None
        self.fail = False
        self.calls = 0

    @property
    def last_lifecycle_market_snapshot(self):
        return self._last_snapshot

    async def get_lifecycle_market_snapshot(self, symbols):
        self.calls += 1
        if self.fail:
            raise RuntimeError("market unavailable")
        self._last_snapshot = self._snapshot
        return self._snapshot

    async def get_universe_snapshot(self, symbols):
        return [
            CoinSnapshot(symbol, self._snapshot.prices[symbol], Decimal("0"))
            for symbol in symbols
            if symbol in self._snapshot.prices
        ]


def test_lifecycle_market_returns_one_timestamped_snapshot_for_value_weight_order_and_series(db_session):
    agent = _lifecycle_agent(db_session)
    execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"), cycle_id="btc")
    execute_buy(db_session, agent, "ETHUSDT", Decimal("100"), Decimal("100"), cycle_id="eth")
    agent.cash_usd = Decimal("600")
    db_session.commit()
    market = LifecycleMarketFake(LifecycleMarketSnapshot(
        as_of=datetime(2026, 7, 14, 10, tzinfo=timezone.utc),
        prices={"BTCUSDT": Decimal("100"), "ETHUSDT": Decimal("300")},
        series_24h={
            "BTCUSDT": [Decimal("100"), Decimal("100")],
            "ETHUSDT": [Decimal("90"), Decimal("100")],
        },
    ))
    _client(db_session)
    app.dependency_overrides[routes.lifecycle_market_dep] = lambda: market
    client = TestClient(app, raise_server_exceptions=False)

    body = client.get(f"/api/agents/{agent.id}/lifecycles").json()

    assert body["market"]["status"] == "fresh"
    assert body["market"]["as_of"]
    assert [row["symbol"] for row in body["items"]] == ["ETHUSDT", "BTCUSDT"]
    assert Decimal(body["items"][0]["exposure_usd"]) == Decimal("300")
    assert Decimal(body["items"][0]["portfolio_weight_pct"]) == Decimal("30")
    assert body["items"][0]["market_series_24h"] == ["90", "100"]


def test_lifecycle_market_projects_series_onto_closed_rows_in_closed_and_all_states(db_session):
    agent = _lifecycle_agent(db_session)
    execute_buy(db_session, agent, "SOLUSDT", Decimal("100"), Decimal("100"), cycle_id="open")
    execute_sell(db_session, agent, "SOLUSDT", Decimal("1"), Decimal("110"), cycle_id="close")
    execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"), cycle_id="btc")
    market = LifecycleMarketFake(LifecycleMarketSnapshot(
        as_of=datetime(2026, 7, 14, 10, tzinfo=timezone.utc),
        prices={"BTCUSDT": Decimal("120"), "SOLUSDT": Decimal("110")},
        series_24h={
            "BTCUSDT": [Decimal("100"), Decimal("120")],
            "SOLUSDT": [Decimal("90"), Decimal("100")],
        },
    ))
    client = _client(db_session)
    app.dependency_overrides[routes.lifecycle_market_dep] = lambda: market

    closed = client.get(f"/api/agents/{agent.id}/lifecycles?state=closed").json()["items"][0]
    all_rows = client.get(f"/api/agents/{agent.id}/lifecycles?state=all").json()["items"]

    assert closed["exposure_usd"] is None
    assert closed["market_series_24h"] == ["90", "100"]
    assert [row["market_series_24h"] for row in all_rows] == [["100", "120"], ["90", "100"]]


def test_lifecycle_market_uses_timestamped_stale_snapshot_when_provider_fails(db_session):
    agent = _lifecycle_agent(db_session)
    execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"), cycle_id="btc")
    market = LifecycleMarketFake(LifecycleMarketSnapshot(
        as_of=datetime(2026, 7, 14, 10, tzinfo=timezone.utc),
        prices={"BTCUSDT": Decimal("120")},
        series_24h={"BTCUSDT": [Decimal("100"), Decimal("120")]},
    ))
    client = _client(db_session)
    app.dependency_overrides[routes.lifecycle_market_dep] = lambda: market
    url = f"/api/agents/{agent.id}/lifecycles"

    first = client.get(url).json()
    market.fail = True
    second = client.get(url).json()

    assert second["market"] == {"status": "stale", "as_of": first["market"]["as_of"]}
    assert second["items"][0]["exposure_usd"] == first["items"][0]["exposure_usd"]


def test_lifecycle_market_explicitly_marks_market_unavailable_without_cache(db_session):
    agent = _lifecycle_agent(db_session)
    execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"), cycle_id="btc")
    market = LifecycleMarketFake(LifecycleMarketSnapshot(
        as_of=datetime(2026, 7, 14, 10, tzinfo=timezone.utc),
        prices={"BTCUSDT": Decimal("120")},
        series_24h={"BTCUSDT": [Decimal("100"), Decimal("120")]},
    ))
    market.fail = True
    client = _client(db_session)
    app.dependency_overrides[routes.lifecycle_market_dep] = lambda: market

    body = client.get(f"/api/agents/{agent.id}/lifecycles").json()

    assert body["market"] == {"status": "unavailable", "as_of": None}
    assert body["items"][0]["exposure_usd"] is None
    assert body["items"][0]["portfolio_weight_pct"] is None
    assert body["items"][0]["market_series_24h"] is None


def test_lifecycle_market_does_not_fetch_for_an_empty_displayed_collection(db_session):
    agent = _lifecycle_agent(db_session)
    market = LifecycleMarketFake(LifecycleMarketSnapshot(
        as_of=datetime(2026, 7, 14, 10, tzinfo=timezone.utc),
        prices={}, series_24h={},
    ))
    client = _client(db_session)
    app.dependency_overrides[routes.lifecycle_market_dep] = lambda: market

    body = client.get(f"/api/agents/{agent.id}/lifecycles").json()

    assert body == {"items": [], "next_cursor": None, "market": {"status": "unavailable", "as_of": None}}
    assert market.calls == 0


def test_lifecycle_collection_defaults_to_open_and_closed_window_is_seven_days(db_session):
    agent = _lifecycle_agent(db_session)
    execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"), cycle_id="btc")
    execute_buy(db_session, agent, "ETHUSDT", Decimal("100"), Decimal("100"), cycle_id="eth")
    execute_sell(db_session, agent, "ETHUSDT", Decimal("1"), Decimal("110"), cycle_id="eth-close")
    eth_lifecycle = db_session.query(PositionLifecycle).filter_by(symbol="ETHUSDT").one()
    eth_lifecycle.closed_at = datetime.now(timezone.utc) - timedelta(days=8)
    db_session.commit()
    client = _client(db_session)
    _use_fake_market([CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("1"))])

    assert [row["symbol"] for row in client.get(f"/api/agents/{agent.id}/lifecycles").json()["items"]] == ["BTCUSDT"]
    assert client.get(f"/api/agents/{agent.id}/lifecycles?state=closed").json()["items"] == []
    all_rows = client.get(
        f"/api/agents/{agent.id}/lifecycles?state=all&closed_since=2020-01-01T00:00:00Z"
    ).json()["items"]
    assert [row["status"] for row in all_rows] == ["open", "closed"]


def test_closed_since_never_filters_open_lifecycles_and_closed_result_is_net_of_fees(db_session):
    agent = _lifecycle_agent(db_session)
    execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"), cycle_id="open")
    execute_buy(db_session, agent, "ETHUSDT", Decimal("100"), Decimal("100"), cycle_id="closed")
    execute_sell(db_session, agent, "ETHUSDT", Decimal("1"), Decimal("120"), cycle_id="close")
    client = _client(db_session)
    _use_fake_market([CoinSnapshot("BTCUSDT", Decimal("110"), Decimal("1"))])

    body = client.get(
        f"/api/agents/{agent.id}/lifecycles?state=all&closed_since=2999-01-01T00:00:00Z"
    ).json()

    assert [row["symbol"] for row in body["items"]] == ["BTCUSDT"]
    closed = client.get(
        f"/api/agents/{agent.id}/lifecycles?state=closed&closed_since=2020-01-01T00:00:00Z"
    ).json()["items"][0]
    assert Decimal(closed["fees_usd"]) == Decimal("0.22")
    assert Decimal(closed["net_result_usd"]) == Decimal("19.78")
    assert Decimal(closed["net_result_pct"]) == Decimal("19.78")
    assert closed["quantity"] is None and closed["exposure_usd"] is None


@pytest.mark.parametrize("query", [
    "state=wat", "closed_since=nope", "limit=0", "limit=101", "cursor=nope",
])
def test_lifecycle_collection_rejects_invalid_query_values(db_session, query):
    agent = _lifecycle_agent(db_session)
    assert _client(db_session).get(f"/api/agents/{agent.id}/lifecycles?{query}").status_code == 422


@pytest.mark.parametrize("limit", [1, 100])
def test_lifecycle_collection_accepts_limit_boundaries(db_session, limit):
    agent = _lifecycle_agent(db_session)
    response = _client(db_session).get(f"/api/agents/{agent.id}/lifecycles?limit={limit}")
    assert response.status_code == 200


def test_lifecycle_collection_order_and_cursor_have_no_gaps_at_equal_timestamps(db_session):
    agent = _lifecycle_agent(db_session)
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        execute_buy(db_session, agent, symbol, Decimal("100"), Decimal("100"), cycle_id=symbol)
        execute_sell(db_session, agent, symbol, Decimal("1"), Decimal("110"), cycle_id=f"{symbol}-close")
    same_time = datetime(2026, 7, 12, 12, tzinfo=timezone.utc)
    lifecycles = db_session.query(PositionLifecycle).all()
    for lifecycle in lifecycles:
        lifecycle.closed_at = same_time
    db_session.commit()
    client = _client(db_session)

    first = client.get(f"/api/agents/{agent.id}/lifecycles?state=closed&limit=2").json()
    second = client.get(
        f"/api/agents/{agent.id}/lifecycles?state=closed&limit=2&cursor={first['next_cursor']}"
    ).json()

    ids = [row["lifecycle_id"] for row in first["items"] + second["items"]]
    assert ids == sorted((row.id for row in lifecycles), reverse=True)
    assert len(ids) == len(set(ids)) == 3
    assert second["next_cursor"] is None


def test_open_collection_is_unpaginated_and_uses_live_exposure_order(db_session):
    agent = _lifecycle_agent(db_session)
    for symbol, value in (("BTCUSDT", "200"), ("ETHUSDT", "150"), ("SOLUSDT", "100")):
        execute_buy(db_session, agent, symbol, Decimal(value), Decimal("100"), cycle_id=symbol)
    client = _client(db_session)
    _use_fake_market([
        CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1")),
        CoinSnapshot("ETHUSDT", Decimal("100"), Decimal("1")),
        CoinSnapshot("SOLUSDT", Decimal("100"), Decimal("1")),
    ])

    page = client.get(f"/api/agents/{agent.id}/lifecycles?limit=1").json()

    assert [row["symbol"] for row in page["items"]] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert page["next_cursor"] is None


def test_lifecycle_collection_cursor_is_bound_to_state_and_closed_since(db_session):
    agent = _lifecycle_agent(db_session)
    for symbol in ("BTCUSDT", "ETHUSDT"):
        execute_buy(db_session, agent, symbol, Decimal("100"), Decimal("100"), cycle_id=symbol)
        execute_sell(db_session, agent, symbol, Decimal("1"), Decimal("110"), cycle_id=f"{symbol}-close")
    client = _client(db_session)
    cursor = client.get(f"/api/agents/{agent.id}/lifecycles?state=closed&limit=1").json()["next_cursor"]

    assert client.get(
        f"/api/agents/{agent.id}/lifecycles?state=all&cursor={cursor}"
    ).status_code == 422
    assert client.get(
        f"/api/agents/{agent.id}/lifecycles?state=closed&closed_since=2020-01-01T00:00:00Z&cursor={cursor}"
    ).status_code == 422


def test_lifecycle_collection_rejects_cross_agent_and_invalid_key_cursors(db_session):
    agent = _lifecycle_agent(db_session)
    execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"), cycle_id="btc")
    execute_sell(db_session, agent, "BTCUSDT", Decimal("1"), Decimal("110"), cycle_id="btc-close")
    execute_buy(db_session, agent, "ETHUSDT", Decimal("100"), Decimal("100"), cycle_id="eth")
    execute_sell(db_session, agent, "ETHUSDT", Decimal("1"), Decimal("110"), cycle_id="eth-close")
    other = _lifecycle_agent(db_session)
    client = _client(db_session)
    cursor = client.get(f"/api/agents/{agent.id}/lifecycles?state=closed&limit=1").json()["next_cursor"]

    assert client.get(f"/api/agents/{other.id}/lifecycles?state=closed&cursor={cursor}").status_code == 422
    padded = cursor + "=" * (-len(cursor) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded).decode())
    payload["key"][0] = "not-a-date"
    invalid = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    assert client.get(f"/api/agents/{agent.id}/lifecycles?state=closed&cursor={invalid}").status_code == 422

    for non_object in ([], None, "cursor", 1):
        invalid = base64.urlsafe_b64encode(json.dumps(non_object).encode()).decode().rstrip("=")
        assert client.get(f"/api/agents/{agent.id}/lifecycles?state=closed&cursor={invalid}").status_code == 422


def test_lifecycle_collection_keeps_successive_lives_of_same_symbol_distinct(db_session):
    agent = _lifecycle_agent(db_session)
    execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"), cycle_id="first")
    execute_sell(db_session, agent, "BTCUSDT", Decimal("1"), Decimal("110"), cycle_id="first-close")
    execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"), cycle_id="second")
    client = _client(db_session)
    _use_fake_market([CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))])

    all_rows = client.get(f"/api/agents/{agent.id}/lifecycles?state=all").json()["items"]
    closed_rows = client.get(f"/api/agents/{agent.id}/lifecycles?state=closed").json()["items"]

    assert [row["status"] for row in all_rows] == ["open", "closed"]
    assert len({row["lifecycle_id"] for row in all_rows}) == 2
    assert [row["lifecycle_id"] for row in closed_rows] == [all_rows[1]["lifecycle_id"]]


def test_lifecycle_collection_closed_and_all_use_documented_order_with_ties(db_session):
    agent = _lifecycle_agent(db_session)
    for symbol in ("BTCUSDT", "ETHUSDT"):
        execute_buy(db_session, agent, symbol, Decimal("100"), Decimal("100"), cycle_id=f"{symbol}-open")
        execute_sell(db_session, agent, symbol, Decimal("1"), Decimal("110"), cycle_id=f"{symbol}-close")
    execute_buy(db_session, agent, "SOLUSDT", Decimal("100"), Decimal("100"), cycle_id="still-open")
    tied_close = datetime(2026, 7, 12, 12, tzinfo=timezone.utc)
    closed_lifecycles = db_session.query(PositionLifecycle).filter(
        PositionLifecycle.closed_at.is_not(None)
    ).all()
    for lifecycle in closed_lifecycles:
        lifecycle.closed_at = tied_close
    db_session.commit()
    client = _client(db_session)
    _use_fake_market([CoinSnapshot("SOLUSDT", Decimal("100"), Decimal("1"))])

    closed_rows = client.get(f"/api/agents/{agent.id}/lifecycles?state=closed").json()["items"]
    all_rows = client.get(f"/api/agents/{agent.id}/lifecycles?state=all").json()["items"]

    expected_closed_ids = sorted((row.id for row in closed_lifecycles), reverse=True)
    assert [row["lifecycle_id"] for row in closed_rows] == expected_closed_ids
    assert [row["status"] for row in all_rows] == ["open", "closed", "closed"]
    assert [row["lifecycle_id"] for row in all_rows[1:]] == expected_closed_ids


def test_all_collection_returns_all_open_and_keyset_paginates_only_closed_history(db_session):
    agent = _lifecycle_agent(db_session)
    execute_buy(db_session, agent, "XRPUSDT", Decimal("100"), Decimal("100"), cycle_id="open")
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        execute_buy(db_session, agent, symbol, Decimal("100"), Decimal("100"), cycle_id=symbol)
        execute_sell(db_session, agent, symbol, Decimal("1"), Decimal("110"), cycle_id=f"{symbol}-close")
    client = _client(db_session)
    _use_fake_market([CoinSnapshot("XRPUSDT", Decimal("100"), Decimal("1"))])

    first = client.get(f"/api/agents/{agent.id}/lifecycles?state=all&limit=1").json()
    second = client.get(
        f"/api/agents/{agent.id}/lifecycles?state=all&limit=1&cursor={first['next_cursor']}"
    ).json()
    third = client.get(
        f"/api/agents/{agent.id}/lifecycles?state=all&limit=1&cursor={second['next_cursor']}"
    ).json()

    rows = first["items"] + second["items"] + third["items"]
    assert [row["status"] for row in first["items"]] == ["open", "closed"]
    assert [row["status"] for row in second["items"] + third["items"]] == ["closed", "closed"]
    assert len({row["lifecycle_id"] for row in rows}) == 4
    assert third["next_cursor"] is None


def test_open_lifecycle_api_tracks_increase_partial_close_and_second_life(db_session):
    agent = Agent(name="Lifecycle API", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("300"), initial_capital_usd=Decimal("300"))
    db_session.add(agent); db_session.commit()
    client = _client(db_session)
    _use_fake_market([CoinSnapshot("BTCUSDT", Decimal("110"), Decimal("1"))])

    execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), Decimal("100"), cycle_id="open")
    first_lifecycle = client.get(f"/api/agents/{agent.id}/lifecycles/open").json()[0]["lifecycle_id"]
    execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), Decimal("100"), cycle_id="increase")
    execute_sell(db_session, agent, "BTCUSDT", Decimal("0.4"), Decimal("120"), cycle_id="partial")
    row = client.get(f"/api/agents/{agent.id}/lifecycles/open").json()[0]
    assert row["lifecycle_id"] == first_lifecycle
    assert row["cycle_id"] == "partial"
    assert Decimal(row["quantity"]) == Decimal("0.6")

    execute_sell(db_session, agent, "BTCUSDT", Decimal("0.6"), Decimal("120"), cycle_id="close")
    assert client.get(f"/api/agents/{agent.id}/lifecycles/open").json() == []
    execute_buy(db_session, agent, "BTCUSDT", Decimal("40"), Decimal("80"), cycle_id="second")
    second = client.get(f"/api/agents/{agent.id}/lifecycles/open").json()[0]
    assert second["lifecycle_id"] != first_lifecycle
    assert second["cycle_id"] == "second"


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
                  duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    journal.append_entries(db_session, agent.id, "coin_theses", ["BTC: bull"])
    db_session.commit()
    client = _client(db_session)
    r = client.get(f"/api/agents/{agent.id}/memory")
    assert r.status_code == 200
    body = r.json()
    assert body["coin_theses"] == "BTC: bull"
    assert body["trade_lessons"] == ""


def test_get_agent_memory_includes_policy_and_caps(db_session):
    from app.brain import journal
    agent = Agent(name="Pol", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    rows = journal.append_entries(db_session, agent.id, "self_policy", ["mai più del 30% su una coin"])
    db_session.commit()
    client = _client(db_session)
    body = client.get(f"/api/agents/{agent.id}/memory").json()
    assert body["self_policy"] == [
        {"ref": journal.policy_ref(rows[0]), "content": "mai più del 30% su una coin"}]
    assert body["caps"]["coin_theses"] == journal.SECTION_CAPS["coin_theses"]
    assert body["caps"]["self_policy"] == journal.SECTION_CAPS["self_policy"]


def test_get_trades_returns_rows_newest_first(db_session):
    agent = Agent(name="T", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    t0 = datetime.now(timezone.utc) - timedelta(hours=2)
    db_session.add(Trade(agent_id=agent.id, symbol="BTCUSDT", side="BUY",
                         quantity=Decimal("0.5"), price=Decimal("100"), fee=Decimal("0.05"),
                         timestamp=t0))
    db_session.add(Trade(agent_id=agent.id, symbol="ETHUSDT", side="SELL",
                         quantity=Decimal("2"), price=Decimal("50"), fee=Decimal("0.1"),
                         timestamp=t0 + timedelta(hours=1)))
    db_session.commit()
    client = _client(db_session)
    resp = client.get(f"/api/agents/{agent.id}/trades")
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["symbol"] for r in rows] == ["ETHUSDT", "BTCUSDT"]   # newest first
    assert rows[0]["side"] == "SELL"
    assert Decimal(rows[0]["quantity"]) == Decimal("2")
    assert Decimal(rows[0]["price"]) == Decimal("50")
    assert Decimal(rows[0]["fee"]) == Decimal("0.1")


def test_get_trades_empty_for_agent_without_trades(db_session):
    agent = Agent(name="T0", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    client = _client(db_session)
    resp = client.get(f"/api/agents/{agent.id}/trades")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_events_returns_last_100_desc(db_session):
    agent = Agent(name="C", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"))
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
        MemoryEntry(agent_id=aid, section="coin_theses", content="BTC: bull"),
    ])
    db_session.commit()

    resp = client.delete(f"/api/agents/{aid}")
    assert resp.status_code == 204
    assert db_session.get(AgentModel, aid) is None
    assert db_session.query(Position).filter_by(agent_id=aid).count() == 0
    assert db_session.query(Trade).filter_by(agent_id=aid).count() == 0
    assert db_session.query(EquitySnapshot).filter_by(agent_id=aid).count() == 0
    assert db_session.query(Event).filter_by(agent_id=aid).count() == 0
    assert db_session.query(MemoryEntry).filter_by(agent_id=aid).count() == 0


def test_delete_agent_removes_lifecycle_ledger_rows(db_session):
    from app.db.models import PositionEvaluation, PositionLifecycle

    client = _client(db_session)
    aid = _mk(client, name="DoomedLedger").json()["id"]
    agent = db_session.get(Agent, aid)
    execute_buy(db_session, agent, "BTCUSDT", Decimal("25"), Decimal("100"), cycle_id="c1")

    assert client.delete(f"/api/agents/{aid}").status_code == 204
    assert db_session.query(PositionLifecycle).filter_by(agent_id=aid).count() == 0
    assert db_session.query(PositionEvaluation).filter_by(agent_id=aid).count() == 0
    assert db_session.query(Trade).filter_by(agent_id=aid).count() == 0


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
        self._last_lifecycle_market_snapshot = None
    async def get_top_symbols(self, quote, n): return self._symbols
    async def get_universe_snapshot(self, symbols): return self._snap
    async def get_price(self, symbol): return self._price
    @property
    def last_lifecycle_market_snapshot(self):
        return self._last_lifecycle_market_snapshot
    async def get_lifecycle_market_snapshot(self, symbols):
        snapshot = LifecycleMarketSnapshot(
            as_of=datetime.now(timezone.utc),
            prices={coin.symbol: coin.price for coin in self._snap},
            series_24h={coin.symbol: [] for coin in self._snap},
        )
        self._last_lifecycle_market_snapshot = snapshot
        return snapshot


def _use_fake_market(snapshot=None, price=Decimal("120")):
    snap = snapshot if snapshot is not None else [CoinSnapshot("BTCUSDT", price, Decimal("1"))]
    market = FakeMarketPreview(snap, price)
    app.dependency_overrides[routes.market_dep] = lambda: market
    app.dependency_overrides[routes.lifecycle_market_dep] = lambda: market


def test_get_prompt_returns_three_prompts(db_session):
    agent = Agent(name="P", instructions="compra basso",
                  duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"), model_name="deepseek/deepseek-v4-flash")
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
                  cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"), model_name="deepseek/deepseek-v4-flash")
    db_session.add(agent); db_session.commit()
    client = _client(db_session)
    app.dependency_overrides[routes.market_dep] = lambda: FailingMarketPreview()
    resp = client.get(f"/api/agents/{agent.id}/prompt")
    assert resp.status_code == 502


def test_get_decisions_returns_records_newest_first(db_session):
    from app.db.models import DecisionRecord
    agent = Agent(name="D", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"))
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
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"))
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
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"))
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
    hr = {h["window"]: h["hit_rate"] for h in body["hit_rates"]}
    assert Decimal(hr["24h"]) == Decimal("75")
    assert hr["7d"] is None                                        # no 7d scores
    assert [h["window"] for h in body["hit_rates"]] == ["24h", "7d"]   # short→long
    assert Decimal(body["benchmarks"]["hodl_btc"]["return_pct"]) == Decimal("10")


def test_agent_metrics_unknown_agent_is_all_zero(db_session):
    client = _client(db_session)
    body = client.get("/api/agents/9999/metrics").json()
    assert Decimal(body["return_pct"]) == Decimal("0")
    assert body["benchmarks"] == {}
    assert all(h["hit_rate"] is None for h in body["hit_rates"])


def test_agent_metrics_windows_follow_settings(db_session, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "scoring_window_short", "12h")
    monkeypatch.setattr(settings, "scoring_window_long", "3d")
    client = _client(db_session)
    aid = _mk(client, name="Wnd").json()["id"]
    _decision_with_score(db_session, aid, "deepseek/x", "12h", 2, 1)
    body = client.get(f"/api/agents/{aid}/metrics").json()
    hr = {h["window"]: h["hit_rate"] for h in body["hit_rates"]}
    assert set(hr) == {"12h", "3d"}
    assert Decimal(hr["12h"]) == Decimal("50")


def test_model_metrics_aggregates_hitrate_by_model(db_session):
    client = _client(db_session)
    aid = _mk(client, name="MdlA").json()["id"]
    _decision_with_score(db_session, aid, "deepseek/x", "24h", 2, 2)
    _decision_with_score(db_session, aid, "deepseek/x", "24h", 2, 1)
    _decision_with_score(db_session, aid, "glm/y", "24h", 1, 0)
    body = client.get("/api/metrics/by-model").json()
    by_model = {m["model_name"]: {h["window"]: h["hit_rate"] for h in m["hit_rates"]}
                for m in body}
    assert Decimal(by_model["deepseek/x"]["24h"]) == Decimal("75")   # 3 hits / 4 actions
    assert Decimal(by_model["glm/y"]["24h"]) == Decimal("0")


def test_model_metrics_ignores_stale_window_labels(db_session):
    # Righe DecisionScore scritte con label di una config precedente non devono
    # né crashare né inquinare i conteggi delle finestre correnti.
    client = _client(db_session)
    aid = _mk(client, name="Stale").json()["id"]
    _decision_with_score(db_session, aid, "deepseek/x", "24h", 2, 2)
    _decision_with_score(db_session, aid, "deepseek/x", "48h", 5, 0)   # label storica
    body = client.get("/api/metrics/by-model").json()
    m = body[0]
    assert m["n_scored_actions"] == 2                                  # solo finestre correnti
    hr = {h["window"]: h["hit_rate"] for h in m["hit_rates"]}
    assert Decimal(hr["24h"]) == Decimal("100")
    assert "48h" not in hr


def test_get_memory_journal_returns_entries_newest_first(db_session):
    from app.brain import journal
    agent = Agent(name="Jn", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    journal.append_entries(db_session, agent.id, "coin_theses", ["BTC: bull", "ETH: flat"], cycle_id="c1")
    db_session.commit()
    journal.apply_distillation(db_session, agent.id, "coin_theses", ["BTC+ETH: merged"], cycle_id="c2")
    db_session.commit()
    client = _client(db_session)
    resp = client.get(f"/api/agents/{agent.id}/memory/journal")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 3                                    # 2 superseded + 1 active
    assert body[0]["content"] == "BTC+ETH: merged" and body[0]["active"] is True   # newest first
    assert {e["active"] for e in body} == {True, False}


def test_memory_journal_includes_self_policy_entries(db_session):
    from app.brain import journal
    agent = Agent(name="Policy API", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    journal.append_entries(db_session, agent.id, "self_policy", ["Wait for evidence."])
    db_session.commit()
    client = _client(db_session)

    resp = client.get(f"/api/agents/{agent.id}/memory/journal")

    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["section"] == "self_policy"
    assert body[0]["content"] == "Wait for evidence."


def test_get_memory_journal_empty_for_unknown_agent(db_session):
    client = _client(db_session)
    resp = client.get("/api/agents/9999/memory/journal")
    assert resp.status_code == 200 and resp.json() == []


def test_get_observations_returns_recent_newest_first(db_session):
    from app.db.models import Observation
    db_session.add_all([
        Observation(source="CoinDesk", kind="news", title="old", url="http://a",
                    symbols_json='["BTC"]', dedup_hash="h1",
                    published_at=datetime(2026, 7, 1, tzinfo=timezone.utc)),
        Observation(source="Cointelegraph", kind="news", title="new", url=None,
                    symbols_json='[]', dedup_hash="h2",
                    published_at=datetime(2026, 7, 3, tzinfo=timezone.utc)),
    ])
    db_session.commit()
    client = _client(db_session)
    body = client.get("/api/observations").json()
    assert [o["title"] for o in body] == ["new", "old"]     # published_at desc
    assert body[0]["url"] is None and body[0]["symbols"] == []
    assert body[1]["source"] == "CoinDesk" and body[1]["symbols"] == ["BTC"]


def test_get_observations_empty(db_session):
    client = _client(db_session)
    assert client.get("/api/observations").json() == []


def test_get_brief_returns_filtered_view(db_session):
    import json as _json
    from app.db.models import MarketBrief
    agent = Agent(name="B", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    brief = {"regime": "risk-off",
             "highlights": [
                 {"symbol": "BTCUSDT", "snapshot": "s1", "signal": "bullish", "note": "n1"},
                 {"symbol": "SOLUSDT", "snapshot": "s2", "signal": "bearish", "note": "n2"}],
             "key_news": ["headline A"]}
    db_session.add(MarketBrief(cycle_id="c1", parsed_brief=_json.dumps(brief),
                               system_prompt="s", user_prompt="u", raw_response="r",
                               parse_status="ok", model_provider="openrouter",
                               model_name="m", latency_ms=10))
    db_session.commit()
    client = _client(db_session)
    _use_fake_market()                        # get_top_symbols → ["BTCUSDT"]
    body = client.get(f"/api/agents/{agent.id}/brief").json()
    assert body["regime"] == "risk-off"
    assert body["key_news"] == ["headline A"]
    assert [h["symbol"] for h in body["highlights"]] == ["BTCUSDT"]   # SOLUSDT fuori universo → filtrato
    assert body["highlights"][0]["signal"] == "bullish"


def test_get_brief_null_when_no_brief(db_session):
    agent = Agent(name="B", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    client = _client(db_session)
    _use_fake_market()
    resp = client.get(f"/api/agents/{agent.id}/brief")
    assert resp.status_code == 200 and resp.json() is None


def test_get_brief_404_when_agent_missing(db_session):
    client = _client(db_session)
    _use_fake_market()
    assert client.get("/api/agents/999/brief").status_code == 404


def test_get_brief_502_when_market_fails(db_session):
    import json as _json
    from app.db.models import MarketBrief
    agent = Agent(name="B", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    db_session.add(MarketBrief(cycle_id="c1",
                               parsed_brief=_json.dumps({"regime": "x", "highlights": [], "key_news": []}),
                               system_prompt="s", user_prompt="u", raw_response="r",
                               parse_status="ok", model_provider="openrouter", model_name="m", latency_ms=1))
    db_session.commit()
    client = _client(db_session)
    app.dependency_overrides[routes.market_dep] = lambda: FailingMarketPreview()
    assert client.get(f"/api/agents/{agent.id}/brief").status_code == 502


def test_events_expose_payload(db_session):
    client = _client(db_session)
    aid = _mk(client, name="Ev").json()["id"]
    db_session.add(Event(agent_id=aid, kind="trade", message="sold",
                         payload={"symbol": "BTCUSDT", "qty": "1.5"}, cycle_id="c1"))
    db_session.commit()
    resp = client.get(f"/api/agents/{aid}/events")
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["payload"] == {"symbol": "BTCUSDT", "qty": "1.5"}
    assert row["cycle_id"] == "c1"


def test_positions_expose_lifecycle_fields(db_session):
    agent = Agent(name="Lc", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("100"), initial_capital_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    opened = datetime.now(timezone.utc) - timedelta(hours=3)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100"),
                            opened_at=opened, realized_usd=Decimal("2.50")))
    db_session.commit()
    client = _client(db_session)
    _use_fake_market()
    row = client.get(f"/api/agents/{agent.id}/positions").json()[0]
    assert row["opened_at"] is not None
    assert Decimal(row["realized_usd"]) == Decimal("2.50")


def test_closed_positions_read_from_events(db_session):
    client = _client(db_session)
    aid = _mk(client, name="Closed").json()["id"]
    summary = {
        "opened_at": "2026-07-01T10:00:00+00:00",
        "held_minutes": 120,
        "invested_usd": "50.00",
        "realized_total_usd": "2.80",
        "realized_total_pct": "5.60",
        "closed_at": "2026-07-01T12:00:00+00:00",
    }
    db_session.add(Event(agent_id=aid, kind="trade", message="full close",
                         payload={"symbol": "SYNUSDT", "position_summary": summary},
                         cycle_id="c-close"))
    db_session.add(Event(agent_id=aid, kind="trade", message="partial sell",
                         payload={"symbol": "SYNUSDT"}, cycle_id="c-partial"))
    db_session.commit()
    resp = client.get(f"/api/agents/{aid}/positions/closed")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "SYNUSDT"
    assert Decimal(row["realized_total_usd"]) == Decimal("2.80")
    assert Decimal(row["realized_total_pct"]) == Decimal("5.60")
    assert Decimal(row["invested_usd"]) == Decimal("50.00")
    assert row["held_minutes"] == 120
    assert row["close_cycle_id"] == "c-close"


def test_agent_out_carries_decision_seconds(db_session):
    from app.core.config import settings
    client = _client(db_session)
    _mk(client, name="Dec")
    rows = client.get("/api/agents").json()
    assert len(rows) == 1
    assert rows[0]["decision_seconds"] == settings.decision_seconds


def test_return_pct_uses_agent_capital_not_config(db_session, monkeypatch):
    """Il cuore della fix: cambiare la config non deve riscrivere la storia."""
    agent = Agent(name="R", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("50"), initial_capital_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    client = _client(db_session)

    before = Decimal(str(client.get(f"/api/agents/{agent.id}").json()["return_pct"]))
    assert before == Decimal("-50")                      # 50 su 100

    monkeypatch.setattr(routes.settings, "initial_capital_usd", Decimal("500"))
    after = Decimal(str(client.get(f"/api/agents/{agent.id}").json()["return_pct"]))
    assert after == before                               # invariato: -50, non -90


def test_create_agent_stamps_initial_capital_from_config(db_session):
    client = _client(db_session)
    resp = _mk(client, name="Seeded")
    assert resp.status_code == 201
    agent = db_session.query(Agent).filter_by(name="Seeded").one()
    assert agent.initial_capital_usd == routes.settings.initial_capital_usd
    assert agent.cash_usd == agent.initial_capital_usd
