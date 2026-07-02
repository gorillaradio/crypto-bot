# Soglie di rischio mediate dall'LLM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Il battito (heartbeat) smette di vendere meccanicamente sul breach di una soglia: rileva il breach e **sveglia l'LLM** per decidere; le soglie diventano configurabili per-agente.

**Architecture:** Il battito, ogni 5 min, confronta ogni posizione con le soglie *dell'agente* (`breached()`). Un breach *fresco* (posizione oltre soglia e "armata") lancia un ciclo di decisione off-cycle (riusa `run_decision`) con una nota di risveglio nel prompt, poi disarma le posizioni in breach; una posizione rientrata nella banda si ri-arma (edge-triggered). Un lock per-agente evita decisioni sovrapposte.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (Mapped/mapped_column), Alembic, Pydantic v2, APScheduler, pytest (async, SQLite in-memory), React + react-hook-form + zod (frontend).

**Spec di riferimento:** [docs/superpowers/specs/2026-07-01-soglie-rischio-llm-design.md](../specs/2026-07-01-soglie-rischio-llm-design.md)

## Global Constraints

- Soglie come **frazioni** (`0.10` = 10%). `stop_loss ∈ (0, 1)`, `take_profit ∈ (0, 5]`. Entrambe **opzionali** (`None` = soglia disattivata). Storage `Numeric(5, 4)`.
- `Position.breach_armed`: `Boolean`, `default=True`, `nullable=False`.
- Migrazione: **backfill** di *tutti* gli agenti esistenti a `stop_loss=0.10`, `take_profit=0.20` (preserva il rischio delle run in corso).
- Anti-spam = **edge-triggered per-posizione** (nessun cooldown a tempo). Sveglia quando la posizione *attraversa* la soglia mentre è armata; si ri-arma quando rientra nella banda; al risveglio si disarmano **tutte** le posizioni in breach.
- Concorrenza = **lock asincrono per-agente**, acquisizione **non bloccante**: se una decisione è già in corso per l'agente, si **salta** (senza disarmare).
- Il battito **non chiama mai** `execute_sell`. La vendita, se avviene, viene dalla `Decision` dell'LLM.
- Costanti esistenti invariate: `fee_rate=0.001`, `min_trade_usd=5`, `decision_buy_default_usd=10`, `heartbeat_seconds=300`, `decision_seconds=3600`.
- **Deviazione dallo spec (deliberata):** la sezione "Configurazione" dello spec (default in `config.py`) è **omessa** — sarebbe codice morto: il form frontend pre-riempie 10/20 e la migrazione hardcoda 0.10/0.20; le soglie sono opzionali (nessun defaulting server-side).

## Setup

- Il branch dedicato `risk-thresholds-llm` **esiste già** (spec e piano sono committati lì). Assicurati di esserci sopra: `git checkout risk-thresholds-llm`.
- Comandi backend: da `backend/`, con la venv attiva (`source .venv/bin/activate`). Test: `pytest`. Migrazioni: `alembic`.
- Comandi frontend: da `frontend/`. Typecheck/build: `npm run build`.
- I test usano SQLite in-memory (`conftest.py::db_session`) con `Base.metadata.create_all`, quindi **non** servono migrazioni per i test; la migrazione Alembic serve solo al Postgres reale.

## File Structure

| File | Responsabilità | Azione |
|------|----------------|--------|
| `backend/app/db/models.py` | `Agent.stop_loss/take_profit`, `Position.breach_armed` | Modify |
| `backend/alembic/versions/<new>.py` | migrazione additiva + backfill | Create |
| `backend/app/agents/strategy.py` | `breached()` (rileva il breach); rimuove `guardrail_action` | Modify |
| `backend/app/brain/context.py` | `DecisionContext.wake_reason`, `build_context(..., wake_reason=)` | Modify |
| `backend/app/brain/prompt.py` | rende `wake_reason` nel prompt user | Modify |
| `backend/app/agents/runtime.py` | `wake_reason` in `run_decision`; lock + `run_decision_guarded`; nuovo `run_heartbeat` | Modify |
| `backend/app/scheduler/jobs.py` | `_decision_tick` usa `run_decision_guarded` | Modify |
| `backend/app/api/schemas.py` | `AgentCreate` accetta/valida le soglie | Modify |
| `backend/app/api/routes.py` | `create_agent` passa le soglie | Modify |
| `frontend/src/api.ts` | `AgentCreateInput` con le soglie | Modify |
| `frontend/src/components/AgentFormModal.tsx` | 2 campi soglia (create only) | Modify |
| `backend/tests/*` | test nuovi + rimozione dei test obsoleti dell'heartbeat | Modify |
| `docs/pipeline.html` | aggiorna sezione Battito + diagramma + manopole | Modify |

---

