# Open Lifecycle Desktop Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the desktop detail for an open lifecycle, backed by canonical append-only evaluations, literal lifecycle accounting, and a locally loaded accessible React panel.

**Architecture:** Add nullable evaluation context to the existing ledger, record every executable BUY/SELL/HOLD decision against the current lifecycle, and expose one authenticated detail endpoint without expanding the collection payload. Keep selection and frozen row order inside `PositionsTable`; let `OpenLifecycleDetail` own detail fetching, stale-response protection, local states, Escape, and focus.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, pytest; React 19, TypeScript 6, Vitest, Testing Library, Tailwind/shadcn primitives.

## Global Constraints

- Implement only GitHub issue #28; do not add closed-lifecycle detail, timeline pagination, mobile-specific behavior, or remove legacy lifecycle contracts.
- Preserve existing paper-trading data: the migration is additive and all three new columns are nullable.
- `PositionEvaluation` and `Trade` remain append-only.
- BUY/SELL trade, evaluation, projection, and event writes remain one atomic transaction.
- An explicit HOLD is persisted only when its symbol has a current open lifecycle; it creates no trade.
- The collection remains lightweight; detail is loaded only through `GET /api/agents/{agent_id}/lifecycles/{lifecycle_id}`.
- Market failure must not hide canonical evaluation, trade, fee, or realized-accounting data.
- While detail is open, preserve visible lifecycle identity and order; poll updates may replace values by id but not reorder rows.
- Keep the left table region fixed and top-align a natural-height detail cell; add no modal, nested card, internal scroll, or layout animation.
- Every new behavior starts with a failing public-seam test and finishes with the focused suite passing.

---

## File map

- Create `backend/alembic/versions/2c7e4a8d9f01_position_evaluation_context.py`: additive nullable ledger columns, revision after `1a2b3c4d5e6f`.
- Modify `backend/app/db/models.py`: SQLAlchemy mappings for evaluation policy context.
- Modify `backend/app/trading/engine.py`: accept and persist normalized context on BUY/SELL.
- Modify `backend/app/agents/runtime.py`: forward BUY/SELL context and append HOLD evaluations for current lifecycles.
- Modify `backend/app/api/schemas.py`: explicit detail, economy, evaluation, market, and lifecycle-trade response types.
- Modify `backend/app/api/routes.py`: authenticated open-lifecycle detail projection using canonical ledger plus existing market cache.
- Modify `backend/tests/test_models.py`, `backend/tests/test_engine.py`, `backend/tests/test_runtime.py`, `backend/tests/test_api.py`, `backend/tests/test_auth.py`: backend regression coverage through public seams.
- Modify `frontend/src/api.ts`: detail types and fetch function.
- Create `frontend/src/components/OpenLifecycleDetail.tsx`: local request lifecycle and detail rendering.
- Modify `frontend/src/components/PositionsTable.tsx`: selection, fixed columns, frozen ordering, focus restoration, and detail-cell placement.
- Modify `frontend/src/App.tsx`: provide agent/auth context and reset the table when agent or lifecycle view changes.
- Create `frontend/src/__tests__/OpenLifecycleDetail.test.tsx`: component request-state/content/focus tests.
- Modify `frontend/src/__tests__/PositionsTable.test.tsx`, `frontend/src/__tests__/App.auth.test.tsx`: table accessibility/order and application regressions.

---

### Task 1: Persist evaluation policy context additively

**Files:**
- Create: `backend/alembic/versions/2c7e4a8d9f01_position_evaluation_context.py`
- Modify: `backend/app/db/models.py:88-99`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Consumes: existing append-only `PositionEvaluation` ledger and Alembic head `1a2b3c4d5e6f`.
- Produces: `PositionEvaluation.policy_refs: list[str] | None`, `policy_alignment: str | None`, and `override_reason: str | None`.

- [ ] **Step 1: Write the failing model test**

Add a test that creates a lifecycle and evaluation through SQLAlchemy, commits, reloads, and asserts the literal context. Keep the existing canonical-identity test unchanged.

```python
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
```

- [ ] **Step 2: Verify the model test is red**

Run: `cd backend && .venv/bin/pytest tests/test_models.py::test_position_evaluation_persists_policy_context -v`

Expected: FAIL because `policy_refs`, `policy_alignment`, and `override_reason` are not mapped constructor arguments.

- [ ] **Step 3: Add the SQLAlchemy mappings**

Import `JSON` from SQLAlchemy in `backend/app/db/models.py` and add only these nullable fields:

```python
class PositionEvaluation(Base):
    # existing fields stay unchanged
    policy_refs: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    policy_alignment: Mapped[str | None] = mapped_column(String(16), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 4: Add the reversible migration**

Create the migration with the verified current head as its parent:

```python
"""add position evaluation context

Revision ID: 2c7e4a8d9f01
Revises: 1a2b3c4d5e6f
"""
from alembic import op
import sqlalchemy as sa

revision = "2c7e4a8d9f01"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("position_evaluations", sa.Column("policy_refs", sa.JSON(), nullable=True))
    op.add_column("position_evaluations", sa.Column("policy_alignment", sa.String(length=16), nullable=True))
    op.add_column("position_evaluations", sa.Column("override_reason", sa.String(), nullable=True))


def downgrade():
    op.drop_column("position_evaluations", "override_reason")
    op.drop_column("position_evaluations", "policy_alignment")
    op.drop_column("position_evaluations", "policy_refs")
```

- [ ] **Step 5: Verify persistence and migration shape**

Run: `cd backend && .venv/bin/pytest tests/test_models.py -v`

Expected: all model tests PASS.

Run: `cd backend && .venv/bin/alembic heads`

Expected: exactly `2c7e4a8d9f01 (head)`.

- [ ] **Step 6: Commit the persistence slice**

```bash
git add backend/app/db/models.py backend/alembic/versions/2c7e4a8d9f01_position_evaluation_context.py backend/tests/test_models.py
git commit -m "feat: persist evaluation policy context (#28)"
```

---

### Task 2: Record complete BUY, SELL, and HOLD evaluations

**Files:**
- Modify: `backend/app/trading/engine.py:39-158`
- Modify: `backend/app/agents/runtime.py:212-285`
- Test: `backend/tests/test_engine.py`
- Test: `backend/tests/test_runtime.py`

**Interfaces:**
- Consumes: nullable evaluation context fields from Task 1 and `Action.policy_refs`, `Action.policy_alignment`, `Action.override_reason` from `app.brain.schema`.
- Produces: `execute_buy(..., policy_refs: list[str] | None = None, policy_alignment: str = "unrelated", override_reason: str = "")`; identical added keyword arguments on `execute_sell`; HOLD ledger insertion through public `run_decision(...)`.

- [ ] **Step 1: Write failing engine tests for normalized BUY/SELL metadata**

Extend the engine suite with a parameterized test that invokes each public execution function and reads the resulting ledger row:

```python
@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_trade_evaluation_persists_full_policy_context(db_session, side):
    agent = _agent(db_session, "300")
    if side == "SELL":
        execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"), cycle_id="open")
        trade = execute_sell(
            db_session, agent, "BTCUSDT", Decimal("0.5"), Decimal("120"),
            cycle_id="decision", rationale="trim risk", policy_refs=["P002"],
            policy_alignment="violates", override_reason="volatility spike",
        )
    else:
        trade = execute_buy(
            db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"),
            cycle_id="decision", rationale="breakout", policy_refs=["P001"],
            policy_alignment="follows", override_reason="",
        )

    evaluation = (db_session.query(PositionEvaluation)
                  .filter_by(lifecycle_id=trade.lifecycle_id, cycle_id="decision").one())
    assert evaluation.rationale in {"breakout", "trim risk"}
    assert evaluation.policy_refs == (["P001"] if side == "BUY" else ["P002"])
    assert evaluation.policy_alignment == ("follows" if side == "BUY" else "violates")
    assert evaluation.override_reason == ("" if side == "BUY" else "volatility spike")
