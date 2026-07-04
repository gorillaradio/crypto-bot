# Rimozione monolite pipeline v1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminare del tutto il brain v1 (monolite a uno stadio) rendendo v2 (analyst → trader) l'unico percorso decisionale, incluse colonna DB `brain_version`, API, frontend e test.

**Architecture:** Oggi il dispatch è per-agente su `agent.brain_version`: v1 usa `evaluate`/`render_prompt` con snapshot universo completo; v2 usa un *market brief* condiviso (analyst) + `evaluate_trader`. Si collassa tutto sul percorso v2, si rimuove il flag e la sua colonna, e si porta il monitor prompt a mostrare il prompt trader. Nessuna migrazione dati sugli agenti (gli agenti v1 sono già stati eliminati dall'operatore).

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (Postgres in prod, SQLite in-memory nei test via `Base.metadata.create_all`), React + TypeScript + Vitest.

## Global Constraints

- **Nessun agente v1 vivo:** non serve migrazione dati; la nuova migrazione Alembic droppa solo la colonna.
- **`market_briefs` NON si tocca:** la tabella `market_briefs` è stata creata dalla *stessa* migrazione che ha aggiunto `brain_version` (`49407193a9ac`); è infra v2, resta. Quindi si scrive una **nuova** migrazione in avanti (mai `downgrade` di `49407193a9ac`).
- **Test runner backend:** `cd backend && .venv/bin/pytest`. Baseline attuale: **284 test** verdi.
- **Test runner frontend:** `cd frontend && npm test` (vitest) e `npm run build` (tsc + vite).
- **Schema nei test:** costruito da `models.py` via `create_all`, non da Alembic → rimuovere la colonna dal modello vale subito per pytest; la migrazione si verifica con smoke up/down separato.
- **Commit:** chiudere ogni messaggio con `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Ordine dei task:** rispettare l'ordine (dipendenze reali: preview prima di runtime; API prima di frontend; colonna DB per ultima tra le rimozioni backend, cleanup contesto in coda).

## Working-tree note (leggere prima di iniziare)

All'avvio di questo piano il tree ha **due modifiche non committate** fatte dall'operatore, che anticipano parte del lavoro:
- `backend/app/api/schemas.py`: default `AgentCreate.brain_version` già flippato `"v1"` → `"v2"`.
- `backend/tests/test_api.py`: i due test di creazione già rinominati (`..._defaults_brain_version_v2`, `..._accepts_brain_version_v1`).

Il **Task 5** cancella comunque per intero il campo `brain_version` da `AgentCreate`/`AgentOut` e quei test, quindi questi edit vengono assorbiti (spariscono le stesse righe). Nessun conflitto di contenuto: trattare il tree corrente come punto di partenza.

---

## File Structure

Backend (`backend/app/`):
- `agents/preview.py` — monitor prompt: da v1 → v2 (Task 1).
- `agents/runtime.py` — dispatch decisione: collasso a v2 (Task 1 estrae `assemble_trader_context`; Task 2 rimuove v1; Task 8 pulisce il contesto).
- `brain/__init__.py`, `brain/prompt.py` — eliminazione brain v1 (Task 3).
- `brain/context.py` — pulizia campi morti (Task 8).
- `scheduler/jobs.py` — analyst incondizionato (Task 4).
- `api/schemas.py`, `api/routes.py` — rimozione `brain_version` (Task 5).
- `db/models.py` + nuova revisione in `alembic/versions/` — drop colonna (Task 7).

Frontend (`frontend/src/`):
- `components/BrainBadge.tsx` — eliminato (Task 6).
- `components/MarketBriefPanel.tsx`, `App.tsx`, `api.ts` — rimozione `brain_version` (Task 6).

Test toccati: `test_preview`, `test_runtime`, `test_brain_v2_dispatch`→`test_buy_guard`, `test_brain_decide`(del), `test_brain_prompt`(del), `test_scheduler_analyst`, `test_api`, `test_analyst_schema`, `test_analyst_orchestration`; frontend `AgentSidebar/AgentFormModal/ConfirmDeleteModal` fixtures.

---

### Task 1: Monitor prompt → v2 (estrai `assemble_trader_context`, migra `preview.py`)

Il monitor prompt oggi ricostruisce il prompt **v1** (`build_agent_context` + `render_prompt`). Va portato al prompt **trader** v2 — ma **senza** far partire l'analyst (il monitor è read-only, zero LLM/persistenza). Perciò si estrae da `build_trader_context` un helper di assemblaggio che accetta un `brief_row` già risolto, e il preview gli passa `latest_valid_brief` (nessun bootstrap).

**Files:**
- Modify: `backend/app/agents/runtime.py:49-65` (estrai `assemble_trader_context`)
- Modify: `backend/app/agents/preview.py` (intero)
- Test: `backend/tests/test_preview.py`

**Interfaces:**
- Produces: `assemble_trader_context(session, agent, market, symbols, brief_row, *, wake_reason=None) -> DecisionContext` in `runtime.py` (usato da `build_trader_context` e da `preview.py`).
- Consumes: `latest_valid_brief(session)`, `filter_brief_for(brief_row, symbols)` (già in `brain/brief_store.py`); `render_trader_prompt(ctx)` (già in `brain/prompt.py`).

- [ ] **Step 1: Test rosso — il preview deve emettere il prompt trader (con la riga "Market brief")**

In `backend/tests/test_preview.py`, dentro `test_preview_returns_three_prompts_with_real_data`, aggiorna il commento a riga 36 e aggiungi un'asserzione che distingue v2 (subito dopo la riga `assert "cut losers" in out["decision"]["user"]`):

```python
    assert "BTCUSDT" in out["decision"]["user"]                        # posizione aperta
    assert "cut losers" in out["decision"]["user"]                     # memoria
    assert "Market brief" in out["decision"]["user"]                   # prompt v2 (trader), non più tabella universo v1
```

- [ ] **Step 2: Esegui il test — deve fallire**

Run: `cd backend && .venv/bin/pytest tests/test_preview.py::test_preview_returns_three_prompts_with_real_data -q`
Expected: FAIL — `assert "Market brief" in ...` è falso (il preview attuale rende il prompt v1, che ha "Market (universe)").

- [ ] **Step 3: Estrai `assemble_trader_context` in `runtime.py`**

Sostituisci il corpo attuale di `build_trader_context` (righe 49-65) con la coppia risoluzione-brief / assemblaggio:

```python
async def build_trader_context(session, agent, market, symbols, *, wake_reason=None):
    """v2 context: brief (bootstrap se assente) + posizioni live + memoria + eventi + wake_reason.
    NON scarica lo snapshot universo (l'analyst ha già sintetizzato il mercato una volta, condiviso)."""
    brief_row = await get_or_bootstrap_brief(session, market)
    return await assemble_trader_context(session, agent, market, symbols, brief_row,
                                         wake_reason=wake_reason)


async def assemble_trader_context(session, agent, market, symbols, brief_row, *, wake_reason=None):
    """Assembla il DecisionContext del trader da un brief_row GIÀ risolto (nessun bootstrap qui).
    Condiviso dal ciclo di decisione (brief con bootstrap) e dal monitor prompt (solo latest, no LLM)."""
    holdings = []
    for pos in agent.positions:
        last = await market.get_price(pos.symbol)
        holdings.append((pos.symbol, pos.quantity, pos.avg_price, last))
    recent = [e.message for e in (
        session.query(Event).filter_by(agent_id=agent.id)
        .order_by(Event.timestamp.desc()).limit(10).all())]
    memory = journal.compact_view(session, agent.id)
    brief = filter_brief_for(brief_row, symbols) if brief_row is not None else None
    return build_context(instructions=agent.instructions, cash_usd=agent.cash_usd,
                         holdings=holdings, universe=[], recent_events=recent,
                         memory=memory, brief=brief, wake_reason=wake_reason)
```

- [ ] **Step 4: Riscrivi `preview.py` sul percorso v2 (read-only, no bootstrap)**

Sostituisci l'intero `backend/app/agents/preview.py` con:

```python
from app.agents.runtime import assemble_trader_context, universe_size
from app.brain.prompt import render_trader_prompt, retry_user_suffix
from app.brain.memory import build_reflection_prompt, ClosedTrade
from app.brain.brief_store import latest_valid_brief

_RETRY_EXAMPLE_ERROR = ("1 validation error for Decision: actions.0.type — "
                        "input should be 'BUY', 'SELL' or 'HOLD'")


async def render_agent_prompts_preview(session, agent, market) -> dict:
    """Ricostruisce i prompt (decision/reflection/retry) che la pipeline invierebbe ORA per
    questo agente, con dati reali. Nessuna chiamata LLM, nessuna persistenza: usa l'ultimo brief
    valido senza bootstrap (se non c'è, il prompt trader mostra 'brief non disponibile')."""
    symbols = await market.get_top_symbols("USDT", universe_size(agent))
    brief_row = latest_valid_brief(session)          # read-only: niente bootstrap → niente LLM
    ctx = await assemble_trader_context(session, agent, market, symbols, brief_row, wake_reason=None)
    d_system, d_user = render_trader_prompt(ctx)

    retry_user = d_user + retry_user_suffix(_RETRY_EXAMPLE_ERROR)

    closed = [ClosedTrade(symbol=p.symbol, qty=p.quantity, sell_price=p.last_price,
                          avg_cost=p.avg_price, realized_pnl_pct=p.unrealized_pnl_pct)
              for p in ctx.positions]
    held_symbols = [p.symbol for p in ctx.positions]
    r_system, r_user = build_reflection_prompt(ctx.memory, closed, held_symbols, agent.instructions)
    refl_note = ("Anteprima: le posizioni attuali come se chiuse ora." if closed
                 else "Nessuna posizione aperta: mostrato a scopo strutturale "
                      "(la reflection scatta alla chiusura di un trade).")

    return {
        "decision":   {"system": d_system, "user": d_user, "note": None},
        "reflection": {"system": r_system, "user": r_user, "note": refl_note},
        "retry":      {"system": d_system, "user": retry_user,
                       "note": "Suffisso di retry mostrato con un errore d'esempio."},
    }
```

- [ ] **Step 5: Esegui i test del preview — devono passare**

Run: `cd backend && .venv/bin/pytest tests/test_preview.py -q`
Expected: PASS (entrambi i test del preview verdi).

- [ ] **Step 6: Esegui l'intera suite backend — nessuna regressione**

Run: `cd backend && .venv/bin/pytest -q`
Expected: PASS, 284 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/agents/runtime.py backend/app/agents/preview.py backend/tests/test_preview.py
git commit -m "refactor(rm-v1): monitor prompt su percorso v2 (assemble_trader_context, no bootstrap)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Collasso del dispatch decisionale su v2

Rimuove il ramo v1 dal runtime: via `_select_brain`, `build_agent_context`, `_build_decision_context`; `run_decision` usa sempre `evaluate_trader`; `_run_decision_llm` costruisce il contesto con `build_trader_context`. Aggiorna i test che dipendono dai simboli v1.

**Files:**
- Modify: `backend/app/agents/runtime.py` (import riga 10; rimuovi righe 27-46, 68-69, 72-75; aggiorna righe 197 e 231)
- Modify: `backend/tests/test_runtime.py` (import riga 5; rimuovi 2 test)
- Rename+Modify: `backend/tests/test_brain_v2_dispatch.py` → `backend/tests/test_buy_guard.py`

**Interfaces:**
- Consumes: `evaluate_trader` (da `app.brain`), `build_trader_context` (Task 1).
- Produces: `run_decision(..., brain_decide=None)` con default `evaluate_trader`; niente più `_select_brain`/`_build_decision_context`/`build_agent_context`.

- [ ] **Step 1: Aggiorna l'import del brain in `runtime.py` (riga 10)**

Da:
```python
from app.brain import evaluate as brain_decide_default, evaluate_trader
```
A:
```python
from app.brain import evaluate_trader
```

- [ ] **Step 2: Elimina `build_agent_context` (righe 27-46)**

Cancella l'intera funzione `async def build_agent_context(...)` (dal docstring "Costruisce il DecisionContext dai dati vivi…" fino al `return build_context(... wake_reason=wake_reason)`). `build_trader_context`/`assemble_trader_context` restano.

- [ ] **Step 3: Elimina `_select_brain` e `_build_decision_context` (righe 68-75)**

Cancella:
```python
def _select_brain(agent):
    return evaluate_trader if agent.brain_version == "v2" else brain_decide_default


async def _build_decision_context(session, agent, market, symbols, *, wake_reason=None):
    if agent.brain_version == "v2":
        return await build_trader_context(session, agent, market, symbols, wake_reason=wake_reason)
    return await build_agent_context(session, agent, market, symbols, wake_reason=wake_reason)
```

- [ ] **Step 4: `run_decision` usa sempre `evaluate_trader` (riga ~197)**

In `run_decision`, sostituisci:
```python
    if brain_decide is None:
        brain_decide = _select_brain(agent)
```
con:
```python
    if brain_decide is None:
        brain_decide = evaluate_trader
```

- [ ] **Step 5: `_run_decision_llm` costruisce il contesto trader (riga ~231)**

In `_run_decision_llm`, sostituisci:
```python
        ctx = await _build_decision_context(session, agent, market, symbols, wake_reason=wake_reason)
```
con:
```python
        ctx = await build_trader_context(session, agent, market, symbols, wake_reason=wake_reason)
```

(La guardia BUY a riga ~232 `... if ctx.universe else set(symbols)` resta invariata per ora — `ctx.universe` è `[]`, quindi usa `set(symbols)`; verrà semplificata nel Task 8.)

- [ ] **Step 6: Aggiorna `test_runtime.py` — togli l'import e i 2 test di `build_agent_context`**

Riga 5, da:
```python
from app.agents.runtime import run_heartbeat, run_decision, run_decision_guarded, build_agent_context, universe_size
```
A:
```python
from app.agents.runtime import run_heartbeat, run_decision, run_decision_guarded, universe_size
```
Poi cancella per intero i due test `async def test_build_agent_context_assembles_from_live_data(...)` (righe ~457-471) e `async def test_build_agent_context_includes_recent_observations(...)` (righe ~645-663). Lascia intatti `test_universe_size_maps_universe_field` e `test_run_decision_explicit_trigger_wins`.

- [ ] **Step 7: Rinomina e sfoltisci `test_brain_v2_dispatch.py`**

```bash
git mv backend/tests/test_brain_v2_dispatch.py backend/tests/test_buy_guard.py
```
In `backend/tests/test_buy_guard.py`: (a) cambia l'import riga 8 `from app.agents.runtime import _select_brain, run_decision` → `from app.agents.runtime import run_decision`; (b) cancella l'intero `async def test_select_brain_by_version(...)` (righe 22-25); (c) togli `brain_version` dall'helper `_agent` così non dipende dalla colonna (Task 7). L'helper diventa:
```python
def _agent(session):
    a = Agent(name="T", cash_usd=Decimal("1000"),
              model_name="deepseek/deepseek-v4-flash",
              duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1))
    session.add(a); session.commit()
    return a
