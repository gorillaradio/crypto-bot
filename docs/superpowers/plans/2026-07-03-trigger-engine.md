# Trigger Engine (Pipeline v2 — Fase 5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize the existing edge-triggered wake mechanism (today only stop/take-profit *breach*) to also wake an agent on **price movement** (|~1h move| ≥ 5% on a held coin) and **portfolio-relevant news**, with a per-agent hourly wake budget that caps the two discretionary triggers while leaving breach always allowed.

**Architecture:** The per-beat `run_heartbeat` (every 5 min, already iterates held positions with live prices) is extended to also detect movement (via Binance klines) and news (via a per-agent `last_seen_observation_id` bookmark over the Fase-4 `Observation` table). At most **one** decision fires per beat, chosen by priority `breach > movement > news`; movement/news are gated by a rolling-hour budget counted off existing `DecisionRecord` rows (no new table). The scheduled 1h cycle stays as the always-on fallback. New pure/DB trigger logic lives in a new `app/agents/triggers.py`; orchestration stays in `run_heartbeat`.

**Tech Stack:** Python 3.13, SQLAlchemy 2 (Mapped), Alembic, pytest (asyncio auto mode, in-memory SQLite via `create_all`), Binance public REST (`get_klines`), pydantic-settings.

## Global Constraints

- **Branch:** `pipeline-v2` (long-lived). **NO push / merge / PR without explicit user request** — auto-deploy is on `main`, nothing reaches prod until the final 6-phase merge. Paper trading only.
- **Free solutions only** — no paid APIs. Binance public REST (`/api/v3/klines`) needs no key.
- **Tests use `Base.metadata.create_all`, never Alembic migrations.** Each migration is a hand-written mirror of the model. Migration up/down smoke-test runs separately on a throwaway SQLite in the finalization task.
- **Datetime UTC-aware discipline (Fase-4 latent note):** never compare a Python `datetime` against `Observation.published_at` / `DecisionRecord.created_at` **in SQL** on SQLite (tz is dropped on write → lexicographic string compare misfires). Fetch rows with SQL equality/`IN`/`id` filters only, then normalize with a local `_as_utc()` and compare the time window **in Python** — exactly as `app/eval/scoring_job.py` already does.
- **`_base` quote coupling:** base symbols come from `app.feeds.query._base`, which strips only `USDT/USDC/BUSD/USD`. All callers pass `USDT` universes today. Do not introduce a non-USDT quote without extending `_QUOTES`.
- **Additive only:** every new model field/config knob is additive with a default; no existing signature loses backward compatibility. Existing tests must stay green.
- **Model per task** is stated in each task header.
- **Base commit for the final review:** `7167673` (Fase-5 commits start here). Final review scope = `7167673..HEAD`, **NOT** `main...pipeline-v2`.

---

## File Structure

- **Create** `backend/app/agents/triggers.py` — new trigger logic: `movement_change` (pure), `count_recent_event_wakes` (budget, DB), `fresh_news_for` (news bookmark match, DB), `advance_news_watermark` (DB). One responsibility: "what, besides breach, should wake this agent, and may it?".
- **Create** `backend/tests/test_triggers.py` — unit tests for the four `triggers.py` functions.
- **Modify** `backend/app/core/config.py` — 3 new settings (`wake_budget_per_hour`, `movement_threshold`, `movement_window_hours`).
- **Modify** `backend/app/db/models.py` — `Position.move_armed`, `Agent.last_seen_observation_id`, `DecisionRecord.trigger` comment, `Observation.published_at` UTC comment.
- **Create** `backend/alembic/versions/<rev>_trigger_engine_columns.py` — hand-written migration for the two new columns.
- **Modify** `backend/app/agents/runtime.py` — `trigger` kwarg plumbed through `run_decision_guarded` / `run_decision` / `_run_decision_llm`; movement + news detection and one-wake-per-beat orchestration inside `run_heartbeat`; watermark advance after a successful decision.
- **Modify** `backend/tests/test_runtime.py` — new tests for trigger plumbing, movement wake, news wake, watermark advance.

No scheduler change: the trigger logic rides the existing `_heartbeat_tick` (5 min) and the existing `_decision_tick` (1h fallback) is unchanged.

---

### Task 1: Foundation — config knobs, schema columns, migration, comments

**Model:** sonnet

**Files:**
- Modify: `backend/app/core/config.py:11-15`
- Modify: `backend/app/db/models.py:26-41` (Position), `:12-30` (Agent), `:88` (DecisionRecord comment), `:151` (Observation comment)
- Create: `backend/alembic/versions/<rev>_trigger_engine_columns.py`
- Test: `backend/tests/test_triggers.py`

**Interfaces:**
- Produces: `settings.wake_budget_per_hour: int` (=2), `settings.movement_threshold: Decimal` (=0.05), `settings.movement_window_hours: int` (=1); `Position.move_armed: bool` (default True); `Agent.last_seen_observation_id: int | None` (default None).

- [ ] **Step 1: Write the failing test** — `backend/tests/test_triggers.py`

```python
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.core.config import settings
from app.db.models import Agent, Position


def _agent(session):
    a = Agent(name="T", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("100"))
    session.add(a); session.commit()
    return a


def test_settings_have_trigger_knobs():
    assert settings.wake_budget_per_hour == 2
    assert settings.movement_threshold == Decimal("0.05")
    assert settings.movement_window_hours == 1


def test_new_columns_defaults(db_session):
    agent = _agent(db_session)
    assert agent.last_seen_observation_id is None
    pos = Position(agent_id=agent.id, symbol="BTCUSDT",
                   quantity=Decimal("1"), avg_price=Decimal("100"))
    db_session.add(pos); db_session.commit()
    assert pos.move_armed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_triggers.py -v`
