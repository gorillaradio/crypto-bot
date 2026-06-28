# Agent Memory v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each agent a persistent long-term memory (3 capped sections) that it reads on every decision and rewrites by reflecting on its own closed trades (SELLs).

**Architecture:** A new `agent_memory` DB table holds one row per `(agent_id, section)`. The runtime loads the 3 sections into the decision context (rendered into the prompt) and, after any SELL executes, runs one reflection LLM call (same provider/model as the agent) that rewrites the sections under hard caps. The `brain/` package stays pure (no DB); the runtime is the only DB toucher. A read-only dashboard panel surfaces the sections.

**Tech Stack:** Python 3 / SQLAlchemy 2 (Mapped columns) / Alembic / Pydantic v2 / FastAPI / React 19 + Vite + Vitest.

## Global Constraints

- **Money/price math is always `Decimal`** — never float. (Reviewers enforce this.)
- **All tests run offline** — fake adapters, fake market, SQLite in-memory `db_session` fixture. No network.
- **Backend tests:** `backend/.venv/bin/pytest backend/tests -q` (system Python is PEP-668; never system pip).
- **Frontend tests:** `cd frontend && npm test` (vitest).
- **The brain package never touches the DB.** Memory I/O lives only in `agents/runtime.py` and `api/routes.py`.
- **Alembic head is `b2c3d4e5f6a7`** — the new migration's `down_revision` must be exactly that.
- **Section keys are stable code identifiers:** `coin_theses`, `trade_lessons`, `strategy_notes`. Caps: 8 / 10 / 5.
- **Reflection failure is non-fatal** — caught, logged as a `reflection` event, existing memory left untouched, never raised into the scheduler loop.

---

## File Structure

- `backend/app/db/models.py` — **modify**: add `AgentMemory` table.
- `backend/alembic/versions/c3d4e5f6a7b8_agent_memory.py` — **create**: migration for the table.
- `backend/app/brain/context.py` — **modify**: add `MemoryView` dataclass + `memory` field on `DecisionContext`.
- `backend/app/brain/prompt.py` — **modify**: render the memory block into the decision prompt.
- `backend/app/brain/memory.py` — **create**: pure reflection logic (prompt build, parse, caps, `run_reflection`).
- `backend/app/agents/runtime.py` — **modify**: read memory into context; capture closed trades; trigger + persist reflection.
- `backend/app/api/routes.py` + `backend/app/api/schemas.py` — **modify**: `GET /agents/{id}/memory`.
- `frontend/src/api.ts` — **modify**: `AgentMemory` type + `getMemory`.
- `frontend/src/components/MemoryPanel.tsx` — **create**: read-only 3-section panel.
- `frontend/src/App.tsx` — **modify**: fetch + render the panel.

---