### Task 1: Modello dati — soglie agente + `breach_armed` posizione + migrazione

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/<generated>.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `Agent.stop_loss: Decimal | None`, `Agent.take_profit: Decimal | None`, `Position.breach_armed: bool` (default `True`).

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_models.py` aggiungi (in cima assicurati di avere gli import `from decimal import Decimal`, `from datetime import datetime, timezone, timedelta`, `from app.db.models import Agent, Position`):

```python
def _mk_agent(session, **over):
    kw = dict(name="T", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("100"))
    kw.update(over)
    a = Agent(**kw)
    session.add(a); session.commit()
    return a


def test_agent_accepts_risk_thresholds(db_session):
    a = _mk_agent(db_session, stop_loss=Decimal("0.10"), take_profit=Decimal("0.20"))
    assert a.stop_loss == Decimal("0.10")
    assert a.take_profit == Decimal("0.20")


def test_agent_thresholds_default_none(db_session):
    a = _mk_agent(db_session)
    assert a.stop_loss is None and a.take_profit is None


def test_position_breach_armed_defaults_true(db_session):
    a = _mk_agent(db_session)
    p = Position(agent_id=a.id, symbol="BTCUSDT", quantity=Decimal("1"), avg_price=Decimal("100"))
    db_session.add(p); db_session.commit()
    assert p.breach_armed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_models.py -k "risk_thresholds or breach_armed or thresholds_default" -v`
Expected: FAIL (`TypeError: 'stop_loss' is an invalid keyword argument for Agent` / no attribute `breach_armed`).

- [ ] **Step 3: Modify the models**

In `backend/app/db/models.py`, aggiungi `Boolean` all'import SQLAlchemy:

```python
from sqlalchemy import ForeignKey, Numeric, String, DateTime, UniqueConstraint, Boolean
```

Nella classe `Agent`, dopo `model_name`, aggiungi:

```python
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
```

Nella classe `Position`, dopo `avg_price`, aggiungi:

```python
    breach_armed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_models.py -v`
Expected: PASS (tutti, inclusi quelli preesistenti).

- [ ] **Step 5: Create the Alembic migration**

Genera il file (imposta automaticamente `down_revision` all'head corrente):

Run: `cd backend && alembic revision -m "agent risk thresholds and position breach_armed"`

Apri il file generato in `backend/alembic/versions/` e scrivi `upgrade`/`downgrade` (lascia intatte le righe `revision`/`down_revision` auto-generate):

```python
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column("agents", sa.Column("stop_loss", sa.Numeric(5, 4), nullable=True))
    op.add_column("agents", sa.Column("take_profit", sa.Numeric(5, 4), nullable=True))
    op.add_column("positions", sa.Column("breach_armed", sa.Boolean(),
                                          nullable=False, server_default=sa.true()))
    # preserva il comportamento di rischio degli agenti creati sotto il guardrail hardcoded
    op.execute("UPDATE agents SET stop_loss = 0.10, take_profit = 0.20")


def downgrade() -> None:
    op.drop_column("positions", "breach_armed")
    op.drop_column("agents", "take_profit")
    op.drop_column("agents", "stop_loss")
```

- [ ] **Step 6: Verify the migration is consistent**

Run: `cd backend && alembic heads` (Expected: una sola head — quella nuova).
Se un Postgres di sviluppo è disponibile (`docker compose up -d postgres`), esegui `alembic upgrade head` e poi `alembic downgrade -1` per verificare andata/ritorno. Se non disponibile in locale, la migrazione girerà in deploy — non forzare.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/ backend/tests/test_models.py
git commit -m "feat(db): per-agent risk thresholds + position breach_armed"
```

---

### Task 2: `breached()` — rilevamento del breach

**Files:**
- Modify: `backend/app/agents/strategy.py`
- Test: `backend/tests/test_strategy.py`

**Interfaces:**
- Produces: `breached(avg_price, last_price, stop_loss, take_profit) -> str | None` (ritorna `"stop"`, `"take"` o `None`).
- Nota: `guardrail_action` resta in vita fino al Task 7 (ancora importata dal vecchio `run_heartbeat`).

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_strategy.py` aggiungi (in cima: `from app.agents.strategy import breached`):

```python
def test_breached_stop_side():
    assert breached(Decimal("100"), Decimal("85"), Decimal("0.10"), Decimal("0.20")) == "stop"


def test_breached_take_side():
    assert breached(Decimal("100"), Decimal("125"), Decimal("0.10"), Decimal("0.20")) == "take"


def test_breached_within_band():
    assert breached(Decimal("100"), Decimal("105"), Decimal("0.10"), Decimal("0.20")) is None


def test_breached_disabled_thresholds():
    assert breached(Decimal("100"), Decimal("50"), None, None) is None


def test_breached_stop_only_take_none():
    assert breached(Decimal("100"), Decimal("130"), Decimal("0.10"), None) is None


