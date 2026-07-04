# Memoria a journal (Pipeline v2 — Fase 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn agent memory from an LLM-rewritten blob into an append-only journal — reflection *adds* timestamped entries instead of overwriting, a periodic LLM distillation pass compacts a section when it exceeds its cap, and the decision prompt keeps receiving the exact same compact view it sees today.

**Architecture:** A new append-only table `MemoryEntry` (many rows per `(agent_id, section)`, each row one one-line entry with `created_at`, `cycle_id`, `active`) replaces the single-blob `AgentMemory`. A new DB-access module `app/brain/journal.py` owns all journal reads/writes (append with dedup, active-entry queries, the derived compact view, and the distillation apply that soft-supersedes old entries). `app/brain/memory.py` stays pure (prompt-building + parsing) and gains an *append*-style reflection contract plus a new *distillation* LLM call; both are recorded as `DecisionRecord`s (Fase 1 audit). `runtime.py` orchestrates: reads the compact view for the prompt, appends reflection entries after a closed trade, then distills any over-cap section. The existing compact-view endpoint is unchanged in shape (now derived from the journal); a thin new endpoint + React timeline expose the raw journal.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (typed `Mapped`), Pydantic v2, Alembic, pytest (SQLite in-memory via `conftest.db_session`); frontend React 19 + Vitest/testing-library. LLM calls go through the existing `ProviderAdapter.complete_json` (injected in tests, never hit for real).

## Global Constraints

- **Branch:** all work continues on the long-lived `pipeline-v2` branch. Never commit to `main`, never push, no PR until the user explicitly asks. (Auto-deploy runs on push to `main`; nothing reaches prod until the final merge — intended, paper trading.)
- **Alembic head is `5adb80d611b1`** (`eval_harness_tables`). This plan adds **two** migrations, chained: migration #1 (`down_revision = '5adb80d611b1'`) creates `memory_entries` + backfills; migration #2 (`down_revision = <migration #1 id>`) drops `agent_memory`.
- **Tests never run migrations** — `conftest.db_session` builds tables with `Base.metadata.create_all`. A new/removed model is testable the moment `app/db/models.py` changes. Each migration is a hand-written mirror, verified separately against a throwaway SQLite DB (SQLite does **not** enforce FKs by default, so raw-SQL seeding needs no parent `agents` row).
- **Match existing style:** long-text columns use bare `String` (no length), like `Event.message`. Timestamps are `DateTime(timezone=True), default=_now` (Python-side default; every insert goes through the ORM). Booleans mirror `Position.breach_armed` (`Boolean, nullable=False, default=True`). `cycle_id` mirrors `Event.cycle_id` (`String(32), index=True, nullable=True`).
- **Auth:** reads use `_: str = Depends(require_viewer_or_admin)`; ORM rows serialize directly through a plain-`BaseModel` `response_model` (proven by `get_events`/`get_decisions`/`get_benchmarks`).
- **Prompt format is frozen (committente decision):** the decision prompt must keep receiving a `MemoryView` (`coin_theses`/`trade_lessons`/`strategy_notes` as newline-joined strings). The journal is internal; the view the LLM sees stays compact and identically-shaped.
- **Reflection stays closed-trade-only** (committente decision): no reflection on HOLD cycles in v1. Distillation runs inside the same closed-trade path, never as a separate scheduler job.
- **Distillation is by recency** (committente decision): utility-based criteria are v2. The compact view shows the most-recent `cap` active entries per section.
- **Retention:** keep everything — superseded entries are marked `active=False`, never deleted (the journal is the audit trail; that is the whole point of Fase 3). No pruning.
- **Design decisions locked with committente (2026-07-03):** (1) new `MemoryEntry` table, backfill existing memory, retire `AgentMemory`; (2) cap by entry count, distill inside the reflection path, record the distillation LLM call as a `DecisionRecord`; (3) compact view derived from the journal (no separate distilled blob); (4) per-entry metadata = `section` + `content` + `created_at` + `cycle_id` + `active`; (5) dashboard = journal read endpoint first, then a thin timeline panel.

## Branch & Setup

Before Task 1:

```bash
cd /Users/seb/Dev/gorillaradio/crypto-bot
git switch pipeline-v2                              # already exists; Fasi 1–2 are here
git status                                          # expect: clean
source backend/.venv/bin/activate                  # or use backend/.venv/bin/<tool> explicitly
cd backend && python -m pytest -q                   # sanity: 173 green before we start
cd ../frontend && npx vitest run                     # sanity: 39 green
```

Baseline: **173 backend tests green**, **39 frontend tests green**, Alembic head `5adb80d611b1`, working tree clean.

---

## Part A — Journal foundation (additive; `agent_memory` untouched, both tables coexist)

### Task 1: `MemoryEntry` model + migration #1 (create + backfill)

**Files:**
- Modify: `backend/app/db/models.py` (append `MemoryEntry`; keep `AgentMemory`)
- Create: `backend/alembic/versions/<generated>_memory_entries.py`
- Test: `backend/tests/test_models.py` (append two tests)

**Interfaces:**
- Produces `app.db.models.MemoryEntry`: `id:int, agent_id:int(FK agents.id, indexed), section:str(40), content:str, cycle_id:str(32)|None(indexed), active:bool(default True), created_at:datetime(default _now, indexed)`. **No** unique constraint (append-only, many rows per section).

- [ ] **Step 1: Write the failing model tests**

Append to `backend/tests/test_models.py` (the file already imports `Agent`; `datetime, timezone, timedelta, Decimal` are imported at the top):

```python
def test_memory_entry_persists_with_defaults(db_session):
    from app.db.models import MemoryEntry
    agent = Agent(name="J", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    row = MemoryEntry(agent_id=agent.id, section="coin_theses", content="BTC: bull")
    db_session.add(row); db_session.commit(); db_session.refresh(row)
    assert row.id is not None and row.created_at is not None
    assert row.active is True                       # default active
    assert row.cycle_id is None                     # nullable


def test_memory_entry_allows_many_rows_per_section(db_session):
    from app.db.models import MemoryEntry
    agent = Agent(name="J2", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    db_session.add_all([
        MemoryEntry(agent_id=agent.id, section="coin_theses", content="BTC: bull", cycle_id="c1"),
        MemoryEntry(agent_id=agent.id, section="coin_theses", content="ETH: flat", cycle_id="c1"),
    ])
    db_session.commit()                              # no unique constraint → both persist
    assert db_session.query(MemoryEntry).filter_by(agent_id=agent.id, section="coin_theses").count() == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_models.py -q`
Expected: FAIL with `ImportError: cannot import name 'MemoryEntry'`.

- [ ] **Step 3: Add the model**

Append to `backend/app/db/models.py` (imports already include `Boolean`, `Integer`, `String`, `DateTime`, `ForeignKey`; `_now` is defined at the top):

```python
class MemoryEntry(Base):
    __tablename__ = "memory_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    section: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(String)
    cycle_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_models.py -q`
Expected: PASS (existing model tests + the two new ones).

- [ ] **Step 5: Generate the migration skeleton**

Run: `cd backend && python -m alembic revision -m "memory_entries create and backfill"`
Expected: creates `backend/alembic/versions/<hash>_memory_entries_create_and_backfill.py` with `down_revision = '5adb80d611b1'` prefilled. Note the generated `<hash>` — Task 4's migration will chain onto it.

- [ ] **Step 6: Fill in the migration (DDL + backfill; does NOT drop `agent_memory`)**

Replace the generated `upgrade()`/`downgrade()` bodies. The backfill splits each existing `agent_memory` blob into one `memory_entries` row per non-empty line, preserving order (insertion order → ascending `id`) and stamping `created_at` from the blob's `updated_at`:

```python
def upgrade() -> None:
    op.create_table(
        "memory_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("section", sa.String(length=40), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("cycle_id", sa.String(length=32), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_memory_entries_agent_id", "memory_entries", ["agent_id"])
    op.create_index("ix_memory_entries_cycle_id", "memory_entries", ["cycle_id"])
    op.create_index("ix_memory_entries_created_at", "memory_entries", ["created_at"])

    # Backfill: one entry per non-empty line of each existing agent_memory blob.
    memory = sa.table(
        "agent_memory",
        sa.column("agent_id", sa.Integer),
        sa.column("section", sa.String),
        sa.column("content", sa.String),
        sa.column("updated_at", sa.DateTime),
    )
    entries = sa.table(
        "memory_entries",
        sa.column("agent_id", sa.Integer),
        sa.column("section", sa.String),
        sa.column("content", sa.String),
        sa.column("cycle_id", sa.String),
        sa.column("active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
    )
    conn = op.get_bind()
    for row in conn.execute(sa.select(memory)):
        for line in (row.content or "").split("\n"):
            line = line.strip()
            if not line:
                continue
            conn.execute(entries.insert().values(
                agent_id=row.agent_id, section=row.section, content=line,
                cycle_id=None, active=True, created_at=row.updated_at))


def downgrade() -> None:
    op.drop_index("ix_memory_entries_created_at", table_name="memory_entries")
    op.drop_index("ix_memory_entries_cycle_id", table_name="memory_entries")
    op.drop_index("ix_memory_entries_agent_id", table_name="memory_entries")
    op.drop_table("memory_entries")
```

