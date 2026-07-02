# Decision Record (Pipeline v2 — Fase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every LLM call the trading brain makes — decision *and* reflection — as an auditable `DecisionRecord` (prompts, raw response, parse outcome, model, latency), and expose it read-only at `GET /api/agents/{id}/decisions`.

**Architecture:** Today `brain.decide()` throws away the raw LLM response and whether the parse succeeded/repaired/failed — it returns only the parsed `Decision`. We surface that lost information with a richer `evaluate()` (brain) and `run_reflection_result()` (memory) that return a small trace dataclass alongside the parsed result; `decide()`/`run_reflection()` stay as thin backward-compatible wrappers. The runtime (`_run_decision_llm`), which already knows `agent`, `cycle_id` and `wake_reason`, writes one `DecisionRecord` row per LLM call. The brain layer stays DB-free (no model imports); the join and the DB write live in `agents/runtime.py`. A new read-only endpoint mirrors the existing `GET .../events`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (typed `Mapped` models), Pydantic v2, Alembic, pytest (SQLite in-memory via `conftest.db_session`), `time.perf_counter` for latency.

## Global Constraints

- **Branch:** all work on the long-lived `pipeline-v2` branch (committente's decision, 2026-07-02). Never commit to `main`, never push, no PR until the user asks. (Auto-deploy runs on push to `main`, so nothing reaches prod until the final merge — intended.)
- **Alembic head is `139946be1c6f`** (`agent_risk_thresholds_and_position_`). The new migration's `down_revision` must be `139946be1c6f`.
- **Tests never run migrations** — `conftest.db_session` builds tables with `Base.metadata.create_all`. A new model is testable the moment it is added to `app/db/models.py`. The Alembic migration is a hand-written mirror, verified separately.
- **Match existing style:** long-text columns use bare `String` (no length), like `Event.message` and `AgentMemory.content`. Timestamps are `DateTime(timezone=True), default=_now` (Python-side default; every insert goes through the ORM).
- **Auth:** reads use `_: str = Depends(require_viewer_or_admin)`; the codebase serializes ORM rows directly through a plain-`BaseModel` `response_model` (proven by `test_get_events_returns_last_100_desc`).
- **Retention:** keep everything — no pruning, no caps (paper trading, low volume).
- **`parse_status` vocabulary is exactly `ok | repaired | failed`** (per roadmap). A provider/network error (no response at all) is recorded as `failed` with `raw_response = NULL` — the null raw distinguishes "no response" from "unparseable response" without adding a fourth status.

## Branch & Setup

Before Task 1:

```bash
cd /Users/seb/Dev/gorillaradio/crypto-bot
git checkout main && git switch -c pipeline-v2     # long-lived integration branch off main
source backend/.venv/bin/activate                  # or use backend/.venv/bin/<tool> explicitly
cd backend && python -m pytest -q                  # sanity: 105 green before we start
```

---

### Task 1: `DecisionRecord` model + Alembic migration

**Files:**
- Modify: `backend/app/db/models.py` (add `Integer` to the sqlalchemy import; add `DecisionRecord`)
- Create: `backend/alembic/versions/<generated>_decision_records.py`
- Test: `backend/tests/test_models.py` (append two tests)

**Interfaces:**
- Produces: `app.db.models.DecisionRecord` with columns
  `id:int, agent_id:int(FK agents.id, indexed), cycle_id:str(32, indexed), kind:str(20), trigger:str(20), system_prompt:str, user_prompt:str, raw_response:str|None, parsed_output:str|None, parse_status:str(10), model_provider:str(40), model_name:str|None(80), latency_ms:int, created_at:datetime(default _now, indexed)`.

- [ ] **Step 1: Write the failing model tests**

Append to `backend/tests/test_models.py` (the file already defines `_mk_agent`):

```python
def test_decision_record_persists_with_defaults(db_session):
    from app.db.models import DecisionRecord
    a = _mk_agent(db_session)
    rec = DecisionRecord(agent_id=a.id, cycle_id="cyc1", kind="decision", trigger="schedule",
                         system_prompt="sys", user_prompt="usr", raw_response="raw",
                         parsed_output='{"actions":[]}', parse_status="ok",
                         model_provider="openrouter", model_name="m", latency_ms=123)
    db_session.add(rec); db_session.commit(); db_session.refresh(rec)
    assert rec.id is not None
    assert rec.created_at is not None            # Python-side default applied on insert
    assert rec.raw_response == "raw"


def test_decision_record_allows_null_raw_parsed_and_model(db_session):
    from app.db.models import DecisionRecord
    a = _mk_agent(db_session)
    rec = DecisionRecord(agent_id=a.id, cycle_id="cyc2", kind="reflection", trigger="breach",
                         system_prompt="s", user_prompt="u", raw_response=None,
                         parsed_output=None, parse_status="failed",
                         model_provider="openrouter", model_name=None, latency_ms=0)
    db_session.add(rec); db_session.commit()
    assert rec.raw_response is None and rec.parsed_output is None and rec.model_name is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_models.py -q`
Expected: FAIL with `ImportError: cannot import name 'DecisionRecord'`.

- [ ] **Step 3: Add the model**

In `backend/app/db/models.py`, extend the sqlalchemy import (add `Integer`):

```python
from sqlalchemy import ForeignKey, Numeric, String, DateTime, UniqueConstraint, Boolean, Integer
```

Append the model at the end of the file:

```python
class DecisionRecord(Base):
    __tablename__ = "decision_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    cycle_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(20))            # "decision" | "reflection"
    trigger: Mapped[str] = mapped_column(String(20))         # "schedule" | "breach"
    system_prompt: Mapped[str] = mapped_column(String)
    user_prompt: Mapped[str] = mapped_column(String)
    raw_response: Mapped[str | None] = mapped_column(String, nullable=True)
    parsed_output: Mapped[str | None] = mapped_column(String, nullable=True)
    parse_status: Mapped[str] = mapped_column(String(10))    # "ok" | "repaired" | "failed"
    model_provider: Mapped[str] = mapped_column(String(40))
    model_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_models.py -q`
Expected: PASS (all model tests, including the two new ones).

- [ ] **Step 5: Generate the migration skeleton**

Run: `cd backend && python -m alembic revision -m "decision records"`
Expected: creates `backend/alembic/versions/<hash>_decision_records.py` with `down_revision = '139946be1c6f'` (current head) prefilled. (`alembic revision` without `--autogenerate` does not touch the database.)

- [ ] **Step 6: Fill in the migration**

Replace the generated `upgrade()`/`downgrade()` bodies (mirror `f6a7b8c9d0e1_share_links.py`):

```python
def upgrade() -> None:
    op.create_table(
        "decision_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("cycle_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("system_prompt", sa.String(), nullable=False),
        sa.Column("user_prompt", sa.String(), nullable=False),
        sa.Column("raw_response", sa.String(), nullable=True),
        sa.Column("parsed_output", sa.String(), nullable=True),
        sa.Column("parse_status", sa.String(length=10), nullable=False),
        sa.Column("model_provider", sa.String(length=40), nullable=False),
        sa.Column("model_name", sa.String(length=80), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_decision_records_agent_id", "decision_records", ["agent_id"])
    op.create_index("ix_decision_records_cycle_id", "decision_records", ["cycle_id"])
    op.create_index("ix_decision_records_created_at", "decision_records", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_decision_records_created_at", table_name="decision_records")
    op.drop_index("ix_decision_records_cycle_id", table_name="decision_records")
    op.drop_index("ix_decision_records_agent_id", table_name="decision_records")
    op.drop_table("decision_records")
```

- [ ] **Step 7: Smoke-test the migration up and down**

Run (SQLite throwaway DB — zero external deps; env.py honours `DATABASE_URL`):

```bash
cd backend && rm -f _mig_smoke.db
DATABASE_URL="sqlite:///./_mig_smoke.db" python -m alembic upgrade head
DATABASE_URL="sqlite:///./_mig_smoke.db" python -m alembic downgrade -1
rm -f _mig_smoke.db
```

Expected: `upgrade` ends with `Running upgrade 139946be1c6f -> <hash>, decision records` and no error; `downgrade` runs cleanly. (If the pre-existing chain is not SQLite-clean on your machine, fall back to a throwaway Postgres and set `DATABASE_URL` to it — the memory note "Postgres usa-e-getta" describes this path.)

- [ ] **Step 8: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/*_decision_records.py backend/tests/test_models.py
git commit -m "feat(db): DecisionRecord table + migration for audit of LLM decisions"
```

---

### Task 2: `evaluate()` — brain surfaces raw response, parse status, latency

**Files:**
- Modify: `backend/app/brain/schema.py` (add `DecisionResult`)
- Modify: `backend/app/brain/__init__.py` (add `evaluate`; `decide` becomes a wrapper)
- Test: `backend/tests/test_brain_decide.py` (append four tests; existing four stay unchanged)

**Interfaces:**
- Produces: `app.brain.schema.DecisionResult(decision: Decision, system: str = "", user: str = "", raw: str | None = None, parse_status: str = "ok", latency_ms: int = 0)`.
- Produces: `app.brain.evaluate(ctx, adapter) -> DecisionResult`. `parse_status` ∈ `{"ok","repaired","failed"}`. `raw` holds the last response text received (`None` on provider error).
- Produces: `app.brain.decide(ctx, adapter) -> Decision` (unchanged behaviour: `evaluate(ctx, adapter).decision`).

- [ ] **Step 1: Write the failing tests for `evaluate`**

Append to `backend/tests/test_brain_decide.py` and update the import line at the top from `from app.brain import decide` to `from app.brain import decide, evaluate`:

```python
def test_evaluate_ok_captures_raw_status_latency():
    raw = '{"actions":[{"type":"HOLD","rationale":"wait"}],"note":"n"}'
    r = evaluate(_ctx(), _Adapter([raw]))
    assert r.decision.note == "n"
    assert r.parse_status == "ok"
    assert r.raw == raw
    assert r.system and r.user            # prompts captured for replay
    assert r.latency_ms >= 0


def test_evaluate_repaired_keeps_corrected_raw():
    r = evaluate(_ctx(), _Adapter(["not json", '{"actions":[],"note":"recovered"}']))
    assert r.parse_status == "repaired"
    assert r.raw == '{"actions":[],"note":"recovered"}'   # the second, corrected response
    assert r.decision.note == "recovered"


def test_evaluate_failed_keeps_last_raw():
    r = evaluate(_ctx(), _Adapter(["bad", "still bad"]))
    assert r.parse_status == "failed"
    assert r.raw == "still bad"           # last response retained for debugging
    assert r.decision.actions == []


def test_evaluate_provider_error_is_failed_with_null_raw():
    r = evaluate(_ctx(), _Adapter([RuntimeError("boom")]))
    assert r.parse_status == "failed"
    assert r.raw is None                  # no response ever received
    assert "error" in r.decision.note.lower()
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_brain_decide.py -q`
Expected: FAIL with `ImportError: cannot import name 'evaluate'`.

- [ ] **Step 3: Add `DecisionResult` to schema.py**

In `backend/app/brain/schema.py`, add `from dataclasses import dataclass` at the top and append after the `Decision` class:

```python
@dataclass
class DecisionResult:
    decision: Decision
    system: str = ""
    user: str = ""
    raw: str | None = None
    parse_status: str = "ok"      # "ok" | "repaired" | "failed"
    latency_ms: int = 0
```

- [ ] **Step 4: Rewrite `brain/__init__.py`**

Replace the whole file with:

```python
from time import perf_counter
from app.brain.schema import Decision, DecisionResult
from app.brain.context import DecisionContext
from app.brain.prompt import render_prompt, retry_user_suffix


def _elapsed_ms(t0: float) -> int:
    return int((perf_counter() - t0) * 1000)


def evaluate(ctx: DecisionContext, adapter) -> DecisionResult:
    system, user = render_prompt(ctx)
    t0 = perf_counter()
    try:
        raw = adapter.complete_json(system, user)
    except Exception as exc:  # network / provider error — no response received
        return DecisionResult(Decision(actions=[], note=f"brain error: {exc}"),
                              system, user, None, "failed", _elapsed_ms(t0))
    try:
        decision = Decision.model_validate_json(raw)
        return DecisionResult(decision, system, user, raw, "ok", _elapsed_ms(t0))
    except Exception as first_err:
        raw2 = None
        try:
            raw2 = adapter.complete_json(system, user + retry_user_suffix(str(first_err)))
            decision = Decision.model_validate_json(raw2)
            return DecisionResult(decision, system, user, raw2, "repaired", _elapsed_ms(t0))
        except Exception as second_err:
            return DecisionResult(
                Decision(actions=[], note=f"decision parse failed: {second_err}"),
                system, user, raw2 if raw2 is not None else raw, "failed", _elapsed_ms(t0))


def decide(ctx: DecisionContext, adapter) -> Decision:
    return evaluate(ctx, adapter).decision
```

- [ ] **Step 5: Run the whole brain-decide suite to verify it passes**

Run: `cd backend && python -m pytest tests/test_brain_decide.py -q`
Expected: PASS — the four original `decide` tests (unchanged) AND the four new `evaluate` tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/brain/schema.py backend/app/brain/__init__.py backend/tests/test_brain_decide.py
git commit -m "feat(brain): evaluate() surfaces raw response, parse status and latency"
```

---

### Task 3: `run_reflection_result()` — reflection surfaces its trace

**Files:**
- Modify: `backend/app/brain/memory.py` (add `ReflectionResult` + `run_reflection_result`; `run_reflection` unchanged)
- Test: `backend/tests/test_brain_memory.py` (append three tests; existing test unchanged)

**Interfaces:**
- Produces: `app.brain.memory.ReflectionResult(memory: MemoryView, system: str = "", user: str = "", raw: str | None = None, parse_status: str = "ok", latency_ms: int = 0)`.
- Produces: `app.brain.memory.run_reflection_result(memory, closed, held_symbols, instructions, adapter) -> ReflectionResult`. Never raises: provider error or unparseable response → `parse_status="failed"` and `memory` returned **unchanged**. `parse_status` ∈ `{"ok","failed"}` (reflection has no retry step).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_brain_memory.py` and extend the import to include `run_reflection_result, ReflectionResult`:

```python
def test_run_reflection_result_ok_captures_trace():
    class FakeAdapter:
        def complete_json(self, system, user):
            return '{"coin_theses": ["BTC: bull"], "trade_lessons": [], "strategy_notes": []}'
    r = run_reflection_result(MemoryView(), [], [], "x", FakeAdapter())
    assert r.parse_status == "ok"
    assert r.memory.coin_theses == "BTC: bull"
    assert r.raw and r.system and r.user
    assert r.latency_ms >= 0


def test_run_reflection_result_parse_failure_keeps_memory():
    class FakeAdapter:
        def complete_json(self, system, user): return "not json"
    r = run_reflection_result(MemoryView(coin_theses="keep me"), [], [], "x", FakeAdapter())
    assert r.parse_status == "failed"
    assert r.memory.coin_theses == "keep me"      # unchanged on failure
    assert r.raw == "not json"


def test_run_reflection_result_provider_error_is_failed():
    class FakeAdapter:
        def complete_json(self, system, user): raise RuntimeError("down")
    r = run_reflection_result(MemoryView(coin_theses="keep me"), [], [], "x", FakeAdapter())
    assert r.parse_status == "failed"
    assert r.raw is None
    assert r.memory.coin_theses == "keep me"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_brain_memory.py -q`
Expected: FAIL with `ImportError: cannot import name 'run_reflection_result'`.

- [ ] **Step 3: Add `ReflectionResult` and `run_reflection_result`**

In `backend/app/brain/memory.py`, add to the top imports:

```python
from dataclasses import dataclass
from time import perf_counter
```

Append at the end of the file:

```python
@dataclass
class ReflectionResult:
    memory: MemoryView
    system: str = ""
    user: str = ""
    raw: str | None = None
    parse_status: str = "ok"      # "ok" | "failed"
    latency_ms: int = 0


def run_reflection_result(memory: MemoryView, closed: list[ClosedTrade],
                          held_symbols: list[str], instructions: str, adapter) -> ReflectionResult:
    system, user = build_reflection_prompt(memory, closed, held_symbols, instructions)
    t0 = perf_counter()
    try:
        raw = adapter.complete_json(system, user)
    except Exception:                     # provider error — memory left unchanged
        return ReflectionResult(memory, system, user, None, "failed", int((perf_counter() - t0) * 1000))
    try:
        new_memory = enforce_caps(parse_reflection(raw))
        return ReflectionResult(new_memory, system, user, raw, "ok", int((perf_counter() - t0) * 1000))
    except Exception:                     # unparseable — keep old memory
        return ReflectionResult(memory, system, user, raw, "failed", int((perf_counter() - t0) * 1000))
```

Note: `run_reflection` stays exactly as-is (it still raises on error; only `test_brain_memory`'s existing happy-path test uses it, and the runtime will switch to `run_reflection_result` in Task 5).

- [ ] **Step 4: Run the whole memory suite to verify it passes**

Run: `cd backend && python -m pytest tests/test_brain_memory.py -q`
Expected: PASS — the original test plus the three new ones.

- [ ] **Step 5: Commit**

```bash
git add backend/app/brain/memory.py backend/tests/test_brain_memory.py
git commit -m "feat(brain): run_reflection_result() surfaces reflection trace, never raises"
```

---

### Task 4: Runtime writes a `DecisionRecord` for each decision

**Files:**
- Modify: `backend/app/agents/runtime.py` (imports; default `brain_decide=evaluate`; `_record_llm_call` helper; write the decision record; compute `trigger`)
- Test: `backend/tests/test_runtime.py` (migrate injected `brain_decide` fakes to the new `DecisionResult` contract; add three new tests)

**Interfaces:**
- Consumes: `app.brain.evaluate` (Task 2) as the default `brain_decide`; the injected `brain_decide` now returns `DecisionResult`. `app.db.models.DecisionRecord` (Task 1).
- Produces: `_record_llm_call(session, agent, cycle_id, kind, trigger, *, system, user, raw, parsed_output, parse_status, latency_ms) -> None` (module-level in `runtime.py`, reused by Task 5). Behaviour: each `run_decision` writes exactly one `DecisionRecord` with `kind="decision"`, `trigger="breach"` if `wake_reason` else `"schedule"`, sharing the cycle's `cycle_id`.

- [ ] **Step 1: Write the three new decision-record tests**

These inject fakes that return the NEW `DecisionResult` contract and assert on the persisted `DecisionRecord`. Add them to `backend/tests/test_runtime.py`, and extend two import lines:
- schema import → `from app.brain.schema import Decision, Action, DecisionResult`
- models import → add `DecisionRecord`

```python
async def test_run_decision_writes_decision_record(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    result = DecisionResult(Decision(actions=[], note="hold"),
                            system="SYS", user="USR", raw='{"actions":[],"note":"hold"}',
                            parse_status="ok", latency_ms=42)
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: result)
    rec = db_session.query(DecisionRecord).filter_by(agent_id=agent.id).one()
    assert rec.kind == "decision" and rec.trigger == "schedule"
    assert rec.parse_status == "ok"
    assert rec.raw_response == '{"actions":[],"note":"hold"}'
    assert rec.system_prompt == "SYS" and rec.user_prompt == "USR"
    assert rec.model_provider == "openrouter"
    assert rec.model_name == "deepseek/deepseek-v4-flash"
    assert rec.latency_ms == 42
    assert rec.cycle_id is not None
    assert '"note":"hold"' in rec.parsed_output      # parsed Decision serialized


async def test_decision_record_trigger_is_breach_on_wake(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       wake_reason="BTCUSDT -12% oltre stop",
                       brain_decide=lambda ctx, adapter: DecisionResult(Decision(actions=[], note="held")))
    rec = db_session.query(DecisionRecord).filter_by(agent_id=agent.id).one()
    assert rec.trigger == "breach"


async def test_decision_record_shares_cycle_id_with_events(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[Action(type="BUY", symbol="BTCUSDT",
                                        usd_amount=Decimal("50"), rationale="dip")], note="in")
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision))
    rec = db_session.query(DecisionRecord).filter_by(agent_id=agent.id).one()
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").one()
    assert rec.cycle_id == ev.cycle_id and rec.cycle_id is not None
```

- [ ] **Step 2: Run the new tests to verify they fail (RED)**

Run: `cd backend && python -m pytest tests/test_runtime.py -q`
Expected: the three new tests FAIL — the runtime does not record yet and still dereferences the brain result as a bare `Decision`, so a `DecisionResult`-returning fake raises `AttributeError: 'DecisionResult' object has no attribute 'actions'`. The pre-existing tests still PASS (their fakes still return a bare `Decision` — untouched so far). Red for the right reason, before wiring anything.

- [ ] **Step 3: Wire the runtime AND migrate the existing fakes (one atomic contract flip)**

The brain contract flips from returning `Decision` to returning `DecisionResult`; the runtime and every injected `brain_decide` fake must change together, or the suite is green at no intermediate point. Do BOTH halves in this step.

**3a — runtime (`backend/app/agents/runtime.py`):**

1. Imports — add `DecisionRecord` and switch the brain default to `evaluate`:
   ```python
   from app.db.models import EquitySnapshot, Event, AgentMemory, DecisionRecord
   from app.brain import evaluate as brain_decide_default
   ```
2. Add the helper next to `_persist_memory` (bottom of file):
   ```python
   def _record_llm_call(session, agent, cycle_id, kind, trigger, *,
                        system, user, raw, parsed_output, parse_status, latency_ms) -> None:
       session.add(DecisionRecord(
           agent_id=agent.id, cycle_id=cycle_id, kind=kind, trigger=trigger,
           system_prompt=system, user_prompt=user, raw_response=raw,
           parsed_output=parsed_output, parse_status=parse_status,
           model_provider=agent.model_provider, model_name=agent.model_name,
           latency_ms=latency_ms))
   ```
3. In `_run_decision_llm`, change the call site to keep the `DecisionResult` and derive `decision`:
   ```python
           adapter = make_adapter(agent.model_provider, agent.model_name)
           result = brain_decide(ctx, adapter)
       except Exception as exc:
           ...
           return

       decision = result.decision
       trigger = "breach" if wake_reason else "schedule"
   ```
   (The `decision = ...` line replaces the old `decision = brain_decide(ctx, adapter)`; `trigger` is computed once here and reused by Task 5.)
4. Immediately before the decision-summary `Event` is added (the `session.add(Event(... kind="decision" ... f"{kind_label}: {note} ...")`), record the call:
   ```python
       _record_llm_call(session, agent, cycle_id, "decision", trigger,
                        system=result.system, user=result.user, raw=result.raw,
                        parsed_output=decision.model_dump_json(),
                        parse_status=result.parse_status, latency_ms=result.latency_ms)
   ```
   It is added to the session and flushed by the existing `session.commit()` that follows the summary event.

**3b — migrate every injected `brain_decide` fake in `backend/tests/test_runtime.py`** (leave the `reflect=` fakes untouched — Task 5 handles them; the `DecisionResult` import was already added in Step 1):

1. Replace every `brain_decide=lambda ctx, adapter: decision` with `brain_decide=lambda ctx, adapter: DecisionResult(decision)`. This exact lowercase-`decision` pattern occurs in nine tests ("executes buy", "all-in buy", "sells fraction", "buy-then-sell", "reflection runs once on sell", "share one cycle_id", "two cycles", "no reflection when no sell", "reflection failure isolated"); it wraps only the `brain_decide=` argument and leaves any trailing `, reflect=...` on the same call intact.
2. In `test_run_decision_passes_wake_reason_and_marks_event`, change `capture` to return a wrapped result:
   ```python
   def capture(ctx, adapter):
       captured["wake"] = ctx.wake_reason
       return DecisionResult(Decision(actions=[], note="held"))
   ```
3. In `test_guarded_runs_when_free` and `test_guarded_skips_when_locked`, wrap the inline decisions: `brain_decide=lambda ctx, adapter: DecisionResult(Decision(actions=[], note="ok"))` and `... DecisionResult(Decision(actions=[], note="x"))`.

- [ ] **Step 4: Run the full backend suite to verify green**

Run: `cd backend && python -m pytest -q`
Expected: PASS — all previously-green tests (fakes now return `DecisionResult`, runtime reads `.decision`) plus the three new decision-record tests. If a pre-existing runtime test errors with `AttributeError: 'DecisionResult' object has no attribute 'actions'`, you missed a fake in 3b — find and wrap it. Watch that `test_llm_data_gathering_error_writes_event_no_trade` (real default `evaluate`, errors inside `build_agent_context` before any LLM call) still writes only the error `Event` and zero `DecisionRecord`/`Trade` rows.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/runtime.py backend/tests/test_runtime.py
git commit -m "feat(runtime): persist a DecisionRecord for every decision cycle"
```

---

### Task 5: Runtime records the reflection call too

**Files:**
- Modify: `backend/app/agents/runtime.py` (imports; default `reflect=run_reflection_result`; record + status-aware persist in the reflection block; `import json`, `from dataclasses import asdict`)
- Test: `backend/tests/test_runtime.py` (migrate reflect fakes; add one new test)

**Interfaces:**
- Consumes: `app.brain.memory.run_reflection_result` (Task 3) as the default `reflect`; the injected `reflect` now returns `ReflectionResult`. Reuses `_record_llm_call` (Task 4) and the local `trigger`.
- Produces: when a cycle closes a trade, one additional `DecisionRecord` with `kind="reflection"`, same `cycle_id`/`trigger` as its decision; memory is persisted only when `parse_status == "ok"`.

- [ ] **Step 1: Write the new reflection-record test**

In `backend/tests/test_runtime.py`, add the import `from app.brain.memory import ReflectionResult` (near the other brain imports), then add the test below. Do NOT touch the existing reflect fakes yet — Step 3 migrates them atomically with the runtime rewiring:
   ```python
   async def test_reflection_call_is_recorded(db_session):
       agent = _llm_agent(db_session)
       db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                               quantity=Decimal("1"), avg_price=Decimal("100")))
       db_session.commit()
       snap = [CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("2"))]
       market = FakeMarketLLM(snap, Decimal("120"), (Decimal("120"), Decimal("121")))
       decision = Decision(actions=[Action(type="SELL", symbol="BTCUSDT", fraction=Decimal("1"))], note="exit")
       refl = ReflectionResult(MemoryView(coin_theses="BTC: booked"),
                               system="RSYS", user="RUSR", raw='{"coin_theses":["BTC: booked"]}',
                               parse_status="ok", latency_ms=7)
       await run_decision(db_session, agent, market, ["BTCUSDT"],
                          brain_decide=lambda ctx, adapter: DecisionResult(decision),
                          reflect=lambda *a, **k: refl)
       recs = db_session.query(DecisionRecord).filter_by(agent_id=agent.id).all()
       assert sorted(r.kind for r in recs) == ["decision", "reflection"]
       rr = db_session.query(DecisionRecord).filter_by(agent_id=agent.id, kind="reflection").one()
       dd = db_session.query(DecisionRecord).filter_by(agent_id=agent.id, kind="decision").one()
       assert rr.parse_status == "ok" and rr.raw_response == '{"coin_theses":["BTC: booked"]}'
       assert rr.latency_ms == 7 and rr.trigger == "schedule"
       assert rr.cycle_id == dd.cycle_id             # decision + reflection share the cycle
   ```

- [ ] **Step 2: Run the new test to verify it fails (RED)**

Run: `cd backend && python -m pytest tests/test_runtime.py -q`
Expected: `test_reflection_call_is_recorded` FAILS — the un-wired runtime treats the injected `ReflectionResult` as if it were a `MemoryView`, so `_persist_memory` raises `AttributeError`, the existing `except` logs a "reflection: errore" event, and no reflection `DecisionRecord` is written → the `["decision","reflection"]` assertion fails. The pre-existing reflection tests still PASS (their fakes still return `MemoryView`/raise — untouched so far). Red for the right reason.

- [ ] **Step 3: Wire the runtime AND migrate the reflect fakes (one atomic contract flip)**

The reflect contract flips from returning `MemoryView` to returning `ReflectionResult`; the runtime reflection block and every injected `reflect` fake must change together. Do BOTH halves in this step.

**3a — runtime (`backend/app/agents/runtime.py`):**

1. Add to the top imports:
   ```python
   import json
   from dataclasses import asdict
   ```
2. Switch the reflect default to the rich version:
   ```python
   from app.brain.memory import run_reflection_result, ClosedTrade
   ```
   and in both `run_decision` and `run_decision_guarded` signatures change `reflect=run_reflection` to `reflect=run_reflection_result`.
3. Replace the reflection block (`if closed_trades:` … through its `session.commit()`) with:
   ```python
       if closed_trades:
           try:
               rr = reflect(ctx.memory, closed_trades, held_symbols, agent.instructions, adapter)
               _record_llm_call(session, agent, cycle_id, "reflection", trigger,
                                system=rr.system, user=rr.user, raw=rr.raw,
                                parsed_output=(json.dumps(asdict(rr.memory))
                                               if rr.parse_status == "ok" else None),
                                parse_status=rr.parse_status, latency_ms=rr.latency_ms)
               if rr.parse_status == "ok":
                   _persist_memory(session, agent.id, rr.memory)
                   session.add(Event(agent_id=agent.id, kind="reflection", cycle_id=cycle_id,
                                     message="memoria aggiornata dopo trade chiuso"))
               else:
                   session.add(Event(agent_id=agent.id, kind="reflection", cycle_id=cycle_id,
                                     message="reflection: risposta non valida, memoria invariata"))
           except Exception as exc:
               session.add(Event(agent_id=agent.id, kind="reflection", cycle_id=cycle_id,
                                 message=f"reflection: errore — {exc}"))
           session.commit()
   ```
   (A raising injected fake still lands in `except` → error event, no record, memory untouched — preserving `test_reflection_failure_is_isolated`. The default `run_reflection_result` never raises, so in production a failed reflection is recorded with `parse_status="failed"` and a "risposta non valida" event.)

**3b — migrate the injected `reflect` fakes in `backend/tests/test_runtime.py`** (the `ReflectionResult` import was already added in Step 1):

1. In `test_reflection_runs_once_on_sell_and_persists`, change `fake_reflect` to return a `ReflectionResult` (default `parse_status="ok"` → memory persisted):
   ```python
   def fake_reflect(memory, closed, held_symbols, instructions, adapter):
       calls.append(closed)
       return ReflectionResult(MemoryView(coin_theses="BTC: took profit", trade_lessons="green exit"))
   ```
   The existing assertions (`AgentMemory.coin_theses == "BTC: took profit"`, a `reflection` event containing "memoria") stay valid.
2. In `test_no_reflection_when_no_sell`, the reflect lambda is never invoked; update it for contract consistency: `reflect=lambda *a, **k: calls.append(1) or ReflectionResult(MemoryView())`.
3. Leave `test_reflection_failure_is_isolated`'s `boom` as a raising fake — the runtime still wraps `reflect` in try/except, so a raising reflect must still produce the "reflection: errore — provider down" event with memory untouched.

- [ ] **Step 4: Run the full backend suite to verify green**

Run: `cd backend && python -m pytest -q`
Expected: PASS — everything, including `test_reflection_call_is_recorded`, `test_reflection_runs_once_on_sell_and_persists`, and `test_reflection_failure_is_isolated`. If `test_reflection_runs_once_on_sell_and_persists` fails with an `AttributeError` in `_persist_memory`, one half of Step 3 landed without the other — both must land together.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/runtime.py backend/tests/test_runtime.py
git commit -m "feat(runtime): record reflection LLM calls as DecisionRecord (kind=reflection)"
```

---

### Task 6: Read endpoint `GET /api/agents/{id}/decisions` + delete cascade

**Files:**
- Modify: `backend/app/api/schemas.py` (add `DecisionRecordOut`)
- Modify: `backend/app/api/routes.py` (import `DecisionRecord` + `DecisionRecordOut`; add endpoint; add `DecisionRecord` to the delete cascade)
- Test: `backend/tests/test_api.py` (endpoint list + empty + delete-cascade), `backend/tests/test_auth.py` (authorization)

**Interfaces:**
- Consumes: `app.db.models.DecisionRecord`.
- Produces: `GET /api/agents/{agent_id}/decisions -> list[DecisionRecordOut]`, newest first, capped at 100, `require_viewer_or_admin`. Missing agent → `200 []` (mirrors `GET .../events`, which does not 404). Deleting an agent removes its `decision_records`.

- [ ] **Step 1: Write the failing endpoint + auth + cascade tests**

Add to `backend/tests/test_api.py`:

```python
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
```

Add to `backend/tests/test_auth.py` (mirrors `test_reads_require_a_session`):

```python
def test_decisions_require_a_session(client, db_session):
    assert client.get("/api/agents/1/decisions").status_code == 401
    db_session.add(ShareLink(token="v3")); db_session.commit()
    client.post("/api/auth/viewer", json={"token": "v3"})
    assert client.get("/api/agents/1/decisions").status_code == 200   # viewer can read
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api.py::test_get_decisions_returns_records_newest_first tests/test_auth.py::test_decisions_require_a_session -q`
Expected: FAIL with `404 Not Found` (route does not exist yet) → assertion errors on status code.

- [ ] **Step 3: Add the response schema**

In `backend/app/api/schemas.py`, add after `EventOut`:

```python
class DecisionRecordOut(BaseModel):
    id: int
    cycle_id: str
    kind: str
    trigger: str
    system_prompt: str
    user_prompt: str
    raw_response: str | None = None
    parsed_output: str | None = None
    parse_status: str
    model_provider: str
    model_name: str | None = None
    latency_ms: int
    created_at: datetime
```

- [ ] **Step 4: Add the endpoint and extend the delete cascade**

In `backend/app/api/routes.py`:

1. Import the model — extend the models import line to include `DecisionRecord`:
   `from app.db.models import Agent, AgentMemory, DecisionRecord, EquitySnapshot, Event, Position, Trade`
2. Import the schema — add `DecisionRecordOut` to the `app.api.schemas` import.
3. In `delete_agent`, add `DecisionRecord` to the cascade loop:
   `for model in (Position, Trade, EquitySnapshot, Event, AgentMemory, DecisionRecord):`
4. Add the endpoint (mirror `get_events` — newest first, limit 100, no 404):
   ```python
   @router.get("/agents/{agent_id}/decisions", response_model=list[DecisionRecordOut])
   def get_decisions(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
       return (
           session.query(DecisionRecord)
           .filter_by(agent_id=agent_id)
           .order_by(DecisionRecord.created_at.desc(), DecisionRecord.id.desc())
           .limit(100)
           .all()
       )
   ```

- [ ] **Step 5: Run the full backend suite to verify green**

Run: `cd backend && python -m pytest -q`
Expected: PASS — all tests, including the four new API/auth tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api.py backend/tests/test_auth.py
git commit -m "feat(api): GET /agents/{id}/decisions read endpoint + delete cascade"
```

---

## Self-Review

**Spec coverage (roadmap Fase 1 deliverables):**
- `DecisionRecord` table with agent_id, cycle_id, trigger, system/user prompt, raw response, parsed decision, parse outcome (ok/repaired/failed), model+provider, latency, timestamp → Task 1 (model + migration). ✓
- Write the record inside `decide()`/`_run_decision_llm`, including reflection → Tasks 4 (decision) + 5 (reflection). The raw/status/latency are surfaced by `evaluate` (Task 2) and `run_reflection_result` (Task 3); the DB write is in the runtime. ✓
- Read-only `GET /api/agents/{id}/decisions` → Task 6. ✓
- "Keep everything, no retention" → no pruning logic anywhere. ✓
- Synergy with prompt-monitor's `build_agent_context` → already reused by `_run_decision_llm`; unchanged. ✓

**Type consistency:** `DecisionResult(decision, system, user, raw, parse_status, latency_ms)` and `ReflectionResult(memory, system, user, raw, parse_status, latency_ms)` field names match every call site (Tasks 2/3 define, Tasks 4/5 consume). `_record_llm_call` signature matches both invocations. `DecisionRecord` column names match the migration, the ORM model, `DecisionRecordOut`, and every test literal. `parse_status` domain is `ok|repaired|failed` (decision) / `ok|failed` (reflection) everywhere.

**Placeholder scan:** every step contains the actual code/command; no TBD/"handle errors"/"similar to". ✓

**Authorization / destructive coverage (user testing rules):** authorization test (`test_decisions_require_a_session`, 401 without session) ✓; destructive safeguard (`test_delete_agent_removes_decision_records`, no FK orphan in Postgres) ✓; business rules (one record per cycle, trigger reflects wake_reason, decision+reflection share cycle_id, failed reflection leaves memory intact) covered in Tasks 4–5. Input validation is N/A (only a path `int`, validated by FastAPI).

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-02-decision-record.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration. REQUIRED SUB-SKILL: superpowers:subagent-driven-development.
2. **Inline Execution** — execute tasks in this session with checkpoints. REQUIRED SUB-SKILL: superpowers:executing-plans.

Do not start execution until the user asks (this session is plan-only).