## Task 1: `AgentMemory` table + migration

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/c3d4e5f6a7b8_agent_memory.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `AgentMemory(Base)` with columns `id`, `agent_id`, `section: str`, `content: str`, `updated_at`, and a unique constraint on `(agent_id, section)` named `uq_agent_memory_section`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_models.py`:

```python
def test_agent_memory_unique_per_section(db_session):
    from app.db.models import AgentMemory
    import pytest
    from sqlalchemy.exc import IntegrityError
    agent = Agent(name="M", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    db_session.add(AgentMemory(agent_id=agent.id, section="coin_theses", content="BTC: bull"))
    db_session.commit()
    # a different section for the same agent is allowed
    db_session.add(AgentMemory(agent_id=agent.id, section="trade_lessons", content="sold too early"))
    db_session.commit()
    # a duplicate (agent, section) violates the unique constraint
    db_session.add(AgentMemory(agent_id=agent.id, section="coin_theses", content="BTC: bear"))
    with pytest.raises(IntegrityError):
        db_session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `backend/.venv/bin/pytest backend/tests/test_models.py::test_agent_memory_unique_per_section -q`
Expected: FAIL with `ImportError`/`AttributeError` (cannot import `AgentMemory`).

- [ ] **Step 3: Add the model**

In `backend/app/db/models.py`, extend the imports line:

```python
from sqlalchemy import ForeignKey, Numeric, String, DateTime, UniqueConstraint
```

Append at end of file:

```python
class AgentMemory(Base):
    __tablename__ = "agent_memory"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    section: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(String, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    __table_args__ = (UniqueConstraint("agent_id", "section", name="uq_agent_memory_section"),)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `backend/.venv/bin/pytest backend/tests/test_models.py -q`
Expected: PASS (all model tests).

- [ ] **Step 5: Hand-write the Alembic migration**

Create `backend/alembic/versions/c3d4e5f6a7b8_agent_memory.py`:

```python
"""agent memory"""
from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_memory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("section", sa.String(length=40), nullable=False),
        sa.Column("content", sa.String(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("agent_id", "section", name="uq_agent_memory_section"),
    )


def downgrade():
    op.drop_table("agent_memory")
```

- [ ] **Step 6: Verify the migration chains from the current head**

Run: `backend/.venv/bin/alembic -c backend/alembic.ini heads`
Expected: prints `c3d4e5f6a7b8 (head)`. (No DB connection needed — `heads` reads the script files only. If `alembic.ini` path differs, use the repo's documented invocation.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/c3d4e5f6a7b8_agent_memory.py backend/tests/test_models.py
git commit -m "feat(brain): agent_memory table + migration"
```

---

## Task 2: `MemoryView` in context + render into prompt

**Files:**
- Modify: `backend/app/brain/context.py`
- Modify: `backend/app/brain/prompt.py`
- Test: `backend/tests/test_brain_context.py`, `backend/tests/test_brain_prompt.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `MemoryView(coin_theses: str = "", trade_lessons: str = "", strategy_notes: str = "")` (dataclass, in `context.py`).
  - `DecisionContext` gains a `memory: MemoryView` field.
  - `build_context(..., memory: MemoryView | None = None)` — defaults to an empty `MemoryView`.
  - `render_prompt` appends a "Your memory" block listing only non-empty sections.

- [ ] **Step 1: Write the failing context test**

Add to `backend/tests/test_brain_context.py`:

```python
def test_build_context_carries_memory():
    from app.brain.context import MemoryView
    mem = MemoryView(coin_theses="BTC: bull", trade_lessons="sold too early")
    ctx = build_context(
        instructions="x", cash_usd=Decimal("10"), holdings=[],
        universe=[], recent_events=[], memory=mem,
    )
    assert ctx.memory.coin_theses == "BTC: bull"
    assert ctx.memory.strategy_notes == ""        # default empty section

def test_build_context_defaults_memory_empty():
    ctx = build_context(instructions="x", cash_usd=Decimal("10"),
                        holdings=[], universe=[], recent_events=[])
    assert ctx.memory.coin_theses == ""
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend/.venv/bin/pytest backend/tests/test_brain_context.py -q`
Expected: FAIL (`ImportError: MemoryView` / unexpected keyword `memory`).

- [ ] **Step 3: Implement context changes**

In `backend/app/brain/context.py`, add the dataclass (after `CoinSnapshot`):

```python
@dataclass
class MemoryView:
    coin_theses: str = ""
    trade_lessons: str = ""
    strategy_notes: str = ""
```

Add the field to `DecisionContext`:

```python
@dataclass
class DecisionContext:
    instructions: str
    cash_usd: Decimal
    equity_usd: Decimal
    positions: list[PositionView]
    universe: list[CoinSnapshot]
    recent_events: list[str]
    memory: MemoryView
```

Update `build_context`:

```python
def build_context(*, instructions, cash_usd, holdings, universe, recent_events, memory=None) -> DecisionContext:
    positions: list[PositionView] = []
    equity = cash_usd
    for symbol, quantity, avg_price, last_price in holdings:
        pnl = ((last_price - avg_price) / avg_price * Decimal("100")) if avg_price else Decimal("0")
        positions.append(PositionView(symbol, quantity, avg_price, last_price, pnl))
        equity += quantity * last_price
    return DecisionContext(
        instructions=instructions, cash_usd=cash_usd, equity_usd=equity,
        positions=positions, universe=universe, recent_events=recent_events,
        memory=memory or MemoryView(),
    )
```

- [ ] **Step 4: Run to verify context tests pass**

Run: `backend/.venv/bin/pytest backend/tests/test_brain_context.py -q`
Expected: PASS.

- [ ] **Step 5: Write the failing prompt test**

Add to `backend/tests/test_brain_prompt.py`:

```python
def test_prompt_includes_memory_when_present():
    from app.brain.context import MemoryView
    ctx = build_context(
        instructions="x", cash_usd=Decimal("100"), holdings=[], universe=[],
        recent_events=[], memory=MemoryView(coin_theses="BTC: accumulate", strategy_notes="I FOMO on pumps"),
    )
    _system, user = render_prompt(ctx)
    assert "BTC: accumulate" in user
    assert "I FOMO on pumps" in user
    assert "Trade lessons:" not in user        # empty section omitted

def test_prompt_omits_memory_block_when_empty():
    _system, user = render_prompt(_ctx())      # _ctx() has no memory
    assert "Your memory" not in user
```

- [ ] **Step 6: Run to verify it fails**

Run: `backend/.venv/bin/pytest backend/tests/test_brain_prompt.py -q`
Expected: FAIL (memory lines absent from the prompt).

- [ ] **Step 7: Render memory in the prompt**

In `backend/app/brain/prompt.py`, add one sentence to `_SYSTEM` (right before the `Decide what to do` line):

```python
Your memory below is your own prior reflection on past trades — treat it as your evolving view.
```

In `render_prompt`, after the `Recent events` block (after the `lines += [f"  - {e}" ...]` line), insert:

```python
    mem = ctx.memory
    mem_lines = []
    for label, text in (("Coin theses", mem.coin_theses),
                        ("Trade lessons", mem.trade_lessons),
                        ("Strategy notes", mem.strategy_notes)):
        rows = [l for l in text.splitlines() if l.strip()]
        if rows:
            mem_lines.append(f"{label}:")
            mem_lines += [f"  - {l}" for l in rows]
    if mem_lines:
        lines += ["", "Your memory (you wrote this; update your behaviour accordingly):"] + mem_lines
```

- [ ] **Step 8: Run to verify prompt tests pass**

Run: `backend/.venv/bin/pytest backend/tests/test_brain_prompt.py -q`
Expected: PASS (new + existing prompt tests).

- [ ] **Step 9: Commit**

```bash
git add backend/app/brain/context.py backend/app/brain/prompt.py backend/tests/test_brain_context.py backend/tests/test_brain_prompt.py
git commit -m "feat(brain): carry memory in context and render it into the decision prompt"
```

---

## Task 3: `brain/memory.py` — reflection logic (pure)

**Files:**
- Create: `backend/app/brain/memory.py`
- Test: `backend/tests/test_brain_memory.py`

**Interfaces:**
- Consumes: `MemoryView` from `app.brain.context`.
- Produces:
  - `CAP_COIN_THESES = 8`, `CAP_TRADE_LESSONS = 10`, `CAP_STRATEGY_NOTES = 5`.
  - `ClosedTrade(symbol: str, qty: Decimal, sell_price: Decimal, avg_cost: Decimal, realized_pnl_pct: Decimal)` (dataclass).
  - `MemoryUpdate(BaseModel)` with `coin_theses/trade_lessons/strategy_notes: list[str]` (default `[]`).
  - `build_reflection_prompt(memory: MemoryView, closed: list[ClosedTrade], held_symbols: list[str], instructions: str) -> tuple[str, str]`.
  - `parse_reflection(raw: str) -> MemoryUpdate`.
  - `enforce_caps(update: MemoryUpdate) -> MemoryView`.
  - `run_reflection(memory, closed, held_symbols, instructions, adapter) -> MemoryView` (calls `adapter.complete_json`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_brain_memory.py`:

```python
from decimal import Decimal
from app.brain.context import MemoryView
from app.brain.memory import (
    ClosedTrade, MemoryUpdate, build_reflection_prompt, parse_reflection,
    enforce_caps, run_reflection,
    CAP_COIN_THESES, CAP_TRADE_LESSONS, CAP_STRATEGY_NOTES,
)


def test_enforce_caps_truncates_and_joins():
    update = MemoryUpdate(
        coin_theses=[f"C{i}" for i in range(9)],     # 9 -> 8
        trade_lessons=[f"L{i}" for i in range(11)],  # 11 -> 10
        strategy_notes=[f"N{i}" for i in range(6)],  # 6 -> 5
    )
    mem = enforce_caps(update)
    assert len(mem.coin_theses.splitlines()) == CAP_COIN_THESES
    assert len(mem.trade_lessons.splitlines()) == CAP_TRADE_LESSONS
    assert len(mem.strategy_notes.splitlines()) == CAP_STRATEGY_NOTES
    assert mem.coin_theses.splitlines()[0] == "C0"   # keeps the first N


def test_parse_reflection_reads_json():
    raw = '{"coin_theses": ["BTC: bull"], "trade_lessons": [], "strategy_notes": ["patient"]}'
    update = parse_reflection(raw)
    assert update.coin_theses == ["BTC: bull"]
    assert update.strategy_notes == ["patient"]


def test_build_reflection_prompt_mentions_outcome_and_memory():
    mem = MemoryView(coin_theses="BTC: old view")
    closed = [ClosedTrade("BTCUSDT", Decimal("1"), Decimal("120"), Decimal("100"), Decimal("20"))]
    system, user = build_reflection_prompt(mem, closed, ["ETHUSDT"], "be bold")
    assert "JSON" in system and "be bold" in system
    assert "BTCUSDT" in user and "+20.00%" in user
    assert "BTC: old view" in user            # current memory shown for rewrite


def test_run_reflection_uses_adapter_and_caps():
    class FakeAdapter:
        def complete_json(self, system, user):
            return '{"coin_theses": ["BTC: bull", "ETH: flat"], "trade_lessons": ["sold too early"], "strategy_notes": []}'
    mem = run_reflection(MemoryView(), [], [], "x", FakeAdapter())
    assert mem.coin_theses == "BTC: bull\nETH: flat"
    assert mem.trade_lessons == "sold too early"
    assert mem.strategy_notes == ""
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend/.venv/bin/pytest backend/tests/test_brain_memory.py -q`
Expected: FAIL (`ModuleNotFoundError: app.brain.memory`).

- [ ] **Step 3: Implement `brain/memory.py`**

Create `backend/app/brain/memory.py`:

```python
import json
from dataclasses import dataclass
from decimal import Decimal
from pydantic import BaseModel
from app.brain.context import MemoryView

CAP_COIN_THESES = 8
CAP_TRADE_LESSONS = 10
CAP_STRATEGY_NOTES = 5


@dataclass
class ClosedTrade:
    symbol: str
    qty: Decimal
    sell_price: Decimal
    avg_cost: Decimal
    realized_pnl_pct: Decimal


class MemoryUpdate(BaseModel):
    coin_theses: list[str] = []
    trade_lessons: list[str] = []
    strategy_notes: list[str] = []


_REFLECT_SYSTEM = """You are the reflective memory of an autonomous paper-trading agent.
The agent just closed one or more trades. Rewrite its long-term memory in light of the outcomes.
Output ONLY a JSON object of this exact shape:
{{"coin_theses": ["<SYMBOL: one-line current view>", ...],
  "trade_lessons": ["<one-line lesson from a closed trade>", ...],
  "strategy_notes": ["<one-line observation about the agent's own behaviour>", ...]}}
Rewrite each list fully (do NOT append). Keep at most {coin} coin_theses, {lessons} trade_lessons,
{notes} strategy_notes. One short line per item. Output JSON only, no prose.

The agent's operator instructions:
{instructions}"""


def build_reflection_prompt(memory: MemoryView, closed: list[ClosedTrade],
                            held_symbols: list[str], instructions: str) -> tuple[str, str]:
    system = _REFLECT_SYSTEM.format(
        coin=CAP_COIN_THESES, lessons=CAP_TRADE_LESSONS, notes=CAP_STRATEGY_NOTES,
        instructions=instructions or "(none provided)",
    )
    lines = ["Closed trades this cycle:"]
    for t in closed:
        lines.append(f"  {t.symbol}: sold {t.qty} @ ${t.sell_price} "
                     f"(avg cost ${t.avg_cost}, realized {t.realized_pnl_pct:+.2f}%)")
    lines += ["", f"Currently held: {', '.join(held_symbols) or '(none)'}", "", "Current memory:"]
    for label, text in (("Coin theses", memory.coin_theses),
                        ("Trade lessons", memory.trade_lessons),
                        ("Strategy notes", memory.strategy_notes)):
        lines.append(f"{label}:")
        lines += [f"  - {l}" for l in text.splitlines() if l.strip()] or ["  (none)"]
    return system, "\n".join(lines)


def parse_reflection(raw: str) -> MemoryUpdate:
    return MemoryUpdate.model_validate(json.loads(raw))


def enforce_caps(update: MemoryUpdate) -> MemoryView:
    def cap(items: list[str], n: int) -> str:
        return "\n".join(s.strip() for s in items[:n] if s.strip())
    return MemoryView(
        coin_theses=cap(update.coin_theses, CAP_COIN_THESES),
        trade_lessons=cap(update.trade_lessons, CAP_TRADE_LESSONS),
        strategy_notes=cap(update.strategy_notes, CAP_STRATEGY_NOTES),
    )


def run_reflection(memory: MemoryView, closed: list[ClosedTrade],
                   held_symbols: list[str], instructions: str, adapter) -> MemoryView:
    system, user = build_reflection_prompt(memory, closed, held_symbols, instructions)
    raw = adapter.complete_json(system, user)
    return enforce_caps(parse_reflection(raw))
```

- [ ] **Step 4: Run to verify tests pass**

Run: `backend/.venv/bin/pytest backend/tests/test_brain_memory.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/brain/memory.py backend/tests/test_brain_memory.py
git commit -m "feat(brain): pure reflection logic (prompt, parse, caps, run_reflection)"
```

---

## Task 4: Runtime wiring — read memory, capture closed trades, reflect

**Files:**
- Modify: `backend/app/agents/runtime.py`
- Test: `backend/tests/test_runtime.py`

**Interfaces:**
- Consumes: `MemoryView` (`app.brain.context`), `run_reflection`, `ClosedTrade` (`app.brain.memory`), `AgentMemory` (`app.db.models`).
- Produces:
  - `run_decision(session, agent, market, symbols, buy_usd, *, brain_decide=..., reflect=run_reflection)` — new `reflect` keyword (injectable for tests).
  - `_persist_memory(session, agent_id, mem: MemoryView)` — upserts the 3 section rows.
  - A `reflection` kind `Event` per cycle that closed ≥1 trade.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_runtime.py` (the existing `_llm_agent`, `FakeMarketLLM`, `CoinSnapshot`, `Decision`, `Action` helpers are already imported there):

```python
from app.brain.context import MemoryView
from app.db.models import AgentMemory


async def test_reflection_runs_once_on_sell_and_persists(db_session):
    agent = _llm_agent(db_session)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("2"))]
    market = FakeMarketLLM(snap, Decimal("120"), (Decimal("120"), Decimal("121")))
    decision = Decision(actions=[Action(type="SELL", symbol="BTCUSDT", fraction=Decimal("1"))], note="exit")

    calls = []
    def fake_reflect(memory, closed, held_symbols, instructions, adapter):
        calls.append(closed)
        return MemoryView(coin_theses="BTC: took profit", trade_lessons="green exit")

    await run_decision(db_session, agent, market, ["BTCUSDT"], Decimal("10"),
                       brain_decide=lambda ctx, adapter: decision, reflect=fake_reflect)

    assert len(calls) == 1                       # exactly one reflection call
    assert calls[0][0].symbol == "BTCUSDT"
    assert calls[0][0].realized_pnl_pct == Decimal("20")   # (120-100)/100*100
    row = db_session.query(AgentMemory).filter_by(agent_id=agent.id, section="coin_theses").one()
    assert row.content == "BTC: took profit"
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="reflection").one()
    assert "memoria" in ev.message.lower()