```
e nel test `test_guard_uses_symbols_when_universe_empty` cambia la chiamata `agent = _agent(db_session, "v2")` → `agent = _agent(db_session)`.

- [ ] **Step 8: Esegui la suite backend — verde**

Run: `cd backend && .venv/bin/pytest -q`
Expected: PASS. Conteggio atteso: 284 − 3 test rimossi (`test_select_brain_by_version`, i 2 `build_agent_context`) = **281 passed**.

- [ ] **Step 9: Commit**

```bash
git add backend/app/agents/runtime.py backend/tests/test_runtime.py backend/tests/test_buy_guard.py
git commit -m "refactor(rm-v1): collassa il dispatch decisionale sul solo percorso trader v2

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Elimina il brain v1 (`evaluate`, `decide`, `render_prompt`)

Dopo il Task 2, `evaluate`/`decide`/`render_prompt` sono usati solo dai loro test unitari. Si eliminano insieme ai test.

**Files:**
- Modify: `backend/app/brain/__init__.py` (rimuovi `evaluate` e `decide`)
- Modify: `backend/app/brain/prompt.py` (rimuovi `render_prompt`; import riga 1)
- Delete: `backend/tests/test_brain_decide.py`
- Delete: `backend/tests/test_brain_prompt.py`

**Interfaces:**
- Produces: `app.brain` espone `evaluate_trader`, `decide`(rimosso), `DecisionResult`, `Decision`. Restano `_evaluate_with`, `evaluate_trader`.

