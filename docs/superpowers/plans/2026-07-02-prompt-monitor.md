# Monitor dei prompt per-agente — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un pannello read-only nella dashboard che, per un agente selezionato, mostra i prompt (decision/reflection/retry) renderizzati dal vivo con dati reali, usando lo stesso codice della pipeline.

**Architecture:** Estrarre la costruzione del contesto (`build_agent_context`) da `_run_decision_llm` così che pipeline reale e monitor la condividano (zero drift). Un helper `render_agent_prompts_preview` produce le 3 coppie system/user senza chiamare l'LLM né persistere. Un endpoint GET le espone; un pannello React le mostra.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pydantic v2, pytest (async, SQLite in-memory), React + TypeScript + shadcn/Tailwind, vitest.

**Spec di riferimento:** [docs/superpowers/specs/2026-07-01-prompt-monitor-design.md](../specs/2026-07-01-prompt-monitor-design.md)

## Global Constraints

- **Read-only, monitor-only.** Nessun editing dei prompt (fase successiva). Nessuna modifica al contratto JSON né a `schema.py`.
- **Nessuno storage nuovo, nessuna chiamata LLM.** La preview costruisce i prompt e basta.
- **Zero drift:** il monitor DEVE usare lo stesso `build_agent_context`/`render_prompt`/`build_reflection_prompt` della pipeline, non copie.
- **Auth:** l'endpoint usa `require_viewer_or_admin` (come gli altri GET dell'agente).
- **Branch:** `prompt-monitor` (già creato, impilato sul tip di `risk-thresholds-llm`). Restare su questo branch.
- Comandi backend: da `backend/`, venv attiva (`source .venv/bin/activate`). Test: `pytest`. Baseline attuale: **105 passed, 1 warning** (StarletteDeprecationWarning pre-esistente dal TestClient di FastAPI — non è codice nostro, resta).
- Comandi frontend: da `frontend/`. Typecheck/build: `npm run build`. Test: `npm test` (vitest).

## File Structure

| File | Responsabilità | Azione |
|------|----------------|--------|
| `backend/app/agents/runtime.py` | estrarre `build_agent_context` + `universe_size`; `_run_decision_llm` li riusa | Modify |
| `backend/app/brain/prompt.py` | `retry_user_suffix(error)` (estratto per anti-drift) | Modify |
| `backend/app/brain/__init__.py` | usa `retry_user_suffix` nel retry | Modify |
| `backend/app/agents/preview.py` | `render_agent_prompts_preview(session, agent, market)` | Create |
| `backend/app/api/schemas.py` | `PromptPair`, `PromptPreviewOut` | Modify |
| `backend/app/api/routes.py` | `market_dep` + `GET /agents/{id}/prompt` | Modify |
| `frontend/src/api.ts` | tipi `PromptPair`/`PromptPreview` + `getPrompt` | Modify |
| `frontend/src/components/PromptPanel.tsx` | `PromptPanel` (fetch) + `PromptView` (puro) | Create |
| `frontend/src/App.tsx` | montare `<PromptPanel agentId={selId} />` | Modify |
| `backend/tests/test_runtime.py`, `backend/tests/test_preview.py`, `backend/tests/test_brain_prompt.py`, `backend/tests/test_api.py` | test backend | Modify/Create |
| `frontend/src/__tests__/PromptView.test.tsx` | test frontend | Create |

---

### Task 1: Estrarre `build_agent_context` (refactor comportamento-preservante)

**Files:**
- Modify: `backend/app/agents/runtime.py`
- Test: `backend/tests/test_runtime.py`