def test_breached_zero_avg_price():
    assert breached(Decimal("0"), Decimal("50"), Decimal("0.10"), Decimal("0.20")) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_strategy.py -k breached -v`
Expected: FAIL (`ImportError: cannot import name 'breached'`).

- [ ] **Step 3: Implement `breached`**

In `backend/app/agents/strategy.py`, aggiungi **sopra** `guardrail_action` (lascia `guardrail_action` invariata):

```python
def breached(avg_price: Decimal, last_price: Decimal,
             stop_loss: Decimal | None, take_profit: Decimal | None) -> str | None:
    """Ritorna "stop" | "take" | None. Soglie come frazioni (0.10 = 10%); None disattiva quel
    lato. Usata dal battito per decidere se svegliare l'LLM."""
    if avg_price <= 0:
        return None
    change = (last_price - avg_price) / avg_price
    if stop_loss is not None and change <= -stop_loss:
        return "stop"
    if take_profit is not None and change >= take_profit:
        return "take"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_strategy.py -v`
Expected: PASS (nuovi + i 3 vecchi di `guardrail_action`, ancora presenti).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/strategy.py backend/tests/test_strategy.py
git commit -m "feat(strategy): breached() threshold detector with per-agent thresholds"
```

---

### Task 3: `wake_reason` nel contesto e nel prompt

**Files:**
- Modify: `backend/app/brain/context.py`
- Modify: `backend/app/brain/prompt.py`
- Test: `backend/tests/test_brain_context.py`, `backend/tests/test_brain_prompt.py`

**Interfaces:**
- Consumes: `build_context` (esistente).
- Produces: `DecisionContext.wake_reason: str | None`; `build_context(..., wake_reason=None)`; `render_prompt` mette `wake_reason` in cima al messaggio user.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_brain_context.py` aggiungi (import: `from decimal import Decimal`, `from app.brain.context import build_context`):

```python
def test_build_context_carries_wake_reason():
    ctx = build_context(instructions="", cash_usd=Decimal("100"), holdings=[],
                        universe=[], recent_events=[], wake_reason="SOLUSDT -12%")
    assert ctx.wake_reason == "SOLUSDT -12%"


def test_build_context_wake_reason_defaults_none():
    ctx = build_context(instructions="", cash_usd=Decimal("100"), holdings=[],
                        universe=[], recent_events=[])
    assert ctx.wake_reason is None
```

In `backend/tests/test_brain_prompt.py` aggiungi (import: `from decimal import Decimal`, `from app.brain.context import build_context`, `from app.brain.prompt import render_prompt`):

```python
def test_render_prompt_surfaces_wake_reason():
    ctx = build_context(instructions="", cash_usd=Decimal("100"), holdings=[],
                        universe=[], recent_events=[],
                        wake_reason="SOLUSDT a -12.30%, oltre la tua soglia di stop")
    _system, user = render_prompt(ctx)
    assert "SOLUSDT a -12.30%, oltre la tua soglia di stop" in user


def test_render_prompt_no_wake_marker_when_none():
    ctx = build_context(instructions="", cash_usd=Decimal("100"), holdings=[],
                        universe=[], recent_events=[])
    _system, user = render_prompt(ctx)
    assert "⚠" not in user
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_brain_context.py -k wake tests/test_brain_prompt.py -k wake -v`
Expected: FAIL (`TypeError: build_context() got an unexpected keyword argument 'wake_reason'`).

- [ ] **Step 3: Add `wake_reason` to the context**

In `backend/app/brain/context.py`, nella dataclass `DecisionContext`, aggiungi come **ultimo** campo:

```python
    wake_reason: str | None = None
```

Nella firma di `build_context` aggiungi il parametro e passalo al costrutto. La firma diventa:

```python
def build_context(*, instructions, cash_usd, holdings, universe, recent_events, memory=None, wake_reason=None) -> DecisionContext:
```

e nel `return DecisionContext(...)` aggiungi `wake_reason=wake_reason,` dopo `memory=memory or MemoryView(),`.

- [ ] **Step 4: Surface it in the prompt**

In `backend/app/brain/prompt.py::render_prompt`, sostituisci la riga:

```python
    lines = [f"Cash: ${ctx.cash_usd}", f"Equity: ${ctx.equity_usd}", "", "Open positions:"]