Expected: FAIL — `AttributeError: ... 'move_armed'` / missing settings attrs.

- [ ] **Step 3: Add config knobs** — in `backend/app/core/config.py`, after line 14 (`news_poll_seconds`):

```python
    # --- trigger engine (Fase 5) ---
    wake_budget_per_hour: int = 2          # max news+movement wakes/hour per agent
    movement_threshold: Decimal = Decimal("0.05")   # |~1h move| >= this fraction => movement wake
    movement_window_hours: int = 1
```

- [ ] **Step 4: Add model columns + comments** — in `backend/app/db/models.py`:

In `Agent`, after `created_at` (line 28):
```python
    # News wake bookmark: highest Observation.id this agent has already "seen"
    # (present in a prior decision's prompt). NULL = never decided yet.
    last_seen_observation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
```

In `Position`, after `breach_armed` (line 40):
```python
    move_armed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

Change `DecisionRecord.trigger` comment (line 88) to:
```python
    trigger: Mapped[str] = mapped_column(String(20))  # "schedule" | "breach" | "movement" | "news"
```

Add a comment above `Observation.published_at` (line 151):
```python
    # MUST be written UTC-aware: SQLite drops tzinfo, so any datetime ordering/compare
    # is correct only while every writer stores UTC. Sole writer today: app/feeds/rss.py.
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
```

- [ ] **Step 5: Run tests to verify create_all-based tests pass**

Run: `cd backend && python -m pytest tests/test_triggers.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Write the migration** — confirm head, generate a stamped file, hand-fill it.

Run: `cd backend && alembic heads` → expect single head `6c4cc097ac38`.
Run: `cd backend && alembic revision -m "trigger engine columns"` → note the generated `<rev>` filename.

Replace the generated `upgrade`/`downgrade` bodies (keep the generated `revision`, set `down_revision`):
```python
revision = "<rev>"            # keep the auto-generated id
down_revision = "6c4cc097ac38"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.add_column("positions",
        sa.Column("move_armed", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("agents",
        sa.Column("last_seen_observation_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "last_seen_observation_id")
    op.drop_column("positions", "move_armed")
```

- [ ] **Step 7: Verify single head + full backend suite**

Run: `cd backend && alembic heads` → expect single head = `<rev>`.
Run: `cd backend && python -m pytest -q` → expect 213 passed + 2 new = **215 passed**.

- [ ] **Step 8: Commit**

```bash
git add backend/app/core/config.py backend/app/db/models.py backend/alembic/versions/ backend/tests/test_triggers.py
git commit -m "feat(triggers): config knobs + move_armed/last_seen_observation_id columns + migration"
```

---

### Task 2: `movement_change` — pure move fraction

**Model:** haiku

**Files:**
- Create: `backend/app/agents/triggers.py`
- Test: `backend/tests/test_triggers.py`

**Interfaces:**
- Produces: `movement_change(first: Decimal, last: Decimal) -> Decimal` — signed fraction `(last-first)/first`; returns `Decimal("0")` when `first <= 0`.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_triggers.py`

```python
from app.agents.triggers import movement_change


def test_movement_change_up():
    assert movement_change(Decimal("100"), Decimal("108")) == Decimal("0.08")


def test_movement_change_down_is_signed():
    assert movement_change(Decimal("100"), Decimal("93")) == Decimal("-0.07")


def test_movement_change_flat():
    assert movement_change(Decimal("100"), Decimal("100")) == Decimal("0")


def test_movement_change_zero_first_guards():
    assert movement_change(Decimal("0"), Decimal("50")) == Decimal("0")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_triggers.py -k movement_change -v`
Expected: FAIL — `ModuleNotFoundError: app.agents.triggers`.

- [ ] **Step 3: Create `triggers.py` with the pure function**

```python
from decimal import Decimal


def movement_change(first: Decimal, last: Decimal) -> Decimal:
    """Signed price move over a window: (last - first) / first. 0 when first <= 0."""
    if first <= 0:
        return Decimal("0")
    return (last - first) / first
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_triggers.py -k movement_change -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/triggers.py backend/tests/test_triggers.py
git commit -m "feat(triggers): movement_change pure helper"
```

---

### Task 3: `count_recent_event_wakes` — rolling-hour budget counter

**Model:** sonnet

**Files:**
- Modify: `backend/app/agents/triggers.py`
- Test: `backend/tests/test_triggers.py`

**Interfaces:**
- Consumes: `DecisionRecord(kind, trigger, agent_id, created_at)`.
- Produces: `count_recent_event_wakes(session, agent_id: int) -> int` — number of `kind == "decision"` records with `trigger in ("movement","news")` whose `created_at` is within the last hour (Python-side `_as_utc` compare). Excludes breach/schedule and reflection/distillation rows.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_triggers.py`

