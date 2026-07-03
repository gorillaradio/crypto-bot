# Evaluation Harness (Pipeline v2 — Fase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure whether an agent has edge — overlay each agent's equity against three ghost benchmarks (HODL BTC, equal-weight universe, a band of 100 random portfolios), score every past decision after 24h/7d windows, and expose equity/hit-rate/max-drawdown/Sharpe per agent and per model.

**Architecture:** All benchmark/scoring/metric *math* lives in a new DB-free, network-free package `app/eval/` (pure functions, trivially unit-tested). Three new tables persist the outputs: `BenchmarkBasis` (each agent's frozen start prices + frozen universe, captured lazily on its first heartbeat), `BenchmarkSnapshot` (the forward benchmark curves, written each heartbeat right next to the agent's `EquitySnapshot` so the curves share timestamps), and `DecisionScore` (one score row per `DecisionRecord` × window). The heartbeat records benchmark snapshots; a new scheduler job re-scores matured `DecisionRecord`s using Binance historical klines. Read-only endpoints (mirroring Fase 1's `GET .../decisions`) feed a React overlay chart + metrics panel.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (typed `Mapped`), Pydantic v2, Alembic, pytest (SQLite in-memory via `conftest.db_session`), Python `random`/`statistics` stdlib, Binance public klines (free); frontend React 19 + recharts + Vitest/testing-library.

## Global Constraints

- **Branch:** all work continues on the long-lived `pipeline-v2` branch. Never commit to `main`, never push, no PR until the user asks. (Auto-deploy runs on push to `main`; nothing reaches prod until the final merge — intended, paper trading.)
- **Alembic head is `e49468a9c8dc`** (`decision_records`). The new migration's `down_revision` must be `e49468a9c8dc`.
- **Tests never run migrations** — `conftest.db_session` builds tables with `Base.metadata.create_all`. A new model is testable the moment it is added to `app/db/models.py`. The Alembic migration is a hand-written mirror, verified separately with a throwaway SQLite DB.
- **Match existing style:** long-text/JSON columns use bare `String` (no length), like `Event.message`. Money is `Numeric(20, 8)`. Timestamps are `DateTime(timezone=True), default=_now` (Python-side default; every insert goes through the ORM).
- **Auth:** reads use `_: str = Depends(require_viewer_or_admin)`; ORM rows are serialized directly through a plain-`BaseModel` `response_model` (proven by `get_events`/`get_equity`/`get_decisions`).
- **Retention:** keep everything — no pruning, no caps (paper trading, low volume).
- **Free data only** (committente constraint): historical prices come from Binance public klines (`/api/v3/klines`), never a paid feed.
- **Deterministic randomness:** the random benchmark must be reproducible. Seed `random.Random` with an **integer** derived from `agent_id` and the trader index — never `hash()` of a str/tuple (`PYTHONHASHSEED` randomizes those across processes).
- **Benchmark model (decided with committente 2026-07-03):** the "random trader" is **100 random buy-and-hold portfolios** (monkey portfolios): random weights over the frozen universe at start, held. Stored as a `p10/p50/p90` band, not 100 lines. HODL BTC and equal-weight are single lines. The universe is **frozen at the agent's first heartbeat** so benchmark composition doesn't drift with top-100 membership.

## Branch & Setup

Before Task 1:

```bash
cd /Users/seb/Dev/gorillaradio/crypto-bot
git switch pipeline-v2                              # already exists; Fase 1 is here
source backend/.venv/bin/activate                  # or use backend/.venv/bin/<tool> explicitly
cd backend && python -m pytest -q                  # sanity: 130 green before we start
```

Baseline: **130 backend tests green**, Alembic head `e49468a9c8dc`, working tree clean.

---

## Part A — Benchmarks

### Task 1: `app/eval/benchmarks.py` — pure benchmark math

**Files:**
- Create: `backend/app/eval/__init__.py` (empty)
- Create: `backend/app/eval/benchmarks.py`
- Test: `backend/tests/test_eval_benchmarks.py`

**Interfaces:**
- Produces: `app.eval.benchmarks.compute_benchmark_equities(*, initial: Decimal, universe: list[str], start_prices: dict[str, Decimal], now_prices: dict[str, Decimal], seed: int, n_random: int = 100) -> dict[str, Decimal]` returning keys exactly `"hodl_btc"`, `"equal_weight"`, `"random_p10"`, `"random_p50"`, `"random_p90"`.
- Produces (used by tests + reused internally): `random_weights(seed: int, trader_index: int, symbols: list[str]) -> dict[str, float]`, `hodl_btc_equity`, `equal_weight_equity`, `random_basket_equity`, `percentile(sorted_values: list[Decimal], p: float) -> Decimal`, and module constant `BTC_SYMBOL = "BTCUSDT"`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_eval_benchmarks.py`:

```python
from decimal import Decimal
from app.eval.benchmarks import (
    compute_benchmark_equities, random_weights, hodl_btc_equity,
    equal_weight_equity, percentile, BTC_SYMBOL,
)


def test_hodl_btc_doubles_when_btc_doubles():
    eq = hodl_btc_equity(Decimal("100"), {BTC_SYMBOL: Decimal("100")}, {BTC_SYMBOL: Decimal("200")})
    assert eq == Decimal("200")


def test_hodl_btc_falls_back_to_initial_without_btc():
    assert hodl_btc_equity(Decimal("100"), {}, {}) == Decimal("100")


def test_equal_weight_averages_symbol_returns():
    # AAA +100%, BBB flat → equal dollar split ends at 1.5x
    eq = equal_weight_equity(Decimal("100"), ["AAA", "BBB"],
                             {"AAA": Decimal("10"), "BBB": Decimal("10")},
                             {"AAA": Decimal("20"), "BBB": Decimal("10")})
    assert eq == Decimal("150")


def test_random_weights_are_deterministic_and_normalized():
    w1 = random_weights(7, 3, ["AAA", "BBB", "CCC"])
    w2 = random_weights(7, 3, ["AAA", "BBB", "CCC"])
    assert w1 == w2                                   # reproducible
    assert abs(sum(w1.values()) - 1.0) < 1e-9         # weights sum to 1
    assert random_weights(8, 3, ["AAA", "BBB", "CCC"]) != w1   # different agent → different draw


def test_percentile_interpolates():
    vals = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5")]
    assert percentile(vals, 0.0) == Decimal("1")
    assert percentile(vals, 0.5) == Decimal("3")
    assert percentile(vals, 1.0) == Decimal("5")


def test_compute_returns_five_named_series_with_ordered_band():
    universe = ["AAA", "BBB", "CCC", "DDD"]
    start = {s: Decimal("10") for s in universe} | {BTC_SYMBOL: Decimal("100")}
    now = {"AAA": Decimal("20"), "BBB": Decimal("5"), "CCC": Decimal("10"),
           "DDD": Decimal("15"), BTC_SYMBOL: Decimal("150")}
    out = compute_benchmark_equities(initial=Decimal("100"), universe=universe,
                                     start_prices=start, now_prices=now, seed=42, n_random=100)
    assert set(out) == {"hodl_btc", "equal_weight", "random_p10", "random_p50", "random_p90"}
    assert out["hodl_btc"] == Decimal("150")          # BTC +50%
    assert out["random_p10"] <= out["random_p50"] <= out["random_p90"]


def test_compute_is_reproducible_for_same_seed():
    universe = ["AAA", "BBB"]
    start = {"AAA": Decimal("10"), "BBB": Decimal("10")}
    now = {"AAA": Decimal("11"), "BBB": Decimal("9")}
    a = compute_benchmark_equities(initial=Decimal("100"), universe=universe,
                                   start_prices=start, now_prices=now, seed=1)
    b = compute_benchmark_equities(initial=Decimal("100"), universe=universe,
                                   start_prices=start, now_prices=now, seed=1)
    assert a == b
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_eval_benchmarks.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.eval'`.

- [ ] **Step 3: Create the package and implementation**

Create `backend/app/eval/__init__.py` (empty file).

Create `backend/app/eval/benchmarks.py`:

```python
import random
from decimal import Decimal

BTC_SYMBOL = "BTCUSDT"


def random_weights(seed: int, trader_index: int, symbols: list[str]) -> dict[str, float]:
    # Integer seed only — never hash() a str/tuple (PYTHONHASHSEED randomizes those).
    rng = random.Random(seed * 1_000_003 + trader_index)
    raw = [rng.random() for _ in symbols]
    total = sum(raw) or 1.0
    return {s: r / total for s, r in zip(symbols, raw)}


def hodl_btc_equity(initial: Decimal, start_prices: dict[str, Decimal],
                    now_prices: dict[str, Decimal]) -> Decimal:
    s = start_prices.get(BTC_SYMBOL)
    n = now_prices.get(BTC_SYMBOL)
    if not s or not n:
        return initial
    return initial * (n / s)


def equal_weight_equity(initial: Decimal, universe: list[str],
                        start_prices: dict[str, Decimal], now_prices: dict[str, Decimal]) -> Decimal:
    valid = [s for s in universe if start_prices.get(s) and now_prices.get(s)]
    if not valid:
        return initial
    per = initial / Decimal(len(valid))
    return sum((per * (now_prices[s] / start_prices[s]) for s in valid), Decimal("0"))


def random_basket_equity(initial: Decimal, weights: dict[str, float],
                         start_prices: dict[str, Decimal], now_prices: dict[str, Decimal]) -> Decimal:
    total = Decimal("0")
    for s, w in weights.items():
        s0 = start_prices.get(s)
        s1 = now_prices.get(s)
        if not s0 or not s1:
            continue
        total += initial * Decimal(str(w)) * (s1 / s0)
    return total


def percentile(sorted_values: list[Decimal], p: float) -> Decimal:
    if not sorted_values:
        return Decimal("0")
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = p * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = Decimal(str(idx - lo))
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def compute_benchmark_equities(*, initial: Decimal, universe: list[str],
                               start_prices: dict[str, Decimal], now_prices: dict[str, Decimal],
                               seed: int, n_random: int = 100) -> dict[str, Decimal]:
    eqs = []
    for i in range(n_random):
        w = random_weights(seed, i, universe)
        eqs.append(random_basket_equity(initial, w, start_prices, now_prices))
    eqs.sort()
    return {
        "hodl_btc": hodl_btc_equity(initial, start_prices, now_prices),
        "equal_weight": equal_weight_equity(initial, universe, start_prices, now_prices),
        "random_p10": percentile(eqs, 0.10),
        "random_p50": percentile(eqs, 0.50),
        "random_p90": percentile(eqs, 0.90),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_eval_benchmarks.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/eval/__init__.py backend/app/eval/benchmarks.py backend/tests/test_eval_benchmarks.py
git commit -m "feat(eval): pure benchmark math (HODL BTC, equal-weight, random monkey-portfolio band)"
```

---

### Task 2: Three models + one migration (`BenchmarkBasis`, `BenchmarkSnapshot`, `DecisionScore`)

**Files:**
- Modify: `backend/app/db/models.py` (append three models)
- Create: `backend/alembic/versions/<generated>_eval_harness_tables.py`
- Test: `backend/tests/test_models.py` (append four tests)

**Interfaces:**
- Produces `app.db.models.BenchmarkBasis`: `id:int, agent_id:int(FK agents.id, unique index), universe_json:str, start_prices_json:str, initial_capital:Decimal(20,8), created_at:datetime`.
- Produces `app.db.models.BenchmarkSnapshot`: `id:int, agent_id:int(FK, indexed), kind:str(20), equity_usd:Decimal(20,8), timestamp:datetime(default _now, indexed)`.
- Produces `app.db.models.DecisionScore`: `id:int, decision_record_id:int(FK decision_records.id, indexed), window:str(8), n_actions:int, n_hits:int, avg_return_pct:Decimal(12,4)|None, scored_at:datetime(default _now)`, with `UniqueConstraint("decision_record_id", "window")`.

- [ ] **Step 1: Write the failing model tests**

Append to `backend/tests/test_models.py` (the file already defines `_mk_agent`):

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_models.py -q`
Expected: FAIL with `ImportError: cannot import name 'BenchmarkBasis'`.

- [ ] **Step 3: Add the models**

Append to `backend/app/db/models.py` (imports already include `Integer`, `Numeric`, `String`, `DateTime`, `ForeignKey`, `UniqueConstraint`):

```python
class BenchmarkBasis(Base):
    __tablename__ = "benchmark_basis"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), unique=True, index=True)
    universe_json: Mapped[str] = mapped_column(String)          # JSON list of frozen symbols
    start_prices_json: Mapped[str] = mapped_column(String)      # JSON {symbol: "price"} at start
    initial_capital: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BenchmarkSnapshot(Base):
    __tablename__ = "benchmark_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))               # hodl_btc | equal_weight | random_p10|p50|p90
    equity_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class DecisionScore(Base):
    __tablename__ = "decision_scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    decision_record_id: Mapped[int] = mapped_column(ForeignKey("decision_records.id"), index=True)
    window: Mapped[str] = mapped_column(String(8))              # "24h" | "7d"
    n_actions: Mapped[int] = mapped_column(Integer)
    n_hits: Mapped[int] = mapped_column(Integer)
    avg_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("decision_record_id", "window", name="uq_decision_score_window"),)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_models.py -q`
Expected: PASS (existing model tests + the four new ones).

- [ ] **Step 5: Generate the migration skeleton**

Run: `cd backend && python -m alembic revision -m "eval harness tables"`
Expected: creates `backend/alembic/versions/<hash>_eval_harness_tables.py` with `down_revision = 'e49468a9c8dc'` prefilled.

- [ ] **Step 6: Fill in the migration**

Replace the generated `upgrade()`/`downgrade()` bodies (mirror `e49468a9c8dc_decision_records.py`):

```python
def upgrade() -> None:
    op.create_table(
        "benchmark_basis",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("universe_json", sa.String(), nullable=False),
        sa.Column("start_prices_json", sa.String(), nullable=False),
        sa.Column("initial_capital", sa.Numeric(20, 8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_benchmark_basis_agent_id", "benchmark_basis", ["agent_id"], unique=True)

    op.create_table(
        "benchmark_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("equity_usd", sa.Numeric(20, 8), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_benchmark_snapshots_agent_id", "benchmark_snapshots", ["agent_id"])
    op.create_index("ix_benchmark_snapshots_timestamp", "benchmark_snapshots", ["timestamp"])

    op.create_table(
        "decision_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_record_id", sa.Integer(), sa.ForeignKey("decision_records.id"), nullable=False),
        sa.Column("window", sa.String(length=8), nullable=False),
        sa.Column("n_actions", sa.Integer(), nullable=False),
        sa.Column("n_hits", sa.Integer(), nullable=False),
        sa.Column("avg_return_pct", sa.Numeric(12, 4), nullable=True),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("decision_record_id", "window", name="uq_decision_score_window"),
    )
    op.create_index("ix_decision_scores_decision_record_id", "decision_scores", ["decision_record_id"])


def downgrade() -> None:
    op.drop_index("ix_decision_scores_decision_record_id", table_name="decision_scores")
    op.drop_table("decision_scores")
    op.drop_index("ix_benchmark_snapshots_timestamp", table_name="benchmark_snapshots")
    op.drop_index("ix_benchmark_snapshots_agent_id", table_name="benchmark_snapshots")
    op.drop_table("benchmark_snapshots")
    op.drop_index("ix_benchmark_basis_agent_id", table_name="benchmark_basis")
    op.drop_table("benchmark_basis")
```

- [ ] **Step 7: Smoke-test the migration up and down**

```bash
cd backend && rm -f _mig_smoke.db
DATABASE_URL="sqlite:///./_mig_smoke.db" python -m alembic upgrade head
DATABASE_URL="sqlite:///./_mig_smoke.db" python -m alembic downgrade -1
rm -f _mig_smoke.db
```

Expected: `upgrade` ends with `Running upgrade e49468a9c8dc -> <hash>, eval harness tables` and no error; `downgrade` runs cleanly.

- [ ] **Step 8: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/*_eval_harness_tables.py backend/tests/test_models.py
git commit -m "feat(db): BenchmarkBasis, BenchmarkSnapshot, DecisionScore tables + migration"
```

---

### Task 3: Heartbeat records benchmark snapshots

**Files:**
- Modify: `backend/app/agents/runtime.py` (imports; `record_benchmark_snapshot` helper; call it in `run_heartbeat`)
- Test: `backend/tests/test_runtime.py` (extend the two heartbeat fakes; add three tests)

**Interfaces:**
- Consumes: `app.eval.benchmarks.compute_benchmark_equities` (Task 1); `app.db.models.BenchmarkBasis`, `BenchmarkSnapshot` (Task 2); `settings.initial_capital_usd`; `universe_size` (existing); `market.get_top_symbols`, `market.get_universe_snapshot` (existing `BinanceClient` methods).
- Produces: `record_benchmark_snapshot(session, agent, market) -> None` (async, module-level in `runtime.py`). On the agent's first call it freezes a `BenchmarkBasis` (universe via `get_top_symbols`, start prices via `get_universe_snapshot`); every call writes five `BenchmarkSnapshot` rows (`hodl_btc`, `equal_weight`, `random_p10`, `random_p50`, `random_p90`). It is self-isolating: any failure rolls back its own work and never propagates (benchmarks are telemetry, they must not break the heartbeat).

- [ ] **Step 1: Extend the heartbeat fakes and write the three tests**

In `backend/tests/test_runtime.py`, extend the models import (line 3) to add `BenchmarkBasis, BenchmarkSnapshot`, and give both heartbeat fakes a universe (so benchmark recording works). Replace the `FakeMarket` and `FakeMarketHB` class bodies with:

```python
class FakeMarket:
    def __init__(self, price, book):
        self._price, self._book = price, book
    async def get_price(self, symbol): return self._price
    async def get_book_ticker(self, symbol): return self._book
    async def get_top_symbols(self, quote, n): return ["BTCUSDT"]
    async def get_universe_snapshot(self, symbols):
        return [CoinSnapshot(s, self._price, Decimal("0")) for s in symbols]


class FakeMarketHB:
    """Market per l'heartbeat: prezzo unico per ogni simbolo + get_top_symbols + universo."""
    def __init__(self, price, symbols=None):
        self._price, self._symbols = price, symbols or ["BTCUSDT"]
    async def get_price(self, symbol): return self._price
    async def get_top_symbols(self, quote, n): return self._symbols
    async def get_universe_snapshot(self, symbols):
        return [CoinSnapshot(s, self._price, Decimal("0")) for s in symbols]
```

Then append these tests:

```python
async def test_heartbeat_writes_benchmark_snapshots_and_basis(db_session):
    agent = _agent(db_session, "100")
    market = FakeMarketHB(price=Decimal("100"), symbols=["BTCUSDT", "ETHUSDT"])
    await run_heartbeat(db_session, agent, market)
    basis = db_session.query(BenchmarkBasis).filter_by(agent_id=agent.id).one()
    assert basis.initial_capital == Decimal("100")
    kinds = sorted(r.kind for r in
                   db_session.query(BenchmarkSnapshot).filter_by(agent_id=agent.id).all())
    assert kinds == ["equal_weight", "hodl_btc", "random_p10", "random_p50", "random_p90"]
    # at the first heartbeat every benchmark equals the initial capital (start == now prices)
    for r in db_session.query(BenchmarkSnapshot).filter_by(agent_id=agent.id).all():
        assert r.equity_usd == Decimal("100")


async def test_heartbeat_basis_frozen_across_beats(db_session):
    agent = _agent(db_session, "100")
    await run_heartbeat(db_session, agent, FakeMarketHB(price=Decimal("100")))   # freezes basis at 100
    await run_heartbeat(db_session, agent, FakeMarketHB(price=Decimal("200")))   # BTC doubled
    assert db_session.query(BenchmarkBasis).filter_by(agent_id=agent.id).count() == 1   # frozen once
    hodl = (db_session.query(BenchmarkSnapshot)
            .filter_by(agent_id=agent.id, kind="hodl_btc")
            .order_by(BenchmarkSnapshot.id.desc()).first())
    assert hodl.equity_usd == Decimal("200")     # 100 * 200/100


async def test_heartbeat_benchmark_failure_does_not_break_equity(db_session):
    agent = _agent(db_session, "100")

    class BrokenUniverse:
        async def get_price(self, symbol): return Decimal("100")
        async def get_top_symbols(self, quote, n): return ["BTCUSDT"]
        async def get_universe_snapshot(self, symbols): raise RuntimeError("ticker down")

    await run_heartbeat(db_session, agent, BrokenUniverse())
    # equity snapshot still written, benchmark rows absent, no exception bubbled up
    assert db_session.query(EquitySnapshot).filter_by(agent_id=agent.id).one().equity_usd == Decimal("100")
    assert db_session.query(BenchmarkSnapshot).filter_by(agent_id=agent.id).count() == 0
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_runtime.py -k benchmark -q`
Expected: FAIL — `run_heartbeat` does not record benchmarks yet, so `test_heartbeat_writes_benchmark_snapshots_and_basis` finds zero `BenchmarkBasis` rows (`NoResultFound`).

- [ ] **Step 3: Add the helper and call it in `run_heartbeat`**

In `backend/app/agents/runtime.py`, extend the models import (line 7):

```python
from app.db.models import EquitySnapshot, Event, AgentMemory, DecisionRecord, BenchmarkBasis, BenchmarkSnapshot
```

Add near the top (with the other imports):

```python
from app.eval.benchmarks import compute_benchmark_equities
```

Append the helper at the end of the file (after `_persist_memory`):

```python
async def record_benchmark_snapshot(session, agent, market) -> None:
    """Write the ghost-benchmark equities for this beat. Self-isolating: on any error
    it rolls back its own work and returns — benchmarks are telemetry, never a reason
    to break the heartbeat."""
    try:
        basis = session.query(BenchmarkBasis).filter_by(agent_id=agent.id).first()
        if basis is None:
            symbols = await market.get_top_symbols("USDT", universe_size(agent))
            snap = await market.get_universe_snapshot(symbols)
            start_prices = {c.symbol: c.price for c in snap}
            basis = BenchmarkBasis(
                agent_id=agent.id,
                universe_json=json.dumps(symbols),
                start_prices_json=json.dumps({s: str(p) for s, p in start_prices.items()}),
                initial_capital=settings.initial_capital_usd)
            session.add(basis)
            now_prices = start_prices
            universe = symbols
        else:
            universe = json.loads(basis.universe_json)
            start_prices = {s: Decimal(p) for s, p in json.loads(basis.start_prices_json).items()}
            snap = await market.get_universe_snapshot(universe)
            now_prices = {c.symbol: c.price for c in snap}
        equities = compute_benchmark_equities(
            initial=basis.initial_capital, universe=universe,
            start_prices=start_prices, now_prices=now_prices, seed=agent.id)
        for kind, equity in equities.items():
            session.add(BenchmarkSnapshot(agent_id=agent.id, kind=kind, equity_usd=equity))
        session.commit()
    except Exception:
        session.rollback()
```

In `run_heartbeat`, right after the equity snapshot commit (currently `session.add(EquitySnapshot(...)); session.commit()`), add the call **before** the breach early-return:

```python
    equity = agent.cash_usd + positions_value
    session.add(EquitySnapshot(agent_id=agent.id, equity_usd=equity))
    session.commit()

    await record_benchmark_snapshot(session, agent, market)

    if fresh is None:
        return
```

- [ ] **Step 4: Run the full backend suite to verify green**

Run: `cd backend && python -m pytest -q`
Expected: PASS — the three new benchmark tests plus every pre-existing heartbeat test (the enhanced fakes now expose `get_universe_snapshot`/`get_top_symbols`; the extra `BenchmarkSnapshot` rows are in a separate table and don't affect their `EquitySnapshot`/`Trade`/`Position` assertions).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/runtime.py backend/tests/test_runtime.py
git commit -m "feat(runtime): record ghost-benchmark snapshots each heartbeat (basis frozen at first beat)"
```

---

### Task 4: `GET /agents/{id}/benchmarks` + benchmark delete cascade

**Files:**
- Modify: `backend/app/api/schemas.py` (add `BenchmarkPoint`)
- Modify: `backend/app/api/routes.py` (import models/schema; add endpoint; extend delete cascade)
- Test: `backend/tests/test_api.py` (endpoint + cascade), `backend/tests/test_auth.py` (authorization)

**Interfaces:**
- Consumes: `app.db.models.BenchmarkSnapshot`, `BenchmarkBasis`.
- Produces: `GET /agents/{agent_id}/benchmarks -> list[BenchmarkPoint]`, oldest-first (for charting), `require_viewer_or_admin`; missing agent → `200 []`. Deleting an agent removes its `benchmark_basis` + `benchmark_snapshots`.
- Produces schema `BenchmarkPoint(kind: str, timestamp: datetime, equity_usd: Decimal)`.

- [ ] **Step 1: Write the failing endpoint + auth + cascade tests**

Add to `backend/tests/test_api.py`:

```python
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
```

Add to `backend/tests/test_auth.py` (mirrors `test_decisions_require_a_session`):

```python
def test_benchmarks_require_a_session(client, db_session):
    assert client.get("/api/agents/1/benchmarks").status_code == 401
    db_session.add(ShareLink(token="v4")); db_session.commit()
    client.post("/api/auth/viewer", json={"token": "v4"})
    assert client.get("/api/agents/1/benchmarks").status_code == 200   # viewer can read
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api.py::test_get_benchmarks_returns_points_oldest_first tests/test_auth.py::test_benchmarks_require_a_session -q`
Expected: FAIL with `404 Not Found` (route absent) → status-code assertions fail.

- [ ] **Step 3: Add the response schema**

In `backend/app/api/schemas.py`, add after `EquityPoint`:

```python
class BenchmarkPoint(BaseModel):
    kind: str
    timestamp: datetime
    equity_usd: Decimal
```

- [ ] **Step 4: Add the endpoint and extend the delete cascade**

In `backend/app/api/routes.py`:

1. Extend the models import to include the benchmark tables:
   `from app.db.models import Agent, AgentMemory, BenchmarkBasis, BenchmarkSnapshot, DecisionRecord, EquitySnapshot, Event, Position, Trade`
2. Add `BenchmarkPoint` to the `app.api.schemas` import.
3. In `delete_agent`, extend the cascade loop:
   `for model in (Position, Trade, EquitySnapshot, Event, AgentMemory, DecisionRecord, BenchmarkBasis, BenchmarkSnapshot):`
4. Add the endpoint (mirror `get_equity` — oldest first, no 404):
   ```python
   @router.get("/agents/{agent_id}/benchmarks", response_model=list[BenchmarkPoint])
   def get_benchmarks(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
       return (
           session.query(BenchmarkSnapshot)
           .filter_by(agent_id=agent_id)
           .order_by(BenchmarkSnapshot.timestamp.asc(), BenchmarkSnapshot.id.asc())
           .all()
       )
   ```

- [ ] **Step 5: Run the full backend suite to verify green**

Run: `cd backend && python -m pytest -q`
Expected: PASS — all tests including the four new benchmark API/auth tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api.py backend/tests/test_auth.py
git commit -m "feat(api): GET /agents/{id}/benchmarks + benchmark delete cascade"
```

---

## Part B — Per-decision scoring

### Task 5: `BinanceClient.get_price_at` — historical price at a timestamp

**Files:**
- Modify: `backend/app/market/binance.py` (add `get_price_at`)
- Test: `backend/tests/test_binance_price_at.py` (create)

**Interfaces:**
- Produces: `BinanceClient.get_price_at(symbol: str, ms: int) -> Decimal | None`. Fetches the first 1h kline at/after `ms` and returns its close (index 4); returns `None` when Binance returns no candle (delisted/out of range). Convention: both endpoints of a scoring window use this same "hourly close nearest the timestamp" rule, so the measured return is consistent.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_binance_price_at.py` (stubs `_get`, so no network):

```python
import pytest
from decimal import Decimal
from app.market.binance import BinanceClient


class StubClient(BinanceClient):
    def __init__(self, rows):
        super().__init__()
        self._rows = rows
        self.last_params = None
    async def _get(self, path, params):
        self.last_params = params
        return self._rows


async def test_get_price_at_returns_close_of_first_candle():
    # a kline row: [openTime, open, high, low, close, ...]
    c = StubClient([[1000, "10", "12", "9", "11", "…"]])
    price = await c.get_price_at("BTCUSDT", 1000)
    assert price == Decimal("11")                       # index 4 = close
    assert c.last_params["startTime"] == 1000 and c.last_params["limit"] == 1


async def test_get_price_at_returns_none_when_empty():
    c = StubClient([])
    assert await c.get_price_at("BTCUSDT", 1000) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_binance_price_at.py -q`
Expected: FAIL with `AttributeError: 'StubClient' object has no attribute 'get_price_at'`.

- [ ] **Step 3: Implement `get_price_at`**

In `backend/app/market/binance.py`, add after `get_klines`:

```python
    async def get_price_at(self, symbol: str, ms: int) -> Decimal | None:
        data = await self._get(
            "/api/v3/klines",
            {"symbol": symbol, "interval": "1h", "startTime": ms, "limit": 1},
        )
        if not data:
            return None
        return Decimal(data[0][4])  # index 4 = close
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_binance_price_at.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/market/binance.py backend/tests/test_binance_price_at.py
git commit -m "feat(market): BinanceClient.get_price_at — historical hourly close at a timestamp"
```

---

### Task 6: `app/eval/scoring.py` — pure decision scoring

**Files:**
- Create: `backend/app/eval/scoring.py`
- Test: `backend/tests/test_eval_scoring.py`

**Interfaces:**
- Produces: `aligned_return_pct(action_type: str, p0: Decimal, p1: Decimal) -> Decimal` — the decision-aligned return: `(p1-p0)/p0*100` for BUY, its negation for SELL (a SELL "wins" when the price falls afterwards). `0` when `p0 <= 0`.
- Produces: `score_decision(actions: list[dict], p0: dict[str, Decimal], p1: dict[str, Decimal]) -> tuple[int, int, Decimal | None]` → `(n_actions, n_hits, avg_return_pct)`. Counts only BUY/SELL actions whose symbol is priced (present in both `p0` and `p1`, `p0>0`); `hit` = aligned return > 0; `avg_return_pct` is `None` when no action was scorable. `actions` are the dicts from `json.loads(DecisionRecord.parsed_output)["actions"]`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_eval_scoring.py`:

```python
from decimal import Decimal
from app.eval.scoring import aligned_return_pct, score_decision


def test_buy_win_when_price_rises():
    assert aligned_return_pct("BUY", Decimal("100"), Decimal("110")) == Decimal("10")


def test_sell_win_when_price_falls():
    # sold at 100, price fell to 90 → good exit → +10 aligned return
    assert aligned_return_pct("SELL", Decimal("100"), Decimal("90")) == Decimal("10")


def test_score_counts_hits_and_averages_only_priced_actions():
    actions = [
        {"type": "BUY", "symbol": "AAA"},      # 100 → 120, +20, hit
        {"type": "SELL", "symbol": "BBB"},     # 100 → 120, aligned -20, miss
        {"type": "BUY", "symbol": "CCC"},      # unpriced → ignored
        {"type": "HOLD", "symbol": None},      # not BUY/SELL → ignored
    ]
    p0 = {"AAA": Decimal("100"), "BBB": Decimal("100")}
    p1 = {"AAA": Decimal("120"), "BBB": Decimal("120")}
    n, hits, avg = score_decision(actions, p0, p1)
    assert n == 2 and hits == 1
    assert avg == Decimal("0")                 # (+20 + -20) / 2


def test_score_no_scorable_actions_returns_none_avg():
    n, hits, avg = score_decision([{"type": "BUY", "symbol": "ZZZ"}], {}, {})
    assert n == 0 and hits == 0 and avg is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_eval_scoring.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.eval.scoring'`.

- [ ] **Step 3: Implement the scorer**

Create `backend/app/eval/scoring.py`:

```python
from decimal import Decimal


def aligned_return_pct(action_type: str, p0: Decimal, p1: Decimal) -> Decimal:
    if p0 <= 0:
        return Decimal("0")
    ret = (p1 - p0) / p0 * Decimal("100")
    return ret if action_type == "BUY" else -ret


def score_decision(actions: list[dict], p0: dict[str, Decimal],
                   p1: dict[str, Decimal]) -> tuple[int, int, Decimal | None]:
    n = hits = 0
    total = Decimal("0")
    for a in actions:
        t = a.get("type")
        sym = a.get("symbol")
        if t not in ("BUY", "SELL") or not sym:
            continue
        if sym not in p0 or sym not in p1 or p0[sym] <= 0:
            continue
        r = aligned_return_pct(t, p0[sym], p1[sym])
        n += 1
        if r > 0:
            hits += 1
        total += r
    avg = (total / Decimal(n)) if n else None
    return n, hits, avg
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_eval_scoring.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/eval/scoring.py backend/tests/test_eval_scoring.py
git commit -m "feat(eval): pure per-decision scoring (aligned return, hit counting)"
```

---

### Task 7: `score_matured_decisions` — the scoring job body

**Files:**
- Create: `backend/app/eval/scoring_job.py`
- Test: `backend/tests/test_scoring_job.py`

**Interfaces:**
- Consumes: `app.db.models.DecisionRecord`, `DecisionScore` (Task 2); `app.eval.scoring.score_decision` (Task 6); an injected `market` with `get_price_at(symbol, ms) -> Decimal | None` (Task 5).
- Produces: `WINDOWS: dict[str, timedelta] = {"24h": timedelta(hours=24), "7d": timedelta(days=7)}` and `score_matured_decisions(session, market, now: datetime) -> int`. Scores each `kind="decision"`, `parse_status in ("ok","repaired")` record for every window whose maturity (`created_at + delta <= now`) has passed and that has no `DecisionScore` yet; writes one `DecisionScore` per newly-scored `(record, window)`; returns how many it wrote. Robust to naive datetimes from SQLite (treats naive as UTC).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_scoring_job.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_scoring_job.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.eval.scoring_job'`.

- [ ] **Step 3: Implement the job body**

Create `backend/app/eval/scoring_job.py`:

```python
import json
from datetime import datetime, timedelta, timezone
from app.db.models import DecisionRecord, DecisionScore
from app.eval.scoring import score_decision

WINDOWS: dict[str, timedelta] = {"24h": timedelta(hours=24), "7d": timedelta(days=7)}


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ms(dt: datetime) -> int:
    return int(_as_utc(dt).timestamp() * 1000)


async def score_matured_decisions(session, market, now: datetime) -> int:
    now = _as_utc(now)
    written = 0
    records = (session.query(DecisionRecord)
               .filter(DecisionRecord.kind == "decision",
                       DecisionRecord.parse_status.in_(("ok", "repaired")))
               .all())
    for rec in records:
        for window, delta in WINDOWS.items():
            if _as_utc(rec.created_at) + delta > now:
                continue
            already = (session.query(DecisionScore)
                       .filter_by(decision_record_id=rec.id, window=window).first())
            if already:
                continue
            actions = json.loads(rec.parsed_output or "{}").get("actions", [])
            symbols = {a.get("symbol") for a in actions
                       if a.get("type") in ("BUY", "SELL") and a.get("symbol")}
            p0: dict = {}
            p1: dict = {}
            for s in symbols:
                a0 = await market.get_price_at(s, _ms(rec.created_at))
                a1 = await market.get_price_at(s, _ms(_as_utc(rec.created_at) + delta))
                if a0 is not None:
                    p0[s] = a0
                if a1 is not None:
                    p1[s] = a1
            n, hits, avg = score_decision(actions, p0, p1)
            session.add(DecisionScore(decision_record_id=rec.id, window=window,
                                      n_actions=n, n_hits=hits, avg_return_pct=avg))
            written += 1
    session.commit()
    return written
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_scoring_job.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/eval/scoring_job.py backend/tests/test_scoring_job.py
git commit -m "feat(eval): score_matured_decisions — window-based, idempotent per (record, window)"
```

---

### Task 8: Wire the scoring job into the scheduler + config + DecisionScore delete cascade

**Files:**
- Modify: `backend/app/core/config.py` (add `scoring_seconds`)
- Modify: `backend/app/scheduler/jobs.py` (add `_scoring_tick`; register it)
- Modify: `backend/app/api/routes.py` (delete cascade for `DecisionScore`)
- Test: `backend/tests/test_scheduler_jobs.py` (create — scoring tick iterates running agents), `backend/tests/test_api.py` (cascade)

**Interfaces:**
- Consumes: `app.eval.scoring_job.score_matured_decisions`; `settings.scoring_seconds`; `BinanceClient`; `datetime.now(timezone.utc)`.
- Produces: `_scoring_tick()` (async) in `scheduler/jobs.py`, registered on `start_scheduler` at `settings.scoring_seconds`. `delete_agent` now also deletes `DecisionScore` rows for the agent's decision records (before deleting the records themselves).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_scheduler_jobs.py`:

```python
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import app.scheduler.jobs as jobs
from app.db.models import Agent, DecisionRecord, DecisionScore


def _running_agent(session):
    a = Agent(name="Run", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("100"), status="running")
    session.add(a); session.commit()
    return a


async def test_scoring_tick_scores_matured_decisions(db_session, monkeypatch):
    agent = _running_agent(db_session)
    rec = DecisionRecord(agent_id=agent.id, cycle_id="c", kind="decision", trigger="schedule",
                         system_prompt="s", user_prompt="u", raw_response="r",
                         parsed_output='{"actions":[{"type":"BUY","symbol":"BTCUSDT"}]}',
                         parse_status="ok", model_provider="openrouter", model_name="m", latency_ms=1)
    rec.created_at = datetime.now(timezone.utc) - timedelta(days=8)
    db_session.add(rec); db_session.commit()

    # session factory used by the tick → our in-memory session
    monkeypatch.setattr(jobs, "get_session", lambda: _CtxSession(db_session))

    class FakeMarket:
        async def get_price_at(self, symbol, ms): return Decimal("100")
    monkeypatch.setattr(jobs, "BinanceClient", lambda: FakeMarket())

    await jobs._scoring_tick()
    assert db_session.query(DecisionScore).filter_by(decision_record_id=rec.id).count() == 2


class _CtxSession:
    """Minimal context-manager wrapper so `with get_session() as s:` yields our test session."""
    def __init__(self, s): self._s = s
    def __enter__(self): return self._s
    def __exit__(self, *a): return False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_scheduler_jobs.py -q`
Expected: FAIL with `AttributeError: module 'app.scheduler.jobs' has no attribute '_scoring_tick'`.

- [ ] **Step 3: Add config, the tick, and register it**

In `backend/app/core/config.py`, add after `decision_seconds`:

```python
    scoring_seconds: int = 900       # re-score matured decisions every 15 min
```

In `backend/app/scheduler/jobs.py`, add imports at the top:

```python
from datetime import datetime, timezone
from app.eval.scoring_job import score_matured_decisions
```

Add the tick (after `_decision_tick`):

```python
async def _scoring_tick():
    market = BinanceClient()
    now = datetime.now(timezone.utc)
    with get_session() as session:
        try:
            await score_matured_decisions(session, market, now)
        except Exception as exc:
            logger.error("scoring tick failed: %s", exc)
            session.rollback()
```

Register it in `start_scheduler` (after the decision job):

```python
    _scheduler.add_job(_scoring_tick, "interval", seconds=settings.scoring_seconds)
```

- [ ] **Step 4: Run the scheduler test to verify it passes**

Run: `cd backend && python -m pytest tests/test_scheduler_jobs.py -q`
Expected: PASS.

- [ ] **Step 5: Add the DecisionScore delete cascade + its test**

Add to `backend/tests/test_api.py`:

```python
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
```

In `backend/app/api/routes.py`, import `DecisionScore` (extend the models import line) and, in `delete_agent`, delete the scores **before** the cascade loop (which deletes the parent `DecisionRecord`s):

```python
    rec_ids = [rid for (rid,) in
               session.query(DecisionRecord.id).filter_by(agent_id=agent_id).all()]
    if rec_ids:
        (session.query(DecisionScore)
         .filter(DecisionScore.decision_record_id.in_(rec_ids))
         .delete(synchronize_session=False))
    for model in (Position, Trade, EquitySnapshot, Event, AgentMemory, DecisionRecord,
                  BenchmarkBasis, BenchmarkSnapshot):
        session.query(model).filter_by(agent_id=agent_id).delete(synchronize_session=False)
```

- [ ] **Step 6: Run the full backend suite to verify green**

Run: `cd backend && python -m pytest -q`
Expected: PASS — all tests, including the scheduler tick and the DecisionScore cascade.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/config.py backend/app/scheduler/jobs.py backend/app/api/routes.py backend/tests/test_scheduler_jobs.py backend/tests/test_api.py
git commit -m "feat(scheduler): scoring tick + config; delete cascade for DecisionScore"
```

---

## Part C — Metrics

### Task 9: `app/eval/metrics.py` — pure risk/return metrics

**Files:**
- Create: `backend/app/eval/metrics.py`
- Test: `backend/tests/test_eval_metrics.py`

**Interfaces:**
- Produces: `total_return_pct(series: list[Decimal]) -> Decimal` (`0` if `<2` points or first is `0`); `max_drawdown_pct(series: list[Decimal]) -> Decimal` (largest peak-to-trough decline as a positive %); `sharpe(series: list[Decimal]) -> Decimal` (mean/population-stdev of per-step returns; `0` if `<2` returns or stdev `0`; unannualized — comparable across series at the same cadence); `hit_rate(n_hits: int, n_actions: int) -> Decimal | None` (`None` if `n_actions <= 0`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_eval_metrics.py`:

```python
from decimal import Decimal
from app.eval.metrics import total_return_pct, max_drawdown_pct, sharpe, hit_rate


def test_total_return_pct():
    assert total_return_pct([Decimal("100"), Decimal("150")]) == Decimal("50")
    assert total_return_pct([Decimal("100")]) == Decimal("0")     # need ≥2 points


def test_max_drawdown_pct():
    # 100 → 120 → 60 → 90: peak 120, trough 60 → 50% drawdown
    assert max_drawdown_pct([Decimal("100"), Decimal("120"), Decimal("60"), Decimal("90")]) == Decimal("50")
    assert max_drawdown_pct([Decimal("100"), Decimal("110")]) == Decimal("0")   # monotonic up


def test_sharpe_zero_when_flat():
    assert sharpe([Decimal("100"), Decimal("100"), Decimal("100")]) == Decimal("0")


def test_sharpe_positive_for_steady_growth():
    # Varying step returns (10% then ~13.6%) → nonzero stdev → positive Sharpe.
    # NB: [100,110,121] is exact 10% compounding → identical step returns → stdev 0 → Sharpe 0
    # (which would falsify this assertion), so use a non-geometric series.
    assert sharpe([Decimal("100"), Decimal("110"), Decimal("125")]) > Decimal("0")


def test_hit_rate():
    assert hit_rate(3, 4) == Decimal("75")
    assert hit_rate(0, 0) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_eval_metrics.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.eval.metrics'`.

- [ ] **Step 3: Implement the metrics**

Create `backend/app/eval/metrics.py`:

```python
from decimal import Decimal
from statistics import mean, pstdev


def total_return_pct(series: list[Decimal]) -> Decimal:
    if len(series) < 2 or series[0] == 0:
        return Decimal("0")
    return (series[-1] - series[0]) / series[0] * Decimal("100")


def max_drawdown_pct(series: list[Decimal]) -> Decimal:
    if not series:
        return Decimal("0")
    peak = series[0]
    mdd = Decimal("0")
    for v in series:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak * Decimal("100")
            if dd > mdd:
                mdd = dd
    return mdd


def sharpe(series: list[Decimal]) -> Decimal:
    rets = [(series[i] - series[i - 1]) / series[i - 1]
            for i in range(1, len(series)) if series[i - 1] != 0]
    if len(rets) < 2:
        return Decimal("0")
    sd = pstdev(rets)
    if sd == 0:
        return Decimal("0")
    return mean(rets) / sd


def hit_rate(n_hits: int, n_actions: int) -> Decimal | None:
    if n_actions <= 0:
        return None
    return Decimal(n_hits) / Decimal(n_actions) * Decimal("100")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_eval_metrics.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/eval/metrics.py backend/tests/test_eval_metrics.py
git commit -m "feat(eval): pure metrics (total return, max drawdown, Sharpe, hit-rate)"
```

---

### Task 10: Metrics endpoints — per agent and per model

**Files:**
- Modify: `backend/app/api/schemas.py` (add `BenchmarkMetric`, `AgentMetricsOut`, `ModelMetricsOut`)
- Modify: `backend/app/api/routes.py` (import metrics + models; add two endpoints)
- Test: `backend/tests/test_api.py` (endpoints), `backend/tests/test_auth.py` (authorization)

**Interfaces:**
- Consumes: `app.eval.metrics.{total_return_pct, max_drawdown_pct, sharpe, hit_rate}`; `EquitySnapshot`, `BenchmarkSnapshot`, `DecisionRecord`, `DecisionScore`.
- Produces: `GET /agents/{agent_id}/metrics -> AgentMetricsOut` (agent equity metrics + a `benchmarks` map for `hodl_btc`/`equal_weight`/`random_p50` + hit-rate per window). `GET /metrics/by-model -> list[ModelMetricsOut]` (hit-rate aggregated by `DecisionRecord.model_name`). Both `require_viewer_or_admin`; missing agent → all-zero metrics, empty benchmarks, `None` hit-rates (mirrors the no-404 read convention).
- Produces schemas: `BenchmarkMetric(return_pct, max_drawdown_pct, sharpe: Decimal)`; `AgentMetricsOut(return_pct, max_drawdown_pct, sharpe: Decimal, hit_rate_24h, hit_rate_7d: Decimal|None, benchmarks: dict[str, BenchmarkMetric])`; `ModelMetricsOut(model_name: str|None, n_scored_actions: int, hit_rate_24h, hit_rate_7d: Decimal|None)`.

- [ ] **Step 1: Write the failing endpoint + auth tests**

Add to `backend/tests/test_api.py`:

```python
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
```

Add to `backend/tests/test_auth.py`:

```python
def test_metrics_require_a_session(client, db_session):
    assert client.get("/api/agents/1/metrics").status_code == 401
    assert client.get("/api/metrics/by-model").status_code == 401
    db_session.add(ShareLink(token="v5")); db_session.commit()
    client.post("/api/auth/viewer", json={"token": "v5"})
    assert client.get("/api/agents/1/metrics").status_code == 200
    assert client.get("/api/metrics/by-model").status_code == 200
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api.py::test_agent_metrics_reports_return_drawdown_and_hitrate tests/test_auth.py::test_metrics_require_a_session -q`
Expected: FAIL with `404 Not Found` (routes absent).

- [ ] **Step 3: Add the schemas**

In `backend/app/api/schemas.py`, add after `BenchmarkPoint`:

```python
class BenchmarkMetric(BaseModel):
    return_pct: Decimal
    max_drawdown_pct: Decimal
    sharpe: Decimal


class AgentMetricsOut(BaseModel):
    return_pct: Decimal
    max_drawdown_pct: Decimal
    sharpe: Decimal
    hit_rate_24h: Decimal | None = None
    hit_rate_7d: Decimal | None = None
    benchmarks: dict[str, BenchmarkMetric]


class ModelMetricsOut(BaseModel):
    model_name: str | None = None
    n_scored_actions: int
    hit_rate_24h: Decimal | None = None
    hit_rate_7d: Decimal | None = None
```

- [ ] **Step 4: Add the endpoints**

In `backend/app/api/routes.py`:

1. Extend the schema import to include `AgentMetricsOut, BenchmarkMetric, ModelMetricsOut`.
2. Ensure `DecisionScore` is imported (added in Task 8).
3. Add the metrics helpers + endpoints (near `get_benchmarks`):

```python
from app.eval.metrics import total_return_pct, max_drawdown_pct, sharpe, hit_rate


@router.get("/agents/{agent_id}/metrics", response_model=AgentMetricsOut)
def get_agent_metrics(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    eq = [r.equity_usd for r in
          session.query(EquitySnapshot).filter_by(agent_id=agent_id)
          .order_by(EquitySnapshot.timestamp.asc(), EquitySnapshot.id.asc()).all()]
    benchmarks: dict[str, BenchmarkMetric] = {}
    for kind in ("hodl_btc", "equal_weight", "random_p50"):
        series = [r.equity_usd for r in
                  session.query(BenchmarkSnapshot).filter_by(agent_id=agent_id, kind=kind)
                  .order_by(BenchmarkSnapshot.timestamp.asc(), BenchmarkSnapshot.id.asc()).all()]
        if series:
            benchmarks[kind] = BenchmarkMetric(
                return_pct=total_return_pct(series),
                max_drawdown_pct=max_drawdown_pct(series),
                sharpe=sharpe(series))

    def _hit_rate(window: str):
        rows = (session.query(DecisionScore)
                .join(DecisionRecord, DecisionScore.decision_record_id == DecisionRecord.id)
                .filter(DecisionRecord.agent_id == agent_id, DecisionScore.window == window).all())
        return hit_rate(sum(r.n_hits for r in rows), sum(r.n_actions for r in rows))

    return AgentMetricsOut(
        return_pct=total_return_pct(eq),
        max_drawdown_pct=max_drawdown_pct(eq),
        sharpe=sharpe(eq),
        hit_rate_24h=_hit_rate("24h"),
        hit_rate_7d=_hit_rate("7d"),
        benchmarks=benchmarks)


@router.get("/metrics/by-model", response_model=list[ModelMetricsOut])
def get_model_metrics(session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    rows = (session.query(DecisionRecord.model_name, DecisionScore.window,
                          DecisionScore.n_hits, DecisionScore.n_actions)
            .join(DecisionScore, DecisionScore.decision_record_id == DecisionRecord.id)
            .filter(DecisionRecord.kind == "decision").all())
    agg: dict = {}
    for model_name, window, nh, na in rows:
        d = agg.setdefault(model_name, {"24h": [0, 0], "7d": [0, 0]})
        d[window][0] += nh
        d[window][1] += na
    return [
        ModelMetricsOut(
            model_name=model_name,
            n_scored_actions=d["24h"][1] + d["7d"][1],
            hit_rate_24h=hit_rate(*d["24h"]),
            hit_rate_7d=hit_rate(*d["7d"]))
        for model_name, d in agg.items()
    ]
```

- [ ] **Step 5: Run the full backend suite to verify green**

Run: `cd backend && python -m pytest -q`
Expected: PASS — all tests including the three metrics API tests + auth test.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api.py backend/tests/test_auth.py
git commit -m "feat(api): GET /agents/{id}/metrics and /metrics/by-model (equity + benchmark + hit-rate)"
```

---

## Part D — Dashboard (React, Vitest-TDD)

> All frontend commands run from `frontend/`. The project has Vitest + testing-library configured (`src/test-setup.ts`, existing `EquityChart.test.tsx`), so these are real red→green tests, not eyeball checks.

### Task 11: `BenchmarkChart` overlay component + api fetcher

**Files:**
- Modify: `frontend/src/api.ts` (add `BenchmarkPoint` type + `getBenchmarks`)
- Create: `frontend/src/components/BenchmarkChart.tsx`
- Test: `frontend/src/__tests__/BenchmarkChart.test.tsx`

**Interfaces:**
- Produces (api.ts): `type BenchmarkPoint = { kind: string; timestamp: string; equity_usd: string }` and `getBenchmarks(id: number): Promise<BenchmarkPoint[]>` hitting `/api/agents/${id}/benchmarks`.
- Produces: `BenchmarkChart({ equity, benchmarks }: { equity: EquityPoint[]; benchmarks: BenchmarkPoint[] })` — a recharts `ComposedChart` overlaying the agent equity line, HODL BTC, equal-weight, the random median (`random_p50`, dashed) and the random band (area between `random_p10` and `random_p90`). Merges all series by timestamp. Root element has `data-testid="benchmark-chart"`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/BenchmarkChart.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { BenchmarkChart } from "../components/BenchmarkChart";

describe("BenchmarkChart", () => {
  it("renders the overlay container with agent + benchmark data", () => {
    render(
      <BenchmarkChart
        equity={[{ timestamp: "2026-07-01T00:00:00Z", equity_usd: "100" }]}
        benchmarks={[
          { kind: "hodl_btc", timestamp: "2026-07-01T00:00:00Z", equity_usd: "100" },
          { kind: "random_p10", timestamp: "2026-07-01T00:00:00Z", equity_usd: "95" },
          { kind: "random_p90", timestamp: "2026-07-01T00:00:00Z", equity_usd: "105" },
        ]}
      />,
    );
    expect(screen.getByTestId("benchmark-chart")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/BenchmarkChart.test.tsx`
Expected: FAIL — cannot resolve `../components/BenchmarkChart`.

- [ ] **Step 3: Add the api fetcher**

In `frontend/src/api.ts`, add the type after `EquityPoint` (line 17) and the fetcher after `getEquity` (line 41):

```typescript
export type BenchmarkPoint = { kind: string; timestamp: string; equity_usd: string };
```

```typescript
export const getBenchmarks = (id: number) => get<BenchmarkPoint[]>(`/api/agents/${id}/benchmarks`);
```

- [ ] **Step 4: Create the component**

Create `frontend/src/components/BenchmarkChart.tsx`:

```tsx
import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import type { EquityPoint, BenchmarkPoint } from "../api";

type Row = { t: number; agent?: number; randomBand?: [number, number] } & Record<string, unknown>;

export function BenchmarkChart({ equity, benchmarks }: { equity: EquityPoint[]; benchmarks: BenchmarkPoint[] }) {
  const byTs = new Map<number, Row>();
  const row = (t: number): Row => {
    let r = byTs.get(t);
    if (!r) { r = { t }; byTs.set(t, r); }
    return r;
  };
  for (const e of equity) row(new Date(e.timestamp).getTime()).agent = Number(e.equity_usd);
  for (const b of benchmarks) row(new Date(b.timestamp).getTime())[b.kind] = Number(b.equity_usd);
  const data = [...byTs.values()].sort((a, b) => a.t - b.t);
  for (const d of data) {
    const lo = d.random_p10 as number | undefined;
    const hi = d.random_p90 as number | undefined;
    if (lo != null && hi != null) d.randomBand = [lo, hi];
  }

  return (
    <div data-testid="benchmark-chart" className="w-full h-72">
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} hide />
          <YAxis width={56} tick={{ fill: "oklch(0.70 0.014 260)", fontSize: 11 }}
                 axisLine={false} tickLine={false} />
          <Tooltip
            contentStyle={{ background: "oklch(0.20 0.010 260)", border: "1px solid oklch(0.30 0.014 260)",
              borderRadius: 8, fontSize: 12 }}
            labelFormatter={(t) => new Date(Number(t)).toLocaleString()} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Area dataKey="randomBand" name="random (10–90%)" stroke="none"
                fill="oklch(0.62 0.02 260)" fillOpacity={0.18} isAnimationActive={false} />
          <Line dataKey="random_p50" name="random median" stroke="oklch(0.62 0.02 260)"
                strokeDasharray="3 3" dot={false} strokeWidth={1.5} isAnimationActive={false} />
          <Line dataKey="hodl_btc" name="HODL BTC" stroke="oklch(0.75 0.15 60)"
                dot={false} strokeWidth={1.5} isAnimationActive={false} />
          <Line dataKey="equal_weight" name="equal-weight" stroke="oklch(0.70 0.12 200)"
                dot={false} strokeWidth={1.5} isAnimationActive={false} />
          <Line dataKey="agent" name="agent" stroke="oklch(0.78 0.16 150)"
                dot={false} strokeWidth={2.5} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/BenchmarkChart.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api.ts frontend/src/components/BenchmarkChart.tsx frontend/src/__tests__/BenchmarkChart.test.tsx
git commit -m "feat(ui): BenchmarkChart overlay (agent vs HODL/equal-weight/random band) + api fetcher"
```

---

### Task 12: `MetricsPanel` component + api fetchers

**Files:**
- Modify: `frontend/src/api.ts` (add metrics types + `getAgentMetrics`, `getModelMetrics`)
- Create: `frontend/src/components/MetricsPanel.tsx`
- Test: `frontend/src/__tests__/MetricsPanel.test.tsx`

**Interfaces:**
- Produces (api.ts): `type BenchmarkMetric = { return_pct: string; max_drawdown_pct: string; sharpe: string }`; `type AgentMetrics = { return_pct: string; max_drawdown_pct: string; sharpe: string; hit_rate_24h: string | null; hit_rate_7d: string | null; benchmarks: Record<string, BenchmarkMetric> }`; `getAgentMetrics(id: number): Promise<AgentMetrics>`; `type ModelMetrics = { model_name: string | null; n_scored_actions: number; hit_rate_24h: string | null; hit_rate_7d: string | null }`; `getModelMetrics(): Promise<ModelMetrics[]>`.
- Produces: `MetricsPanel({ metrics }: { metrics: AgentMetrics | null })` — renders return / max drawdown / Sharpe / hit-rate (24h, 7d) and a small benchmark-comparison list. Renders a lightweight empty state when `metrics` is `null`. Root has `data-testid="metrics-panel"`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/MetricsPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MetricsPanel } from "../components/MetricsPanel";

describe("MetricsPanel", () => {
  it("shows return, drawdown and hit-rate", () => {
    render(
      <MetricsPanel
        metrics={{
          return_pct: "-10", max_drawdown_pct: "25", sharpe: "0.4",
          hit_rate_24h: "75", hit_rate_7d: null,
          benchmarks: { hodl_btc: { return_pct: "10", max_drawdown_pct: "5", sharpe: "0.9" } },
        }}
      />,
    );
    expect(screen.getByTestId("metrics-panel")).toBeInTheDocument();
    expect(screen.getByText(/Max drawdown/i)).toBeInTheDocument();
    expect(screen.getByText(/75%/)).toBeInTheDocument();
  });

  it("renders an empty state when metrics are null", () => {
    render(<MetricsPanel metrics={null} />);
    expect(screen.getByTestId("metrics-panel")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/MetricsPanel.test.tsx`
Expected: FAIL — cannot resolve `../components/MetricsPanel`.

- [ ] **Step 3: Add the api types + fetchers**

In `frontend/src/api.ts`, add after the `BenchmarkPoint` type:

```typescript
export type BenchmarkMetric = { return_pct: string; max_drawdown_pct: string; sharpe: string };
export type AgentMetrics = {
  return_pct: string; max_drawdown_pct: string; sharpe: string;
  hit_rate_24h: string | null; hit_rate_7d: string | null;
  benchmarks: Record<string, BenchmarkMetric>;
};
export type ModelMetrics = {
  model_name: string | null; n_scored_actions: number;
  hit_rate_24h: string | null; hit_rate_7d: string | null;
};
```

and the fetchers after `getBenchmarks`:

```typescript
export const getAgentMetrics = (id: number) => get<AgentMetrics>(`/api/agents/${id}/metrics`);
export const getModelMetrics = () => get<ModelMetrics[]>("/api/metrics/by-model");
```

- [ ] **Step 4: Create the component**

Create `frontend/src/components/MetricsPanel.tsx`:

```tsx
import type { AgentMetrics } from "../api";

const pct = (v: string | null) => (v == null ? "—" : `${Number(v).toFixed(1)}%`);
const num = (v: string) => Number(v).toFixed(2);

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm font-medium tabular-nums">{value}</span>
    </div>
  );
}

export function MetricsPanel({ metrics }: { metrics: AgentMetrics | null }) {
  if (!metrics) {
    return (
      <div data-testid="metrics-panel" className="text-sm text-muted-foreground">
        Nessuna metrica ancora.
      </div>
    );
  }
  return (
    <div data-testid="metrics-panel" className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <Stat label="Return" value={pct(metrics.return_pct)} />
      <Stat label="Max drawdown" value={pct(metrics.max_drawdown_pct)} />
      <Stat label="Sharpe" value={num(metrics.sharpe)} />
      <Stat label="Hit-rate 24h" value={pct(metrics.hit_rate_24h)} />
      <Stat label="Hit-rate 7d" value={pct(metrics.hit_rate_7d)} />
      {Object.entries(metrics.benchmarks).map(([kind, m]) => (
        <Stat key={kind} label={`${kind} return`} value={pct(m.return_pct)} />
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/MetricsPanel.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api.ts frontend/src/components/MetricsPanel.tsx frontend/src/__tests__/MetricsPanel.test.tsx
git commit -m "feat(ui): MetricsPanel (return/drawdown/Sharpe/hit-rate) + api fetchers"
```

---

### Task 13: Wire `BenchmarkChart` + `MetricsPanel` into `App.tsx`

**Files:**
- Modify: `frontend/src/App.tsx` (imports; state; fetch on select; render)
- Verify: `frontend/src` type-check + full Vitest suite

**Interfaces:**
- Consumes: `getBenchmarks`, `getAgentMetrics`, `BenchmarkPoint`, `AgentMetrics` (Tasks 11–12); `BenchmarkChart`, `MetricsPanel`.
- Produces: the selected agent's detail view renders the benchmark overlay + metrics panel alongside the existing `EquityChart`, refreshed whenever `selId` changes.

- [ ] **Step 1: Add imports**

In `frontend/src/App.tsx`, extend the api import (around lines 3–5) to add `getBenchmarks, getAgentMetrics` and the types `BenchmarkPoint, AgentMetrics`, and add the component imports next to `EquityChart` (line 10):

```tsx
import { BenchmarkChart } from "./components/BenchmarkChart";
import { MetricsPanel } from "./components/MetricsPanel";
```

- [ ] **Step 2: Add state**

After `const [equity, setEquity] = useState<EquityPoint[]>([]);` (line 57), add:

```tsx
  const [benchmarks, setBenchmarks] = useState<BenchmarkPoint[]>([]);
  const [metrics, setMetrics] = useState<AgentMetrics | null>(null);
```

- [ ] **Step 3: Fetch on select**

In the `selId` effect, right after `getEquity(selId).then(setEquity).catch(onErr);` (line 83), add:

```tsx
      getBenchmarks(selId).then(setBenchmarks).catch(onErr);
      getAgentMetrics(selId).then(setMetrics).catch(onErr);
```

- [ ] **Step 4: Render**

Immediately after the existing `<EquityChart data={equity} baseline={100} />` (line 192), add:

```tsx
                <BenchmarkChart equity={equity} benchmarks={benchmarks} />
                <MetricsPanel metrics={metrics} />
```

- [ ] **Step 5: Type-check and run the whole frontend suite**

Run: `cd frontend && npx tsc -b && npx vitest run`
Expected: type-check clean; all frontend tests pass (existing + `BenchmarkChart` + `MetricsPanel`).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(ui): wire BenchmarkChart + MetricsPanel into the agent detail view"
```

---

## Self-Review

**Spec coverage (roadmap Fase 2 deliverables):**
- *Portafogli fantasma per agente: HODL BTC, equal-weight, random (band); a costo zero con i prezzi già scaricati dall'heartbeat* → Task 1 (math) + Task 2 (tables) + Task 3 (recorded in heartbeat from one shared universe snapshot per beat). ✓
- *Scoring per decisione: job che rivaluta ogni DecisionRecord dopo finestre fisse (24h/7g)* → Task 5 (historical price) + Task 6 (scoring math) + Task 7 (job) + Task 8 (scheduler). ✓
- *Metriche di confronto: equity, hit-rate, max drawdown, Sharpe* → Task 9 (math) + Task 10 (endpoints). ✓
- *Dashboard: equity dell'agente sovrapposta ai benchmark; hit-rate e metriche per agente e per modello* → Task 4 (curve endpoint) + Task 10 (metrics endpoints) + Tasks 11–13 (overlay chart, metrics panel, wiring). ✓
- *Random trader isola fortuna da skill* → 100 seeded monkey-portfolios → p10/p50/p90 band (Task 1, Task 3). ✓
- *Keep everything, no retention* → no pruning anywhere. ✓

**Placeholder scan:** every step contains real code/commands; no TBD / "handle errors" / "similar to Task N". ✓

**Type consistency:**
- `compute_benchmark_equities(...) -> dict` keys `hodl_btc|equal_weight|random_p10|random_p50|random_p90` match `BenchmarkSnapshot.kind` writes (Task 3), the metrics loop (`hodl_btc|equal_weight|random_p50`, Task 10), and the chart dataKeys (Task 11). ✓
- `score_decision(...) -> (n_actions, n_hits, avg_return_pct)` matches `DecisionScore(n_actions, n_hits, avg_return_pct)` (Tasks 6/7) and the metrics aggregation (Task 10). ✓
- `get_price_at(symbol, ms) -> Decimal | None` defined Task 5, consumed by the scoring job Task 7 and the fake markets in tests. ✓
- `DecisionScore` unique `(decision_record_id, window)` (Task 2) is what makes the job idempotent (Task 7) and is asserted in Task 2's test. ✓
- Schema field names (`return_pct`, `max_drawdown_pct`, `sharpe`, `hit_rate_24h/7d`, `benchmarks`, `model_name`, `n_scored_actions`) match between `AgentMetricsOut`/`ModelMetricsOut` (Task 10), the API tests (Task 10), and the frontend types (Tasks 11–12). ✓

**Authorization / destructive / business-rule coverage (user testing rules):**
- Authorization: `test_benchmarks_require_a_session` (Task 4), `test_metrics_require_a_session` (Task 10) — 401 without a session, 200 for viewer. ✓
- Destructive safeguards: `test_delete_agent_removes_benchmark_rows` (Task 4), `test_delete_agent_removes_decision_scores` (Task 8) — no FK orphans in Postgres. ✓
- Business rules: idempotent scoring (`test_already_scored_decision_is_not_rescored`), maturity gating (`test_immature_decision_is_not_scored`), skip reflection/failed records (Task 7), benchmark basis frozen once across beats (Task 3), benchmark failure never breaks the heartbeat/equity (Task 3). ✓
- Input validation: N/A beyond path `int`s validated by FastAPI; the eval math handles empty/zero series explicitly (Task 9 tests).

**Cost check:** benchmarks reuse one `get_universe_snapshot` per beat (note: currently per-agent — a shared-per-tick optimization is possible later but out of scope, YAGNI). Scoring uses free Binance klines on demand. No paid data. ✓

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-03-evaluation-harness.md`. It is large (13 tasks, four parts). Recommended: execute **part by part** (A → B → C → D), reviewing between parts, so each vertical slice is verified before the next builds on it.

Two execution styles:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, two-stage review between tasks. REQUIRED SUB-SKILL: superpowers:subagent-driven-development.
2. **Inline Execution** — execute tasks in this session with checkpoints. REQUIRED SUB-SKILL: superpowers:executing-plans.

Do not start execution until the user asks.