```

con:

```python
    lines = []
    if ctx.wake_reason:
        lines += [f"⚠ {ctx.wake_reason}", ""]
    lines += [f"Cash: ${ctx.cash_usd}", f"Equity: ${ctx.equity_usd}", "", "Open positions:"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_brain_context.py tests/test_brain_prompt.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/brain/context.py backend/app/brain/prompt.py backend/tests/test_brain_context.py backend/tests/test_brain_prompt.py
git commit -m "feat(brain): wake_reason in decision context and prompt"
```

---

### Task 4: `run_decision` accetta `wake_reason` e marca l'evento off-cycle

**Files:**
- Modify: `backend/app/agents/runtime.py:27-31` (`run_decision`), `:33` (`_run_decision_llm` firma), `:54-56` (`build_context`), `:104-107` (evento decision)
- Test: `backend/tests/test_runtime.py`

**Interfaces:**
- Consumes: `DecisionContext.wake_reason` (Task 3).
- Produces: `run_decision(..., wake_reason=None)`; l'evento `decision` include "fuori ciclo" quando `wake_reason` è valorizzato.

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_runtime.py` aggiungi:

```python
async def test_run_decision_passes_wake_reason_and_marks_event(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    captured = {}

    def capture(ctx, adapter):
        captured["wake"] = ctx.wake_reason
        return Decision(actions=[], note="held")

    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       wake_reason="BTCUSDT -12% oltre stop", brain_decide=capture)
    assert captured["wake"] == "BTCUSDT -12% oltre stop"
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").one()
    assert "fuori ciclo" in ev.message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_runtime.py -k wake_reason_and_marks -v`
Expected: FAIL (`run_decision() got an unexpected keyword argument 'wake_reason'`).

- [ ] **Step 3: Thread `wake_reason` through the runtime**

In `backend/app/agents/runtime.py`, cambia `run_decision`:

```python
async def run_decision(session, agent, market, symbols, *, wake_reason=None,
                       brain_decide=brain_decide_default, reflect=run_reflection) -> None:
    cycle_id = uuid4().hex
    await _run_decision_llm(session, agent, market, symbols, brain_decide, reflect, cycle_id, wake_reason)
```

Cambia la firma di `_run_decision_llm` aggiungendo `wake_reason=None` in coda:

```python
async def _run_decision_llm(session, agent, market, symbols, brain_decide, reflect, cycle_id: str, wake_reason=None) -> None:
```

Nella chiamata a `build_context` dentro `_run_decision_llm`, aggiungi `wake_reason=wake_reason`:

```python
        ctx = build_context(instructions=agent.instructions, cash_usd=agent.cash_usd,
                            holdings=holdings, universe=universe, recent_events=recent,
                            memory=memory, wake_reason=wake_reason)
```

Sostituisci il blocco dell'evento `decision` (dopo il loop delle azioni):

```python
    note = decision.note or "(no note)"
    kind_label = "ciclo decisione fuori ciclo (LLM)" if wake_reason else "ciclo decisione (LLM)"
    session.add(Event(agent_id=agent.id, kind="decision", cycle_id=cycle_id,
                      message=f"{kind_label}: {note} — {actions} operazioni, {skipped} saltate, {errors} errori"))
```

(Il carattere `—` è un em-dash, come nell'originale: preservalo.)

- [ ] **Step 4: Run test to verify it passes + no regression**

Run: `cd backend && pytest tests/test_runtime.py -v`
Expected: PASS (nuovo + tutti i preesistenti che passano `run_decision` senza `wake_reason`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/runtime.py backend/tests/test_runtime.py
git commit -m "feat(runtime): run_decision accepts wake_reason, marks off-cycle event"
```

---

### Task 5: Lock per-agente + `run_decision_guarded`

**Files:**
- Modify: `backend/app/agents/runtime.py` (import `asyncio`, lock registry, `run_decision_guarded`)
- Modify: `backend/app/scheduler/jobs.py:7,37` (usa `run_decision_guarded`)
- Test: `backend/tests/test_runtime.py`

**Interfaces:**
- Consumes: `run_decision` (Task 4).
- Produces: `run_decision_guarded(session, agent, market, symbols, *, wake_reason=None, brain_decide=..., reflect=...) -> bool` (True se ha eseguito, False se saltato per lock già preso); `_agent_lock(agent_id) -> asyncio.Lock`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_runtime.py`, aggiorna l'import in cima aggiungendo `run_decision_guarded`:

```python
from app.agents.runtime import run_heartbeat, run_decision, run_decision_guarded
```

Aggiungi i test:

```python
async def test_guarded_runs_when_free(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    ran = await run_decision_guarded(db_session, agent, market, ["BTCUSDT"],
                                     brain_decide=lambda ctx, adapter: Decision(actions=[], note="ok"))
    assert ran is True


async def test_guarded_skips_when_locked(db_session):
    from app.agents.runtime import _agent_lock
    agent = _llm_agent(db_session)
    market = FakeMarketLLM([], Decimal("100"), (Decimal("99"), Decimal("101")))
    lock = _agent_lock(agent.id)
    await lock.acquire()
    try:
        ran = await run_decision_guarded(db_session, agent, market, ["BTCUSDT"],
                                         brain_decide=lambda ctx, adapter: Decision(actions=[], note="x"))
        assert ran is False
    finally:
        lock.release()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_runtime.py -k "guarded" -v`
Expected: FAIL (`cannot import name 'run_decision_guarded'`).

- [ ] **Step 3: Implement the lock + guarded runner**

In `backend/app/agents/runtime.py`, aggiungi `import asyncio` in cima. Poi, **dopo** la definizione di `run_decision`, aggiungi:

```python
_agent_locks: dict[int, asyncio.Lock] = {}


def _agent_lock(agent_id: int) -> asyncio.Lock:
    lock = _agent_locks.get(agent_id)
    if lock is None:
        lock = asyncio.Lock()
        _agent_locks[agent_id] = lock
    return lock


async def run_decision_guarded(session, agent, market, symbols, *, wake_reason=None,
                               brain_decide=brain_decide_default, reflect=run_reflection) -> bool:
    """Esegue una decisione sotto il lock dell'agente. Se una decisione è già in corso per
    questo agente, salta e ritorna False (quella in corso copre la situazione)."""
    lock = _agent_lock(agent.id)
    if lock.locked():
        return False
    async with lock:
        await run_decision(session, agent, market, symbols, wake_reason=wake_reason,
                           brain_decide=brain_decide, reflect=reflect)
    return True
```

- [ ] **Step 4: Wire the scheduler to the guarded runner**

In `backend/app/scheduler/jobs.py`, cambia l'import:

```python
from app.agents.runtime import run_heartbeat, run_decision_guarded
```

e nella funzione `_decision_tick`, sostituisci `await run_decision(session, agent, market, symbols_cache[n])` con:

```python
                await run_decision_guarded(session, agent, market, symbols_cache[n])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_runtime.py tests/test_jobs.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/runtime.py backend/app/scheduler/jobs.py backend/tests/test_runtime.py
git commit -m "feat(runtime): per-agent decision lock + run_decision_guarded"
```

---

### Task 6: Nuovo `run_heartbeat` — sveglia l'LLM, non vende

**Files:**
- Modify: `backend/app/agents/runtime.py` (import `breached`, riscrittura `run_heartbeat`)
- Test: `backend/tests/test_runtime.py` (rimuove 3 test obsoleti, aggiunge 6 nuovi)

**Interfaces:**
- Consumes: `breached` (Task 2), `Agent.stop_loss/take_profit` + `Position.breach_armed` (Task 1), `run_decision_guarded` (Task 5).
- Produces: `run_heartbeat(session, agent, market, *, trigger_decision=None) -> None` (default `run_decision_guarded`; iniettabile nei test).

- [ ] **Step 1: Remove the obsolete heartbeat tests**

In `backend/tests/test_runtime.py`, **elimina** queste 3 funzioni (l'heartbeat non vende più meccanicamente):
- `test_heartbeat_sells_on_stop_loss`
- `test_heartbeat_equity_includes_sell_proceeds`
- `test_heartbeat_sell_event_has_no_cycle_id`

Mantieni `test_heartbeat_writes_equity_snapshot` (nessuna posizione → nessun breach → resta valido).

- [ ] **Step 2: Write the new failing tests**

In `backend/tests/test_runtime.py` aggiungi gli helper e i test:

```python
class FakeMarketHB:
    """Market per l'heartbeat: prezzo unico per ogni simbolo + get_top_symbols."""
    def __init__(self, price, symbols=None):
        self._price, self._symbols = price, symbols or ["BTCUSDT"]
    async def get_price(self, symbol): return self._price
    async def get_top_symbols(self, quote, n): return self._symbols


def _armed_agent(session, stop="0.10", take="0.20"):
    a = Agent(name="H", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("0"), stop_loss=Decimal(stop), take_profit=Decimal(take))
    session.add(a); session.commit()
    return a


async def test_heartbeat_within_band_saves_equity_no_trigger(db_session):
    agent = _armed_agent(db_session)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    market = FakeMarketHB(price=Decimal("105"))          # +5%, in banda
    calls = []
    async def fake_trigger(*a, **k): calls.append(1); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert calls == []
    snap = db_session.query(EquitySnapshot).filter_by(agent_id=agent.id).one()
    assert snap.equity_usd == Decimal("105")


async def test_heartbeat_fresh_breach_triggers_disarms_no_sell(db_session):
    agent = _armed_agent(db_session)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    market = FakeMarketHB(price=Decimal("85"))           # -15% → stop
    calls = []
    async def fake_trigger(session, agent, market, symbols, *, wake_reason=None):
        calls.append(wake_reason); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert len(calls) == 1 and "stop" in calls[0] and "BTCUSDT" in calls[0]
    assert db_session.query(Trade).filter_by(agent_id=agent.id).count() == 0   # nessuna vendita meccanica
    pos = db_session.query(Position).filter_by(agent_id=agent.id).one()
    assert pos.breach_armed is False


async def test_heartbeat_disarmed_breach_does_not_retrigger(db_session):
    agent = _armed_agent(db_session)
    p = Position(agent_id=agent.id, symbol="BTCUSDT", quantity=Decimal("1"), avg_price=Decimal("100"))
    p.breach_armed = False
    db_session.add(p); db_session.commit()
    market = FakeMarketHB(price=Decimal("85"))           # ancora oltre soglia, ma disarmata
    calls = []
    async def fake_trigger(*a, **k): calls.append(1); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert calls == []


async def test_heartbeat_rearms_when_back_in_band(db_session):
    agent = _armed_agent(db_session)
    p = Position(agent_id=agent.id, symbol="BTCUSDT", quantity=Decimal("1"), avg_price=Decimal("100"))
    p.breach_armed = False
    db_session.add(p); db_session.commit()
    market = FakeMarketHB(price=Decimal("100"))          # rientrata in banda
    async def fake_trigger(*a, **k): return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    db_session.refresh(p)
    assert p.breach_armed is True


async def test_heartbeat_no_thresholds_never_triggers(db_session):
    a = Agent(name="Blind", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("0"))
    db_session.add(a); db_session.commit()
    db_session.add(Position(agent_id=a.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    market = FakeMarketHB(price=Decimal("50"))           # -50%, ma soglie None
    calls = []
    async def fake_trigger(*a, **k): calls.append(1); return True
    await run_heartbeat(db_session, a, market, trigger_decision=fake_trigger)
    assert calls == []


async def test_heartbeat_armed_position_triggers_despite_other_disarmed(db_session):
    agent = _armed_agent(db_session)
    p1 = Position(agent_id=agent.id, symbol="AAAUSDT", quantity=Decimal("1"), avg_price=Decimal("100"))
    p1.breach_armed = False                              # già svegliato per questa
    p2 = Position(agent_id=agent.id, symbol="BBBUSDT", quantity=Decimal("1"), avg_price=Decimal("100"))
    db_session.add_all([p1, p2]); db_session.commit()
    market = FakeMarketHB(price=Decimal("85"), symbols=["AAAUSDT", "BBBUSDT"])  # entrambe -15%
    calls = []
    async def fake_trigger(session, agent, market, symbols, *, wake_reason=None):
        calls.append(wake_reason); return True
    await run_heartbeat(db_session, agent, market, trigger_decision=fake_trigger)
    assert len(calls) == 1 and "BBBUSDT" in calls[0]     # la posizione armata sveglia
    db_session.refresh(p1); db_session.refresh(p2)
    assert p1.breach_armed is False and p2.breach_armed is False  # entrambe disarmate al risveglio
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_runtime.py -k heartbeat -v`
Expected: FAIL (il vecchio `run_heartbeat` vende e non accetta `trigger_decision`).

- [ ] **Step 4: Rewrite `run_heartbeat`**

In `backend/app/agents/runtime.py`, cambia l'import da strategy:

```python
from app.agents.strategy import breached
```

Sostituisci **interamente** la funzione `run_heartbeat` con:

```python
async def run_heartbeat(session, agent, market, *, trigger_decision=None) -> None:
    if trigger_decision is None:
        trigger_decision = run_decision_guarded
    positions_value = Decimal("0")
    breached_positions = []
    fresh = None                                  # (symbol, side, change_pct) del primo breach fresco
    for pos in list(agent.positions):
        last = await market.get_price(pos.symbol)
        positions_value += pos.quantity * last
        side = breached(pos.avg_price, last, agent.stop_loss, agent.take_profit)
        if side is None:
            if not pos.breach_armed:              # rientrata in banda → ri-arma
                pos.breach_armed = True
        else:
            breached_positions.append(pos)
            if pos.breach_armed and fresh is None:
                change_pct = (last - pos.avg_price) / pos.avg_price * Decimal("100")
                fresh = (pos.symbol, side, change_pct)
    equity = agent.cash_usd + positions_value
    session.add(EquitySnapshot(agent_id=agent.id, equity_usd=equity))
    session.commit()

    if fresh is None:
        return
    symbol, side, change_pct = fresh
    threshold = agent.stop_loss if side == "stop" else agent.take_profit
    label = "stop" if side == "stop" else "take-profit"
    wake_reason = (f"Risveglio fuori ciclo: {symbol} a {change_pct:+.2f}%, oltre la tua "
                   f"soglia di {label} {threshold * Decimal('100'):.2f}%. Rivaluta.")
    n = 100 if agent.universe == "TOP_100" else 50
    symbols = await market.get_top_symbols("USDT", n)
    triggered = await trigger_decision(session, agent, market, symbols, wake_reason=wake_reason)
    if triggered:
        for p in breached_positions:              # l'LLM ha visto l'intero portafoglio: disarma tutte
            p.breach_armed = False
        session.commit()
```

Nota: `run_heartbeat` ora referenzia `run_decision_guarded` e `breached`, entrambi definiti nel modulo (il default `None` risolve a runtime, quindi l'ordine di definizione non conta).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_runtime.py -v`
Expected: PASS (i nuovi test heartbeat + tutti i test LLM/decision preesistenti).

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/runtime.py backend/tests/test_runtime.py
git commit -m "feat(runtime): heartbeat wakes LLM on fresh breach (edge-triggered), no mechanical sell"
```

---

### Task 7: Rimuovi `guardrail_action` (ora inutilizzata)

**Files:**
- Modify: `backend/app/agents/strategy.py` (elimina `guardrail_action`)
- Modify: `backend/tests/test_strategy.py` (elimina i 3 test di `guardrail_action`)

- [ ] **Step 1: Verify nothing else imports it**

Run: `cd backend && grep -rn "guardrail_action" app/`
Expected: nessun risultato (dopo il Task 6, `runtime.py` importa `breached`). Se ci sono risultati residui, correggi prima.

- [ ] **Step 2: Remove the function and its tests**

In `backend/app/agents/strategy.py`, elimina la funzione `guardrail_action` (resta solo `breached` e l'import `from decimal import Decimal`).

In `backend/tests/test_strategy.py`, elimina i 3 test `test_guardrail_sells_on_stop_loss`, `test_guardrail_sells_on_take_profit`, `test_guardrail_holds_within_band` e l'import `from app.agents.strategy import guardrail_action` (mantieni `from app.agents.strategy import breached`).

- [ ] **Step 3: Run the full backend suite**

Run: `cd backend && pytest -v`
Expected: PASS (nessun riferimento a `guardrail_action`).

- [ ] **Step 4: Commit**

```bash
git add backend/app/agents/strategy.py backend/tests/test_strategy.py
git commit -m "refactor(strategy): drop unused guardrail_action"
```

---

### Task 8: API — accetta e valida le soglie alla creazione

**Files:**
- Modify: `backend/app/api/schemas.py:7-12` (`AgentCreate`)
- Modify: `backend/app/api/routes.py:42-50` (`create_agent`)
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `Agent.stop_loss/take_profit` (Task 1).
- Produces: `AgentCreate.stop_loss/take_profit: Decimal | None` (frazioni, validate); persistite sull'`Agent`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_api.py` aggiungi:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_api.py -k "thresholds or stop_loss or take_profit" -v`
Expected: FAIL (i due 422 falliscono con 201; le soglie non vengono persistite).

- [ ] **Step 3: Add validated fields to the schema**

In `backend/app/api/schemas.py`, nella classe `AgentCreate`, aggiungi (dopo `universe`):

```python
    stop_loss: Decimal | None = Field(default=None, gt=0, lt=1)
    take_profit: Decimal | None = Field(default=None, gt=0, le=5)
```

(`Decimal` e `Field` sono già importati.)

- [ ] **Step 4: Persist them in the route**

In `backend/app/api/routes.py::create_agent`, nel costrutto `Agent(...)` aggiungi (dopo `model_name=payload.model_name,`):

```python
        stop_loss=payload.stop_loss,
        take_profit=payload.take_profit,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_api.py -v`
Expected: PASS (nuovi + preesistenti, che non inviano soglie → `None`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api.py
git commit -m "feat(api): accept and validate per-agent risk thresholds on create"
```

---

### Task 9: Frontend — campi soglia nel form di creazione

**Files:**
- Modify: `frontend/src/api.ts:44-50` (`AgentCreateInput`)
- Modify: `frontend/src/components/AgentFormModal.tsx`

**Interfaces:**
- Consumes: `POST /api/agents` con `stop_loss`/`take_profit` frazioni opzionali (Task 8).

- [ ] **Step 1: Extend the API input type**

In `frontend/src/api.ts`, in `AgentCreateInput` aggiungi due campi:

```typescript
export type AgentCreateInput = {
  name: string;
  instructions: string;
  duration_days: number;
  model_name: string;
  universe: "TOP_50" | "TOP_100";
  stop_loss: number | null;
  take_profit: number | null;
};
```

- [ ] **Step 2: Add the form fields and conversion**

In `frontend/src/components/AgentFormModal.tsx`:

a) In `type FormValues` aggiungi:

```typescript
  stopLoss: number | null;
  takeProfit: number | null;
```

b) Nello `schema` (dentro `.object({...})`) aggiungi:

```typescript
      stopLoss: z.number().gt(0).lt(100).nullable(),
      takeProfit: z.number().gt(0).max(500).nullable(),
```

c) In `defaultValues` aggiungi:

```typescript
      stopLoss: 10,
      takeProfit: 20,
```

d) In `onSubmit`, nella chiamata `createAgent({...})`, aggiungi la conversione %→frazione:

```typescript
          stop_loss: values.stopLoss == null ? null : values.stopLoss / 100,
          take_profit: values.takeProfit == null ? null : values.takeProfit / 100,
```

e) Dentro il blocco `{!isEdit && ( ... )}`, dopo il `FormField` di `universe`, aggiungi i due campi (vuoto = disattivato):