async def test_no_reflection_when_no_sell(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("50"))], note="in")
    calls = []
    await run_decision(db_session, agent, market, ["BTCUSDT"], Decimal("10"),
                       brain_decide=lambda ctx, adapter: decision,
                       reflect=lambda *a, **k: calls.append(1) or MemoryView())
    assert calls == []
    assert db_session.query(AgentMemory).filter_by(agent_id=agent.id).count() == 0


async def test_reflection_failure_is_isolated(db_session):
    agent = _llm_agent(db_session)
    db_session.add(AgentMemory(agent_id=agent.id, section="coin_theses", content="BTC: keep"))
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("2"))]
    market = FakeMarketLLM(snap, Decimal("120"), (Decimal("120"), Decimal("121")))
    decision = Decision(actions=[Action(type="SELL", symbol="BTCUSDT", fraction=Decimal("1"))], note="exit")

    def boom(*a, **k):
        raise RuntimeError("provider down")

    await run_decision(db_session, agent, market, ["BTCUSDT"], Decimal("10"),
                       brain_decide=lambda ctx, adapter: decision, reflect=boom)

    # existing memory untouched
    row = db_session.query(AgentMemory).filter_by(agent_id=agent.id, section="coin_theses").one()
    assert row.content == "BTC: keep"
    # error logged as a reflection event, loop did not crash (the SELL still executed)
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="reflection").one()
    assert "errore" in ev.message and "provider down" in ev.message
    assert db_session.query(Trade).filter_by(agent_id=agent.id, side="SELL").count() == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend/.venv/bin/pytest backend/tests/test_runtime.py -q`
Expected: FAIL (`run_decision` has no `reflect` kwarg / no reflection event written).

- [ ] **Step 3: Update imports in `runtime.py`**

Change the existing import lines at the top of `backend/app/agents/runtime.py`:

```python
from app.db.models import EquitySnapshot, Event, AgentMemory
from app.brain.context import build_context, MemoryView
from app.brain.memory import run_reflection, ClosedTrade
```

(Keep all other existing imports.)

- [ ] **Step 4: Add the `reflect` parameter to `run_decision`**

Replace the `run_decision` signature and its `_run_decision_llm` call:

```python
async def run_decision(session, agent, market, symbols, buy_usd: Decimal, *,
                       brain_decide=brain_decide_default, reflect=run_reflection) -> None:
    if agent.strategy == "sma":
        await _run_decision_sma(session, agent, market, symbols, buy_usd)
    else:
        await _run_decision_llm(session, agent, market, symbols, brain_decide, reflect)