**Interfaces:**
- Produces: `async build_agent_context(session, agent, market, symbols, *, wake_reason=None) -> DecisionContext`; `universe_size(agent) -> int`.
- Consumes: `build_context`, `MemoryView`, `Event`, `AgentMemory` (già importati in runtime.py).

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_runtime.py`, aggiungi in cima all'import di runtime `build_agent_context` e `universe_size`:

```python
from app.agents.runtime import run_heartbeat, run_decision, run_decision_guarded, build_agent_context, universe_size
```

Aggiungi i test (gli helper `_llm_agent`, `FakeMarketLLM`, `CoinSnapshot`, `Position`, `AgentMemory`, `Decimal` esistono già nel file):

```python
async def test_build_agent_context_assembles_from_live_data(db_session):
    agent = _llm_agent(db_session)
    agent.instructions = "compra basso vendi alto"
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("2"), avg_price=Decimal("100")))
    db_session.add(AgentMemory(agent_id=agent.id, section="coin_theses", content="BTC: bull"))
    db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("110"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("110"), (Decimal("109"), Decimal("111")))
    ctx = await build_agent_context(db_session, agent, market, ["BTCUSDT"], wake_reason="w")
    assert ctx.instructions == "compra basso vendi alto"
    assert ctx.wake_reason == "w"
    assert [c.symbol for c in ctx.universe] == ["BTCUSDT"]
    assert any(p.symbol == "BTCUSDT" and p.last_price == Decimal("110") for p in ctx.positions)
    assert ctx.memory.coin_theses == "BTC: bull"


def test_universe_size_maps_universe_field():
    class A: universe = "TOP_100"
    class B: universe = "TOP_50"
    assert universe_size(A()) == 100
    assert universe_size(B()) == 50
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_runtime.py -k "build_agent_context or universe_size" -v`
Expected: FAIL (`cannot import name 'build_agent_context'`).

- [ ] **Step 3: Add `universe_size` and `build_agent_context`, refactor `_run_decision_llm`**

In `backend/app/agents/runtime.py`, aggiungi **dopo gli import** (prima di `run_heartbeat`):

```python
def universe_size(agent) -> int:
    return 100 if agent.universe == "TOP_100" else 50


async def build_agent_context(session, agent, market, symbols, *, wake_reason=None):
    """Costruisce il DecisionContext dai dati vivi (universo, posizioni, eventi recenti,
    memoria). Usata sia dal ciclo di decisione sia dal monitor dei prompt, così il monitor
    mostra esattamente ciò che la pipeline invierebbe."""
    universe = await market.get_universe_snapshot(symbols)

    holdings = []
    for pos in agent.positions:
        last = await market.get_price(pos.symbol)
        holdings.append((pos.symbol, pos.quantity, pos.avg_price, last))

    recent = [e.message for e in (
        session.query(Event).filter_by(agent_id=agent.id)
        .order_by(Event.timestamp.desc()).limit(10).all())]

    mem_rows = {r.section: r.content for r in
                session.query(AgentMemory).filter_by(agent_id=agent.id).all()}
    memory = MemoryView(
        coin_theses=mem_rows.get("coin_theses", ""),
        trade_lessons=mem_rows.get("trade_lessons", ""),
        strategy_notes=mem_rows.get("strategy_notes", ""),
    )
    return build_context(instructions=agent.instructions, cash_usd=agent.cash_usd,
                         holdings=holdings, universe=universe, recent_events=recent,
                         memory=memory, wake_reason=wake_reason)
```

Poi nel `try` di `_run_decision_llm`, sostituisci il blocco che va da `universe = await market.get_universe_snapshot(symbols)` fino a `memory = MemoryView(... )` e la chiamata a `build_context(...)` con:

```python
    try:
        ctx = await build_agent_context(session, agent, market, symbols, wake_reason=wake_reason)
        universe_symbols = {c.symbol for c in ctx.universe}
        adapter = make_adapter(agent.model_provider, agent.model_name)
        decision = brain_decide(ctx, adapter)
```

(cioè: `build_agent_context` rimpiazza tutta la raccolta dati; `universe_symbols` si deriva da `ctx.universe`; `adapter`/`decision` restano.)

Infine, nel blocco `if closed_trades:`, cambia `reflect(memory, ...)` in `reflect(ctx.memory, ...)`:

```python
            new_mem = reflect(ctx.memory, closed_trades, held_symbols, agent.instructions, adapter)