- [ ] **Step 1: Rimuovi `evaluate` e `decide` da `brain/__init__.py`**

Cancella queste due funzioni (righe 34-43), lasciando `_evaluate_with` ed `evaluate_trader`:
```python
def evaluate(ctx: DecisionContext, adapter) -> DecisionResult:
    return _evaluate_with(ctx, adapter, render_prompt)
```
e
```python
def decide(ctx: DecisionContext, adapter) -> Decision:
    return evaluate(ctx, adapter).decision
```
Aggiorna l'import riga 4, da:
```python
from app.brain.prompt import render_prompt, render_trader_prompt, retry_user_suffix
```
A:
```python
from app.brain.prompt import render_trader_prompt, retry_user_suffix
```
`Decision` non è più usato in `__init__.py` dopo la rimozione di `decide`: togli `Decision` dall'import riga 2 se resta inutilizzato (lascia `DecisionResult`), cioè:
```python
from app.brain.schema import DecisionResult
```

- [ ] **Step 2: Rimuovi `render_prompt` da `brain/prompt.py`**

Cancella l'intera `def render_prompt(ctx: DecisionContext) -> tuple[str, str]:` (righe 18-60). Restano `render_trader_prompt` e `retry_user_suffix`. `render_trader_prompt` non usa `DecisionContext` come annotazione? La usa nel commento; l'import riga 1 `from app.brain.context import DecisionContext` resta usato solo se compare in annotazioni: `render_trader_prompt(ctx: DecisionContext)` — sì, la mantiene. Lascia l'import invariato.