```

- [ ] **Step 5: Load memory into the context (inside `_run_decision_llm`)**

Change the `_run_decision_llm` signature to accept `reflect`:

```python
async def _run_decision_llm(session, agent, market, symbols, brain_decide, reflect) -> None:
```

Inside its `try:` block, build `memory` before `build_context` and pass it in:

```python
        mem_rows = {r.section: r.content for r in
                    session.query(AgentMemory).filter_by(agent_id=agent.id).all()}
        memory = MemoryView(
            coin_theses=mem_rows.get("coin_theses", ""),
            trade_lessons=mem_rows.get("trade_lessons", ""),
            strategy_notes=mem_rows.get("strategy_notes", ""),
        )
        ctx = build_context(instructions=agent.instructions, cash_usd=agent.cash_usd,
                            holdings=holdings, universe=universe, recent_events=recent,
                            memory=memory)
```

- [ ] **Step 6: Capture closed trades in the action loop**

Initialize before the `for action in decision.actions:` loop:

```python
    held = {p.symbol: p for p in agent.positions}
    actions = skipped = errors = 0
    closed_trades: list[ClosedTrade] = []
```

In the `SELL` branch, capture `avg_cost` **before** `execute_sell` and record the closed trade after it:

```python
            elif action.type == "SELL" and action.symbol in held:
                frac = action.fraction if action.fraction is not None else Decimal("1")
                qty = held[action.symbol].quantity * frac
                if qty <= 0:
                    skipped += 1; continue
                avg_cost = held[action.symbol].avg_price
                bid, _ask = await market.get_book_ticker(action.symbol)
                execute_sell(session, agent, action.symbol, qty, bid)
                realized = ((bid - avg_cost) / avg_cost * Decimal("100")) if avg_cost else Decimal("0")
                closed_trades.append(ClosedTrade(symbol=action.symbol, qty=qty, sell_price=bid,
                                                 avg_cost=avg_cost, realized_pnl_pct=realized))
                _append_rationale(session, agent, action.rationale)
                held = {p.symbol: p for p in agent.positions}; actions += 1