```

- [ ] **Step 4: Run tests to verify they pass (nessuna regressione)**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_runtime.py tests/test_jobs.py -v`
Expected: PASS (i nuovi test + TUTTI i test decision/heartbeat preesistenti — il refactor è comportamento-preservante).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/runtime.py backend/tests/test_runtime.py
git commit -m "refactor(runtime): extract build_agent_context + universe_size for reuse"
```

---

### Task 2: Modulo di preview + estrazione del suffisso di retry

**Files:**
- Modify: `backend/app/brain/prompt.py`, `backend/app/brain/__init__.py`
- Create: `backend/app/agents/preview.py`
- Test: `backend/tests/test_brain_prompt.py`, `backend/tests/test_preview.py`

**Interfaces:**
- Consumes: `build_agent_context`, `universe_size` (Task 1); `render_prompt`, `build_reflection_prompt`, `ClosedTrade`.
- Produces: `retry_user_suffix(error: str) -> str`; `async render_agent_prompts_preview(session, agent, market) -> dict` con chiavi `decision`/`reflection`/`retry`, ognuna `{system, user, note?}`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_brain_prompt.py` aggiungi (import: `from app.brain.prompt import retry_user_suffix`):

```python
def test_retry_user_suffix_contains_schema_and_correction_ask():
    s = retry_user_suffix("boom")
    assert "boom" in s
    assert "not valid JSON" in s
    assert "corrected JSON" in s
```

Crea `backend/tests/test_preview.py`:

```python
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.db.models import Agent, Position, AgentMemory
from app.brain.context import CoinSnapshot
from app.agents.preview import render_agent_prompts_preview


class FakeMarketPreview:
    def __init__(self, snapshot, price, symbols=None):
        self._snap, self._price, self._symbols = snapshot, price, symbols or ["BTCUSDT"]
    async def get_top_symbols(self, quote, n): return self._symbols
    async def get_universe_snapshot(self, symbols): return self._snap
    async def get_price(self, symbol): return self._price


def _agent(session, instructions=""):
    a = Agent(name="P", instructions=instructions,
              duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("100"), model_name="deepseek/deepseek-v4-flash")
    session.add(a); session.commit()
    return a


async def test_preview_returns_three_prompts_with_real_data(db_session):
    agent = _agent(db_session, instructions="compra basso vendi alto")
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.add(AgentMemory(agent_id=agent.id, section="trade_lessons", content="cut losers"))
    db_session.commit()
    market = FakeMarketPreview([CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("3"))], Decimal("120"))
    out = await render_agent_prompts_preview(db_session, agent, market)
    assert set(out) == {"decision", "reflection", "retry"}
    assert "compra basso vendi alto" in out["decision"]["system"]     # istruzioni operatore
    assert "BTCUSDT" in out["decision"]["user"]                        # universo/posizione
    assert "cut losers" in out["decision"]["user"]                     # memoria
    assert out["retry"]["user"].startswith(out["decision"]["user"])    # retry = decision user + suffisso
    assert "corrected JSON" in out["retry"]["user"]
    assert "BTCUSDT" in out["reflection"]["user"]                      # posizione come trade ipotetico


async def test_preview_no_positions_has_note(db_session):
    agent = _agent(db_session)
    market = FakeMarketPreview([CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("3"))], Decimal("120"))
    out = await render_agent_prompts_preview(db_session, agent, market)
    assert "Nessuna posizione" in out["reflection"]["note"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_brain_prompt.py -k retry_user_suffix tests/test_preview.py -v`
Expected: FAIL (`cannot import name 'retry_user_suffix'` / `No module named 'app.agents.preview'`).

- [ ] **Step 3: Add `retry_user_suffix` and use it in `decide`**

In `backend/app/brain/prompt.py`, aggiungi in fondo:

```python
def retry_user_suffix(error: str) -> str:
    """Suffisso appeso al messaggio user quando la risposta non è JSON valido.
    Condiviso tra decide() (retry reale) e il monitor dei prompt (con errore d'esempio)."""
    return (f"\n\nYour previous reply was not valid JSON for the schema "
            f"({error}). Reply with ONLY the corrected JSON object.")
```

In `backend/app/brain/__init__.py`, cambia l'import e la chiamata di retry:

```python
from app.brain.prompt import render_prompt, retry_user_suffix
```

e sostituisci il blocco `raw2 = adapter.complete_json(...)` con:

```python
            raw2 = adapter.complete_json(system, user + retry_user_suffix(str(first_err)))
```

- [ ] **Step 4: Create the preview module**

Crea `backend/app/agents/preview.py`:

```python
from app.agents.runtime import build_agent_context, universe_size
from app.brain.prompt import render_prompt, retry_user_suffix
from app.brain.memory import build_reflection_prompt, ClosedTrade

_RETRY_EXAMPLE_ERROR = ("1 validation error for Decision: actions.0.type — "
                        "input should be 'BUY', 'SELL' or 'HOLD'")


async def render_agent_prompts_preview(session, agent, market) -> dict:
    """Ricostruisce i prompt (decision/reflection/retry) che la pipeline invierebbe ORA per
    questo agente, con dati reali. Nessuna chiamata LLM, nessuna persistenza."""
    symbols = await market.get_top_symbols("USDT", universe_size(agent))
    ctx = await build_agent_context(session, agent, market, symbols, wake_reason=None)
    d_system, d_user = render_prompt(ctx)

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

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_brain_prompt.py tests/test_preview.py tests/test_brain_decide.py -v`
Expected: PASS (nuovi + `decide()` preesistente col retry ancora verde).

- [ ] **Step 6: Commit**

```bash
git add backend/app/brain/prompt.py backend/app/brain/__init__.py backend/app/agents/preview.py backend/tests/test_brain_prompt.py backend/tests/test_preview.py
git commit -m "feat(preview): live prompt preview helper + shared retry suffix"
```

---

### Task 3: Endpoint API `GET /agents/{id}/prompt`