Nel docstring/commenti di `render_trader_prompt` c'è un riferimento a "v1" (righe 94-95: "identical output to render_prompt (v1). Duplicated deliberately to keep the v1 renderer untouched"). Sostituisci quel commento con una nota non più riferita al v1:
```python
    # Blocco memoria: stesso formato usato altrove nel prompt. ~10 righe.
```

- [ ] **Step 3: Cancella i test unitari v1**

```bash
git rm backend/tests/test_brain_decide.py backend/tests/test_brain_prompt.py
```

- [ ] **Step 4: Esegui la suite backend — verde**

Run: `cd backend && .venv/bin/pytest -q`
Expected: PASS. `test_brain_decide.py` (8 test) e `test_brain_prompt.py` (~9 test) rimossi.

- [ ] **Step 5: Commit**

```bash
git add backend/app/brain/__init__.py backend/app/brain/prompt.py
git commit -m "refactor(rm-v1): elimina brain v1 (evaluate/decide/render_prompt) e i suoi test

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Analyst cycle incondizionato nello scheduler

Senza v1, ogni agente running consuma il brief → l'analyst deve girare sempre (non più dietro il gate `any(brain_version=="v2")`).

**Files:**
- Modify: `backend/app/scheduler/jobs.py:33-39`
- Modify: `backend/tests/test_scheduler_analyst.py` (intero)

- [ ] **Step 1: Test rosso — l'analyst gira anche senza distinzione di versione**

Sostituisci l'intero `backend/tests/test_scheduler_analyst.py` con (un solo test: gira sempre se c'è almeno un agente running; niente più "skipped when all v1"):
```python
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
from app.db.models import Agent
from app.scheduler import jobs