```

Also add one assertion to the existing default-path engine test that a write without new arguments stores `[]`, `"unrelated"`, and `""`.

- [ ] **Step 2: Verify the engine tests are red**

Run: `cd backend && .venv/bin/pytest tests/test_engine.py -k 'policy_context or evaluation_matches_trade' -v`

Expected: FAIL because the execution functions do not accept or persist the new keywords.

- [ ] **Step 3: Implement minimal engine forwarding and normalization**

Extend both signatures without changing existing positional parameters:

```python
def execute_buy(
    session, agent: Agent, symbol: str, usd_amount: Decimal, ask: Decimal,
    cycle_id: str | None = None, rationale: str | None = None,
    policy_refs: list[str] | None = None, policy_alignment: str = "unrelated",
    override_reason: str = "",
) -> Trade:
```

Use the same trailing keyword arguments for `execute_sell`. In each `PositionEvaluation(...)`, add:

```python
policy_refs=list(policy_refs or []),
policy_alignment=policy_alignment or "unrelated",
override_reason=override_reason or "",
```

Do not add commits or flushes; `_persist_trade_atomically` remains the only transaction boundary.

- [ ] **Step 4: Re-run engine tests including rollback safeguards**

Run: `cd backend && .venv/bin/pytest tests/test_engine.py -v`

Expected: all engine tests PASS, including both existing atomic rollback tests.

- [ ] **Step 5: Write failing `run_decision` tests for public runtime behavior**

Add three tests using the existing `_llm_agent`, `FakeMarketLLM`, `DecisionResult`, and `Action` fixtures:

```python
async def test_run_decision_persists_full_context_for_buy_and_sell(db_session):
    agent = _llm_agent(db_session)
    market = FakeMarketLLM(
        [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))],
        Decimal("100"), (Decimal("100"), Decimal("101")),
    )
    decision = Decision(actions=[
        Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("50"), rationale="open",
               policy_refs=["P001"], policy_alignment="follows"),
        Action(type="SELL", symbol="BTCUSDT", fraction=Decimal("0.5"), rationale="trim",
               policy_refs=["P002"], policy_alignment="violates", override_reason="risk cap"),
    ])
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision))

    evaluations = (db_session.query(PositionEvaluation)
                   .order_by(PositionEvaluation.id).all())
    assert [(row.action, row.policy_refs, row.policy_alignment, row.override_reason)
            for row in evaluations] == [
        ("BUY", ["P001"], "follows", ""),
        ("SELL", ["P002"], "violates", "risk cap"),
    ]


async def test_run_decision_records_hold_for_open_lifecycle_without_trade(db_session):
    agent = _llm_agent(db_session)
    opening = execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), Decimal("100"), cycle_id="open")
    trade_count = db_session.query(Trade).count()
    decision = Decision(actions=[Action(
        type="HOLD", symbol="BTCUSDT", rationale="thesis intact",
        policy_refs=["P003"], policy_alignment="follows",
    )])
    market = FakeMarketLLM(
        [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))],
        Decimal("100"), (Decimal("99"), Decimal("101")),
    )
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision))

    hold = db_session.query(PositionEvaluation).filter_by(action="HOLD").one()
    lifecycle = db_session.get(PositionLifecycle, opening.lifecycle_id)
    assert hold.lifecycle_id == opening.lifecycle_id
    assert hold.rationale == "thesis intact"
    assert db_session.query(Trade).count() == trade_count
    assert lifecycle.last_cycle_id == hold.cycle_id