**Files:**
- Modify: `backend/app/api/schemas.py`, `backend/app/api/routes.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `render_agent_prompts_preview` (Task 2).
- Produces: `GET /api/agents/{id}/prompt` → `PromptPreviewOut { decision, reflection, retry }` (ognuno `PromptPair { system, user, note? }`); `market_dep()` iniettabile nei test.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_api.py` aggiungi (in cima al file `from app.api import routes, auth` esiste già; aggiungi l'import del fake e i test):

```python
from app.brain.context import CoinSnapshot


class FakeMarketPreview:
    def __init__(self, snapshot, price, symbols=None):
        self._snap, self._price, self._symbols = snapshot, price, symbols or ["BTCUSDT"]
    async def get_top_symbols(self, quote, n): return self._symbols
    async def get_universe_snapshot(self, symbols): return self._snap
    async def get_price(self, symbol): return self._price


def _use_fake_market(snapshot=None, price=Decimal("120")):
    snap = snapshot if snapshot is not None else [CoinSnapshot("BTCUSDT", price, Decimal("1"))]
    app.dependency_overrides[routes.market_dep] = lambda: FakeMarketPreview(snap, price)


def test_get_prompt_returns_three_prompts(db_session):
    agent = Agent(name="P", instructions="compra basso",
                  duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"), model_name="deepseek/deepseek-v4-flash")
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_api.py -k "get_prompt" -v`
Expected: FAIL (`AttributeError: module ... has no attribute 'market_dep'` / 404 route non trovata → 405/404 diverso).

- [ ] **Step 3: Add schemas**

In `backend/app/api/schemas.py`, aggiungi (dopo `MemoryOut`):

```python
class PromptPair(BaseModel):
    system: str
    user: str
    note: str | None = None


class PromptPreviewOut(BaseModel):
    decision: PromptPair
    reflection: PromptPair
    retry: PromptPair
```

- [ ] **Step 4: Add the market dependency and the endpoint**

In `backend/app/api/routes.py`, aggiungi agli import:

```python
from app.market.binance import BinanceClient
from app.agents.preview import render_agent_prompts_preview
```

e aggiungi `PromptPreviewOut` alla riga di import da `app.api.schemas`.

Aggiungi la dependency (vicino a `_latest_equity`, a livello modulo):

```python
def market_dep() -> BinanceClient:
    return BinanceClient()
```

Aggiungi l'endpoint (dopo `get_events`):

```python
@router.get("/agents/{agent_id}/prompt", response_model=PromptPreviewOut)
async def get_prompt(agent_id: int, session=Depends(session_dep),
                     market=Depends(market_dep), _: str = Depends(require_viewer_or_admin)):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    try:
        return await render_agent_prompts_preview(session, agent, market)
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"prompt preview unavailable: {exc}")
```

Nota: l'auth è delegata a `require_viewer_or_admin` (stesso dep degli altri GET, coperto da `test_auth.py`); nessun test 401 dedicato qui.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_api.py -v`
Expected: PASS (nuovi + preesistenti; `_clear_overrides` autouse ripulisce l'override di `market_dep`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api.py
git commit -m "feat(api): GET /agents/{id}/prompt live prompt preview endpoint"
```

---

### Task 4: Frontend — pannello "Prompt" nella scheda agente

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/App.tsx`
- Create: `frontend/src/components/PromptPanel.tsx`
- Test: `frontend/src/__tests__/PromptView.test.tsx`

**Interfaces:**
- Consumes: `GET /api/agents/{id}/prompt` (Task 3).
- Produces: `getPrompt(id)`, tipi `PromptPreview`/`PromptPair`; componenti `PromptPanel` (fetch) e `PromptView` (puro).

- [ ] **Step 1: Extend the API client**

In `frontend/src/api.ts`, dopo `export type AgentMemory = {...}` aggiungi i tipi:

```typescript
export type PromptPair = { system: string; user: string; note?: string | null };
export type PromptPreview = { decision: PromptPair; reflection: PromptPair; retry: PromptPair };
```

e dopo `export const getMemory = ...` aggiungi:

```typescript
export const getPrompt = (id: number) => get<PromptPreview>(`/api/agents/${id}/prompt`);
```

- [ ] **Step 2: Write the failing frontend test**

Crea `frontend/src/__tests__/PromptView.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { PromptView } from "../components/PromptPanel";
import type { PromptPreview } from "../api";

const preview: PromptPreview = {
  decision: { system: "SYS-DECISION", user: "USER-DECISION" },
  reflection: { system: "SYS-REFLECT", user: "USER-REFLECT", note: "nota reflection" },
  retry: { system: "SYS-DECISION", user: "USER-RETRY" },
};

describe("PromptView", () => {
  it("shows the decision prompt by default", () => {
    render(<PromptView preview={preview} />);
    expect(screen.getByText("SYS-DECISION")).toBeInTheDocument();
    expect(screen.getByText("USER-DECISION")).toBeInTheDocument();
  });

  it("switches to reflection and shows its note", () => {
    render(<PromptView preview={preview} />);
    fireEvent.click(screen.getByRole("button", { name: "Reflection" }));
    expect(screen.getByText("USER-REFLECT")).toBeInTheDocument();
    expect(screen.getByText("nota reflection")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npm test -- PromptView`
Expected: FAIL (modulo `PromptPanel` inesistente).

- [ ] **Step 4: Create the component**

Crea `frontend/src/components/PromptPanel.tsx`:

```tsx
import { useEffect, useState } from "react";
import { getPrompt, AuthError, type PromptPreview } from "../api";

const PIECES: { key: keyof PromptPreview; label: string }[] = [
  { key: "decision", label: "Decisione" },
  { key: "reflection", label: "Reflection" },
  { key: "retry", label: "Retry" },
];

export function PromptView({ preview }: { preview: PromptPreview }) {
  const [active, setActive] = useState<keyof PromptPreview>("decision");
  const pair = preview[active];
  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-2">
        {PIECES.map((p) => (
          <button
            key={p.key}
            onClick={() => setActive(p.key)}
            className={`text-xs px-2 py-1 rounded ${
              active === p.key ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>
      {pair.note && <p className="text-xs text-muted-foreground">{pair.note}</p>}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">system</h3>
        <pre className="text-xs bg-muted rounded p-2 overflow-auto max-h-64 whitespace-pre-wrap">{pair.system}</pre>
      </div>
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">user</h3>
        <pre className="text-xs bg-muted rounded p-2 overflow-auto max-h-64 whitespace-pre-wrap">{pair.user}</pre>
      </div>
    </div>
  );
}

export function PromptPanel({ agentId }: { agentId: number }) {
  const [preview, setPreview] = useState<PromptPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setPreview(null);
    setError(null);
    getPrompt(agentId)
      .then((p) => alive && setPreview(p))
      .catch((e) => alive && setError(e instanceof AuthError ? "Non autorizzato" : "Prompt non disponibile"));
    return () => {
      alive = false;
    };
  }, [agentId]);
  if (error) return <p className="text-sm text-muted-foreground">{error}</p>;
  if (!preview) return <p className="text-sm text-muted-foreground">Carico i prompt…</p>;
  return <PromptView preview={preview} />;
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npm test -- PromptView`
Expected: PASS.

- [ ] **Step 6: Mount the panel in the agent detail**

In `frontend/src/App.tsx`, aggiungi l'import (vicino agli altri import di componenti, es. dopo la riga `import { MemoryPanel } ...`):

```tsx
import { PromptPanel } from "./components/PromptPanel";
```

Poi, subito **dopo** la Card "Memoria" (il blocco che chiude a riga ~215, `</Card>` dopo `{memory ? <MemoryPanel .../> : ...}`), aggiungi una nuova Card:

```tsx
            <Card>
              <CardContent>
                <h2 className="text-sm font-semibold text-muted-foreground mb-3">Prompt (inviati all'LLM)</h2>
                <PromptPanel agentId={selId} />
              </CardContent>
            </Card>
```

(`selId` è la variabile dell'agente selezionato già usata a `App.tsx:84-85` per `getPositions`/`getMemory`.)

- [ ] **Step 7: Typecheck / build**

Run: `cd frontend && npm run build`
Expected: build senza errori TypeScript.

- [ ] **Step 8: Run the full frontend test suite**

Run: `cd frontend && npm test`
Expected: PASS (PromptView + i test preesistenti).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api.ts frontend/src/components/PromptPanel.tsx frontend/src/App.tsx frontend/src/__tests__/PromptView.test.tsx
git commit -m "feat(frontend): per-agent prompt monitor panel"
```

---

## Self-Review (eseguita in fase di stesura)

- **Copertura spec:** anti-drift via `build_agent_context` (T1) ✓; helper preview con decision/reflection/retry live (T2) ✓; retry-suffix estratto per non divergere (T2) ✓; endpoint read-only `require_viewer_or_admin` (T3) ✓; pannello frontend read-only per-agente (T4) ✓. Non-obiettivi rispettati: nessun editing, nessuno storage, nessuna chiamata LLM, nessun cambio a `schema.py`.
- **Coerenza tipi:** `build_agent_context(...) -> DecisionContext` prodotto in T1, consumato in T2; `render_agent_prompts_preview(...) -> dict{decision,reflection,retry}` prodotto in T2, esposto come `PromptPreviewOut` in T3, tipizzato come `PromptPreview` in T4; `universe_size` prodotto in T1, usato in T2.
- **Reflection senza posizioni:** gestita con nota dedicata (T2), testata (T2 Step 1) ✓.
- **Refactor comportamento-preservante:** T1 non aggiunge/rimuove eventi o persistenza; coperto dai test runtime esistenti (T1 Step 4).
- **Auth:** endpoint dietro `require_viewer_or_admin` come i sibling GET; test 401 delegato a `test_auth.py` (coerente con lo stile del repo).
- **Costo runtime:** ogni apertura del pannello = 2 chiamate Binance (`get_top_symbols` + `get_universe_snapshot`) + N `get_price`; accettabile on-demand (non bloccante per lo switch agente perché il pannello fa fetch proprio).
- **Verifica browser:** l'E2E autenticato non è eseguibile in locale (auth dev non wired: `admin_password` vuota, nessun proxy) — come per la feature rischio. Gate = `npm run build` + test vitest; la verifica visiva richiede uno stack configurato.