```

- [ ] **Step 7: Trigger reflection after the decision event commit**

After the existing `session.commit()` that follows the decision `Event`, append:

```python
    if closed_trades:
        try:
            held_symbols = [p.symbol for p in agent.positions]
            new_mem = reflect(memory, closed_trades, held_symbols, agent.instructions, adapter)
            _persist_memory(session, agent.id, new_mem)
            session.add(Event(agent_id=agent.id, kind="reflection",
                              message="memoria aggiornata dopo trade chiuso"))
        except Exception as exc:
            session.add(Event(agent_id=agent.id, kind="reflection",
                              message=f"reflection: errore — {exc}"))
        session.commit()
```

Add the helper near `_append_rationale`:

```python
def _persist_memory(session, agent_id, mem: MemoryView) -> None:
    for section, content in (("coin_theses", mem.coin_theses),
                             ("trade_lessons", mem.trade_lessons),
                             ("strategy_notes", mem.strategy_notes)):
        row = (session.query(AgentMemory)
               .filter_by(agent_id=agent_id, section=section).first())
        if row is None:
            session.add(AgentMemory(agent_id=agent_id, section=section, content=content))
        else:
            row.content = content
```

- [ ] **Step 8: Run to verify the runtime tests pass**

Run: `backend/.venv/bin/pytest backend/tests/test_runtime.py -q`
Expected: PASS (new reflection tests + all existing runtime tests).

- [ ] **Step 9: Commit**

```bash
git add backend/app/agents/runtime.py backend/tests/test_runtime.py
git commit -m "feat(brain): trigger reflection on closed trades and persist memory"
```

---

## Task 5: API endpoint `GET /agents/{id}/memory`

**Files:**
- Modify: `backend/app/api/schemas.py`, `backend/app/api/routes.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `AgentMemory` (`app.db.models`).
- Produces: `MemoryOut(coin_theses: str, trade_lessons: str, strategy_notes: str)` and `GET /api/agents/{agent_id}/memory`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api.py` (follow the file's existing client/fixture pattern — use the same TestClient/session helper already used by other route tests in that file):

```python
def test_get_agent_memory_returns_sections(client, db_session):
    from app.db.models import Agent, AgentMemory
    from datetime import datetime, timezone
    from decimal import Decimal
    a = Agent(name="Mem", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"))
    db_session.add(a); db_session.commit()
    db_session.add(AgentMemory(agent_id=a.id, section="coin_theses", content="BTC: bull"))
    db_session.commit()
    r = client.get(f"/api/agents/{a.id}/memory")
    assert r.status_code == 200
    body = r.json()
    assert body["coin_theses"] == "BTC: bull"
    assert body["trade_lessons"] == ""        # missing section -> empty string
```

> Note for the implementer: match `test_api.py`'s existing fixtures. If that file uses a single `client` fixture that owns its own session, adapt the setup to insert rows through the same session the app uses (mirror how other tests in the file seed agents).

- [ ] **Step 2: Run to verify it fails**

Run: `backend/.venv/bin/pytest backend/tests/test_api.py -q`
Expected: FAIL (404 — route not defined).

- [ ] **Step 3: Add the schema**

Append to `backend/app/api/schemas.py`:

```python
class MemoryOut(BaseModel):
    coin_theses: str
    trade_lessons: str
    strategy_notes: str
```

- [ ] **Step 4: Add the route**

In `backend/app/api/routes.py`, add `AgentMemory` to the `app.db.models` import and `MemoryOut` to the `app.api.schemas` import, then append:

```python
@router.get("/agents/{agent_id}/memory", response_model=MemoryOut)
def get_memory(agent_id: int, session=Depends(session_dep)):
    rows = {r.section: r.content for r in
            session.query(AgentMemory).filter_by(agent_id=agent_id).all()}
    return MemoryOut(
        coin_theses=rows.get("coin_theses", ""),
        trade_lessons=rows.get("trade_lessons", ""),
        strategy_notes=rows.get("strategy_notes", ""),
    )
```

- [ ] **Step 5: Run to verify it passes**

Run: `backend/.venv/bin/pytest backend/tests/test_api.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api.py
git commit -m "feat(api): GET /agents/{id}/memory"
```

---

## Task 6: Dashboard memory panel (read-only)

**Files:**
- Modify: `frontend/src/api.ts`
- Create: `frontend/src/components/MemoryPanel.tsx`
- Create: `frontend/src/__tests__/MemoryPanel.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `GET /api/agents/{id}/memory`.
- Produces: `AgentMemory` type, `getMemory(id)`, and a `<MemoryPanel memory={...} />` component.

- [ ] **Step 1: Add the API type + fetch**

In `frontend/src/api.ts`, add the type (after `Position`):

```typescript
export type AgentMemory = {
  coin_theses: string;
  trade_lessons: string;
  strategy_notes: string;
};
```

And the fetch (after `getPositions`):

```typescript
export const getMemory = (id: number) => get<AgentMemory>(`/api/agents/${id}/memory`);
```

- [ ] **Step 2: Write the failing component test**

Create `frontend/src/__tests__/MemoryPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MemoryPanel } from "../components/MemoryPanel";

describe("MemoryPanel", () => {
  it("renders non-empty sections as list items", () => {
    render(<MemoryPanel memory={{ coin_theses: "BTC: bull\nETH: flat", trade_lessons: "", strategy_notes: "patient" }} />);
    expect(screen.getByText("BTC: bull")).toBeInTheDocument();
    expect(screen.getByText("ETH: flat")).toBeInTheDocument();
    expect(screen.getByText("patient")).toBeInTheDocument();
  });

  it("shows an empty hint when all sections are blank", () => {
    render(<MemoryPanel memory={{ coin_theses: "", trade_lessons: "", strategy_notes: "" }} />);
    expect(screen.getByText(/nessuna memoria/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npm test -- MemoryPanel`
Expected: FAIL (cannot resolve `../components/MemoryPanel`).

- [ ] **Step 4: Implement the component**

Create `frontend/src/components/MemoryPanel.tsx`:

```tsx
import type { AgentMemory } from "../api";

const SECTIONS: { key: keyof AgentMemory; label: string }[] = [
  { key: "coin_theses", label: "Tesi per coin" },
  { key: "trade_lessons", label: "Lezioni dai trade" },
  { key: "strategy_notes", label: "Note di strategia" },
];

export function MemoryPanel({ memory }: { memory: AgentMemory }) {
  const empty = SECTIONS.every((s) => !memory[s.key].trim());
  if (empty) return <p className="empty">Ancora nessuna memoria. L'agente non ha chiuso trade.</p>;

  return (
    <div className="memory">
      {SECTIONS.map((s) => {
        const rows = memory[s.key].split("\n").filter((l) => l.trim());
        if (!rows.length) return null;
        return (
          <div key={s.key} className="memory-section">
            <h3>{s.label}</h3>
            <ul>{rows.map((l, i) => <li key={i}>{l}</li>)}</ul>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npm test -- MemoryPanel`
Expected: PASS.

- [ ] **Step 6: Wire it into `App.tsx`**

Add to the imports:

```tsx
import { MemoryPanel } from "./components/MemoryPanel";
import { getMemory, type AgentMemory } from "./api";
```

(Merge `getMemory`/`AgentMemory` into the existing `./api` import if preferred.)

Add state next to the other `useState` calls:

```tsx
  const [memory, setMemory] = useState<AgentMemory | null>(null);
```

In the per-agent `useEffect` `load` function (the one with `getEquity/getEvents/getPositions`), add:

```tsx
      getMemory(selId).then(setMemory).catch(() => {});
```

Add a panel inside the `two-col` block (after the Attività `section`), or as a new full-width `section` below it:

```tsx
            <section className="card">
              <h2>Memoria</h2>
              {memory ? <MemoryPanel memory={memory} /> : <p className="empty">…</p>}
            </section>
```

- [ ] **Step 7: Run the full frontend test suite + build**

Run: `cd frontend && npm test && npm run build`
Expected: PASS + clean build (`tsc -b` type-checks the new code).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api.ts frontend/src/components/MemoryPanel.tsx frontend/src/__tests__/MemoryPanel.test.tsx frontend/src/App.tsx
git commit -m "feat(dashboard): read-only agent memory panel"
```

---

## Final verification

- [ ] Run the full backend suite: `backend/.venv/bin/pytest backend/tests -q` — expect all green (52 prior + new tests).
- [ ] Run the frontend suite + build: `cd frontend && npm test && npm run build` — expect green.
- [ ] Confirm `backend/.venv/bin/alembic -c backend/alembic.ini heads` prints `c3d4e5f6a7b8 (head)`.

---

## Self-Review notes

- **Spec coverage:** table+migration (T1), read-into-prompt + short-term=recent_events unchanged (T2), pure reflection with caps 8/10/5 (T3), SELL-triggered reflection + one-call-per-cycle + realized P&L from pre-sell avg cost + failure isolation (T4), API (T5), read-only dashboard panel (T6). Parked items (scratchpad, periodic reflection, dedicated model) intentionally absent.
- **Interface consistency:** `MemoryView` defined in T2 and reused by T3/T4; `run_reflection(memory, closed, held_symbols, instructions, adapter)` signature identical in T3 (definition) and T4 (call); `ClosedTrade` fields match between T3 and the T4 construction site; section keys `coin_theses/trade_lessons/strategy_notes` consistent across model, runtime, API, and frontend.
- **Spec refinement:** the spec's reflection input used `positions: list[PositionView]`; this plan uses `held_symbols: list[str]` instead (no price re-fetch needed post-trade, simpler and fully offline-testable). Spec updated to match.