pytestmark = pytest.mark.asyncio


def _agent(session):
    a = Agent(name="T", status="running", cash_usd=Decimal("100"),
              model_name="m", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1))
    session.add(a); session.commit()
    return a


class _FakeMarket:
    """Stands in for BinanceClient() in the per-agent loop path."""
    def __init__(self):
        self.get_top_symbols = AsyncMock(return_value=["BTCUSDT"])


async def test_analyst_runs_once_when_agents_present(db_session, monkeypatch):
    _agent(db_session)
    monkeypatch.setattr(jobs, "get_session", lambda: _ctxmgr(db_session))
    monkeypatch.setattr(jobs, "BinanceClient", lambda: _FakeMarket())
    monkeypatch.setattr(jobs, "run_decision_guarded", AsyncMock(return_value=True))
    monkeypatch.setattr(jobs, "universe_size", lambda a: 100)
    cycle = AsyncMock(return_value=None)
    monkeypatch.setattr(jobs, "run_analyst_cycle", cycle)
    await jobs._decision_tick()
    cycle.assert_awaited_once()


async def test_analyst_skipped_when_no_running_agents(db_session, monkeypatch):
    monkeypatch.setattr(jobs, "get_session", lambda: _ctxmgr(db_session))
    monkeypatch.setattr(jobs, "BinanceClient", lambda: _FakeMarket())
    monkeypatch.setattr(jobs, "run_decision_guarded", AsyncMock(return_value=True))
    monkeypatch.setattr(jobs, "universe_size", lambda a: 100)
    cycle = AsyncMock(return_value=None)
    monkeypatch.setattr(jobs, "run_analyst_cycle", cycle)
    await jobs._decision_tick()
    cycle.assert_not_awaited()


class _ctxmgr:
    def __init__(self, s): self.s = s
    def __enter__(self): return self.s
    def __exit__(self, *a): return False
```

- [ ] **Step 2: Esegui — `test_analyst_runs_once_when_agents_present` deve fallire**

Run: `cd backend && .venv/bin/pytest tests/test_scheduler_analyst.py -q`
Expected: FAIL su `test_analyst_runs_once_when_agents_present` — con il gate attuale `any(brain_version=="v2")` e un agente senza v2, `run_analyst_cycle` non viene chiamato.

- [ ] **Step 3: Rendi l'analyst incondizionato in `jobs.py`**

In `_decision_tick`, sostituisci:
```python
        agents = session.query(Agent).filter_by(status="running").all()
        if any(a.brain_version == "v2" for a in agents):
            try:
                await run_analyst_cycle(session, market)
            except Exception as exc:
                logger.error("analyst cycle failed: %s", exc)
                session.rollback()
```
con:
```python
        agents = session.query(Agent).filter_by(status="running").all()
        if agents:
            try:
                await run_analyst_cycle(session, market)
            except Exception as exc:
                logger.error("analyst cycle failed: %s", exc)
                session.rollback()
```

- [ ] **Step 4: Esegui — verde**

Run: `cd backend && .venv/bin/pytest tests/test_scheduler_analyst.py -q`
Expected: PASS (entrambi i test).

- [ ] **Step 5: Commit**

```bash
git add backend/app/scheduler/jobs.py backend/tests/test_scheduler_analyst.py
git commit -m "refactor(rm-v1): analyst cycle incondizionato (gira per ogni agente running)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Rimuovi `brain_version` dall'API

Toglie il campo da `AgentCreate` e `AgentOut` e i relativi test. (Assorbe gli edit non committati su `schemas.py`/`test_api.py`.)

**Files:**
- Modify: `backend/app/api/schemas.py` (riga 13; riga 32)
- Modify: `backend/app/api/routes.py` (riga 48; riga 62)
- Modify: `backend/tests/test_api.py` (rimuovi 3 test; togli `brain_version` da 1 fixture)

- [ ] **Step 1: `schemas.py` — togli `brain_version` da `AgentCreate` e `AgentOut`**