```tsx
                <FormField control={form.control} name="stopLoss" render={({ field }) => (
                  <FormItem>
                    <FormLabel>Stop-loss (%) — vuoto = disattivato</FormLabel>
                    <FormControl>
                      <Input type="number" min={0} step="any" value={field.value ?? ""}
                        onChange={(e) => field.onChange(e.target.value === "" ? null : Number(e.target.value))} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )} />

                <FormField control={form.control} name="takeProfit" render={({ field }) => (
                  <FormItem>
                    <FormLabel>Take-profit (%) — vuoto = disattivato</FormLabel>
                    <FormControl>
                      <Input type="number" min={0} step="any" value={field.value ?? ""}
                        onChange={(e) => field.onChange(e.target.value === "" ? null : Number(e.target.value))} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )} />
```

- [ ] **Step 3: Typecheck / build**

Run: `cd frontend && npm run build`
Expected: build senza errori TypeScript.

- [ ] **Step 4: Verify in the browser**

Avvia il dev server (preview_start "frontend") e apri il form "Nuovo agente": i due campi Stop-loss/Take-profit compaiono precompilati a 10/20, si possono svuotare, e la creazione va a buon fine (Network: POST /api/agents con `stop_loss: 0.1`, `take_profit: 0.2`). Cattura uno screenshot del form.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/components/AgentFormModal.tsx
git commit -m "feat(frontend): per-agent stop-loss / take-profit fields in agent form"
```

---

### Task 10: Aggiorna l'explainer `docs/pipeline.html`

**Files:**
- Modify: `docs/pipeline.html` (sezione Battito, diagramma master loop-card, manopole)

- [ ] **Step 1: Update the Battito section prose**

Nella sezione `#battito`, aggiorna l'intro per riflettere il nuovo comportamento. Sostituisci il testo del `p.sec-intro` con qualcosa come:

> «Il battito non pensa e **non vende**: applica una soglia (per-agente) e, quando una posizione la *attraversa*, **sveglia l'LLM** perché decida. Registra sempre l'equity. È un trigger veloce (ogni 5 min) tra una decisione oraria e l'altra, non più un esecutore meccanico.»

- [ ] **Step 2: Update the heartbeat gate diagram**

Nel diagramma SVG della sezione Battito, cambia il nodo di esito da «VENDI tutto / al bid» a «**sveglia l'LLM** / decisione off-cycle», e l'etichetta del ramo che porta lì da un'azione a un trigger. Aggiorna l'`aria-label` dell'SVG di conseguenza. Aggiungi un breve riquadro/nota sull'**edge-triggered** (sveglia una volta, si ri-arma al rientro in banda).

- [ ] **Step 3: Update the master diagram loop card + manopole**

Nella card «Battito · 5 min» (sezione `#insieme`), aggiorna la descrizione: «Loop meccanico… guardrail stop-loss/take-profit» → «Trigger: soglie per-agente; sul breach sveglia l'LLM (non vende)».
Nel pannello «Le manopole» (`#numeri`), cambia le due dial `+20% / −10%` da valori globali a **default per-agente** (etichetta «default form, per-agente»), e togli l'implicazione che siano fisse per tutti.