```python
from app.db.models import DecisionRecord
from app.agents.triggers import count_recent_event_wakes


def _rec(session, agent_id, trigger, kind="decision", age_minutes=1):
    r = DecisionRecord(agent_id=agent_id, cycle_id="c", kind=kind, trigger=trigger,
                       system_prompt="s", user_prompt="u", raw_response="r",
                       parsed_output="{}", parse_status="ok",
                       model_provider="openrouter", model_name="m", latency_ms=1)
    r.created_at = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    session.add(r); session.commit()
    return r


def test_budget_counts_only_movement_and_news_decisions(db_session):
    agent = _agent(db_session)
    _rec(db_session, agent.id, "movement")
    _rec(db_session, agent.id, "news")
    _rec(db_session, agent.id, "breach")                        # exempt trigger
    _rec(db_session, agent.id, "schedule")                     # exempt trigger
    _rec(db_session, agent.id, "movement", kind="reflection")  # not a decision
    assert count_recent_event_wakes(db_session, agent.id) == 2


def test_budget_excludes_records_older_than_one_hour(db_session):
    agent = _agent(db_session)
    _rec(db_session, agent.id, "movement", age_minutes=59)
    _rec(db_session, agent.id, "news", age_minutes=120)        # 2h ago → excluded
    assert count_recent_event_wakes(db_session, agent.id) == 1


def test_budget_is_per_agent(db_session):
    a1, a2 = _agent(db_session), _agent(db_session)
    _rec(db_session, a1.id, "movement")
    assert count_recent_event_wakes(db_session, a2.id) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_triggers.py -k budget -v`
Expected: FAIL — `ImportError: cannot import name 'count_recent_event_wakes'`.

- [ ] **Step 3: Implement the counter** — add to `backend/app/agents/triggers.py`

```python
from datetime import datetime, timedelta, timezone
from app.db.models import DecisionRecord

_EVENT_TRIGGERS = ("movement", "news")


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def count_recent_event_wakes(session, agent_id: int) -> int:
    """Discretionary (movement+news) decision cycles for this agent in the last hour.
    Time window compared in Python (never in SQL) per the UTC-aware discipline."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    rows = (session.query(DecisionRecord)
            .filter(DecisionRecord.agent_id == agent_id,
                    DecisionRecord.kind == "decision",
                    DecisionRecord.trigger.in_(_EVENT_TRIGGERS))
            .all())
    return sum(1 for r in rows if _as_utc(r.created_at) >= cutoff)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_triggers.py -k budget -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/triggers.py backend/tests/test_triggers.py
git commit -m "feat(triggers): count_recent_event_wakes rolling-hour budget counter"
```

---

### Task 4: `trigger` kwarg plumbed through the decision path

**Model:** sonnet

**Files:**
- Modify: `backend/app/agents/runtime.py:85-114` (`run_decision`, `run_decision_guarded`), `:117-130` (`_run_decision_llm` trigger derivation)
- Test: `backend/tests/test_runtime.py`