In `AgentCreate` cancella la riga (attualmente, dopo l'edit operatore):
```python
    brain_version: Literal["v1", "v2"] = "v2"
```
In `AgentOut` cancella la riga:
```python
    brain_version: str
```
Verifica che `Literal` resti importato/usato (lo usa ancora `universe: Literal[...]`), quindi l'import in cima resta invariato.

- [ ] **Step 2: `routes.py` — togli i due usi**

In `create_agent` (riga ~62) cancella la riga:
```python
        brain_version=payload.brain_version,
```
In `_agent_out` (riga ~48) cancella la riga:
```python
        brain_version=agent.brain_version,
```

- [ ] **Step 3: `test_api.py` — rimuovi i 3 test e ripulisci la fixture del brief**

Cancella per intero:
- `def test_agent_out_includes_brain_version(db_session):` (righe ~82-89);
- `def test_create_agent_defaults_brain_version_v2(db_session):` (righe ~537-541);
- `def test_create_agent_accepts_brain_version_v1(db_session):` (righe ~544-548).

In `test_get_brief_returns_filtered_view` (riga ~577-579), togli `brain_version="v2"` dalla costruzione dell'`Agent`:
```python
    agent = Agent(name="B", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"))
```

- [ ] **Step 4: Esegui la suite backend — verde**

Run: `cd backend && .venv/bin/pytest -q`
Expected: PASS (3 test API in meno).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api.py
git commit -m "refactor(rm-v1): rimuovi brain_version dall'API (AgentCreate/AgentOut)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Rimuovi `brain_version` dal frontend

Da fare **subito dopo** il Task 5 (l'API non restituisce più `brain_version`). Elimina il badge e la nota v1, e il campo dal tipo `Agent`.

**Files:**
- Delete: `frontend/src/components/BrainBadge.tsx`
- Modify: `frontend/src/App.tsx` (riga 28 import; riga 193 uso; riga 270 prop)
- Modify: `frontend/src/components/MarketBriefPanel.tsx` (firma + ramo v1)
- Modify: `frontend/src/api.ts` (riga 10)
- Modify: `frontend/src/__tests__/AgentSidebar.test.tsx`, `AgentFormModal.test.tsx`, `ConfirmDeleteModal.test.tsx` (fixture)

- [ ] **Step 1: Elimina il componente badge**

```bash
git rm frontend/src/components/BrainBadge.tsx
```

- [ ] **Step 2: `App.tsx` — togli import e uso del badge, e la prop del pannello**

Cancella la riga 28:
```tsx
import { BrainBadge } from "./components/BrainBadge";
```
Cancella la riga 193:
```tsx
                <BrainBadge version={sel.brain_version} />
```
A riga ~270 cambia:
```tsx
                  <MarketBriefPanel agentId={selId} brainVersion={sel.brain_version} />
```
in:
```tsx
                  <MarketBriefPanel agentId={selId} />
```

- [ ] **Step 3: `MarketBriefPanel.tsx` — togli la prop `brainVersion` e il ramo nota-v1**

Cambia la firma (riga 35):
```tsx
export function MarketBriefPanel({ agentId }: { agentId: number }) {
```
Ed elimina il blocco condizionale (righe 49-53):
```tsx
      {brainVersion !== "v2" && (
        <p className="text-xs text-muted-foreground">
          Questo agente usa il brain v1 (monolitico) e non consuma il market brief.
        </p>
      )}
```

- [ ] **Step 4: `api.ts` — togli `brain_version` dal tipo `Agent`**

Cancella la riga 10:
```ts
  brain_version: string;
```

- [ ] **Step 5: Togli `brain_version` dalle 3 fixture di test**

In ciascuno di `AgentSidebar.test.tsx` (riga 7), `AgentFormModal.test.tsx` (riga 52), `ConfirmDeleteModal.test.tsx` (riga 8) rimuovi il frammento `brain_version: "v1", ` dall'oggetto agente. Esempio per `AgentSidebar.test.tsx`:
```tsx
  id: 1, name: "A", status: "running", instructions: "",
```

- [ ] **Step 6: Esegui test e build frontend — verdi**

Run: `cd frontend && npm test`
Expected: PASS.
Run: `cd frontend && npm run build`
Expected: build pulita (tsc senza errori — nessun riferimento residuo a `brain_version`/`BrainBadge`/`brainVersion`).

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "refactor(rm-v1): rimuovi brain badge e brain_version dal frontend

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Droppa la colonna `agents.brain_version` (modello + migrazione)

Ultimo passo di rimozione: colonna dal modello (vale subito per i test SQLite) + nuova migrazione Alembic in avanti (per Postgres prod), **senza toccare `market_briefs`**.

**Files:**
- Modify: `backend/app/db/models.py:33` (rimuovi il mapping colonna)
- Create: `backend/alembic/versions/<nuova_revisione>_drop_agent_brain_version.py`
- Modify: `backend/tests/test_analyst_schema.py` (rimuovi 2 test)
- Modify: `backend/tests/test_analyst_orchestration.py:61` (togli `brain_version`)

- [ ] **Step 1: Sweep di controllo — dove resta `brain_version` in backend**

Run: `cd backend && grep -rn "brain_version" app tests alembic`
Expected (prima di questo task): `app/db/models.py:33`; `tests/test_analyst_schema.py` (2 test); `tests/test_analyst_orchestration.py:61`; `alembic/versions/49407193a9ac_*.py` (migrazione storica — **non si tocca**). Se compare altro, gestirlo prima di procedere.

- [ ] **Step 2: Rimuovi la colonna dal modello**

In `backend/app/db/models.py`, cancella (righe ~33-34):
```python
    brain_version: Mapped[str] = mapped_column(String(10), nullable=False,
        server_default="v1", ...)
```
(rimuovi l'intero mapping `brain_version`; verifica che `String` resti importato/usato da altre colonne — sì).

- [ ] **Step 3: Ripulisci `test_analyst_schema.py`**

Cancella i due test legati alla colonna (righe ~21-26):
```python
def test_agent_brain_version_defaults_v1(db_session):
    assert _agent(db_session).brain_version == "v1"


def test_agent_brain_version_can_be_v2(db_session):
    assert _agent(db_session, brain_version="v2").brain_version == "v2"
```
Lascia `test_brain_v2_settings_present`, `test_market_brief_insert_and_nullable_payload` e i test dello schema brief.

- [ ] **Step 4: Ripulisci `test_analyst_orchestration.py`**

Riga ~61, togli `brain_version="v2"`:
```python
def _agent(session):
    a = Agent(name="T", cash_usd=Decimal("100"),
              duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1))
    session.add(a); session.commit()
    return a
```

- [ ] **Step 5: Suite backend verde (schema da `models`, no Alembic)**

Run: `cd backend && .venv/bin/pytest -q`
Expected: PASS. Nessun `Agent(brain_version=...)` residuo → nessun `TypeError`.

- [ ] **Step 6: Genera lo scheletro della migrazione**

Run: `cd backend && .venv/bin/alembic revision -m "drop agents.brain_version"`
Questo crea `alembic/versions/<hash>_drop_agents_brain_version.py` con `down_revision = '49407193a9ac'` (l'head singolo attuale).

- [ ] **Step 7: Scrivi upgrade/downgrade (solo la colonna, `market_briefs` intatta)**

Nel file appena creato, imposta i due corpi:
```python
def upgrade() -> None:
    op.drop_column("agents", "brain_version")


def downgrade() -> None:
    op.add_column("agents",
        sa.Column("brain_version", sa.String(length=10), nullable=False, server_default="v2"))
```
(Assicurati che `from alembic import op` e `import sqlalchemy as sa` siano presenti — lo scheletro li include.)

- [ ] **Step 8: Smoke della migrazione up/down su un DB scratch**

Contro un database usa-e-getta (Postgres di prod-parità, es. quello del compose dev — **mai** il DB di produzione):
```bash
cd backend
.venv/bin/alembic upgrade head        # applica il drop
.venv/bin/alembic downgrade -1        # riaggiunge la colonna
.venv/bin/alembic upgrade head        # riapplica
.venv/bin/alembic heads               # deve stampare UN solo head = la nuova revisione
```
Expected: nessun errore; `market_briefs` mai toccata; head singolo.

- [ ] **Step 9: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions backend/tests/test_analyst_schema.py backend/tests/test_analyst_orchestration.py
git commit -m "refactor(rm-v1): droppa colonna agents.brain_version (modello + migrazione)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: Pulizia contesto — rimuovi i campi morti `universe`/`observations` da `DecisionContext`

Dopo la rimozione del v1, `DecisionContext.universe` e `DecisionContext.observations` non sono più letti da nessun renderer (li usava solo `render_prompt`). Si rimuovono dal dataclass e da `build_context`, e si semplifica la guardia BUY. `CoinSnapshot`/`ObservationView` restano (usati da `AnalystContext`).

**Files:**
- Modify: `backend/app/brain/context.py` (dataclass `DecisionContext`; firma `build_context`)
- Modify: `backend/app/agents/runtime.py` (chiamata in `assemble_trader_context`; guardia riga ~232)
- Modify: `backend/tests/test_buy_guard.py` (chiamata `build_context`)

- [ ] **Step 1: Verifica i chiamanti di `build_context` con `universe`/`observations`**

Run: `cd backend && grep -rn "build_context(\|\.universe\|\.observations" app tests | grep -v "AnalystContext\|analyst"`
Expected: i chiamanti che passano `universe=` sono `assemble_trader_context` (in `runtime.py`) e il test `test_buy_guard.py`; l'unico lettore di `ctx.universe` è la guardia in `_run_decision_llm`. Nessun uso di `ctx.observations`. Se emerge altro, aggiornalo di conseguenza.

- [ ] **Step 2: Rimuovi i campi da `DecisionContext` e i parametri da `build_context`**

In `backend/app/brain/context.py`, nel dataclass `DecisionContext` cancella le righe:
```python
    universe: list[CoinSnapshot]
```
e
```python
    observations: list["ObservationView"] = field(default_factory=list)
```
Nella firma di `build_context` togli `universe` e `observations`:
```python
def build_context(*, instructions, cash_usd, holdings, recent_events, memory=None, brief=None, wake_reason=None) -> DecisionContext:
```
e nel corpo, nel costruttore `DecisionContext(...)`, togli `universe=universe` e `observations=observations or []`. (`field` non serve più se `observations` era l'unico uso: verifica l'import `from dataclasses import dataclass, field` — se `field` resta inutilizzato, riducilo a `from dataclasses import dataclass`.)

- [ ] **Step 3: Aggiorna `assemble_trader_context` e la guardia BUY in `runtime.py`**

In `assemble_trader_context`, togli `universe=[]` dalla chiamata a `build_context`:
```python
    return build_context(instructions=agent.instructions, cash_usd=agent.cash_usd,
                         holdings=holdings, recent_events=recent,
                         memory=memory, brief=brief, wake_reason=wake_reason)
```
In `_run_decision_llm`, semplifica la guardia (riga ~232):
```python
        universe_symbols = set(symbols)
```
(sostituisce `{c.symbol for c in ctx.universe} if ctx.universe else set(symbols)`).

- [ ] **Step 4: Aggiorna il test della guardia**

In `backend/tests/test_buy_guard.py`, nel fake context togli `universe=[]`:
```python
    async def _fake_ctx(session, ag, market, symbols, *, wake_reason=None):
        return build_context(instructions="", cash_usd=ag.cash_usd, holdings=[],
                             recent_events=[], brief=None, wake_reason=wake_reason)
```

- [ ] **Step 5: Suite backend verde**

Run: `cd backend && .venv/bin/pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/brain/context.py backend/app/agents/runtime.py backend/tests/test_buy_guard.py
git commit -m "refactor(rm-v1): rimuovi campi morti universe/observations da DecisionContext

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: Verifica finale end-to-end

- [ ] **Step 1: Nessun residuo `brain_version` nel codice vivo**

Run: `cd /Users/seb/Dev/gorillaradio/crypto-bot && grep -rn "brain_version\|BrainBadge\|brainVersion\|render_prompt\|build_agent_context\|_select_brain" backend/app backend/tests frontend/src`
Expected: **solo** la migrazione storica `backend/alembic/versions/49407193a9ac_*.py` (che crea la colonna) e la nuova migrazione (che la droppa). Zero hit in `app/`, `tests/`, `frontend/src`.

- [ ] **Step 2: Suite backend completa verde**

Run: `cd backend && .venv/bin/pytest -q`
Expected: PASS. Attesi ~**262** test (284 baseline − ~22 rimossi: 8 `test_brain_decide` + ~9 `test_brain_prompt` + 1 `test_select_brain_by_version` + 2 `build_agent_context` + 3 API + 2 `test_analyst_schema`). Il numero esatto è indicativo: conta che sia verde e coerente con i test rimossi.

- [ ] **Step 3: Frontend test + build verdi**

Run: `cd frontend && npm test && npm run build`
Expected: PASS + build pulita.

- [ ] **Step 4: (opzionale) Smoke app locale**

Se disponibile l'ambiente compose, avvia backend+frontend e verifica: creazione agente (senza campo brain), dashboard senza badge, pannello "Market brief" mostrato per ogni agente, monitor "Prompt" che mostra il prompt trader (con riga "Market brief").

---

## Self-Review

**Spec coverage** (contro l'overview approvato):
- Backend collapse dispatch → Task 2 ✓
- Brain v1 (`evaluate`/`decide`/`render_prompt`) → Task 3 ✓
- Monitor prompt → v2 → Task 1 ✓
- Scheduler gate incondizionato → Task 4 ✓
- API `brain_version` → Task 5 ✓
- DB colonna + migrazione (senza toccare `market_briefs`) → Task 7 ✓
- Frontend (badge, pannello, api.ts) → Task 6 ✓
- Test v1 → Task 2/3/4/5/7 ✓
- Pulizia opzionale `universe`/`observations` → Task 8 ✓

**Type/naming consistency:** `assemble_trader_context` definito in Task 1 e consumato da `preview.py` (Task 1) e usato internamente da `build_trader_context`; `evaluate_trader` importato in Task 2 coerente con `brain/__init__.py` (dove resta dopo Task 3). `test_brain_v2_dispatch.py` → `test_buy_guard.py` referenziato coerentemente in Task 2 e Task 8.

**Placeholder scan:** nessun "TBD"/"handle edge cases" — ogni step mostra il codice o il comando esatto. Unico punto non-deterministico per natura: l'hash di revisione Alembic (Step 6/7 del Task 7), generato dal comando `alembic revision` — corretto così.

**Dipendenze d'ordine:** Task 1 → 2 (preview smette di usare `build_agent_context` prima che venga rimosso); Task 5 → 6 (API prima del frontend); Task 7 richiede che 2/4/5 abbiano già tolto i `brain_version` dalle rispettive fixture; Task 8 dopo 2/3 (contesto non più letto dal v1).