- [ ] **Step 4: Verify in the browser**

Servi `docs/` (preview) e verifica le sezioni Battito, il diagramma master e le manopole a desktop e mobile. Cattura uno screenshot.

- [ ] **Step 5: Commit**

```bash
git add docs/pipeline.html
git commit -m "docs(pipeline): heartbeat now wakes the LLM (per-agent edge-triggered thresholds)"
```

---

## Self-Review (già eseguita in fase di stesura)

- **Copertura spec:** modello dati (T1), `breached` (T2), `wake_reason` contesto/prompt (T3), decisione off-cycle + marker (T4), lock concorrenza (T5), heartbeat edge-triggered + re-arm + disarm + no-sell (T6), rimozione guardrail (T7), API validazione (T8), form per-agente (T9), docs (T10). Config-defaults dello spec: **omessi deliberatamente** (vedi Global Constraints).
- **Coerenza tipi:** `breached(...) -> str|None` usato in T6; `run_decision_guarded(...) -> bool` prodotto in T5 e consumato in T6; `wake_reason` prodotto in T3, filato in T4, usato in T6; `Position.breach_armed` prodotto in T1, usato in T6.
- **Test che si rompono:** i 3 test heartbeat basati sulla vendita meccanica sono **rimossi** esplicitamente in T6; i 3 test `guardrail_action` in T7.
- **Precisione float→Decimal:** i test API usano tolleranza (T8) perché in SQLite `Numeric` non arrotonda; in Postgres `Numeric(5,4)` arrotonda a 4 decimali.