**Interfaces:**
- Consumes: existing `run_decision` / `run_decision_guarded` / `_run_decision_llm`.
- Produces: all three accept `trigger: str | None = None`; when `None` the label is derived as today (`"breach" if wake_reason else "schedule"`); when provided it is used verbatim for `DecisionRecord.trigger`. `run_decision_guarded(..., trigger=...)` forwards to `run_decision(..., trigger=...)`.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_runtime.py`

```python
async def test_run_decision_explicit_trigger_wins(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    await run_decision(db_session, agent, market, ["BTCUSDT"], wake_reason="x moved 6%",
                       trigger="movement",
                       brain_decide=lambda ctx, adapter: DecisionResult(Decision(actions=[], note="h")))
    rec = db_session.query(DecisionRecord).filter_by(agent_id=agent.id).one()
    assert rec.trigger == "movement"


async def test_run_decision_guarded_forwards_trigger(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    ran = await run_decision_guarded(db_session, agent, market, ["BTCUSDT"], wake_reason="n",
                                     trigger="news",
                                     brain_decide=lambda ctx, adapter: DecisionResult(Decision(actions=[], note="h")))
    assert ran is True
    rec = db_session.query(DecisionRecord).filter_by(agent_id=agent.id).one()
    assert rec.trigger == "news"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_runtime.py -k explicit_trigger -v`
Expected: FAIL — `TypeError: run_decision() got an unexpected keyword argument 'trigger'`.

- [ ] **Step 3: Thread the kwarg** — in `backend/app/agents/runtime.py`:

`run_decision` (line 85) — add `trigger=None` and pass it down:
```python
async def run_decision(session, agent, market, symbols, *, wake_reason=None, trigger=None,
                       brain_decide=brain_decide_default, reflect=run_reflection_result,
                       distill=run_distillation_result) -> None:
    cycle_id = uuid4().hex
    await _run_decision_llm(session, agent, market, symbols, brain_decide, reflect, distill,
                            cycle_id, wake_reason, trigger)
```

`run_decision_guarded` (line 103) — add `trigger=None` and forward:
```python
async def run_decision_guarded(session, agent, market, symbols, *, wake_reason=None, trigger=None,
                               brain_decide=brain_decide_default, reflect=run_reflection_result,
                               distill=run_distillation_result) -> bool:
    lock = _agent_lock(agent.id)
    if lock.locked():
        return False
    async with lock:
        await run_decision(session, agent, market, symbols, wake_reason=wake_reason, trigger=trigger,
                           brain_decide=brain_decide, reflect=reflect, distill=distill)
    return True
```

`_run_decision_llm` (line 117) — accept `trigger=None`, derive when absent (line 130):
```python
async def _run_decision_llm(session, agent, market, symbols, brain_decide, reflect, distill,
                            cycle_id: str, wake_reason=None, trigger=None) -> None:
```
and replace line 130 (`trigger = "breach" if wake_reason else "schedule"`) with:
```python
    trigger = trigger or ("breach" if wake_reason else "schedule")
```

- [ ] **Step 4: Run tests to verify pass + no regression**

Run: `cd backend && python -m pytest tests/test_runtime.py -q`
Expected: PASS — new tests green, and existing `test_run_decision_writes_decision_record` (trigger `"schedule"`) / `test_decision_record_trigger_is_breach_on_wake` (trigger `"breach"`) still green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/runtime.py backend/tests/test_runtime.py
git commit -m "feat(triggers): plumb explicit trigger label through the decision path"
```

---

### Task 5: Movement wake in `run_heartbeat`

**Model:** sonnet

**Files:**
- Modify: `backend/app/agents/runtime.py:45-83` (`run_heartbeat`), add a private klines helper.
- Test: `backend/tests/test_runtime.py`

**Interfaces:**
- Consumes: `movement_change` (Task 2), `count_recent_event_wakes` (Task 3), `settings.movement_threshold` / `movement_window_hours` / `wake_budget_per_hour`, `market.get_klines(symbol, interval, limit)` (returns list of `Decimal` closes, oldest→newest).
- Produces: `run_heartbeat` fires at most one wake/beat with priority `breach > movement`; a fresh movement wake uses `trigger="movement"`, is budget-gated, and disarms `move_armed` on all spiked positions when it (or a breach) fires. Klines fetch is failure-isolated (missing method / network error ⇒ movement skipped that beat).

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_runtime.py`

```python
class FakeMarketMove:
    """Heartbeat market with klines: price flat for equity, klines drive the 1h move."""
    def __init__(self, price, closes, symbols=None):
        self._price, self._closes, self._symbols = price, closes, symbols or ["BTCUSDT"]
    async def get_price(self, symbol): return self._price
    async def get_top_symbols(self, quote, n): return self._symbols
    async def get_universe_snapshot(self, symbols):
        return [CoinSnapshot(s, self._price, Decimal("0")) for s in symbols]
    async def get_klines(self, symbol, interval, limit):
        return list(self._closes)                       # [old, ..., now]


def _move_agent(db_session):
    """Agent with thresholds disabled (no breach) holding BTCUSDT."""
    a = Agent(name="M", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("0"))
    db_session.add(a); db_session.commit()
    db_session.add(Position(agent_id=a.id, symbol="BTCUSDT", quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    return a


async def test_movement_fresh_triggers_and_disarms(db_session):
    agent = _move_agent(db_session)
    market = FakeMarketMove(price=Decimal("100"), closes=[Decimal("100"), Decimal("107")])  # +7%
    calls = []
    async def fake_trigger(session, agent, market, symbols, *, wake_reason=None, trigger=None):
        calls.append((wake_reason, trigger)); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert len(calls) == 1 and calls[0][1] == "movement" and "BTCUSDT" in calls[0][0]
    pos = db_session.query(Position).filter_by(agent_id=agent.id).one()
    assert pos.move_armed is False
    assert db_session.query(Trade).filter_by(agent_id=agent.id).count() == 0


async def test_movement_within_band_does_not_trigger(db_session):
    agent = _move_agent(db_session)
    market = FakeMarketMove(price=Decimal("100"), closes=[Decimal("100"), Decimal("103")])  # +3% < 5%
    calls = []
    async def fake_trigger(*a, **k): calls.append(1); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert calls == []


async def test_movement_disarmed_does_not_retrigger_then_rearms(db_session):
    agent = _move_agent(db_session)
    pos = db_session.query(Position).filter_by(agent_id=agent.id).one()
    pos.move_armed = False; db_session.commit()
    spiking = FakeMarketMove(price=Decimal("100"), closes=[Decimal("100"), Decimal("107")])  # still +7%
    async def fake_trigger(*a, **k): return True
    await run_heartbeat(db_session, agent, spiking, trigger_decision=fake_trigger)
    db_session.refresh(pos); assert pos.move_armed is False            # stays disarmed while spiking
    calm = FakeMarketMove(price=Decimal("100"), closes=[Decimal("100"), Decimal("101")])     # +1%
    await run_heartbeat(db_session, agent, calm, trigger_decision=fake_trigger)
    db_session.refresh(pos); assert pos.move_armed is True             # re-armed when back in band


async def test_breach_takes_priority_over_movement(db_session):
    agent = _armed_agent(db_session)                                   # stop 0.10 / take 0.20
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT", quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    market = FakeMarketMove(price=Decimal("85"), closes=[Decimal("100"), Decimal("85")])  # -15%: breach AND move
    calls = []
    async def fake_trigger(session, agent, market, symbols, *, wake_reason=None, trigger=None):
        calls.append((wake_reason, trigger)); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert len(calls) == 1 and calls[0][1] is None and "stop" in calls[0][0]   # breach path (no trigger kwarg)
    pos = db_session.query(Position).filter_by(agent_id=agent.id).one()
    assert pos.breach_armed is False and pos.move_armed is False        # both disarmed by the one review


async def test_movement_suppressed_when_budget_exhausted(db_session):
    from app.db.models import DecisionRecord
    agent = _move_agent(db_session)
    for _ in range(2):                                                  # 2 recent movement wakes = budget
        r = DecisionRecord(agent_id=agent.id, cycle_id="c", kind="decision", trigger="movement",
                           system_prompt="s", user_prompt="u", raw_response="r", parsed_output="{}",
                           parse_status="ok", model_provider="openrouter", model_name="m", latency_ms=1)
        db_session.add(r)
    db_session.commit()
    market = FakeMarketMove(price=Decimal("100"), closes=[Decimal("100"), Decimal("108")])  # +8%
    calls = []
    async def fake_trigger(*a, **k): calls.append(1); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert calls == []                                                  # deferred
    pos = db_session.query(Position).filter_by(agent_id=agent.id).one()
    assert pos.move_armed is True                                       # NOT disarmed → retries next beat


async def test_movement_klines_error_isolated(db_session):
    """A market without get_klines (or one that raises) must not break the beat; movement skipped."""
    agent = _move_agent(db_session)
    market = FakeMarketHB(price=Decimal("100"))                         # has no get_klines
    calls = []
    async def fake_trigger(*a, **k): calls.append(1); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert calls == []
    assert db_session.query(EquitySnapshot).filter_by(agent_id=agent.id).count() == 1  # beat completed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_runtime.py -k "movement or priority" -v`
Expected: FAIL — movement not detected / `trigger` kwarg unknown to default path.

- [ ] **Step 3: Implement movement in `run_heartbeat`** — replace `backend/app/agents/runtime.py:45-83` with:

```python
async def _position_move(market, symbol):
    """Signed ~window-hour price move for a symbol via klines. None if unavailable
    (missing method / network error / too few candles) — movement is discretionary
    and must never break the beat."""
    try:
        closes = await market.get_klines(symbol, "1h", settings.movement_window_hours + 1)
    except Exception:
        return None
    if not closes or len(closes) < 2:
        return None
    return movement_change(closes[0], closes[-1])


async def run_heartbeat(session, agent, market, *, trigger_decision=None) -> None:
    if trigger_decision is None:
        trigger_decision = run_decision_guarded
    positions_value = Decimal("0")
    breached_positions = []
    spiked_positions = []
    fresh_breach = None                           # (symbol, side, change_pct)
    fresh_move = None                             # (symbol, change_frac)
    for pos in list(agent.positions):
        last = await market.get_price(pos.symbol)
        positions_value += pos.quantity * last
        side = breached(pos.avg_price, last, agent.stop_loss, agent.take_profit)
        if side is None:
            if not pos.breach_armed:
                pos.breach_armed = True
        else:
            breached_positions.append(pos)
            if pos.breach_armed and fresh_breach is None:
                change_pct = (last - pos.avg_price) / pos.avg_price * Decimal("100")
                fresh_breach = (pos.symbol, side, change_pct)
        change = await _position_move(market, pos.symbol)
        if change is None:
            pass                                  # klines unavailable this beat → don't touch arm state
        elif abs(change) < settings.movement_threshold:
            if not pos.move_armed:
                pos.move_armed = True
        else:
            spiked_positions.append(pos)
            if pos.move_armed and fresh_move is None:
                fresh_move = (pos.symbol, change)
    equity = agent.cash_usd + positions_value
    session.add(EquitySnapshot(agent_id=agent.id, equity_usd=equity))
    session.commit()

    await record_benchmark_snapshot(session, agent, market)

    if fresh_breach is None and fresh_move is None:
        return
    n = universe_size(agent)
    symbols = await market.get_top_symbols("USDT", n)

    if fresh_breach is not None:
        symbol, side, change_pct = fresh_breach
        threshold = agent.stop_loss if side == "stop" else agent.take_profit
        label = "stop" if side == "stop" else "take-profit"
        wake_reason = (f"Risveglio fuori ciclo: {symbol} a {change_pct:+.2f}%, oltre la tua "
                       f"soglia di {label} {threshold * Decimal('100'):.2f}%. Rivaluta.")
        triggered = await trigger_decision(session, agent, market, symbols, wake_reason=wake_reason)
    else:
        if count_recent_event_wakes(session, agent.id) >= settings.wake_budget_per_hour:
            return                                # budget exhausted → defer (arm state untouched)
        symbol, change = fresh_move
        wake_reason = (f"Risveglio fuori ciclo: {symbol} si è mossa del "
                       f"{change * Decimal('100'):+.2f}% nell'ultima ora. Rivaluta.")
        triggered = await trigger_decision(session, agent, market, symbols,
                                           wake_reason=wake_reason, trigger="movement")

    if triggered:
        for p in breached_positions:
            p.breach_armed = False
        for p in spiked_positions:
            p.move_armed = False
        session.commit()
```

- [ ] **Step 4: Add imports** — at the top of `runtime.py`, extend the existing feeds import and add triggers:

```python
from app.feeds.query import recent_observations_for
from app.agents.triggers import movement_change, count_recent_event_wakes
```

- [ ] **Step 5: Run the full runtime suite**

Run: `cd backend && python -m pytest tests/test_runtime.py -q`
Expected: PASS — new movement tests green **and** all pre-existing breach/benchmark/LLM tests green (klines-less fakes hit the failure-isolated skip).

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/runtime.py backend/tests/test_runtime.py
git commit -m "feat(triggers): movement wake in heartbeat (budget-gated, breach-priority, failure-isolated klines)"
```

---

### Task 6: `fresh_news_for` — portfolio-relevant news bookmark match

**Model:** sonnet

**Files:**
- Modify: `backend/app/agents/triggers.py`
- Test: `backend/tests/test_triggers.py`

**Interfaces:**
- Consumes: `Observation(id, symbols_json, title, published_at)`, `Agent.positions`, `Agent.last_seen_observation_id`, `app.feeds.query._base`.
- Produces: `fresh_news_for(session, agent) -> Observation | None` — the newest `Observation` with `id > (agent.last_seen_observation_id or 0)` whose tagged base symbols intersect the agent's held base symbols. Returns `None` when the agent holds nothing, when no observation is newer than the bookmark, or when none match. Market-wide observations (`symbols_json == "[]"`) never trigger.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_triggers.py`

```python
import json
from app.db.models import Observation, Position
from app.agents.triggers import fresh_news_for


def _obs(session, title, symbols, pub_hour):
    o = Observation(source="CoinDesk", kind="news", title=title, url=title,
                    symbols_json=json.dumps(symbols), dedup_hash=title,
                    published_at=datetime(2026, 7, 3, pub_hour, 0, tzinfo=timezone.utc))
    session.add(o); session.commit()
    return o


def _holding(session, agent, symbol):
    session.add(Position(agent_id=agent.id, symbol=symbol, quantity=Decimal("1"), avg_price=Decimal("100")))
    session.commit()


def test_fresh_news_returns_newest_matching_beyond_bookmark(db_session):
    agent = _agent(db_session); _holding(db_session, agent, "BTCUSDT")
    _obs(db_session, "old btc", ["BTC"], 8)
    newest = _obs(db_session, "new btc", ["BTC"], 10)
    hit = fresh_news_for(db_session, agent)
    assert hit is not None and hit.id == newest.id


def test_fresh_news_ignores_non_held_and_marketwide(db_session):
    agent = _agent(db_session); _holding(db_session, agent, "BTCUSDT")
    _obs(db_session, "eth news", ["ETH"], 9)      # not held
    _obs(db_session, "macro", [], 9)              # market-wide → never triggers
    assert fresh_news_for(db_session, agent) is None


def test_fresh_news_respects_bookmark(db_session):
    agent = _agent(db_session); _holding(db_session, agent, "BTCUSDT")
    seen = _obs(db_session, "btc seen", ["BTC"], 8)
    agent.last_seen_observation_id = seen.id; db_session.commit()
    assert fresh_news_for(db_session, agent) is None            # nothing newer
    fresh = _obs(db_session, "btc fresh", ["BTC"], 9)
    assert fresh_news_for(db_session, agent).id == fresh.id


def test_fresh_news_none_when_no_holdings(db_session):
    agent = _agent(db_session)
    _obs(db_session, "btc news", ["BTC"], 9)
    assert fresh_news_for(db_session, agent) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_triggers.py -k fresh_news -v`
Expected: FAIL — `ImportError: cannot import name 'fresh_news_for'`.

- [ ] **Step 3: Implement** — add to `backend/app/agents/triggers.py`

```python
import json
from app.db.models import Observation
from app.feeds.query import _base

_NEWS_SCAN_LIMIT = 50


def fresh_news_for(session, agent):
    """Newest Observation past the agent's bookmark that names a held base symbol.
    None if the agent holds nothing, nothing is newer, or nothing matches.
    Market-wide (empty symbols) never triggers a wake."""
    held = {_base(p.symbol) for p in agent.positions}
    if not held:
        return None
    watermark = agent.last_seen_observation_id or 0
    rows = (session.query(Observation)
            .filter(Observation.id > watermark)
            .order_by(Observation.id.desc())
            .limit(_NEWS_SCAN_LIMIT).all())
    for r in rows:                                 # id desc → first match is newest
        syms = json.loads(r.symbols_json or "[]")
        if syms and (set(syms) & held):
            return r
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_triggers.py -k fresh_news -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/triggers.py backend/tests/test_triggers.py
git commit -m "feat(triggers): fresh_news_for portfolio-relevant news bookmark match"
```

---

### Task 7: `advance_news_watermark` + wire into the decision path

**Model:** sonnet

**Files:**
- Modify: `backend/app/agents/triggers.py`
- Modify: `backend/app/agents/runtime.py:179` (after the successful decision commit in `_run_decision_llm`)
- Test: `backend/tests/test_triggers.py`, `backend/tests/test_runtime.py`

**Interfaces:**
- Consumes: `Observation.id`, `Agent.last_seen_observation_id`.
- Produces: `advance_news_watermark(session, agent) -> None` — sets `agent.last_seen_observation_id` to the current `MAX(Observation.id)` (no-op when the table is empty). Called once after every successful decision so any decision "catches the agent up" on news it was shown.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_triggers.py`:
```python
from app.agents.triggers import advance_news_watermark


def test_advance_watermark_sets_to_max(db_session):
    agent = _agent(db_session)
    _obs(db_session, "a", ["BTC"], 8)
    newest = _obs(db_session, "b", ["ETH"], 9)
    advance_news_watermark(db_session, agent)
    assert agent.last_seen_observation_id == newest.id


def test_advance_watermark_noop_when_empty(db_session):
    agent = _agent(db_session)
    advance_news_watermark(db_session, agent)
    assert agent.last_seen_observation_id is None
```

Append to `backend/tests/test_runtime.py`:
```python
async def test_decision_advances_news_watermark(db_session):
    import json as _json
    from app.db.models import Observation
    agent = _llm_agent(db_session)
    o = Observation(source="CoinDesk", kind="news", title="btc", url="u",
                    symbols_json=_json.dumps(["BTC"]), dedup_hash="u",
                    published_at=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc))
    db_session.add(o); db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(Decision(actions=[], note="h")))
    assert agent.last_seen_observation_id == o.id


async def test_failed_decision_does_not_advance_watermark(db_session):
    import json as _json
    from app.db.models import Observation
    agent = _llm_agent(db_session)
    o = Observation(source="CoinDesk", kind="news", title="btc", url="u",
                    symbols_json=_json.dumps(["BTC"]), dedup_hash="u",
                    published_at=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc))
    db_session.add(o); db_session.commit()

    class Broken:
        async def get_universe_snapshot(self, symbols): raise RuntimeError("down")
    await run_decision(db_session, agent, Broken(), ["BTCUSDT"])
    assert agent.last_seen_observation_id is None            # error path returned before advancing
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_triggers.py -k watermark tests/test_runtime.py -k watermark -v`
Expected: FAIL — `advance_news_watermark` missing / watermark stays None after a decision.

- [ ] **Step 3: Implement the helper** — add to `backend/app/agents/triggers.py`

```python
from sqlalchemy import func


def advance_news_watermark(session, agent) -> None:
    """Mark every Observation up to now as seen by this agent (called after a decision)."""
    latest = session.query(func.max(Observation.id)).scalar()
    if latest is not None:
        agent.last_seen_observation_id = latest
```

- [ ] **Step 4: Wire into `_run_decision_llm`** — in `backend/app/agents/runtime.py`, immediately after the main decision commit (line 179, `session.commit()` that follows the decision `Event`), add:

```python
    advance_news_watermark(session, agent)
    session.commit()
```

and extend the triggers import:
```python
from app.agents.triggers import movement_change, count_recent_event_wakes, advance_news_watermark
```

- [ ] **Step 5: Run tests to verify pass + no regression**

Run: `cd backend && python -m pytest tests/test_triggers.py tests/test_runtime.py -q`
Expected: PASS — watermark tests green; existing decision tests unaffected (empty Observation table ⇒ no-op).

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/triggers.py backend/app/agents/runtime.py backend/tests/test_triggers.py backend/tests/test_runtime.py
git commit -m "feat(triggers): advance news watermark after every successful decision"
```

---

### Task 8: News wake folded into `run_heartbeat` priority

**Model:** sonnet

**Files:**
- Modify: `backend/app/agents/runtime.py` (`run_heartbeat` — add news detection + `news` branch, priority `breach > movement > news`)
- Test: `backend/tests/test_runtime.py`

**Interfaces:**
- Consumes: `fresh_news_for` (Task 6), `count_recent_event_wakes` (Task 3), watermark advance (Task 7, already fires inside the decision).
- Produces: when no breach/movement is fresh but `fresh_news_for` returns an observation, `run_heartbeat` fires a `trigger="news"` wake (budget-gated); the watermark advances inside the decision so it does not re-fire. Priority unchanged: breach first, movement second, news last.

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_runtime.py`

```python
def _news_agent_holding_btc(db_session):
    import json as _json
    from app.db.models import Observation
    a = Agent(name="N", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("0"))
    db_session.add(a); db_session.commit()
    db_session.add(Position(agent_id=a.id, symbol="BTCUSDT", quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.add(Observation(source="CoinDesk", kind="news", title="Bitcoin ETF approved", url="u1",
                               symbols_json=_json.dumps(["BTC"]), dedup_hash="u1",
                               published_at=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc)))
    db_session.commit()
    return a


async def test_news_fresh_triggers_news_wake(db_session):
    agent = _news_agent_holding_btc(db_session)
    market = FakeMarketMove(price=Decimal("100"), closes=[Decimal("100"), Decimal("101")])  # calm price
    calls = []
    async def fake_trigger(session, agent, market, symbols, *, wake_reason=None, trigger=None):
        calls.append((wake_reason, trigger)); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert len(calls) == 1 and calls[0][1] == "news" and "Bitcoin ETF approved" in calls[0][0]


async def test_news_suppressed_when_budget_exhausted(db_session):
    from app.db.models import DecisionRecord
    agent = _news_agent_holding_btc(db_session)
    for _ in range(2):
        db_session.add(DecisionRecord(agent_id=agent.id, cycle_id="c", kind="decision", trigger="news",
                       system_prompt="s", user_prompt="u", raw_response="r", parsed_output="{}",
                       parse_status="ok", model_provider="openrouter", model_name="m", latency_ms=1))
    db_session.commit()
    market = FakeMarketMove(price=Decimal("100"), closes=[Decimal("100"), Decimal("101")])
    calls = []
    async def fake_trigger(*a, **k): calls.append(1); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert calls == []                                             # deferred; watermark untouched


async def test_movement_takes_priority_over_news(db_session):
    agent = _news_agent_holding_btc(db_session)                    # holds BTC + has fresh BTC news
    market = FakeMarketMove(price=Decimal("100"), closes=[Decimal("100"), Decimal("108")])  # +8% move too
    calls = []
    async def fake_trigger(session, agent, market, symbols, *, wake_reason=None, trigger=None):
        calls.append(trigger); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert calls == ["movement"]                                   # movement chosen over news
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_runtime.py -k news -v`
Expected: FAIL — no news wake fired.

- [ ] **Step 3: Implement** — in `backend/app/agents/runtime.py` `run_heartbeat`:

Add the news lookup after `record_benchmark_snapshot(...)` and before the early-return:
```python
    news_hit = fresh_news_for(session, agent)
    if fresh_breach is None and fresh_move is None and news_hit is None:
        return
```
(Delete the old two-condition early-return.)

Extend the discretionary `else` branch so movement wins over news:
```python
    else:
        if count_recent_event_wakes(session, agent.id) >= settings.wake_budget_per_hour:
            return                                # budget exhausted → defer
        if fresh_move is not None:
            symbol, change = fresh_move
            wake_reason = (f"Risveglio fuori ciclo: {symbol} si è mossa del "
                           f"{change * Decimal('100'):+.2f}% nell'ultima ora. Rivaluta.")
            trig = "movement"
        else:
            wake_reason = (f"Risveglio fuori ciclo: notizia rilevante — "
                           f"{news_hit.title}. Rivaluta.")
            trig = "news"
        triggered = await trigger_decision(session, agent, market, symbols,
                                           wake_reason=wake_reason, trigger=trig)
```

Extend the triggers import:
```python
from app.agents.triggers import (movement_change, count_recent_event_wakes,
                                  advance_news_watermark, fresh_news_for)
```

- [ ] **Step 4: Run the full runtime suite**

Run: `cd backend && python -m pytest tests/test_runtime.py -q`
Expected: PASS — news tests green; movement/breach/priority tests still green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/runtime.py backend/tests/test_runtime.py
git commit -m "feat(triggers): news wake in heartbeat (priority breach>movement>news, budget-gated)"
```

---

### Task 9: Finalization — full suite, migration smoke, whole-branch review, tracker, memory

**Model:** controller + OPUS review

**Files:**
- Modify: `docs/superpowers/plans/2026-07-02-pipeline-v2-roadmap.md` (tracker row 5 → ✅)
- Memory update (outside repo).

- [ ] **Step 1: Full backend + frontend suites green**

Run: `cd backend && python -m pytest -q` → record the count (expect ~215 backend + the Task-added tests).
Run: `cd frontend && npm test` → expect 41 green (no frontend change this phase).

- [ ] **Step 2: Migration smoke on a throwaway SQLite** (never touches the dev DB)

```bash
cd backend && TMP=$(mktemp -d) && \
  DATABASE_URL="sqlite:///$TMP/smoke.db" alembic upgrade head && \
  DATABASE_URL="sqlite:///$TMP/smoke.db" python -c "import sqlalchemy as sa, os; e=sa.create_engine(os.environ['DATABASE_URL']); i=sa.inspect(e); cols={c['name'] for c in i.get_columns('positions')}; acols={c['name'] for c in i.get_columns('agents')}; assert 'move_armed' in cols and 'last_seen_observation_id' in acols, 'columns missing'; print('up OK')" && \
  DATABASE_URL="sqlite:///$TMP/smoke.db" alembic downgrade -1 && \
  DATABASE_URL="sqlite:///$TMP/smoke.db" python -c "import sqlalchemy as sa, os; e=sa.create_engine(os.environ['DATABASE_URL']); i=sa.inspect(e); cols={c['name'] for c in i.get_columns('positions')}; assert 'move_armed' not in cols, 'downgrade failed'; print('down OK')" && \
  rm -rf $TMP
```
Expected: `up OK` then `down OK`. Confirm `alembic heads` shows a single head.

> If SQLite rejects `drop_column` on downgrade, wrap both drops in `with op.batch_alter_table(...) as b:` and re-run.

- [ ] **Step 3: Whole-branch OPUS review** — scope `7167673..HEAD` (NOT `main...pipeline-v2`). Feed the reviewer the Global Constraints verbatim + the Minor roll-up. Confirm reviewer `tool_uses > 0` and that citations match the diff. Fix Critical/Important; log Minor to the roll-up.

- [ ] **Step 4: Update the roadmap tracker** — set row 5 to `✅ fatta su pipeline-v2 (non in main)` with the plan link, task/commit/test counts.

- [ ] **Step 5: Update memory** `build-status.md` → "FASE 5 COMPLETA", next = Fase 6 (brain a due stadi).

- [ ] **Step 6: Commit the docs**

```bash
git add docs/superpowers/plans/2026-07-02-pipeline-v2-roadmap.md
git commit -m "docs(pipeline): Fase 5 trigger engine → ✅ (tracker)"
```

---

## Self-Review

**Spec coverage (roadmap "Deciso in dettaglio" Fase 5):**
- Trigger taxonomy schedule/breach/movement/news → Task 4 (label) + Tasks 5/8 (wakes). ✓
- Movement = |~1h move| ≥ 5%, configurable, held-only, klines, edge-triggered → Tasks 1/2/5. ✓
- News = first new Observation naming a held coin, per-agent bookmark advancing after each decision → Tasks 6/7/8. ✓
- Budget = 2 news+movement/h, rolling, no new table, deferred-not-dropped, breach+schedule exempt → Tasks 3/5/8. ✓
- Orchestration in `run_heartbeat`, one wake/beat, priority breach>movement>news, explicit trigger to DecisionRecord → Tasks 5/8. ✓
- Fase-4 datetime comment closure → Task 1. ✓
- Non-goals (volume spike, universe-wide, LLM relevance) → not built; none appear in tasks. ✓

**Placeholder scan:** every code/test step carries full code; no TBD/TODO. ✓

**Type consistency:** `movement_change(first,last)->Decimal`, `count_recent_event_wakes(session,agent_id)->int`, `fresh_news_for(session,agent)->Observation|None`, `advance_news_watermark(session,agent)->None`, `trigger` kwarg on `run_decision`/`run_decision_guarded`/`_run_decision_llm`, `market.get_klines(symbol,interval,limit)->list[Decimal]` — names used identically across Tasks 2-8. ✓