- [ ] **Step 7: Smoke-test the migration up/down with seeded data**

SQLite ignores the FK, so we can seed `agent_memory` directly (no `agents` row needed). `char(10)` builds a two-line blob:

```bash
cd backend && rm -f _mig_smoke.db
DATABASE_URL="sqlite:///./_mig_smoke.db" python -m alembic upgrade 5adb80d611b1
sqlite3 _mig_smoke.db "INSERT INTO agent_memory (agent_id, section, content, updated_at) VALUES (1, 'coin_theses', 'BTC: bull' || char(10) || 'ETH: flat', '2026-07-01 00:00:00');"
DATABASE_URL="sqlite:///./_mig_smoke.db" python -m alembic upgrade head
echo '--- memory_entries after backfill (expect 2 rows, active=1) ---'
sqlite3 _mig_smoke.db "SELECT section, content, active FROM memory_entries ORDER BY id;"
DATABASE_URL="sqlite:///./_mig_smoke.db" python -m alembic downgrade -1
echo '--- agent_memory still intact after downgrade ---'
sqlite3 _mig_smoke.db "SELECT count(*) FROM agent_memory;"
rm -f _mig_smoke.db
```

Expected: `upgrade head` ends with `Running upgrade 5adb80d611b1 -> <hash>, memory_entries create and backfill`; the SELECT prints exactly two rows — `coin_theses|BTC: bull|1` and `coin_theses|ETH: flat|1`; `downgrade` runs cleanly and `agent_memory` count is `1`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/*_memory_entries_create_and_backfill.py backend/tests/test_models.py
git commit -m "feat(db): MemoryEntry append-only journal table + migration (create + backfill from agent_memory)"
```

---

### Task 2: `app/brain/journal.py` — journal DB helpers + derived compact view

**Files:**
- Create: `backend/app/brain/journal.py`
- Test: `backend/tests/test_journal.py`

**Interfaces:**
- Consumes: `app.db.models.MemoryEntry`; `app.brain.context.MemoryView`.
- Produces module constants `SECTIONS: tuple[str, str, str] = ("coin_theses", "trade_lessons", "strategy_notes")` and `SECTION_CAPS: dict[str, int] = {"coin_theses": 8, "trade_lessons": 10, "strategy_notes": 5}`.
- Produces `append_entries(session, agent_id: int, section: str, contents: list[str], cycle_id: str | None = None) -> list[MemoryEntry]` — inserts one active row per non-blank, non-duplicate content (exact-match dedup against currently-active entries of that section); returns the rows it added.
- Produces `active_entries(session, agent_id: int, section: str) -> list[MemoryEntry]` — active rows, oldest-first (`created_at asc, id asc`).
- Produces `active_count(session, agent_id: int, section: str) -> int`.
- Produces `compact_view(session, agent_id: int) -> MemoryView` — for each section, the **most-recent `SECTION_CAPS[section]` active entries** (chronological in the output), joined by `"\n"`. This is the frozen decision-prompt view and the hard upper bound on prompt size.
- Produces `apply_distillation(session, agent_id: int, section: str, compacted: list[str], cycle_id: str | None = None) -> None` — marks every currently-active entry of the section `active=False`, then inserts the `compacted` lines as new active entries (soft-supersede: nothing is deleted).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_journal.py`:

```python
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.db.models import Agent, MemoryEntry
from app.brain import journal


def _agent(session):
    a = Agent(name="J", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("100"))
    session.add(a); session.commit()
    return a


def test_append_entries_inserts_active_rows_with_cycle(db_session):
    a = _agent(db_session)
    added = journal.append_entries(db_session, a.id, "coin_theses", ["BTC: bull", "ETH: flat"], cycle_id="c1")
    db_session.commit()
    assert len(added) == 2
    rows = journal.active_entries(db_session, a.id, "coin_theses")
    assert [r.content for r in rows] == ["BTC: bull", "ETH: flat"]   # oldest-first
    assert all(r.active and r.cycle_id == "c1" for r in rows)


def test_append_entries_skips_blank_and_exact_duplicates(db_session):
    a = _agent(db_session)
    journal.append_entries(db_session, a.id, "coin_theses", ["BTC: bull"], cycle_id="c1")
    db_session.commit()
    added = journal.append_entries(db_session, a.id, "coin_theses",
                                   ["BTC: bull", "  ", "BTC: bear"], cycle_id="c2")
    db_session.commit()
    assert [r.content for r in added] == ["BTC: bear"]               # dup + blank dropped
    assert journal.active_count(db_session, a.id, "coin_theses") == 2


def test_compact_view_joins_active_entries_per_section(db_session):
    a = _agent(db_session)
    journal.append_entries(db_session, a.id, "coin_theses", ["BTC: bull", "ETH: flat"])
    journal.append_entries(db_session, a.id, "strategy_notes", ["patient"])
    db_session.commit()
    view = journal.compact_view(db_session, a.id)
    assert view.coin_theses == "BTC: bull\nETH: flat"
    assert view.strategy_notes == "patient"
    assert view.trade_lessons == ""                                  # empty section → empty string


def test_compact_view_caps_to_most_recent_n(db_session):
    a = _agent(db_session)
    cap = journal.SECTION_CAPS["strategy_notes"]                     # 5
    journal.append_entries(db_session, a.id, "strategy_notes",
                           [f"note{i}" for i in range(cap + 3)])      # 8 entries
    db_session.commit()
    lines = journal.compact_view(db_session, a.id).strategy_notes.split("\n")
    assert len(lines) == cap                                         # capped at 5
    assert lines[0] == "note3" and lines[-1] == "note7"              # the most-recent 5, chronological


def test_apply_distillation_supersedes_old_and_inserts_compacted(db_session):
    a = _agent(db_session)
    journal.append_entries(db_session, a.id, "strategy_notes", ["old1", "old2", "old3"], cycle_id="c1")
    db_session.commit()
    journal.apply_distillation(db_session, a.id, "strategy_notes", ["merged"], cycle_id="c2")
    db_session.commit()
    active = journal.active_entries(db_session, a.id, "strategy_notes")
    assert [r.content for r in active] == ["merged"]                 # only the compacted line is active
    superseded = db_session.query(MemoryEntry).filter_by(
        agent_id=a.id, section="strategy_notes", active=False).count()
    assert superseded == 3                                           # nothing deleted, old rows kept
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_journal.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.brain.journal'`.

- [ ] **Step 3: Implement the module**

Create `backend/app/brain/journal.py`:

```python
from app.db.models import MemoryEntry
from app.brain.context import MemoryView

SECTIONS = ("coin_theses", "trade_lessons", "strategy_notes")
SECTION_CAPS = {"coin_theses": 8, "trade_lessons": 10, "strategy_notes": 5}


def _active_q(session, agent_id: int, section: str):
    return (session.query(MemoryEntry)
            .filter_by(agent_id=agent_id, section=section, active=True)
            .order_by(MemoryEntry.created_at.asc(), MemoryEntry.id.asc()))


def append_entries(session, agent_id: int, section: str, contents: list[str],
                   cycle_id: str | None = None) -> list[MemoryEntry]:
    seen = {e.content for e in _active_q(session, agent_id, section).all()}
    added: list[MemoryEntry] = []
    for raw in contents:
        content = raw.strip()
        if not content or content in seen:
            continue
        row = MemoryEntry(agent_id=agent_id, section=section, content=content,
                          cycle_id=cycle_id, active=True)
        session.add(row)
        added.append(row)
        seen.add(content)
    return added


def active_entries(session, agent_id: int, section: str) -> list[MemoryEntry]:
    return _active_q(session, agent_id, section).all()


def active_count(session, agent_id: int, section: str) -> int:
    return _active_q(session, agent_id, section).count()


def compact_view(session, agent_id: int) -> MemoryView:
    def text(section: str) -> str:
        rows = _active_q(session, agent_id, section).all()
        cap = SECTION_CAPS[section]
        recent = rows[-cap:] if len(rows) > cap else rows      # most-recent N, chronological
        return "\n".join(e.content for e in recent)
    return MemoryView(coin_theses=text("coin_theses"),
                      trade_lessons=text("trade_lessons"),
                      strategy_notes=text("strategy_notes"))


def apply_distillation(session, agent_id: int, section: str, compacted: list[str],
                       cycle_id: str | None = None) -> None:
    for e in _active_q(session, agent_id, section).all():
        e.active = False
    for raw in compacted:
        content = raw.strip()
        if content:
            session.add(MemoryEntry(agent_id=agent_id, section=section, content=content,
                                    cycle_id=cycle_id, active=True))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_journal.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/brain/journal.py backend/tests/test_journal.py
git commit -m "feat(brain): journal.py — append/active/compact_view/apply_distillation over MemoryEntry"
```

---

## Part B — Cutover to the journal

> **Delicate integration point.** Task 3 flips the reflection contract *and* the memory read path in one atomic step (Fase 1 lesson: a contract flip that touches injected fakes is one step, never two). Reflection's output changes from a full rewrite to a set of additions, `ReflectionResult` changes shape, `build_agent_context`/`get_memory` switch to the journal, and every fake/seed in the memory tests migrates — all together, RED → wire+migrate → GREEN. Review this task on **opus**.

### Task 3: reflection appends to the journal; context + endpoint read the journal

**Files:**
- Modify: `backend/app/brain/memory.py` (append-semantics prompt; `ReflectionResult` carries `entries`; drop `enforce_caps`, `run_reflection`, `CAP_*`)
- Modify: `backend/app/agents/runtime.py` (`build_agent_context` → `compact_view`; reflection block appends; drop `_persist_memory`)
- Modify: `backend/app/api/routes.py` (`get_memory` → `compact_view`)
- Modify: `backend/tests/test_brain_memory.py`, `backend/tests/test_runtime.py`, `backend/tests/test_api.py`, `backend/tests/test_preview.py` (migrate seeds/fakes/asserts to the journal)

**Interfaces:**
- Consumes: `app.brain.journal.{SECTIONS, append_entries, compact_view}` (Task 2).
- Produces (memory.py): `MemoryUpdate` (unchanged 3-list shape, now meaning "entries to add"); `build_reflection_prompt(memory: MemoryView, closed: list[ClosedTrade], held_symbols: list[str], instructions: str) -> tuple[str, str]` (same signature, append wording, no cap tokens); `parse_reflection(raw: str) -> MemoryUpdate` (unchanged); `ReflectionResult(entries: MemoryUpdate, system: str, user: str, raw: str | None, parse_status: str, latency_ms: int)`; `run_reflection_result(memory, closed, held_symbols, instructions, adapter) -> ReflectionResult`. **Removed:** `enforce_caps`, `run_reflection`, `CAP_COIN_THESES/CAP_TRADE_LESSONS/CAP_STRATEGY_NOTES`.
- Produces (runtime.py): `build_agent_context` now sets `memory = journal.compact_view(session, agent.id)`; the closed-trade block appends `rr.entries` per section (with `cycle_id`). `_persist_memory` is deleted.

- [ ] **Step 1: Rewrite the memory unit tests (RED)**

Replace the whole body of `backend/tests/test_brain_memory.py` with the append-semantics suite (drops the `enforce_caps`/`run_reflection` tests, keeps prompt/parse/result tests):

```python
from decimal import Decimal
from app.brain.context import MemoryView
from app.brain.memory import (
    ClosedTrade, MemoryUpdate, build_reflection_prompt, parse_reflection,
    run_reflection_result, ReflectionResult,
)


def test_parse_reflection_reads_json():
    raw = '{"coin_theses": ["BTC: bull"], "trade_lessons": [], "strategy_notes": ["patient"]}'
    update = parse_reflection(raw)
    assert update.coin_theses == ["BTC: bull"]
    assert update.strategy_notes == ["patient"]


def test_build_reflection_prompt_asks_for_new_entries_and_shows_memory():
    mem = MemoryView(coin_theses="BTC: old view")
    closed = [ClosedTrade("BTCUSDT", Decimal("1"), Decimal("120"), Decimal("100"), Decimal("20"))]
    system, user = build_reflection_prompt(mem, closed, ["ETHUSDT"], "be bold")
    assert "JSON" in system and "be bold" in system
    assert "new" in system.lower() and "do not repeat" in system.lower()   # append semantics
    assert "BTCUSDT" in user and "+20.00%" in user
    assert "BTC: old view" in user                    # current memory shown so the LLM won't repeat it


def test_run_reflection_result_ok_returns_new_entries():
    class FakeAdapter:
        def complete_json(self, system, user):
            return '{"coin_theses": ["BTC: bull", "ETH: flat"], "trade_lessons": ["sold early"], "strategy_notes": []}'
    r = run_reflection_result(MemoryView(), [], [], "x", FakeAdapter())
    assert r.parse_status == "ok"
    assert r.entries.coin_theses == ["BTC: bull", "ETH: flat"]
    assert r.entries.trade_lessons == ["sold early"]
    assert r.raw and r.system and r.user and r.latency_ms >= 0


def test_run_reflection_result_parse_failure_yields_empty_entries():
    class FakeAdapter:
        def complete_json(self, system, user): return "not json"
    r = run_reflection_result(MemoryView(coin_theses="keep me"), [], [], "x", FakeAdapter())
    assert r.parse_status == "failed"
    assert r.entries == MemoryUpdate()                # nothing to append on failure
    assert r.raw == "not json"


def test_run_reflection_result_provider_error_is_failed():
    class FakeAdapter:
        def complete_json(self, system, user): raise RuntimeError("down")
    r = run_reflection_result(MemoryView(coin_theses="keep me"), [], [], "x", FakeAdapter())
    assert r.parse_status == "failed"
    assert r.raw is None
    assert r.entries == MemoryUpdate()
```

- [ ] **Step 2: Run the memory tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_brain_memory.py -q`
Expected: FAIL — `ImportError` (test no longer imports `enforce_caps`/`run_reflection`, but `ReflectionResult` still has no `entries` field / prompt lacks the new wording).

- [ ] **Step 3: Rewrite `memory.py` for append semantics**

Replace the top of `backend/app/brain/memory.py` — the `CAP_*` constants and `_REFLECT_SYSTEM` through the end of `run_reflection_result` — with:

```python
import json
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from pydantic import BaseModel
from app.brain.context import MemoryView


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
The agent just closed one or more trades. Add NEW journal entries capturing what you learned.
Output ONLY a JSON object of this exact shape:
{{"coin_theses": ["<SYMBOL: one-line updated view>", ...],
  "trade_lessons": ["<one-line lesson from a closed trade>", ...],
  "strategy_notes": ["<one-line observation about the agent's own behaviour>", ...]}}
Output ONLY genuinely new entries prompted by these outcomes. Do NOT repeat entries already present
in the current memory shown below; return an empty list for a section that has nothing new.
One short line per item. Output JSON only, no prose.

The agent's operator instructions:
{instructions}"""


def build_reflection_prompt(memory: MemoryView, closed: list[ClosedTrade],
                            held_symbols: list[str], instructions: str) -> tuple[str, str]:
    system = _REFLECT_SYSTEM.format(instructions=instructions or "(none provided)")
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


@dataclass
class ReflectionResult:
    entries: MemoryUpdate
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
    except Exception:                     # provider error — nothing to append
        return ReflectionResult(MemoryUpdate(), system, user, None, "failed", int((perf_counter() - t0) * 1000))
    try:
        entries = parse_reflection(raw)
        return ReflectionResult(entries, system, user, raw, "ok", int((perf_counter() - t0) * 1000))
    except Exception:                     # unparseable — nothing to append
        return ReflectionResult(MemoryUpdate(), system, user, raw, "failed", int((perf_counter() - t0) * 1000))
```

Note: `ReflectionResult` now defaults `entries` only via its dataclass ordering — `entries` is the first, required field. (`ReflectionResult(MemoryUpdate())` is the valid no-op construction used by tests.)

- [ ] **Step 4: Run the memory tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_brain_memory.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Wire the runtime read + write paths to the journal**

In `backend/app/agents/runtime.py`:

(a) Fix imports — drop `AgentMemory` and `MemoryView`, add `journal`:

```python
from app.db.models import EquitySnapshot, Event, DecisionRecord, BenchmarkBasis, BenchmarkSnapshot
from app.trading.engine import execute_buy, execute_sell
from app.agents.strategy import breached
from app.brain import evaluate as brain_decide_default
from app.brain.context import build_context
from app.brain import journal
from app.brain.memory import run_reflection_result, ClosedTrade
from app.brain.providers import make_adapter
from app.eval.benchmarks import compute_benchmark_equities
```

(b) In `build_agent_context`, replace the `mem_rows`/`MemoryView(...)` block with the derived view:

```python
    recent = [e.message for e in (
        session.query(Event).filter_by(agent_id=agent.id)
        .order_by(Event.timestamp.desc()).limit(10).all())]

    memory = journal.compact_view(session, agent.id)
    return build_context(instructions=agent.instructions, cash_usd=agent.cash_usd,
                         holdings=holdings, universe=universe, recent_events=recent,
                         memory=memory, wake_reason=wake_reason)
```

(c) In `_run_decision_llm`, replace the reflection persistence (the `if rr.parse_status == "ok": _persist_memory(...)` branch) so it appends per section:

```python
            if rr.parse_status == "ok":
                for section in journal.SECTIONS:
                    journal.append_entries(session, agent.id, section,
                                           getattr(rr.entries, section), cycle_id=cycle_id)
                session.add(Event(agent_id=agent.id, kind="reflection", cycle_id=cycle_id,
                                  message="memoria aggiornata dopo trade chiuso"))
            else:
                session.add(Event(agent_id=agent.id, kind="reflection", cycle_id=cycle_id,
                                  message="reflection: risposta non valida, memoria invariata"))
```

and change the reflection `_record_llm_call` `parsed_output` from `json.dumps(asdict(rr.memory))` to `rr.entries.model_dump_json()`:

```python
            _record_llm_call(session, agent, cycle_id, "reflection", trigger,
                             system=rr.system, user=rr.user, raw=rr.raw,
                             parsed_output=(rr.entries.model_dump_json()
                                            if rr.parse_status == "ok" else None),
                             parse_status=rr.parse_status, latency_ms=rr.latency_ms)
```

(d) Delete the `_persist_memory` function entirely. If `asdict` is now unused, drop it from the `from dataclasses import asdict` import line (leave the line if other symbols remain; a quick `grep -n asdict backend/app/agents/runtime.py` after editing confirms — remove the import only if the grep is empty).

- [ ] **Step 6: Point the `get_memory` endpoint at the journal**

In `backend/app/api/routes.py`, replace the body of `get_memory` (keep the `AgentMemory` import for now — Task 4 removes it):

```python
@router.get("/agents/{agent_id}/memory", response_model=MemoryOut)
def get_memory(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    from app.brain.journal import compact_view
    view = compact_view(session, agent_id)
    return MemoryOut(coin_theses=view.coin_theses, trade_lessons=view.trade_lessons,
                     strategy_notes=view.strategy_notes)
```

- [ ] **Step 7: Migrate the runtime tests (seeds + fakes + asserts)**

In `backend/tests/test_runtime.py`:

(a) Import line 3 — drop `AgentMemory`, add `MemoryEntry`:

```python
from app.db.models import (Agent, Event, Position, EquitySnapshot, Trade, MemoryEntry,
                           DecisionRecord, BenchmarkBasis, BenchmarkSnapshot)
```

and add under the existing imports:

```python
from app.brain import journal
from app.brain.memory import MemoryUpdate
```

(b) `test_reflection_runs_once_on_sell_and_persists` — fake returns `entries`, assert a journal row:

```python
    calls = []
    def fake_reflect(memory, closed, held_symbols, instructions, adapter):
        calls.append(closed)
        return ReflectionResult(MemoryUpdate(coin_theses=["BTC: took profit"], trade_lessons=["green exit"]))

    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision), reflect=fake_reflect)

    assert len(calls) == 1
    assert calls[0][0].symbol == "BTCUSDT"
    assert calls[0][0].realized_pnl_pct == Decimal("20")
    rows = journal.active_entries(db_session, agent.id, "coin_theses")
    assert [r.content for r in rows] == ["BTC: took profit"]
    assert [r.cycle_id for r in rows] == [rows[0].cycle_id] and rows[0].cycle_id is not None
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="reflection").one()
    assert "memoria" in ev.message.lower()
```

(c) `test_reflection_call_is_recorded` — construct the result with `entries`:

```python
    refl = ReflectionResult(MemoryUpdate(coin_theses=["BTC: booked"]),
                            system="RSYS", user="RUSR", raw='{"coin_theses":["BTC: booked"]}',
                            parse_status="ok", latency_ms=7)
```

(the rest of that test — asserting the reflection `DecisionRecord`'s fields — is unchanged and still valid).

(d) `test_no_reflection_when_no_sell` — no-op result + assert empty journal:

```python
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision),
                       reflect=lambda *a, **k: calls.append(1) or ReflectionResult(MemoryUpdate()))
    assert calls == []
    assert db_session.query(MemoryEntry).filter_by(agent_id=agent.id).count() == 0
```

(e) `test_reflection_failure_is_isolated` — seed a journal entry, assert it survives:

```python
    agent = _llm_agent(db_session)
    journal.append_entries(db_session, agent.id, "coin_theses", ["BTC: keep"])
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    ...
    # existing memory untouched
    rows = journal.active_entries(db_session, agent.id, "coin_theses")
    assert [r.content for r in rows] == ["BTC: keep"]
```

(the event + SELL asserts in that test are unchanged).

(f) `test_build_agent_context_assembles_from_live_data` — seed via the journal:

```python
    journal.append_entries(db_session, agent.id, "coin_theses", ["BTC: bull"])
    db_session.commit()
    ...
    assert ctx.memory.coin_theses == "BTC: bull"
```

(replace the `db_session.add(AgentMemory(...))` line; `db_session.add(Position(...))` stays).

- [ ] **Step 8: Migrate the API + preview tests**

In `backend/tests/test_api.py`, `test_get_agent_memory_returns_sections` — seed a journal row (keep the `AgentMemory` import; Task 4 removes it and the delete-cascade seed):

```python
def test_get_agent_memory_returns_sections(db_session):
    from app.brain import journal
    agent = Agent(name="Mem", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    journal.append_entries(db_session, agent.id, "coin_theses", ["BTC: bull"])
    db_session.commit()
    client = _client(db_session)
    r = client.get(f"/api/agents/{agent.id}/memory")
    assert r.status_code == 200
    body = r.json()
    assert body["coin_theses"] == "BTC: bull"
    assert body["trade_lessons"] == ""
```

In `backend/tests/test_preview.py`, `test_preview_returns_three_prompts_with_real_data` — seed via the journal (replace the `AgentMemory` import with `journal` and the seed line):

```python
from app.brain import journal
# ...
    journal.append_entries(db_session, agent.id, "trade_lessons", ["cut losers"])
    db_session.commit()
```

(the assertion `"cut losers" in out["decision"]["user"]` still holds — the compact view surfaces it).

- [ ] **Step 9: Run the full backend suite to verify green**

Run: `cd backend && python -m pytest -q`
Expected: PASS — all backend tests. If `test_models.py::test_agent_memory_unique_per_section` or `test_api::test_delete_agent_*` reference `AgentMemory`, they still pass here (the model + cascade are removed in Task 4).

- [ ] **Step 10: Commit**

```bash
git add backend/app/brain/memory.py backend/app/agents/runtime.py backend/app/api/routes.py \
        backend/tests/test_brain_memory.py backend/tests/test_runtime.py \
        backend/tests/test_api.py backend/tests/test_preview.py
git commit -m "feat(memory): reflection appends journal entries; decision view derived from the journal"
```

---

### Task 4: retire `AgentMemory` (model + cascade + migration #2)

**Files:**
- Modify: `backend/app/db/models.py` (remove `AgentMemory`)
- Modify: `backend/app/api/routes.py` (delete cascade: `AgentMemory` → `MemoryEntry`; imports)
- Create: `backend/alembic/versions/<generated>_drop_agent_memory.py`
- Modify: `backend/tests/test_models.py` (remove the unique-constraint test), `backend/tests/test_api.py` (cascade seed/assert → `MemoryEntry`)

**Interfaces:**
- Consumes: `app.db.models.MemoryEntry` (Task 1).
- Produces: `AgentMemory` no longer exists anywhere in the app; deleting an agent removes its `memory_entries`; migration #2 drops `agent_memory` (downgrade recreates it and rebuilds one blob row per `(agent_id, section)` by joining active entries).

- [ ] **Step 1: Migrate the two remaining tests (RED)**

In `backend/tests/test_models.py`, delete `test_agent_memory_unique_per_section` entirely (the unique-per-section invariant no longer exists).

In `backend/tests/test_api.py`, `test_delete_agent_removes_agent_and_children` — swap the `AgentMemory` seed + assert for `MemoryEntry`:

```python
        Event(agent_id=aid, kind="decision", message="hi"),
        MemoryEntry(agent_id=aid, section="coin_theses", content="BTC: bull"),
    ])
    ...
    assert db_session.query(MemoryEntry).filter_by(agent_id=aid).count() == 0
```

and update the import on line 7 — drop `AgentMemory`, add `MemoryEntry`:

```python
from app.db.models import Agent, EquitySnapshot, Agent as AgentModel, Position, Trade, Event, MemoryEntry
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api.py::test_delete_agent_removes_agent_and_children -q`
Expected: FAIL — the delete cascade still targets `AgentMemory`, so `memory_entries` rows are not removed (`count() == 0` fails) — actually the row is orphaned; assertion fails.

- [ ] **Step 3: Remove the model and fix the cascade**

In `backend/app/db/models.py`, delete the entire `AgentMemory` class (lines defining `class AgentMemory(Base): ...`).

In `backend/app/api/routes.py`:
- Line 6 import — drop `AgentMemory`, add `MemoryEntry`:
  ```python
  from app.db.models import Agent, BenchmarkBasis, BenchmarkSnapshot, DecisionRecord, DecisionScore, EquitySnapshot, Event, MemoryEntry, Position, Trade
  ```
- In `delete_agent`, swap `AgentMemory` for `MemoryEntry` in the cascade tuple:
  ```python
  for model in (Position, Trade, EquitySnapshot, Event, MemoryEntry, DecisionRecord,
                BenchmarkBasis, BenchmarkSnapshot):
  ```

- [ ] **Step 4: Run the full backend suite to verify green**

Run: `cd backend && python -m pytest -q`
Expected: PASS — the cascade now clears `memory_entries`; no test references `AgentMemory` anymore.

- [ ] **Step 5: Generate + fill migration #2 (drop `agent_memory`)**

Run: `cd backend && python -m alembic revision -m "drop agent_memory"`
Expected: `down_revision` is prefilled with **Task 1's migration hash** (the current head). Fill the bodies (downgrade rebuilds `agent_memory` by joining active entries per section — best-effort restore):

```python
def upgrade() -> None:
    op.drop_table("agent_memory")


def downgrade() -> None:
    op.create_table(
        "agent_memory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("section", sa.String(length=40), nullable=False),
        sa.Column("content", sa.String(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "section", name="uq_agent_memory_section"),
    )
    entries = sa.table(
        "memory_entries",
        sa.column("agent_id", sa.Integer),
        sa.column("section", sa.String),
        sa.column("content", sa.String),
        sa.column("active", sa.Boolean),
        sa.column("id", sa.Integer),
    )
    memory = sa.table(
        "agent_memory",
        sa.column("agent_id", sa.Integer),
        sa.column("section", sa.String),
        sa.column("content", sa.String),
    )
    conn = op.get_bind()
    grouped: dict = {}
    for row in conn.execute(sa.select(entries).where(entries.c.active == True).order_by(entries.c.id)):  # noqa: E712
        grouped.setdefault((row.agent_id, row.section), []).append(row.content)
    for (agent_id, section), lines in grouped.items():
        conn.execute(memory.insert().values(agent_id=agent_id, section=section, content="\n".join(lines)))
```

- [ ] **Step 6: Smoke-test migration #2 up/down**

```bash
cd backend && rm -f _mig_smoke2.db
DATABASE_URL="sqlite:///./_mig_smoke2.db" python -m alembic upgrade head          # through the drop
sqlite3 _mig_smoke2.db "INSERT INTO memory_entries (agent_id, section, content, active, created_at) VALUES (1,'coin_theses','BTC: bull',1,'2026-07-01 00:00:00'),(1,'coin_theses','ETH: flat',1,'2026-07-01 00:01:00');"
DATABASE_URL="sqlite:///./_mig_smoke2.db" python -m alembic downgrade -1           # rebuild agent_memory
echo '--- agent_memory rebuilt (expect one joined blob) ---'
sqlite3 _mig_smoke2.db "SELECT section, content FROM agent_memory;"
DATABASE_URL="sqlite:///./_mig_smoke2.db" python -m alembic upgrade head           # forward again
rm -f _mig_smoke2.db
```

Expected: `upgrade head` runs the drop cleanly; after `downgrade -1` the SELECT prints `coin_theses|BTC: bull\nETH: flat` (one blob, lines joined); the re-`upgrade` runs cleanly.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models.py backend/app/api/routes.py \
        backend/alembic/versions/*_drop_agent_memory.py \
        backend/tests/test_models.py backend/tests/test_api.py
git commit -m "refactor(db): retire AgentMemory — journal is now the single source of truth"
```

---

## Part C — Distillation

### Task 5: `memory.py` distillation prompt/parse/run (pure)

**Files:**
- Modify: `backend/app/brain/memory.py` (add distillation building blocks)
- Test: `backend/tests/test_brain_memory.py` (append distillation tests)

**Interfaces:**
- Produces: `build_distillation_prompt(section: str, entries: list[str], cap: int, instructions: str) -> tuple[str, str]`; `parse_distillation(raw: str) -> list[str]` (reads `{"entries": [...]}`); `DistillationResult(entries: list[str], system: str, user: str, raw: str | None, parse_status: str, latency_ms: int)`; `run_distillation_result(section, entries, cap, instructions, adapter) -> DistillationResult`. On provider error, unparseable output, or an empty compacted list, `parse_status="failed"` and `entries` is the **original** input (caller must skip the apply). On success, `entries` is the compacted list truncated to `cap`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_brain_memory.py`:

```python
from app.brain.memory import (
    build_distillation_prompt, parse_distillation, run_distillation_result, DistillationResult,
)


def test_build_distillation_prompt_mentions_section_cap_and_entries():
    system, user = build_distillation_prompt("coin_theses", ["BTC: a", "BTC: b"], 8, "be terse")
    assert "coin_theses" in system and "8" in system and "be terse" in system
    assert "BTC: a" in user and "BTC: b" in user


def test_parse_distillation_reads_entries_list():
    assert parse_distillation('{"entries": ["one", "two"]}') == ["one", "two"]


def test_run_distillation_ok_truncates_to_cap():
    class FakeAdapter:
        def complete_json(self, system, user):
            return '{"entries": ["merged 1", "merged 2", "merged 3"]}'
    r = run_distillation_result("strategy_notes", ["a", "b", "c", "d"], 2, "x", FakeAdapter())
    assert r.parse_status == "ok"
    assert r.entries == ["merged 1", "merged 2"]       # truncated to cap=2
    assert r.raw and r.latency_ms >= 0


def test_run_distillation_provider_error_keeps_originals():
    class FakeAdapter:
        def complete_json(self, system, user): raise RuntimeError("down")
    orig = ["a", "b", "c"]
    r = run_distillation_result("coin_theses", orig, 8, "x", FakeAdapter())
    assert r.parse_status == "failed" and r.entries == orig and r.raw is None


def test_run_distillation_empty_output_is_failure():
    class FakeAdapter:
        def complete_json(self, system, user): return '{"entries": []}'
    orig = ["a", "b"]
    r = run_distillation_result("coin_theses", orig, 8, "x", FakeAdapter())
    assert r.parse_status == "failed" and r.entries == orig     # never wipe a section to nothing
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_brain_memory.py -k distillation -q`
Expected: FAIL with `ImportError: cannot import name 'build_distillation_prompt'`.

- [ ] **Step 3: Implement the distillation building blocks**

Append to `backend/app/brain/memory.py`:

```python
_DISTILL_SYSTEM = """You compact one section of an autonomous paper-trading agent's long-term memory.
You are given the current entries of the "{section}" section (oldest first). Merge and condense them
into AT MOST {cap} one-line entries, preserving the most recent and most decision-relevant information
and dropping redundancy. Never invent facts. Output ONLY a JSON object of this exact shape:
{{"entries": ["<one short line>", ...]}}
Output JSON only, no prose.

The agent's operator instructions:
{instructions}"""


def build_distillation_prompt(section: str, entries: list[str], cap: int,
                              instructions: str) -> tuple[str, str]:
    system = _DISTILL_SYSTEM.format(section=section, cap=cap,
                                    instructions=instructions or "(none provided)")
    lines = [f"Current {section} entries (oldest first):"]
    lines += [f"  - {e}" for e in entries] or ["  (none)"]
    return system, "\n".join(lines)


def parse_distillation(raw: str) -> list[str]:
    data = json.loads(raw)
    return [str(x) for x in data.get("entries", [])]


@dataclass
class DistillationResult:
    entries: list[str]
    system: str = ""
    user: str = ""
    raw: str | None = None
    parse_status: str = "ok"      # "ok" | "failed"
    latency_ms: int = 0


def run_distillation_result(section: str, entries: list[str], cap: int,
                            instructions: str, adapter) -> DistillationResult:
    system, user = build_distillation_prompt(section, entries, cap, instructions)
    t0 = perf_counter()
    try:
        raw = adapter.complete_json(system, user)
    except Exception:                     # provider error — keep the originals, do not apply
        return DistillationResult(entries, system, user, None, "failed", int((perf_counter() - t0) * 1000))
    try:
        compacted = parse_distillation(raw)
        if not compacted:                 # never wipe a section to nothing
            return DistillationResult(entries, system, user, raw, "failed", int((perf_counter() - t0) * 1000))
        return DistillationResult(compacted[:cap], system, user, raw, "ok", int((perf_counter() - t0) * 1000))
    except Exception:                     # unparseable — keep the originals
        return DistillationResult(entries, system, user, raw, "failed", int((perf_counter() - t0) * 1000))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_brain_memory.py -q`
Expected: PASS (5 reflection + 5 distillation tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/brain/memory.py backend/tests/test_brain_memory.py
git commit -m "feat(memory): distillation prompt/parse/run (compact a section to <= cap, keep originals on failure)"
```

---

### Task 6: runtime distills over-cap sections after reflection

**Files:**
- Modify: `backend/app/agents/runtime.py` (inject `distill`; distill over-cap sections in the closed-trade block)
- Test: `backend/tests/test_runtime.py` (three distillation tests)

**Interfaces:**
- Consumes: `app.brain.journal.{SECTIONS, SECTION_CAPS, active_count, active_entries, apply_distillation}`; `app.brain.memory.run_distillation_result`.
- Produces: `run_decision(..., distill=run_distillation_result)`, `run_decision_guarded(..., distill=run_distillation_result)`, `_run_decision_llm(..., distill, ...)`. After appending reflection entries, for each section whose `active_count > SECTION_CAPS[section]` it calls `distill(section, [contents], cap, agent.instructions, adapter)`, records it as a `DecisionRecord` (`kind="distillation"`), and on success calls `journal.apply_distillation(...)` + writes a `reflection`-kind event `f"memoria distillata: {section}"`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_runtime.py` (imports from Task 3 already include `journal` and `MemoryUpdate`):

```python
def _sell_setup(db_session):
    """An agent holding BTCUSDT with a FakeMarketLLM that sells it (→ triggers reflection)."""
    agent = _llm_agent(db_session)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("2"))]
    market = FakeMarketLLM(snap, Decimal("120"), (Decimal("120"), Decimal("121")))
    decision = Decision(actions=[Action(type="SELL", symbol="BTCUSDT", fraction=Decimal("1"))], note="exit")
    return agent, market, decision


async def test_distillation_runs_when_section_over_cap(db_session):
    agent, market, decision = _sell_setup(db_session)
    cap = journal.SECTION_CAPS["strategy_notes"]                 # 5
    journal.append_entries(db_session, agent.id, "strategy_notes", [f"note{i}" for i in range(cap)])
    db_session.commit()

    # reflection adds one strategy note → 6 active > cap 5 → distillation fires for that section
    def fake_reflect(*a, **k):
        return ReflectionResult(MemoryUpdate(strategy_notes=["note-new"]))
    seen = {}
    def fake_distill(section, entries, cap_, instructions, adapter):
        seen[section] = list(entries)
        return DistillationResult(["merged"], parse_status="ok")

    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision),
                       reflect=fake_reflect, distill=fake_distill)

    assert "strategy_notes" in seen and len(seen["strategy_notes"]) == 6      # saw all active before compaction
    active = journal.active_entries(db_session, agent.id, "strategy_notes")
    assert [r.content for r in active] == ["merged"]                          # compacted set is now active
    assert db_session.query(MemoryEntry).filter_by(agent_id=agent.id, section="strategy_notes",
                                                   active=False).count() == 6  # old ones superseded, kept
    rec = db_session.query(DecisionRecord).filter_by(agent_id=agent.id, kind="distillation").one()
    assert rec.parse_status == "ok" and rec.cycle_id is not None
    ev = [e for e in db_session.query(Event).filter_by(agent_id=agent.id, kind="reflection").all()
          if "distillata" in e.message]
    assert len(ev) == 1 and "strategy_notes" in ev[0].message


async def test_distillation_skipped_when_under_cap(db_session):
    agent, market, decision = _sell_setup(db_session)
    def fake_reflect(*a, **k):
        return ReflectionResult(MemoryUpdate(strategy_notes=["just one"]))
    calls = []
    def fake_distill(*a, **k):
        calls.append(1); return DistillationResult(["x"], parse_status="ok")
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision),
                       reflect=fake_reflect, distill=fake_distill)
    assert calls == []                                                        # 1 entry, never over cap
    assert db_session.query(DecisionRecord).filter_by(agent_id=agent.id, kind="distillation").count() == 0


async def test_distillation_failure_leaves_entries_and_records_failed(db_session):
    agent, market, decision = _sell_setup(db_session)
    cap = journal.SECTION_CAPS["strategy_notes"]
    journal.append_entries(db_session, agent.id, "strategy_notes", [f"note{i}" for i in range(cap)])
    db_session.commit()
    def fake_reflect(*a, **k):
        return ReflectionResult(MemoryUpdate(strategy_notes=["note-new"]))
    def boom_distill(section, entries, cap_, instructions, adapter):
        return DistillationResult(list(entries), parse_status="failed")       # keep originals
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision),
                       reflect=fake_reflect, distill=boom_distill)
    active = journal.active_entries(db_session, agent.id, "strategy_notes")
    assert len(active) == cap + 1                                             # nothing superseded on failure
    rec = db_session.query(DecisionRecord).filter_by(agent_id=agent.id, kind="distillation").one()
    assert rec.parse_status == "failed" and rec.parsed_output is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_runtime.py -k distillation -q`
Expected: FAIL — `run_decision` has no `distill` parameter (`TypeError: unexpected keyword argument 'distill'`).

- [ ] **Step 3: Thread `distill` through and add the distillation loop**

In `backend/app/agents/runtime.py`:

(a) Import `run_distillation_result`:

```python
from app.brain.memory import run_reflection_result, run_distillation_result, ClosedTrade
```

(b) Add `distill=run_distillation_result` to the signatures of `run_decision`, `run_decision_guarded`, and `_run_decision_llm`, and pass it down:

```python
async def run_decision(session, agent, market, symbols, *, wake_reason=None,
                       brain_decide=brain_decide_default, reflect=run_reflection_result,
                       distill=run_distillation_result) -> None:
    cycle_id = uuid4().hex
    await _run_decision_llm(session, agent, market, symbols, brain_decide, reflect, distill, cycle_id, wake_reason)
```

```python
async def run_decision_guarded(session, agent, market, symbols, *, wake_reason=None,
                               brain_decide=brain_decide_default, reflect=run_reflection_result,
                               distill=run_distillation_result) -> bool:
    lock = _agent_lock(agent.id)
    if lock.locked():
        return False
    async with lock:
        await run_decision(session, agent, market, symbols, wake_reason=wake_reason,
                           brain_decide=brain_decide, reflect=reflect, distill=distill)
    return True
```

```python
async def _run_decision_llm(session, agent, market, symbols, brain_decide, reflect, distill, cycle_id: str, wake_reason=None) -> None:
```

(c) In the closed-trade block, after the reflection append + event (inside the `if rr.parse_status == "ok":` branch, right after `session.add(Event(... "memoria aggiornata..."))`), add the distillation loop:

```python
                for section in journal.SECTIONS:
                    if journal.active_count(session, agent.id, section) > journal.SECTION_CAPS[section]:
                        current = [e.content for e in journal.active_entries(session, agent.id, section)]
                        dres = distill(section, current, journal.SECTION_CAPS[section],
                                       agent.instructions, adapter)
                        _record_llm_call(session, agent, cycle_id, "distillation", trigger,
                                         system=dres.system, user=dres.user, raw=dres.raw,
                                         parsed_output=(json.dumps(dres.entries)
                                                        if dres.parse_status == "ok" else None),
                                         parse_status=dres.parse_status, latency_ms=dres.latency_ms)
                        if dres.parse_status == "ok":
                            journal.apply_distillation(session, agent.id, section, dres.entries, cycle_id=cycle_id)
                            session.add(Event(agent_id=agent.id, kind="reflection", cycle_id=cycle_id,
                                              message=f"memoria distillata: {section}"))
```

(`json` is already imported at the top of `runtime.py`.)

- [ ] **Step 4: Run the full backend suite to verify green**

Run: `cd backend && python -m pytest -q`
Expected: PASS — the three distillation tests plus every pre-existing test (the new `distill` param defaults to the real function, unused by the fakes that don't over-fill a section).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/runtime.py backend/tests/test_runtime.py
git commit -m "feat(runtime): distill any over-cap section after reflection (recorded, failure-isolated)"
```

---

## Part D — Journal dashboard (endpoint first, thin timeline)

### Task 7: `GET /agents/{id}/memory/journal` + `MemoryEntryOut`

**Files:**
- Modify: `backend/app/api/schemas.py` (add `MemoryEntryOut`)
- Modify: `backend/app/api/routes.py` (import schema; add endpoint)
- Test: `backend/tests/test_api.py` (endpoint), `backend/tests/test_auth.py` (authorization)

**Interfaces:**
- Consumes: `app.db.models.MemoryEntry`.
- Produces: `GET /agents/{agent_id}/memory/journal -> list[MemoryEntryOut]`, newest-first, capped at 100, `require_viewer_or_admin`; missing agent → `200 []`.
- Produces schema `MemoryEntryOut(section: str, content: str, cycle_id: str | None, active: bool, created_at: datetime)`.

- [ ] **Step 1: Write the failing endpoint + auth tests**

Add to `backend/tests/test_api.py` (uses the `MemoryEntry` import added in Task 4):

```python
def test_get_memory_journal_returns_entries_newest_first(db_session):
    from app.brain import journal
    agent = Agent(name="Jn", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"))
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


def test_get_memory_journal_empty_for_unknown_agent(db_session):
    client = _client(db_session)
    resp = client.get("/api/agents/9999/memory/journal")
    assert resp.status_code == 200 and resp.json() == []
```

Add to `backend/tests/test_auth.py` (mirrors `test_benchmarks_require_a_session`):

```python
def test_memory_journal_requires_a_session(client, db_session):
    assert client.get("/api/agents/1/memory/journal").status_code == 401
    db_session.add(ShareLink(token="v6")); db_session.commit()
    client.post("/api/auth/viewer", json={"token": "v6"})
    assert client.get("/api/agents/1/memory/journal").status_code == 200   # viewer can read
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api.py::test_get_memory_journal_returns_entries_newest_first tests/test_auth.py::test_memory_journal_requires_a_session -q`
Expected: FAIL with `404 Not Found` (route absent).

- [ ] **Step 3: Add the schema**

In `backend/app/api/schemas.py`, add after `MemoryOut`:

```python
class MemoryEntryOut(BaseModel):
    section: str
    content: str
    cycle_id: str | None = None
    active: bool
    created_at: datetime
```

- [ ] **Step 4: Add the endpoint**

In `backend/app/api/routes.py`, add `MemoryEntryOut` to the `app.api.schemas` import and add the endpoint after `get_memory`:

```python
@router.get("/agents/{agent_id}/memory/journal", response_model=list[MemoryEntryOut])
def get_memory_journal(agent_id: int, session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    return (
        session.query(MemoryEntry)
        .filter_by(agent_id=agent_id)
        .order_by(MemoryEntry.created_at.desc(), MemoryEntry.id.desc())
        .limit(100)
        .all()
    )
```

- [ ] **Step 5: Run the full backend suite to verify green**

Run: `cd backend && python -m pytest -q`
Expected: PASS — all backend tests including the two journal-endpoint tests + the auth test.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api.py backend/tests/test_auth.py
git commit -m "feat(api): GET /agents/{id}/memory/journal (newest-first, active + superseded)"
```

---

### Task 8: `MemoryJournal` timeline component + api fetcher

**Files:**
- Modify: `frontend/src/api.ts` (add `MemoryEntry` type + `getMemoryJournal`)
- Create: `frontend/src/components/MemoryJournal.tsx`
- Test: `frontend/src/__tests__/MemoryJournal.test.tsx`

**Interfaces:**
- Produces (api.ts): `type MemoryEntry = { section: string; content: string; cycle_id: string | null; active: boolean; created_at: string }` and `getMemoryJournal(id: number): Promise<MemoryEntry[]>` hitting `/api/agents/${id}/memory/journal`.
- Produces: `MemoryJournal({ entries }: { entries: MemoryEntry[] })` — a timeline list; superseded (`active === false`) entries are dimmed + struck-through; each row shows a section label, the content, and a localized timestamp. Empty state when `entries` is `[]`. Root has `data-testid="memory-journal"`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/MemoryJournal.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MemoryJournal } from "../components/MemoryJournal";

describe("MemoryJournal", () => {
  it("renders active and superseded entries", () => {
    render(
      <MemoryJournal
        entries={[
          { section: "coin_theses", content: "BTC+ETH: merged", cycle_id: "c2", active: true,
            created_at: "2026-07-02T00:00:00Z" },
          { section: "coin_theses", content: "BTC: bull", cycle_id: "c1", active: false,
            created_at: "2026-07-01T00:00:00Z" },
        ]}
      />,
    );
    expect(screen.getByTestId("memory-journal")).toBeInTheDocument();
    expect(screen.getByText("BTC+ETH: merged")).toBeInTheDocument();
    expect(screen.getByText("BTC: bull")).toBeInTheDocument();
  });

  it("renders an empty state when there are no entries", () => {
    render(<MemoryJournal entries={[]} />);
    expect(screen.getByTestId("memory-journal")).toBeInTheDocument();
    expect(screen.getByText(/giornale vuoto/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/MemoryJournal.test.tsx`
Expected: FAIL — cannot resolve `../components/MemoryJournal`.

- [ ] **Step 3: Add the api type + fetcher**

In `frontend/src/api.ts`, add the type after `AgentMemory` (line 40) and the fetcher after `getMemory` (line 58):

```typescript
export type MemoryEntry = {
  section: string; content: string; cycle_id: string | null; active: boolean; created_at: string;
};
```

```typescript
export const getMemoryJournal = (id: number) => get<MemoryEntry[]>(`/api/agents/${id}/memory/journal`);
```

- [ ] **Step 4: Create the component**

Create `frontend/src/components/MemoryJournal.tsx`:

```tsx
import type { MemoryEntry } from "../api";

const SECTION_LABEL: Record<string, string> = {
  coin_theses: "Tesi", trade_lessons: "Lezione", strategy_notes: "Nota",
};

export function MemoryJournal({ entries }: { entries: MemoryEntry[] }) {
  if (!entries.length) {
    return <p data-testid="memory-journal" className="text-sm text-muted-foreground">Giornale vuoto.</p>;
  }
  return (
    <ul data-testid="memory-journal" className="flex flex-col gap-1 text-sm">
      {entries.map((e, i) => (
        <li key={i} className={`flex items-baseline gap-2 ${e.active ? "" : "opacity-50 line-through"}`}>
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground shrink-0">
            {SECTION_LABEL[e.section] ?? e.section}
          </span>
          <span className="flex-1">{e.content}</span>
          <time className="text-xs text-muted-foreground shrink-0 tabular-nums">
            {new Date(e.created_at).toLocaleString()}
          </time>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/MemoryJournal.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api.ts frontend/src/components/MemoryJournal.tsx frontend/src/__tests__/MemoryJournal.test.tsx
git commit -m "feat(ui): MemoryJournal timeline (active + superseded) + api fetcher"
```

---

### Task 9: wire `MemoryJournal` into `App.tsx`

**Files:**
- Modify: `frontend/src/App.tsx` (imports; state; fetch on select; render under `MemoryPanel`)
- Verify: `frontend/src` type-check + full Vitest suite

**Interfaces:**
- Consumes: `getMemoryJournal`, `MemoryEntry` (Task 8); `MemoryJournal`.
- Produces: the selected agent's detail view renders the journal timeline right below the existing compact `MemoryPanel`, refreshed whenever `selId` changes.

- [ ] **Step 1: Add imports**

In `frontend/src/App.tsx`, extend the api import (line 3) to add `getMemoryJournal`, the types import (line 6) to add `type MemoryEntry`, and add the component import next to `MemoryPanel` (line 18):

```tsx
import { MemoryJournal } from "./components/MemoryJournal";
```

- [ ] **Step 2: Add state**

Next to `const [memory, setMemory] = useState<AgentMemory | null>(null);` (line 68), add:

```tsx
  const [journalEntries, setJournalEntries] = useState<MemoryEntry[]>([]);
```

- [ ] **Step 3: Fetch on select and reset**

Next to `setMemory(null);` (line 94) add `setJournalEntries([]);`, and next to `getMemory(selId).then(setMemory).catch(onErr);` (line 101) add:

```tsx
      getMemoryJournal(selId).then(setJournalEntries).catch(onErr);
```

- [ ] **Step 4: Render**

Immediately after the `MemoryPanel` line (line 233, `{memory ? <MemoryPanel memory={memory} /> : <p className="empty">…</p>}`), add:

```tsx
                <MemoryJournal entries={journalEntries} />
```

- [ ] **Step 5: Keep the `App.auth.test` api mock in sync**

`App.tsx` now calls `getMemoryJournal` inside the `selId` effect, and `frontend/src/__tests__/App.auth.test.tsx` mocks the whole `../api` module with an explicit object (an un-mocked fetcher would be `undefined` → the call throws a `TypeError` that `.catch` can't catch, breaking the auth tests). Add the fetcher to the mock, next to `getMemory` (line 15):

```tsx
  getMemoryJournal: vi.fn(() => Promise.resolve([])),
```

- [ ] **Step 6: Type-check and run the whole frontend suite**

Run: `cd frontend && npx tsc -b && npx vitest run`
Expected: type-check clean; all frontend tests pass (existing 39 + `MemoryJournal`'s 2).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/App.tsx frontend/src/__tests__/App.auth.test.tsx
git commit -m "feat(ui): wire MemoryJournal timeline into the agent detail view"
```

---

## Part E — Finalization

### Task 10: whole-branch review, tracker, memory

**Files:**
- Modify: `docs/superpowers/plans/2026-07-02-pipeline-v2-roadmap.md` (tracker row Fase 3)
- Modify: memory index / ledger (see steps)

- [ ] **Step 1: Full-suite green + Alembic sanity**

```bash
cd backend && python -m pytest -q
cd ../frontend && npx vitest run && npx tsc -b
cd ../backend && rm -f _head.db && DATABASE_URL="sqlite:///./_head.db" python -m alembic upgrade head && rm -f _head.db
```

Expected: backend green (~188 tests: 173 baseline − 3 removed [`enforce_caps`, `run_reflection`, `agent_memory` unique-constraint] + ~18 new [2 model, 5 journal, 5 distillation, 3 runtime-distillation, 2 journal-endpoint, 1 auth]), frontend green (~41: 39 + 2 MemoryJournal), type-check clean, `alembic upgrade head` runs both new migrations cleanly. These are estimates — record the **exact** counts from the run for the tracker note.

- [ ] **Step 2: Whole-branch review on opus**

Dispatch a `requesting-code-review` (or an opus review subagent) over the full Fase 3 diff (`git diff main...pipeline-v2 -- backend/app/brain backend/app/agents/runtime.py backend/app/db/models.py backend/app/api backend/alembic frontend/src`, plus the Fase 3 tests). Focus areas: the reflection contract flip (no stale rewrite path left), distillation failure isolation (a bad distill never wipes or shrinks a section incorrectly), the two migrations chain + backfill correctness, and that the decision prompt view is byte-for-byte the same shape as before. Resolve any ⚠ "cannot verify from diff" items yourself (you hold the cross-task context). Verify each review-subagent actually cited the diff (`tool_uses > 0`); re-dispatch on incoherent citations.

- [ ] **Step 3: Update the roadmap tracker**

In `docs/superpowers/plans/2026-07-02-pipeline-v2-roadmap.md`, set the Fase 3 row to:

```markdown
| 3 — Memoria a journal | ✅ fatta su `pipeline-v2` (non in main) | [2026-07-03-memoria-journal](2026-07-03-memoria-journal.md) | 10 task, <N> commit, <B> backend + <F> frontend verdi, 2 migration (create+backfill, drop), final review opus ready-to-merge |
```

(fill `<N>/<B>/<F>` from Step 1). Commit:

```bash
git add docs/superpowers/plans/2026-07-02-pipeline-v2-roadmap.md
git commit -m "docs(pipeline): Fase 3 tracker → ✅ (memoria a journal done on pipeline-v2)"
```

- [ ] **Step 4: Update auto-memory (Build Status)**

Update `/Users/seb/.claude/projects/-Users-seb-Dev-gorillaradio-crypto-bot/memory/build-status.md` to record Fase 3 done on `pipeline-v2` (journal append-only + distillation; not in main), next = Fase 4 (ingestion news, provider gratuiti da scegliere). Keep it to the one-fact-per-file convention; update the `MEMORY.md` pointer line if the hook text changes. (No commit — memory lives outside the repo.)

- [ ] **Step 5: Report status to the user**

Summarize: what landed, the exact test counts, that the branch is NOT merged/pushed (awaiting explicit request), and that Fase 4 is next. Do not merge or push.

---

## Self-Review

**Spec coverage (roadmap Fase 3 deliverables):**
- *`AgentMemory` diventa journal append-only: la reflection aggiunge voci (timestampate, con sezione) invece di riscrivere* → Task 1 (table) + Task 2 (`append_entries`) + Task 3 (reflection append-semantics + runtime append). ✓
- *Distillazione periodica: quando una sezione supera il cap, un passaggio LLM la compatta preservando le voci più recenti/rilevanti* → Task 2 (`apply_distillation`, recency in `compact_view`) + Task 5 (distillation LLM call, keep-recent prompt) + Task 6 (over-cap trigger, apply). ✓
- *Il prompt continua a ricevere la vista compatta (nessun cambiamento di formato lato decisione)* → `compact_view` returns the same `MemoryView` shape; `build_agent_context`/`render_prompt` unchanged downstream; the frozen-prompt constraint. Task 3. ✓
- *Distillazione per recency* → `compact_view` = most-recent-N; distillation prompt says "preserve the most recent". ✓
- *Reflection solo sui trade chiusi, niente reflection su HOLD in v1* → all memory work stays inside the existing `if closed_trades:` block; nothing added to HOLD cycles. ✓
- *Dashboard (coerente con "A tracciata" della Fase 2: prima dati/endpoint, UI sottile)* → Task 7 (endpoint) → Task 8 (component) → Task 9 (wiring). ✓
- *Chiamata LLM di distillazione registrata per audit* → Task 6 records `DecisionRecord(kind="distillation")`. ✓

**Placeholder scan:** every step contains real code/commands; no TBD / "handle errors" / "similar to Task N". ✓

**Type consistency:**
- `MemoryEntry(section, content, cycle_id, active, created_at)` — the model (Task 1), the migration DDL (Tasks 1 & 4), the journal helpers (Task 2), `MemoryEntryOut` (Task 7), and the frontend `MemoryEntry` type (Task 8) all agree on the same five fields. ✓
- `ReflectionResult.entries: MemoryUpdate` (Task 3) is read by runtime via `getattr(rr.entries, section)` (Task 3) and `rr.entries.model_dump_json()` (Task 3); the old `.memory: MemoryView` field is gone everywhere (memory.py, runtime.py, and every fake in test_runtime/test_brain_memory). ✓
- `DistillationResult.entries: list[str]` (Task 5) is consumed by `journal.apply_distillation(..., dres.entries, ...)` and `json.dumps(dres.entries)` (Task 6); on failure `entries` is the untouched input and the caller skips the apply. ✓
- `journal.SECTIONS`/`SECTION_CAPS` keys (`coin_theses`/`trade_lessons`/`strategy_notes`) match `MemoryUpdate`'s fields and the `MemoryView` fields, so `getattr(rr.entries, section)` and `compact_view`'s per-section build are total. ✓
- `compact_view(session, agent_id) -> MemoryView` (Task 2) is what `build_agent_context` (Task 3) and `get_memory` (Task 3) consume; both keep producing the exact `MemoryView`/`MemoryOut` shape the prompt + existing panel already expect. ✓
- New `DecisionRecord.kind` value `"distillation"` is a free-string column (String(20)); Fase 2's scoring + by-model queries filter `kind == "decision"`, so distillation records are correctly ignored there — no Fase 2 regression. ✓

**Authorization / destructive / business-rule coverage (user testing rules):**
- Authorization: `test_memory_journal_requires_a_session` (Task 7) — 401 without a session, 200 for viewer. ✓
- Destructive safeguards: delete cascade now clears `memory_entries` (`test_delete_agent_removes_agent_and_children`, Task 4); distillation soft-supersedes (never deletes) and `test_run_distillation_empty_output_is_failure` + `test_distillation_failure_leaves_entries_and_records_failed` prove a bad/empty distill can't wipe a section. ✓
- Business rules: append dedup (`test_append_entries_skips_blank_and_exact_duplicates`), compact-view cap (`test_compact_view_caps_to_most_recent_n`), distill only over cap (`test_distillation_skipped_when_under_cap`), reflection stays closed-trade-only (`test_no_reflection_when_no_sell`), reflection/distillation failures isolated (Tasks 3 & 6). ✓
- Data-migration safety: seeded up/down smoke tests for both migrations (Tasks 1 & 6→4) exercise the backfill and the reverse rebuild — the highest-risk piece of the phase. ✓

**Cost check:** one extra LLM call per closed-trade cycle *only* when a section is over cap (reflection is already closed-trade-only and infrequent; low-volume paper trading). Distillation triggers at `active > cap` and compacts back to `<= cap` — a full section may distill on most closed-trade cycles; this is accepted for v1 and the `>cap` trigger is the single tunable knob if cost ever matters (add headroom later — YAGNI now). No paid data, no new polling. ✓

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-03-memoria-journal.md`. It is 10 tasks across five parts (A journal foundation, B cutover, C distillation, D dashboard, E finalization). **Task 3 is the delicate atomic cutover — review it on opus.** Recommended: execute **part by part** (A → B → C → D → E) with a user checkpoint between parts, mirroring Fase 2.

Two execution styles:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, two-stage review between tasks, opus for Task 3. REQUIRED SUB-SKILL: superpowers:subagent-driven-development.
2. **Inline Execution** — execute tasks in this session with checkpoints. REQUIRED SUB-SKILL: superpowers:executing-plans.

Do not start execution until the user asks. Do not merge or push.