async def test_run_decision_does_not_create_lifecycle_for_hold_without_position(db_session):
    agent = _llm_agent(db_session)
    decision = Decision(actions=[Action(type="HOLD", symbol="ETHUSDT", rationale="watch")])
    market = FakeMarketLLM([], Decimal("100"), (Decimal("99"), Decimal("101")))
    await run_decision(db_session, agent, market, ["ETHUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision))

    assert db_session.query(PositionEvaluation).count() == 0
    assert db_session.query(PositionLifecycle).count() == 0
    event = db_session.query(Event).filter_by(kind="decision").one()
    assert event.payload["skipped"] == [
        {"type": "HOLD", "symbol": "ETHUSDT", "reason": "posizione inesistente"}
    ]
```

- [ ] **Step 6: Verify runtime tests are red**

Run: `cd backend && .venv/bin/pytest tests/test_runtime.py -k 'full_context_for_buy_and_sell or records_hold or does_not_create_lifecycle' -v`

Expected: metadata assertions fail and the HOLD row is absent.

- [ ] **Step 7: Implement runtime forwarding and HOLD append**

Pass all action context into BUY and SELL:

```python
policy = dict(
    policy_refs=action.policy_refs,
    policy_alignment=action.policy_alignment,
    override_reason=action.override_reason,
)
execute_buy(..., cycle_id=cycle_id, rationale=action.rationale, **policy)
execute_sell(..., cycle_id=cycle_id, rationale=action.rationale, **policy)
```

Add the HOLD branch before the final skip branch:

```python
elif action.type == "HOLD" and action.symbol in held:
    position = held[action.symbol]
    lifecycle = session.get(PositionLifecycle, position.lifecycle_id) if position.lifecycle_id else None
    if lifecycle is None:
        skipped.append({"type": "HOLD", "symbol": action.symbol,
                        "reason": "posizione senza lifecycle"})
        continue
    lifecycle.last_cycle_id = cycle_id
    session.add(PositionEvaluation(
        agent_id=agent.id, lifecycle_id=lifecycle.id, cycle_id=cycle_id,
        action="HOLD", rationale=action.rationale,
        policy_refs=list(action.policy_refs),
        policy_alignment=action.policy_alignment,
        override_reason=action.override_reason,
    ))
    actions += 1
```

Import `PositionEvaluation` and `PositionLifecycle` into `runtime.py`. Leave HOLD without a current position in the existing explicit skip path.

- [ ] **Step 8: Run runtime and engine suites**

Run: `cd backend && .venv/bin/pytest tests/test_runtime.py tests/test_engine.py -v`

Expected: all tests PASS; BUY/SELL rollback behavior remains green.

- [ ] **Step 9: Commit the runtime slice**

```bash
git add backend/app/trading/engine.py backend/app/agents/runtime.py backend/tests/test_engine.py backend/tests/test_runtime.py
git commit -m "feat: record explicit lifecycle evaluations (#28)"
```

---

### Task 3: Expose the canonical open-lifecycle detail API

**Files:**
- Modify: `backend/app/api/schemas.py:30-91`
- Modify: `backend/app/api/routes.py:1-440`
- Test: `backend/tests/test_api.py`
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- Consumes: `GET /api/agents/{agent_id}/lifecycles/{lifecycle_id}`, `_trade_totals(trades)`, `_lifecycle_market_context(market, agent_id, price_symbols, series_symbols)`, and the ledger from Tasks 1–2.
- Produces: `LifecycleDetailOut` with top-level identity, `evaluation`, `economy`, `market`, and `trades`; legacy null evaluation context normalizes to `[]`, `"unrelated"`, and `""`.

- [ ] **Step 1: Write failing API tests for literal accounting and latest evaluation**

Use `_lifecycle_agent`, `_client`, and `LifecycleMarketFake` already present in `test_api.py`. Add `PositionEvaluation` to that file's model imports. First correct the fake's optional-series semantics so an explicit empty list stays empty, matching the production client:

```python
self.requested_series_symbols = list(symbols if series_symbols is None else series_symbols)
# ...
series_24h={
    symbol: self._snapshot.series_24h[symbol]
    for symbol in (symbols if series_symbols is None else series_symbols)
},
```

Then test the endpoint with a market snapshot at 130 and a later HOLD evaluation:

```python
def test_open_lifecycle_detail_returns_latest_evaluation_economy_and_own_trades(
    db_session,
):
    agent = _lifecycle_agent(db_session)
    first = execute_buy(
        db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"),
        cycle_id="open", rationale="enter", policy_refs=["P001"],
        policy_alignment="follows",
    )
    execute_sell(
        db_session, agent, "BTCUSDT", Decimal("0.4"), Decimal("120"),
        cycle_id="partial", rationale="trim",
    )
    other = execute_buy(
        db_session, agent, "ETHUSDT", Decimal("50"), Decimal("50"), cycle_id="other-life",
    )
    lifecycle = db_session.get(PositionLifecycle, first.lifecycle_id)
    db_session.add(PositionEvaluation(
        agent_id=agent.id, lifecycle_id=lifecycle.id, cycle_id="hold",
        action="HOLD", rationale="thesis intact", policy_refs=["P003"],
        policy_alignment="follows", override_reason="",
    ))
    lifecycle.last_cycle_id = "hold"
    db_session.commit()
    market = LifecycleMarketFake(LifecycleMarketSnapshot(
        as_of=datetime(2026, 7, 14, 10, tzinfo=timezone.utc),
        prices={"BTCUSDT": Decimal("130")}, series_24h={},
    ))
    client = _client(db_session)
    app.dependency_overrides[routes.lifecycle_market_dep] = lambda: market

    body = client.get(f"/api/agents/{agent.id}/lifecycles/{lifecycle.id}").json()
    assert body["lifecycle_id"] == lifecycle.id
    assert body["evaluation"] == {
        "action": "HOLD", "rationale": "thesis intact", "cycle_id": "hold",
        "timestamp": body["evaluation"]["timestamp"], "policy_refs": ["P003"],
        "policy_alignment": "follows", "override_reason": "",
    }
    economy = body["economy"]
    assert Decimal(economy["quantity"]) == Decimal("0.6")
    assert Decimal(economy["avg_price"]) == Decimal("100")
    assert Decimal(economy["last_price"]) == Decimal("130")
    assert Decimal(economy["exposure_usd"]) == Decimal("78")
    assert Decimal(economy["invested_usd"]) == Decimal("100")
    assert Decimal(economy["realized_usd"]) == Decimal("8")
    assert Decimal(economy["unrealized_usd"]) == Decimal("18")
    assert Decimal(economy["fees_usd"]) == Decimal("0.148")
    assert Decimal(economy["net_result_usd"]) == Decimal("25.852")
    assert Decimal(economy["net_result_pct"]) == Decimal("25.852")
    assert [(row["side"], row["cycle_id"]) for row in body["trades"]] == [
        ("BUY", "open"), ("SELL", "partial"),
    ]
    assert all(row["cycle_id"] != other.cycle_id for row in body["trades"])
```

Use the existing concrete lifecycle market stub/factory style in `test_api.py`; inject it through `app.dependency_overrides[lifecycle_market_dep]` where the suite already uses FastAPI overrides. Calculate expected fee literals from the configured `fee_rate` if current fixture serialization differs, and keep the assertions exact.

- [ ] **Step 2: Add failing API tests for absence, market fallback, and ownership**

Add four focused tests using the same concrete setup; the first two deliberately construct the ledger directly so evaluation absence and legacy null normalization are observable:

```python
def test_open_lifecycle_detail_declares_missing_evaluation(db_session):
    agent = _lifecycle_agent(db_session)
    lifecycle = PositionLifecycle(
        id="life-no-eval", agent_id=agent.id, symbol="BTCUSDT",
        opening_cycle_id="open", last_cycle_id="open",
    )
    db_session.add(lifecycle)
    db_session.flush()
    db_session.add_all([
        Position(
            agent_id=agent.id, lifecycle_id=lifecycle.id, symbol="BTCUSDT",
            quantity=Decimal("1"), avg_price=Decimal("100"), invested_usd=Decimal("100"),
        ),
        Trade(
            agent_id=agent.id, lifecycle_id=lifecycle.id, cycle_id="open",
            symbol="BTCUSDT", side="BUY", quantity=Decimal("1"),
            price=Decimal("100"), fee=Decimal("0.1"),
        ),
    ])
    db_session.commit()
    client = _client(db_session)
    response = client.get(f"/api/agents/{agent.id}/lifecycles/{lifecycle.id}")
    assert response.status_code == 200
    assert response.json()["evaluation"] is None


def test_open_lifecycle_detail_normalizes_legacy_evaluation_context(db_session):
    agent = _lifecycle_agent(db_session)
    trade = execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"), cycle_id="open")
    saved = db_session.query(PositionEvaluation).filter_by(lifecycle_id=trade.lifecycle_id).one()
    evaluation_id = saved.id
    saved.policy_refs = None
    saved.policy_alignment = None
    saved.override_reason = None
    # This simulates a pre-migration row before append-only listeners are enabled in production;
    # issue one direct SQL UPDATE because ORM mutation is intentionally rejected.
    db_session.rollback()
    db_session.execute(
        PositionEvaluation.__table__.update()
        .where(PositionEvaluation.id == evaluation_id)
        .values(policy_refs=None, policy_alignment=None, override_reason=None)
    )
    db_session.commit()
    client = _client(db_session)
    evaluation = client.get(
        f"/api/agents/{agent.id}/lifecycles/{trade.lifecycle_id}"
    ).json()["evaluation"]
    assert evaluation["policy_refs"] == []
    assert evaluation["policy_alignment"] == "unrelated"
    assert evaluation["override_reason"] == ""


def test_open_lifecycle_detail_uses_fresh_then_stale_market_without_hiding_ledger(db_session):
    agent = _lifecycle_agent(db_session)
    trade = execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"), cycle_id="open")
    market = LifecycleMarketFake(LifecycleMarketSnapshot(
        as_of=datetime(2026, 7, 14, 10, tzinfo=timezone.utc),
        prices={"BTCUSDT": Decimal("120")}, series_24h={},
    ))
    client = _client(db_session)
    app.dependency_overrides[routes.lifecycle_market_dep] = lambda: market
    url = f"/api/agents/{agent.id}/lifecycles/{trade.lifecycle_id}"
    fresh = client.get(url).json()
    market.fail = True
    stale = client.get(url).json()
    assert fresh["market"]["status"] == "fresh"
    assert stale["market"] == {"status": "stale", "as_of": fresh["market"]["as_of"]}
    assert stale["trades"] == fresh["trades"]
    assert stale["economy"]["fees_usd"] == fresh["economy"]["fees_usd"]


def test_open_lifecycle_detail_market_unavailable_keeps_canonical_ledger(db_session):
    agent = _lifecycle_agent(db_session)
    trade = execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"), cycle_id="open")
    market = LifecycleMarketFake(LifecycleMarketSnapshot(
        as_of=datetime(2026, 7, 14, 10, tzinfo=timezone.utc),
        prices={"BTCUSDT": Decimal("120")}, series_24h={},
    ))
    market.fail = True
    client = _client(db_session)
    app.dependency_overrides[routes.lifecycle_market_dep] = lambda: market
    body = client.get(f"/api/agents/{agent.id}/lifecycles/{trade.lifecycle_id}").json()
    assert body["market"] == {"status": "unavailable", "as_of": None}
    assert len(body["trades"]) == 1
    assert Decimal(body["economy"]["fees_usd"]) == Decimal("0.1")
    for field in ("last_price", "exposure_usd", "unrealized_usd", "net_result_usd", "net_result_pct"):
        assert body["economy"][field] is None


def test_open_lifecycle_detail_rejects_missing_closed_and_cross_agent_lifecycle(db_session):
    agent = _lifecycle_agent(db_session)
    other = _lifecycle_agent(db_session)
    opened = execute_buy(db_session, agent, "BTCUSDT", Decimal("100"), Decimal("100"), cycle_id="open")
    closed_trade = execute_buy(db_session, agent, "ETHUSDT", Decimal("100"), Decimal("100"), cycle_id="closed-open")
    execute_sell(db_session, agent, "ETHUSDT", Decimal("1"), Decimal("110"), cycle_id="closed-close")
    closed = db_session.get(PositionLifecycle, closed_trade.lifecycle_id)
    client = _client(db_session)
    assert client.get(f"/api/agents/{agent.id}/lifecycles/missing").status_code == 404
    assert client.get(f"/api/agents/{agent.id}/lifecycles/{closed.id}").status_code == 404
    assert client.get(f"/api/agents/{other.id}/lifecycles/{opened.lifecycle_id}").status_code == 404
```

The existing autouse fixture clears `_lifecycle_market_snapshots` and dependency overrides around each test, so no additional global cleanup is needed.

- [ ] **Step 3: Verify detail tests are red**

Run: `cd backend && .venv/bin/pytest tests/test_api.py -k 'open_lifecycle_detail' -v`

Expected: FAIL with 404/405 because the detail route and schemas do not exist.

- [ ] **Step 4: Define explicit Pydantic response models**

Extend `LifecycleEvaluationOut` and add dedicated types:

```python
class LifecycleEvaluationOut(BaseModel):
    action: str
    rationale: str | None = None
    cycle_id: str | None = None
    timestamp: datetime
    policy_refs: list[str] = []
    policy_alignment: str = "unrelated"
    override_reason: str = ""


class LifecycleEconomyOut(BaseModel):
    quantity: Decimal
    avg_price: Decimal
    last_price: Decimal | None = None
    exposure_usd: Decimal | None = None
    invested_usd: Decimal
    realized_usd: Decimal
    unrealized_usd: Decimal | None = None
    fees_usd: Decimal
    net_result_usd: Decimal | None = None
    net_result_pct: Decimal | None = None


class LifecycleTradeOut(BaseModel):
    id: int
    cycle_id: str | None = None
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    timestamp: datetime


class LifecycleDetailOut(BaseModel):
    lifecycle_id: str
    cycle_id: str | None = None
    symbol: str
    status: Literal["open"] = "open"
    opened_at: datetime
    last_changed_at: datetime
    evaluation: LifecycleEvaluationOut | None = None
    economy: LifecycleEconomyOut
    market: LifecycleMarketOut
    trades: list[LifecycleTradeOut]
```

Import these names explicitly in `routes.py`; do not reuse the collection summary or legacy `OpenLifecycleOut` as the detail contract.

- [ ] **Step 5: Implement the detail route from canonical rows**

Place the static collection route before the dynamic `{lifecycle_id}` route or otherwise preserve FastAPI route matching. The implementation must:

```python
@router.get("/agents/{agent_id}/lifecycles/{lifecycle_id}", response_model=LifecycleDetailOut)
async def get_lifecycle_detail(
    agent_id: int, lifecycle_id: str,
    session=Depends(session_dep), market=Depends(lifecycle_market_dep),
    _: str = Depends(require_viewer_or_admin),
):
    if session.get(Agent, agent_id) is None:
        raise HTTPException(404, "agent not found")
    lifecycle = (session.query(PositionLifecycle)
                 .filter_by(id=lifecycle_id, agent_id=agent_id, closed_at=None).first())
    if lifecycle is None:
        raise HTTPException(404, "open lifecycle not found")
    position = (session.query(Position)
                .filter_by(agent_id=agent_id, lifecycle_id=lifecycle.id).first())
    if position is None:
        raise HTTPException(404, "open lifecycle position not found")
    trades = (session.query(Trade)
              .filter_by(agent_id=agent_id, lifecycle_id=lifecycle.id)
              .order_by(Trade.timestamp.asc(), Trade.id.asc()).all())
    if not trades:
        raise HTTPException(404, "open lifecycle ledger not found")
    evaluation = (session.query(PositionEvaluation)
                  .filter_by(agent_id=agent_id, lifecycle_id=lifecycle.id)
                  .order_by(PositionEvaluation.timestamp.desc(), PositionEvaluation.id.desc())
                  .first())
    snapshot, market_meta = await _lifecycle_market_context(
        market, agent_id, [lifecycle.symbol], [],
    )
    last_price = snapshot.prices.get(lifecycle.symbol) if snapshot is not None else None
    invested, fees, _closed_net = _trade_totals(trades)
    realized = position.realized_usd or Decimal("0")
    unrealized = ((last_price - position.avg_price) * position.quantity
                  if last_price is not None else None)
    net = realized + unrealized - fees if unrealized is not None else None
    last_changed = max(
        [lifecycle.opened_at, trades[-1].timestamp]
        + ([evaluation.timestamp] if evaluation is not None else []),
        key=_utc,
    )
```

Return `LifecycleDetailOut`, normalize legacy context with `list(evaluation.policy_refs or [])`, `evaluation.policy_alignment or "unrelated"`, and `evaluation.override_reason or ""`, and map each trade into `LifecycleTradeOut`. Do not catch the market exception locally; `_lifecycle_market_context` already converts it to stale/unavailable.

- [ ] **Step 6: Run detail API tests**

Run: `cd backend && .venv/bin/pytest tests/test_api.py -k 'open_lifecycle_detail' -v`

Expected: all detail API tests PASS.

- [ ] **Step 7: Add and run anonymous/revoked viewer tests**

Add a sibling to the existing lifecycle auth cases:

```python
def test_lifecycle_detail_rejects_anonymous_and_revoked_viewer(client, db_session):
    assert client.get("/api/agents/1/lifecycles/life-1").status_code == 401
    link = ShareLink(token="detail-viewer")
    db_session.add(link)
    db_session.commit()
    client.post("/api/auth/viewer", json={"token": link.token})
    assert client.get("/api/agents/1/lifecycles/life-1").status_code == 404
    db_session.delete(link)
    db_session.commit()
    assert client.get("/api/agents/1/lifecycles/life-1").status_code == 401
```

Run: `cd backend && .venv/bin/pytest tests/test_auth.py tests/test_api.py -v`

Expected: both suites PASS.

- [ ] **Step 8: Commit the API slice**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api.py backend/tests/test_auth.py
git commit -m "feat: add open lifecycle detail API (#28)"
```

---

### Task 4: Build the locally loaded open-detail component

**Files:**
- Modify: `frontend/src/api.ts:69-113,175-183`
- Create: `frontend/src/components/OpenLifecycleDetail.tsx`
- Create: `frontend/src/__tests__/OpenLifecycleDetail.test.tsx`

**Interfaces:**
- Consumes: Task 3 response from `GET /api/agents/{agent_id}/lifecycles/{lifecycle_id}` and existing `AuthError`, `usd`, `pct`, `dayShort`, `hm` formatting helpers.
- Produces: `getLifecycleDetail(agentId: number, lifecycleId: string): Promise<LifecycleDetail>` and `OpenLifecycleDetail({ agentId, lifecycleId, onClose, onAuthLost })`.

- [ ] **Step 1: Add frontend detail types and fetch function**

Define the API contract literally in `api.ts`:

```typescript
export type LifecycleEvaluation = {
  action: "BUY" | "SELL" | "HOLD";
  rationale: string | null;
  cycle_id: string | null;
  timestamp: string;
  policy_refs: string[];
  policy_alignment: "follows" | "violates" | "unrelated";
  override_reason: string;
};
export type LifecycleEconomy = {
  quantity: string; avg_price: string; last_price: string | null;
  exposure_usd: string | null; invested_usd: string; realized_usd: string;
  unrealized_usd: string | null; fees_usd: string;
  net_result_usd: string | null; net_result_pct: string | null;
};
export type LifecycleTrade = {
  id: number; cycle_id: string | null; side: "BUY" | "SELL";
  quantity: string; price: string; fee: string; timestamp: string;
};
export type LifecycleDetail = {
  lifecycle_id: string; cycle_id: string | null; symbol: string; status: "open";
  opened_at: string; last_changed_at: string; evaluation: LifecycleEvaluation | null;
  economy: LifecycleEconomy; market: LifecycleMarket; trades: LifecycleTrade[];
};

export const getLifecycleDetail = (agentId: number, lifecycleId: string) =>
  get<LifecycleDetail>(`/api/agents/${agentId}/lifecycles/${lifecycleId}`);
```

Replace the old short `LifecycleEvaluation` definition with the expanded one so the legacy open type remains compatible.

- [ ] **Step 2: Write failing component tests for request states and race protection**

Mock `getLifecycleDetail` and define one complete response factory:

```tsx
const detail = (over: Partial<LifecycleDetail> = {}): LifecycleDetail => ({
  lifecycle_id: "life-1",
  cycle_id: "hold",
  symbol: "BTCUSDT",
  status: "open",
  opened_at: "2026-07-14T09:00:00Z",
  last_changed_at: "2026-07-14T10:00:00Z",
  evaluation: {
    action: "HOLD", rationale: "thesis intact", cycle_id: "hold",
    timestamp: "2026-07-14T10:00:00Z", policy_refs: ["P003"],
    policy_alignment: "follows", override_reason: "",
  },
  economy: {
    quantity: "0.6", avg_price: "100", last_price: "130", exposure_usd: "78",
    invested_usd: "100", realized_usd: "8", unrealized_usd: "18",
    fees_usd: "0.148", net_result_usd: "25.852", net_result_pct: "25.852",
  },
  market: { status: "fresh", as_of: "2026-07-14T10:00:00Z" },
  trades: [{
    id: 1, cycle_id: "open", side: "BUY", quantity: "1", price: "100",
    fee: "0.1", timestamp: "2026-07-14T09:00:00Z",
  }],
  ...over,
});
```

Then cover loading, error/retry, auth loss, no evaluation, and a late first response after changing `lifecycleId`:

```tsx
it("keeps loading and errors local and retries the same lifecycle", async () => {
  vi.mocked(getLifecycleDetail)
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce(detail());
  render(<OpenLifecycleDetail agentId={1} lifecycleId="life-1" onClose={vi.fn()} onAuthLost={vi.fn()} />);
  expect(screen.getByText("Caricamento dettaglio…")).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Riprova" }));
  expect(await screen.findByRole("heading", { name: /BTC/ })).toBeInTheDocument();
  expect(getLifecycleDetail).toHaveBeenLastCalledWith(1, "life-1");
});

it("declares the absence of an explicit evaluation without inference", async () => {
  vi.mocked(getLifecycleDetail).mockResolvedValue(detail({ evaluation: null }));
  render(<OpenLifecycleDetail agentId={1} lifecycleId="life-1" onClose={vi.fn()} onAuthLost={vi.fn()} />);
  expect(await screen.findByText("Nessuna valutazione esplicita registrata")).toBeInTheDocument();
});

it("ignores a late response from the previous selection", async () => {
  const first = deferred<LifecycleDetail>();
  vi.mocked(getLifecycleDetail)
    .mockReturnValueOnce(first.promise)
    .mockResolvedValueOnce(detail({ lifecycle_id: "life-2", symbol: "ETHUSDT" }));
  const view = render(<OpenLifecycleDetail agentId={1} lifecycleId="life-1" onClose={vi.fn()} onAuthLost={vi.fn()} />);
  view.rerender(<OpenLifecycleDetail agentId={1} lifecycleId="life-2" onClose={vi.fn()} onAuthLost={vi.fn()} />);
  expect(await screen.findByRole("heading", { name: /ETH/ })).toBeInTheDocument();
  first.resolve(detail({ symbol: "BTCUSDT" }));
  await waitFor(() => expect(screen.queryByRole("heading", { name: /BTC/ })).not.toBeInTheDocument());
});
```

Define the async helper in the test file so the race test has no implicit dependency:

```typescript
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}
```

The test-local `detail(overrides)` factory returns every field in `LifecycleDetail`, with `overrides` merged last.

- [ ] **Step 3: Write failing content, disclosure, Escape, and focus tests**

Use exact accessible queries:

```tsx
it("renders explicit evaluation, net breakdown, market disclosure and collapsed accounting", async () => {
  vi.mocked(getLifecycleDetail).mockResolvedValue(detail());
  render(<OpenLifecycleDetail agentId={1} lifecycleId="life-1" onClose={vi.fn()} onAuthLost={vi.fn()} />);
  expect(await screen.findByText("thesis intact")).toBeInTheDocument();
  expect(screen.getByText("P003")).toBeInTheDocument();
  expect(screen.getByText(/realizzato/i)).toBeInTheDocument();
  expect(screen.getByText(/non realizzato/i)).toBeInTheDocument();
  expect(screen.getByText(/fee/i)).toBeInTheDocument();
  const accounting = screen.getByText("Contabilità").closest("details");
  expect(accounting).not.toHaveAttribute("open");
  fireEvent.click(screen.getByText("Contabilità"));
  expect(screen.getByText(/BUY/)).toBeInTheDocument();
});

it("closes with Escape and focuses the detail heading after load", async () => {
  const onClose = vi.fn();
  vi.mocked(getLifecycleDetail).mockResolvedValue(detail());
  render(<OpenLifecycleDetail agentId={1} lifecycleId="life-1" onClose={onClose} onAuthLost={vi.fn()} />);
  const heading = await screen.findByRole("heading", { name: /BTC/ });
  await waitFor(() => expect(heading).toHaveFocus());
  fireEvent.keyDown(document, { key: "Escape" });
  expect(onClose).toHaveBeenCalledOnce();
});
```

Also assert that `market.status === "unavailable"` renders `—` for market-derived amounts and keeps trade/fee content present, and that an `AuthError` invokes `onAuthLost` without rendering the local retry control.

- [ ] **Step 4: Verify component tests are red**

Run: `cd frontend && npm test -- src/__tests__/OpenLifecycleDetail.test.tsx`

Expected: FAIL because the component and fetch export do not exist.

- [ ] **Step 5: Implement local request state and accessible rendering**

Implement the exact prop and state boundary:

```tsx
type Props = {
  agentId: number;
  lifecycleId: string;
  onClose: () => void;
  onAuthLost: () => void;
};

export function OpenLifecycleDetail({ agentId, lifecycleId, onClose, onAuthLost }: Props) {
  const request = useRef(0);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<
    { kind: "loading" } | { kind: "error" } | { kind: "ready"; detail: LifecycleDetail }
  >({ kind: "loading" });

  useEffect(() => {
    const current = ++request.current;
    setState({ kind: "loading" });
    getLifecycleDetail(agentId, lifecycleId).then(
      detail => { if (request.current === current) setState({ kind: "ready", detail }); },
      error => {
        if (request.current !== current) return;
        if (error instanceof AuthError) onAuthLost();
        else setState({ kind: "error" });
      },
    );
    return () => { request.current += 1; };
  }, [agentId, lifecycleId, attempt, onAuthLost]);
```

Install one document `keydown` listener for Escape with cleanup. Focus `headingRef` only when `state.kind === "ready"`. Render:

- local `role="status"` loading copy;
- local `role="alert"` error plus `Riprova`, implemented as `setAttempt(value => value + 1)`;
- a `tabIndex={-1}` heading named `Dettaglio BTC` and explicit close button;
- evaluation action, rationale, timestamp, policy refs/alignment, and override only from `detail.evaluation`;
- economy net first, then realized/unrealized/fees/invested/exposure;
- fresh/stale/unavailable market disclosure;
- native `<details><summary>Contabilità</summary>…</details>` without `open`, mapping only `detail.trades`.

Use sections and a definition list, not nested `Card`; do not add fixed height or overflow classes.

- [ ] **Step 6: Run focused component tests and type build**

Run: `cd frontend && npm test -- src/__tests__/OpenLifecycleDetail.test.tsx`

Expected: all new component tests PASS.

Run: `cd frontend && npm run build`

Expected: exit 0; the existing bundle-size warning is acceptable.

- [ ] **Step 7: Commit the detail component slice**

```bash
git add frontend/src/api.ts frontend/src/components/OpenLifecycleDetail.tsx frontend/src/__tests__/OpenLifecycleDetail.test.tsx
git commit -m "feat: render open lifecycle detail (#28)"
```

---

### Task 5: Integrate selection into the stable lifecycle table

**Files:**
- Modify: `frontend/src/components/PositionsTable.tsx`
- Modify: `frontend/src/__tests__/PositionsTable.test.tsx`

**Interfaces:**
- Consumes: `OpenLifecycleDetail` from Task 4 and current collection props.
- Produces: `PositionsTable({ items, market, state, agentId, onAuthLost })`; open-row controls with `aria-expanded`; frozen id order and focus restoration while a detail is selected.

- [ ] **Step 1: Write failing selection and fixed-region tests**

Mock `OpenLifecycleDetail` as a small named element so this suite tests table semantics independently from network behavior:

```tsx
vi.mock("../components/OpenLifecycleDetail", () => ({
  OpenLifecycleDetail: ({ lifecycleId, onClose }: { lifecycleId: string; onClose: () => void }) => (
    <div>
      <span>{`detail:${lifecycleId}`}</span>
      <button type="button" onClick={onClose}>Chiudi dettaglio</button>
    </div>
  ),
}));
```

Add two open lifecycles and assert:

```tsx
it("selects an open row and replaces only the right comparison columns", () => {
  render(<PositionsTable agentId={1} onAuthLost={vi.fn()} state="open" market={freshMarket}
          items={[lifecycle(), lifecycle({ lifecycle_id: "life-2", symbol: "ETHUSDT" })]} />);
  const before = screen.getAllByRole("row").slice(2).map(row => row.textContent);
  fireEvent.click(screen.getByRole("button", { name: "Apri dettagli BTC" }));

  expect(screen.getByRole("button", { name: "Apri dettagli BTC" })).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("Selezionata")).toBeInTheDocument();
  expect(screen.getByText("detail:life-1")).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Coin" })).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "24h" })).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Età" })).toBeInTheDocument();
  for (const heading of ["Esposizione", "Peso", "Risultato netto"])
    expect(screen.queryByRole("columnheader", { name: heading })).not.toBeInTheDocument();
  expect(before.map(text => text?.match(/BTC|ETH/)?.[0])).toEqual(["BTC", "ETH"]);
});

it("changes selection directly and permits only open rows", () => {
  render(<PositionsTable agentId={1} onAuthLost={vi.fn()} state="all" market={freshMarket}
          items={[
            lifecycle(),
            lifecycle({ lifecycle_id: "life-2", symbol: "SOLUSDT" }),
            lifecycle({ lifecycle_id: "life-closed", symbol: "ETHUSDT", status: "closed" }),
          ]} />);
  fireEvent.click(screen.getByRole("button", { name: "Apri dettagli BTC" }));
  expect(screen.getByText("detail:life-1")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Apri dettagli SOL" }));
  expect(screen.getByText("detail:life-2")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Apri dettagli ETH" })).not.toBeInTheDocument();
});
```

Assert the left `<col>` elements have stable class names/width declarations before and after selection, and assert the detail cell has `rowSpan={items.length}`, `colSpan={3}`, and a top-alignment class.

- [ ] **Step 2: Write failing frozen-order and focus-restoration tests**

```tsx
it("freezes visible identity/order during polls, updates values, then restores collection order", () => {
  const first = lifecycle({ lifecycle_id: "life-1", symbol: "BTCUSDT", exposure_usd: "100" });
  const second = lifecycle({ lifecycle_id: "life-2", symbol: "ETHUSDT", exposure_usd: "50" });
  const view = render(<PositionsTable agentId={1} onAuthLost={vi.fn()} state="open" market={freshMarket} items={[first, second]} />);
  fireEvent.click(screen.getByRole("button", { name: "Apri dettagli BTC" }));
  view.rerender(<PositionsTable agentId={1} onAuthLost={vi.fn()} state="open" market={freshMarket}
                items={[{ ...second, exposure_usd: "200" }, { ...first, exposure_usd: "110" }]} />);
  expect(screen.getAllByRole("button", { name: /Apri dettagli/ }).map(button => button.textContent)).toEqual(["BTC", "ETH"]);
  fireEvent.click(screen.getByRole("button", { name: "Chiudi dettaglio" }));
  expect(screen.getAllByRole("button", { name: /Apri dettagli/ }).map(button => button.textContent)).toEqual(["ETH", "BTC"]);
  expect(screen.getByText("$200.00")).toBeInTheDocument();
  expect(screen.getByText("$110.00")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Apri dettagli BTC" })).toHaveFocus();
});
```

Also rerender with one frozen lifecycle absent and assert its last snapshot remains visible until close. Inspect every body row and assert its class/style has no `animate-`, `transition-all`, `transition-transform`, or transform style.

- [ ] **Step 3: Verify table tests are red**

Run: `cd frontend && npm test -- src/__tests__/PositionsTable.test.tsx`

Expected: FAIL because current rows are not controls and the component has no detail props/state.

- [ ] **Step 4: Implement stable table selection and frozen rows**

Change the prop type exactly:

```tsx
type Props = {
  items: LifecycleSummary[];
  market: LifecycleMarket;
  state: LifecycleState;
  agentId: number;
  onAuthLost: () => void;
};
```

Add state with no derived sorting:

```tsx
const [selectedId, setSelectedId] = useState<string | null>(null);
const [frozenItems, setFrozenItems] = useState<LifecycleSummary[]>([]);
const triggers = useRef(new Map<string, HTMLButtonElement>());
const liveById = new Map(items.map(item => [item.lifecycle_id, item]));
const displayedItems = selectedId
  ? frozenItems.map(item => liveById.get(item.lifecycle_id) ?? item)
  : items;

const select = (id: string) => {
  if (selectedId === null) setFrozenItems(items);
  setSelectedId(id);
};
const close = () => {
  const trigger = selectedId ? triggers.current.get(selectedId) : undefined;
  setSelectedId(null);
  setFrozenItems([]);
  queueMicrotask(() => trigger?.focus());
};
```

Render a six-column `<colgroup>` for open/detail mode. Give the left region fixed classes such as `w-[8rem]`, `w-[7rem]`, `w-[5rem]`; the three right columns share the remaining width. In open state, render `Età` as the third left column both before and after selection. In all state, keep `Stato` as the third left column.

For each open row, wrap the coin label in a real `<button type="button">` whose accessible name is `Apri dettagli ${coin}`, with `aria-expanded={selectedId === item.lifecycle_id}` and a visible `Selezionata` text marker for the selected row. Closed rows remain plain text.

When `selectedId` is non-null:

- replace the three right headers with one `colSpan={3}` header named `Dettaglio`;
- omit comparison cells from every body row;
- on only the first displayed row, append one `<TableCell rowSpan={displayedItems.length} colSpan={3} className="align-top whitespace-normal ...">` containing `OpenLifecycleDetail`;
- keep every left row rendered in `displayedItems` order;
- pass `agentId`, `selectedId`, `close`, and `onAuthLost` to the detail component.

Do not attach CSS transitions, transforms, fixed heights, or overflow to body rows or detail cell.

- [ ] **Step 5: Run table and detail component tests**

Run: `cd frontend && npm test -- src/__tests__/PositionsTable.test.tsx src/__tests__/OpenLifecycleDetail.test.tsx`

Expected: both suites PASS.

- [ ] **Step 6: Commit the table integration slice**

```bash
git add frontend/src/components/PositionsTable.tsx frontend/src/__tests__/PositionsTable.test.tsx
git commit -m "feat: select open lifecycle detail in place (#28)"
```

---

### Task 6: Wire agent context and protect collection navigation regressions

**Files:**
- Modify: `frontend/src/App.tsx:70-175,320-345`
- Modify: `frontend/src/__tests__/App.auth.test.tsx`

**Interfaces:**
- Consumes: Task 5 `PositionsTable` props and existing `selId`, `positionState`, collection polling/pagination logic.
- Produces: keyed table lifetime per agent/view and global auth-loss behavior for detail requests, without modifying collection fetch cadence.

- [ ] **Step 1: Write failing App tests for reset, polling order, and auth propagation**

Add `getLifecycleDetail` to the `vi.mock("../api")` object and imported mocks. Define complete collection rows and a detail response at module scope:

```tsx
const lifecycle = (over: Record<string, unknown> = {}) => ({
  lifecycle_id: "life-1", symbol: "BTCUSDT", status: "open",
  opened_at: "2026-07-14T09:00:00Z", closed_at: null,
  last_changed_at: "2026-07-14T10:00:00Z", quantity: "1",
  exposure_usd: "100", portfolio_weight_pct: "50", held_minutes: null,
  invested_usd: "100", fees_usd: "0.1", net_result_usd: "5",
  net_result_pct: "5", market_series_24h: ["100", "101"],
  ...over,
});
const btc = lifecycle();
const eth = lifecycle({ lifecycle_id: "life-2", symbol: "ETHUSDT", exposure_usd: "50" });
const btcUpdated = lifecycle({ exposure_usd: "110" });
const ethUpdated = lifecycle({ lifecycle_id: "life-2", symbol: "ETHUSDT", exposure_usd: "200" });
const detailBody = {
  lifecycle_id: "life-1", cycle_id: "hold", symbol: "BTCUSDT", status: "open",
  opened_at: "2026-07-14T09:00:00Z", last_changed_at: "2026-07-14T10:00:00Z",
  evaluation: null,
  economy: {
    quantity: "1", avg_price: "100", last_price: "110", exposure_usd: "110",
    invested_usd: "100", realized_usd: "0", unrealized_usd: "10",
    fees_usd: "0.1", net_result_usd: "9.9", net_result_pct: "9.9",
  },
  market: freshMarket,
  trades: [{
    id: 1, cycle_id: "open", side: "BUY", quantity: "1", price: "100",
    fee: "0.1", timestamp: "2026-07-14T09:00:00Z",
  }],
};
```

Use fake timers only for the polling test and restore real timers in `finally` so later auth tests cannot inherit clock state.

```tsx
it("keeps selected row order through a poll and restores live order after close", async () => {
  vi.mocked(getLifecycles)
    .mockResolvedValueOnce(lifecyclePage([btc, eth], null) as never)
    .mockResolvedValueOnce(lifecyclePage([ethUpdated, btcUpdated], null) as never);
  vi.useFakeTimers();
  try {
    vi.mocked(getLifecycleDetail).mockResolvedValue(detailBody as never);
    render(<App />);
    await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByRole("button", { name: "Apri dettagli BTC" }));
    await act(async () => { vi.advanceTimersByTime(15_000); await Promise.resolve(); });
    expect(screen.getAllByRole("button", { name: /Apri dettagli/ })
      .map(button => button.textContent)).toEqual(["BTC", "ETH"]);
    fireEvent.click(screen.getByRole("button", { name: "Chiudi dettaglio" }));
    expect(screen.getAllByRole("button", { name: /Apri dettagli/ })
      .map(button => button.textContent)).toEqual(["ETH", "BTC"]);
  } finally {
    vi.useRealTimers();
  }
});

it("closes detail when view or agent changes", async () => {
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Apri dettagli BTC" }));
  expect(await screen.findByRole("heading", { name: /Dettaglio BTC/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Chiuse" }));
  expect(screen.queryByRole("heading", { name: /Dettaglio BTC/ })).not.toBeInTheDocument();
});

it("returns to login when detail authorization is lost", async () => {
  vi.mocked(getLifecycleDetail).mockRejectedValueOnce(new AuthError());
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Apri dettagli BTC" }));
  expect(await screen.findByLabelText(/password/i)).toBeInTheDocument();
});
```

Keep the existing filter, load-more serialization, retry, and collection-auth tests in this file as the #26 regression suite.

- [ ] **Step 2: Verify the App tests are red**

Run: `cd frontend && npm test -- src/__tests__/App.auth.test.tsx`

Expected: new tests FAIL because `PositionsTable` lacks agent/auth props and reset identity.

- [ ] **Step 3: Wire the table without changing collection ownership**

Replace the existing call with:

```tsx
{selId !== null && (
  <PositionsTable
    key={`${selId}:${positionState}`}
    agentId={selId}
    items={positions}
    market={positionMarket}
    state={positionState}
    onAuthLost={onAuthLost}
  />
)}
```

The key intentionally resets selection and frozen rows on agent/view changes. Do not reset them on polling updates, `closedSince`, pagination, or market metadata changes. Do not change `lifecycleOptions`, request counters, 15-second interval, or `loadMorePositions`.

- [ ] **Step 4: Run App and full frontend tests**

Run: `cd frontend && npm test -- src/__tests__/App.auth.test.tsx`

Expected: all App tests PASS, including existing lifecycle filter/pagination cases.

Run: `cd frontend && npm test`

Expected: all frontend tests PASS.

- [ ] **Step 5: Run lint and production build**

Run: `cd frontend && npm run lint`

Expected: exit 0; pre-existing warnings may remain, with no new warning in changed files.

Run: `cd frontend && npm run build`

Expected: exit 0; the existing bundle-size warning may remain.

- [ ] **Step 6: Commit the App integration slice**

```bash
git add frontend/src/App.tsx frontend/src/__tests__/App.auth.test.tsx
git commit -m "feat: integrate open detail navigation (#28)"
```

---

### Task 7: Verify migration, acceptance coverage, and branch readiness

**Files:**
- Modify only if verification reveals a #28 defect in a file listed above.
- Test: all backend and frontend suites.

**Interfaces:**
- Consumes: completed Tasks 1–6.
- Produces: reproducible verification evidence and a branch ready for review; no publish, merge, or issue closure without separate authorization.

- [ ] **Step 1: Exercise the migration on a disposable database**

Run:

```bash
rm -f /private/tmp/crypto-bot-ticket-28.sqlite
cd backend
DATABASE_URL=sqlite:////private/tmp/crypto-bot-ticket-28.sqlite .venv/bin/alembic upgrade head
DATABASE_URL=sqlite:////private/tmp/crypto-bot-ticket-28.sqlite .venv/bin/alembic current
```

Expected: upgrade exits 0 and current revision is `2c7e4a8d9f01 (head)`.

Then verify reversibility and re-application:

```bash
DATABASE_URL=sqlite:////private/tmp/crypto-bot-ticket-28.sqlite .venv/bin/alembic downgrade 1a2b3c4d5e6f
DATABASE_URL=sqlite:////private/tmp/crypto-bot-ticket-28.sqlite .venv/bin/alembic upgrade head
```

Expected: both commands exit 0.

- [ ] **Step 2: Run complete backend verification**

Run: `cd backend && .venv/bin/pytest -q`

Expected: all backend tests PASS.

- [ ] **Step 3: Run complete frontend verification**

Run: `cd frontend && npm test && npm run lint && npm run build`

Expected: tests PASS; lint and build exit 0. Record known pre-existing warnings separately from new failures.

- [ ] **Step 4: Inspect the changed surface and whitespace**

Run: `git diff --check && git status --short && git diff --stat main...HEAD && git log --oneline main..HEAD`

Expected: no whitespace errors; only #28 files are changed; commits are the focused slices from this plan.

- [ ] **Step 5: Review each acceptance criterion against an observable test**

Confirm this mapping in the review notes:

- append-only BUY/SELL/HOLD evaluation context: runtime/engine/model tests;
- latest evaluation or explicit absence: API and component tests;
- net/exposure/realized/unrealized/fees: literal API test and detail rendering test;
- collapsed lifecycle-only accounting: API trade isolation and native disclosure test;
- fixed left region/right replacement/top alignment/natural height: table semantic/class tests;
- select/change/close/Escape/focus/keyboard/accessibility: table and component interaction tests;
- local loading/error/retry and global auth loss: component/App tests;
- frozen poll order and restoration: table/App tests;
- #26 filter/pagination behavior: unchanged App lifecycle navigation suite.

- [ ] **Step 6: Request code review before completion claims**

Use `superpowers:requesting-code-review` against `main...HEAD`. Fix only Critical or Important findings within #28 scope, then repeat Steps 2–4. If a finding requires #29–#32 behavior, document it as out of scope instead of expanding this branch.
