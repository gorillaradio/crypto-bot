# Agent CRUD UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user create, edit (name only), and delete trading agents from the dashboard via modal dialogs, with the per-agent universe actually driving the scheduler.

**Architecture:** Add `PATCH`/`DELETE` endpoints and a `universe` field to agent creation on the FastAPI backend; make the decision scheduler resolve symbols per-agent by universe; add two React modal components and wire create/edit/delete controls into the existing single-page dashboard.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic (backend), pytest + pytest-asyncio (backend tests), React + TypeScript + Vite (frontend), Vitest + @testing-library/react (frontend tests).

## Global Constraints

- Backend tests run from `backend/` with `pytest` (config: `asyncio_mode = "auto"`, so async tests need no decorator). Use the `db_session` fixture (in-memory SQLite) from `backend/tests/conftest.py`.
- Frontend tests run from `frontend/` with `npm test` (`vitest run`). Frontend build/typecheck: `npm run build` (`tsc -b && vite build`). Lint: `npm run lint`.
- Universe values are the exact strings `"TOP_50"` and `"TOP_100"`. `TOP_100` is the default.
- Model providers are exactly `"anthropic"`, `"deepseek"`, `"glm"`, `"openrouter"`. Strategies are `"sma"` and `"llm"`.
- Editable-after-creation field is `name` ONLY. All other fields are immutable post-creation.
- Delete is a hard delete; FKs have NO `ON DELETE CASCADE`, so child rows must be deleted explicitly before the agent.
- UI copy is in Italian, matching the existing dashboard (e.g. "nuovo agente", "modifica", "elimina").
- Respect `prefers-reduced-motion` for modal transitions (PRODUCT.md accessibility target).

---

### Task 1: Backend — `universe` on agent creation

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/routes.py:47-64`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Produces: `AgentCreate` now has `universe: Literal["TOP_50", "TOP_100"] = "TOP_100"`. `POST /api/agents` persists `agent.universe = payload.universe`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_api.py`:

```python
from app.db.models import Agent as AgentModel  # add near other imports if not present


def test_create_agent_persists_chosen_universe(db_session):
    client = _client(db_session)
    resp = client.post("/api/agents", json={
        "name": "Small", "instructions": "", "duration_days": 7, "universe": "TOP_50"})
    assert resp.status_code == 201
    agent = db_session.query(AgentModel).filter_by(name="Small").one()
    assert agent.universe == "TOP_50"


def test_create_agent_defaults_universe_to_top_100(db_session):
    client = _client(db_session)
    resp = client.post("/api/agents", json={
        "name": "Big", "instructions": "", "duration_days": 7})
    assert resp.status_code == 201
    agent = db_session.query(AgentModel).filter_by(name="Big").one()
    assert agent.universe == "TOP_100"


def test_create_agent_rejects_invalid_universe(db_session):
    client = _client(db_session)
    resp = client.post("/api/agents", json={
        "name": "Bad", "duration_days": 7, "universe": "TOP_500"})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_api.py -k universe -v`
Expected: FAIL — `TOP_50` is currently ignored (agent stores the global default), and `TOP_500` is currently accepted.

- [ ] **Step 3: Add `universe` to `AgentCreate`**

In `backend/app/api/schemas.py`, edit `AgentCreate`:

```python
class AgentCreate(BaseModel):
    name: str
    instructions: str = ""
    duration_days: int = 7
    strategy: Literal["sma", "llm"] = "llm"
    model_provider: Literal["anthropic", "deepseek", "glm", "openrouter"] | None = None
    model_name: str | None = None
    universe: Literal["TOP_50", "TOP_100"] = "TOP_100"
```

- [ ] **Step 4: Use `payload.universe` in the create route**

In `backend/app/api/routes.py`, in `create_agent`, change the `universe=` line:

```python
        universe=payload.universe,
```

(replacing `universe=settings.universe_default,`)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_api.py -k universe -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api.py
git commit -m "feat(backend): accept per-agent universe on creation"
```

---

### Task 2: Backend — `PATCH /agents/{id}` to rename

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Produces: `AgentUpdate(BaseModel)` with single field `name: str`. `PATCH /api/agents/{agent_id}` returns `AgentOut` (200) or 404.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_api.py`:

```python
def test_patch_agent_renames(db_session):
    client = _client(db_session)
    created = client.post("/api/agents", json={"name": "Old", "duration_days": 7}).json()
    resp = client.patch(f"/api/agents/{created['id']}", json={"name": "New"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"
    assert db_session.get(AgentModel, created["id"]).name == "New"


def test_patch_agent_404_when_missing(db_session):
    client = _client(db_session)
    resp = client.patch("/api/agents/9999", json={"name": "X"})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_api.py -k patch -v`
Expected: FAIL — `405 Method Not Allowed` (no PATCH route).

- [ ] **Step 3: Add `AgentUpdate` schema**

In `backend/app/api/schemas.py`, add after `AgentCreate`:

```python
class AgentUpdate(BaseModel):
    name: str
```

- [ ] **Step 4: Add the PATCH route**

In `backend/app/api/routes.py`, update the import line to include `AgentUpdate`:

```python
from app.api.schemas import AgentCreate, AgentOut, AgentUpdate, EquityPoint, EventOut, MemoryOut, PositionOut
```

Add this route after `get_agent`:

```python
@router.patch("/agents/{agent_id}", response_model=AgentOut)
def update_agent(agent_id: int, payload: AgentUpdate, session=Depends(session_dep)):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    agent.name = payload.name
    session.commit()
    session.refresh(agent)
    return _agent_out(session, agent)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_api.py -k patch -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api.py
git commit -m "feat(backend): PATCH /agents/:id to rename"
```

---

### Task 3: Backend — `DELETE /agents/{id}` with cascade

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Produces: `DELETE /api/agents/{agent_id}` returns 204 on success, 404 if missing. Deletes the agent and all child rows (`Position`, `Trade`, `EquitySnapshot`, `Event`, `AgentMemory`).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_api.py` (extend imports to include the child models):

```python
from datetime import datetime, timezone, timedelta
from app.db.models import Position, Trade, Event, AgentMemory  # add alongside existing imports


def test_delete_agent_removes_agent_and_children(db_session):
    client = _client(db_session)
    created = client.post("/api/agents", json={"name": "Doomed", "duration_days": 7}).json()
    aid = created["id"]
    db_session.add_all([
        Position(agent_id=aid, symbol="BTCUSDT", quantity=Decimal("1"), avg_price=Decimal("100")),
        Trade(agent_id=aid, symbol="BTCUSDT", side="BUY", quantity=Decimal("1"),
              price=Decimal("100"), fee=Decimal("0.1")),
        EquitySnapshot(agent_id=aid, equity_usd=Decimal("100")),
        Event(agent_id=aid, kind="decision", message="hi"),
        AgentMemory(agent_id=aid, section="coin_theses", content="BTC: bull"),
    ])
    db_session.commit()

    resp = client.delete(f"/api/agents/{aid}")
    assert resp.status_code == 204
    assert db_session.get(AgentModel, aid) is None
    assert db_session.query(Position).filter_by(agent_id=aid).count() == 0
    assert db_session.query(Trade).filter_by(agent_id=aid).count() == 0
    assert db_session.query(EquitySnapshot).filter_by(agent_id=aid).count() == 0
    assert db_session.query(Event).filter_by(agent_id=aid).count() == 0
    assert db_session.query(AgentMemory).filter_by(agent_id=aid).count() == 0


def test_delete_agent_404_when_missing(db_session):
    client = _client(db_session)
    resp = client.delete("/api/agents/9999")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_api.py -k delete -v`
Expected: FAIL — `405 Method Not Allowed` (no DELETE route).

- [ ] **Step 3: Add the DELETE route**

In `backend/app/api/routes.py`, update the models import to include `Trade`:

```python
from app.db.models import Agent, AgentMemory, EquitySnapshot, Event, Position, Trade
```

Add this route after `update_agent`:

```python
@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(agent_id: int, session=Depends(session_dep)):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    for model in (Position, Trade, EquitySnapshot, Event, AgentMemory):
        session.query(model).filter_by(agent_id=agent_id).delete(synchronize_session=False)
    session.delete(agent)
    session.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_api.py -k delete -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api.py
git commit -m "feat(backend): DELETE /agents/:id with cascade"
```

---

### Task 4: Backend — scheduler resolves symbols per-agent universe

**Files:**
- Modify: `backend/app/scheduler/jobs.py:25-36`
- Test: `backend/tests/test_jobs.py` (create)

**Interfaces:**
- Consumes: `agent.universe` (`"TOP_50"` | `"TOP_100"`).
- Produces: helper `_universe_size(agent) -> int` (50 or 100); `_decision_tick` fetches top symbols once per distinct size and passes each agent the list matching its own universe.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_jobs.py`:

```python
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import app.scheduler.jobs as jobs
from app.db.models import Agent


def _agent(session, name, universe):
    now = datetime.now(timezone.utc)
    a = Agent(name=name, duration_start=now, duration_end=now + timedelta(days=7),
              cash_usd=Decimal("100"), universe=universe, status="running")
    session.add(a)
    session.commit()
    return a


async def test_decision_tick_uses_per_agent_universe(db_session, monkeypatch):
    _agent(db_session, "small", "TOP_50")
    _agent(db_session, "big", "TOP_100")

    fetched: dict[int, int] = {}
    passed: dict[str, list[str]] = {}

    class FakeMarket:
        async def get_top_symbols(self, quote="USDT", n=100):
            fetched[n] = fetched.get(n, 0) + 1
            return [f"SYM{n}"]

    async def fake_run_decision(session, agent, market, symbols, buy_usd, **kw):
        passed[agent.name] = symbols

    @contextmanager
    def fake_get_session():
        yield db_session

    monkeypatch.setattr(jobs, "BinanceClient", lambda: FakeMarket())
    monkeypatch.setattr(jobs, "run_decision", fake_run_decision)
    monkeypatch.setattr(jobs, "get_session", fake_get_session)

    await jobs._decision_tick()

    assert passed["small"] == ["SYM50"]
    assert passed["big"] == ["SYM100"]
    assert fetched == {50: 1, 100: 1}  # one fetch per distinct size, not per agent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_jobs.py -v`
Expected: FAIL — current `_decision_tick` fetches one list from `settings.universe_default` and gives both agents the same symbols.

- [ ] **Step 3: Rewrite `_decision_tick`**

In `backend/app/scheduler/jobs.py`, replace the `_decision_tick` function with:

```python
def _universe_size(agent: Agent) -> int:
    return 100 if agent.universe == "TOP_100" else 50


async def _decision_tick():
    market = BinanceClient()
    symbols_cache: dict[int, list[str]] = {}
    with get_session() as session:
        for agent in session.query(Agent).filter_by(status="running").all():
            try:
                n = _universe_size(agent)
                if n not in symbols_cache:
                    symbols_cache[n] = await market.get_top_symbols("USDT", n)
                buy_usd = settings.initial_capital_usd / Decimal("10")
                await run_decision(session, agent, market, symbols_cache[n], buy_usd)
            except Exception as exc:
                logger.error("decision tick failed for agent %s: %s", agent.id, exc)
                session.rollback()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_jobs.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/scheduler/jobs.py backend/tests/test_jobs.py
git commit -m "feat(backend): scheduler resolves symbols per-agent universe"
```

---

### Task 5: Frontend — API client mutations

**Files:**
- Modify: `frontend/src/api.ts`

**Interfaces:**
- Produces:
  - `type AgentCreateInput = { name: string; instructions: string; duration_days: number; strategy: "sma" | "llm"; model_provider: "anthropic" | "deepseek" | "glm" | "openrouter" | null; model_name: string | null; universe: "TOP_50" | "TOP_100" }`
  - `createAgent(input: AgentCreateInput): Promise<Agent>`
  - `updateAgent(id: number, input: { name: string }): Promise<Agent>`
  - `deleteAgent(id: number): Promise<void>`

- [ ] **Step 1: Add types and mutation helpers to `api.ts`**

Append to `frontend/src/api.ts`:

```typescript
export type AgentCreateInput = {
  name: string;
  instructions: string;
  duration_days: number;
  strategy: "sma" | "llm";
  model_provider: "anthropic" | "deepseek" | "glm" | "openrouter" | null;
  model_name: string | null;
  universe: "TOP_50" | "TOP_100";
};

async function mutate<T>(path: string, method: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.status === 204 ? (undefined as T) : r.json();
}

export const createAgent = (input: AgentCreateInput) =>
  mutate<Agent>("/api/agents", "POST", input);
export const updateAgent = (id: number, input: { name: string }) =>
  mutate<Agent>(`/api/agents/${id}`, "PATCH", input);
export const deleteAgent = (id: number) =>
  mutate<void>(`/api/agents/${id}`, "DELETE");
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run build`
Expected: build succeeds (no type errors).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api.ts
git commit -m "feat(frontend): API client for agent create/update/delete"
```

---

### Task 6: Frontend — `AgentFormModal` component

**Files:**
- Create: `frontend/src/components/AgentFormModal.tsx`
- Test: `frontend/src/__tests__/AgentFormModal.test.tsx`

**Interfaces:**
- Consumes: `createAgent`, `updateAgent`, `AgentCreateInput`, `Agent` from `../api`.
- Produces: `AgentFormModal` with props
  `{ mode: "create" } | { mode: "edit"; agent: Agent }`, plus `onClose: () => void` and `onSaved: (agent: Agent) => void`.
  - Create mode: renders all fields; when `strategy === "llm"` shows provider select + `model_name` input, hidden when `"sma"`. Submit disabled while `name` is empty or `duration_days < 1`.
  - Edit mode: only the `name` input is editable; shows a note that other fields can't be changed.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/__tests__/AgentFormModal.test.tsx`:

```typescript
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AgentFormModal } from "../components/AgentFormModal";

vi.mock("../api", () => ({
  createAgent: vi.fn(),
  updateAgent: vi.fn(),
}));
import { createAgent, updateAgent } from "../api";

beforeEach(() => {
  vi.mocked(createAgent).mockReset();
  vi.mocked(updateAgent).mockReset();
});

describe("AgentFormModal create", () => {
  it("disables submit until a name is entered", () => {
    render(<AgentFormModal mode="create" onClose={() => {}} onSaved={() => {}} />);
    const submit = screen.getByRole("button", { name: /crea/i });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/nome/i), { target: { value: "Alpha" } });
    expect(submit).not.toBeDisabled();
  });

  it("hides model fields when strategy is sma", () => {
    render(<AgentFormModal mode="create" onClose={() => {}} onSaved={() => {}} />);
    fireEvent.change(screen.getByLabelText(/strategia/i), { target: { value: "sma" } });
    expect(screen.queryByLabelText(/provider/i)).not.toBeInTheDocument();
  });

  it("submits the form payload to createAgent", async () => {
    const onSaved = vi.fn();
    vi.mocked(createAgent).mockResolvedValue({ id: 1, name: "Alpha" } as never);
    render(<AgentFormModal mode="create" onClose={() => {}} onSaved={onSaved} />);
    fireEvent.change(screen.getByLabelText(/nome/i), { target: { value: "Alpha" } });
    fireEvent.click(screen.getByRole("button", { name: /crea/i }));
    await waitFor(() => expect(createAgent).toHaveBeenCalledTimes(1));
    expect(vi.mocked(createAgent).mock.calls[0][0]).toMatchObject({ name: "Alpha" });
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });
});

describe("AgentFormModal edit", () => {
  it("only allows renaming and calls updateAgent", async () => {
    const onSaved = vi.fn();
    vi.mocked(updateAgent).mockResolvedValue({ id: 2, name: "Renamed" } as never);
    const agent = { id: 2, name: "Old", status: "running", instructions: "",
      cash_usd: "100", equity: "100", return_pct: "0",
      duration_start: "", duration_end: "" };
    render(<AgentFormModal mode="edit" agent={agent} onClose={() => {}} onSaved={onSaved} />);
    expect(screen.queryByLabelText(/strategia/i)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/nome/i), { target: { value: "Renamed" } });
    fireEvent.click(screen.getByRole("button", { name: /salva/i }));
    await waitFor(() => expect(updateAgent).toHaveBeenCalledWith(2, { name: "Renamed" }));
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- AgentFormModal`
Expected: FAIL — component file does not exist.

- [ ] **Step 3: Implement `AgentFormModal`**

Create `frontend/src/components/AgentFormModal.tsx`:

```typescript
import { useState } from "react";
import { createAgent, updateAgent, type Agent, type AgentCreateInput } from "../api";

type Props =
  | { mode: "create"; onClose: () => void; onSaved: (a: Agent) => void }
  | { mode: "edit"; agent: Agent; onClose: () => void; onSaved: (a: Agent) => void };

const PROVIDERS = ["anthropic", "deepseek", "glm", "openrouter"] as const;

export function AgentFormModal(props: Props) {
  const isEdit = props.mode === "edit";
  const [name, setName] = useState(isEdit ? props.agent.name : "");
  const [instructions, setInstructions] = useState("");
  const [durationDays, setDurationDays] = useState(7);
  const [strategy, setStrategy] = useState<"sma" | "llm">("llm");
  const [provider, setProvider] = useState<(typeof PROVIDERS)[number]>("anthropic");
  const [modelName, setModelName] = useState("");
  const [universe, setUniverse] = useState<"TOP_50" | "TOP_100">("TOP_100");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const valid = name.trim().length > 0 && durationDays >= 1;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!valid || saving) return;
    setSaving(true);
    setError("");
    try {
      if (isEdit) {
        const a = await updateAgent(props.agent.id, { name: name.trim() });
        props.onSaved(a);
      } else {
        const payload: AgentCreateInput = {
          name: name.trim(),
          instructions,
          duration_days: durationDays,
          strategy,
          model_provider: strategy === "llm" ? provider : null,
          model_name: strategy === "llm" && modelName.trim() ? modelName.trim() : null,
          universe,
        };
        const a = await createAgent(payload);
        props.onSaved(a);
      }
    } catch {
      setError(isEdit ? "modifica fallita" : "creazione fallita");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-overlay" onMouseDown={props.onClose}>
      <div className="modal" role="dialog" aria-modal="true" onMouseDown={(e) => e.stopPropagation()}>
        <h2>{isEdit ? "Modifica agente" : "Nuovo agente"}</h2>
        <form onSubmit={submit}>
          <label htmlFor="agent-name">Nome</label>
          <input id="agent-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />

          {!isEdit && (
            <>
              <label htmlFor="agent-instructions">Istruzioni</label>
              <textarea id="agent-instructions" value={instructions}
                onChange={(e) => setInstructions(e.target.value)} rows={3} />

              <label htmlFor="agent-duration">Durata (giorni)</label>
              <input id="agent-duration" type="number" min={1} value={durationDays}
                onChange={(e) => setDurationDays(Number(e.target.value))} />

              <label htmlFor="agent-strategy">Strategia</label>
              <select id="agent-strategy" value={strategy}
                onChange={(e) => setStrategy(e.target.value as "sma" | "llm")}>
                <option value="llm">LLM</option>
                <option value="sma">SMA</option>
              </select>

              {strategy === "llm" && (
                <>
                  <label htmlFor="agent-provider">Provider</label>
                  <select id="agent-provider" value={provider}
                    onChange={(e) => setProvider(e.target.value as (typeof PROVIDERS)[number])}>
                    {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
                  </select>

                  <label htmlFor="agent-model">Modello</label>
                  <input id="agent-model" value={modelName}
                    onChange={(e) => setModelName(e.target.value)} placeholder="es. claude-opus-4-8" />
                </>
              )}

              <label htmlFor="agent-universe">Universo</label>
              <select id="agent-universe" value={universe}
                onChange={(e) => setUniverse(e.target.value as "TOP_50" | "TOP_100")}>
                <option value="TOP_100">Top 100</option>
                <option value="TOP_50">Top 50</option>
              </select>
            </>
          )}

          {isEdit && (
            <p className="modal-note">Solo il nome è modificabile: gli altri parametri
              definiscono il comportamento e restano fissi per l'intera run.</p>
          )}

          {error && <p className="modal-error">{error}</p>}

          <div className="modal-actions">
            <button type="button" className="btn-ghost" onClick={props.onClose}>Annulla</button>
            <button type="submit" className="btn-primary" disabled={!valid || saving}>
              {isEdit ? "Salva" : "Crea"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- AgentFormModal`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AgentFormModal.tsx frontend/src/__tests__/AgentFormModal.test.tsx
git commit -m "feat(frontend): AgentFormModal for create and rename"
```

---

### Task 7: Frontend — `ConfirmDeleteModal` component

**Files:**
- Create: `frontend/src/components/ConfirmDeleteModal.tsx`
- Test: `frontend/src/__tests__/ConfirmDeleteModal.test.tsx`

**Interfaces:**
- Consumes: `deleteAgent`, `Agent` from `../api`.
- Produces: `ConfirmDeleteModal` with props `{ agent: Agent; onClose: () => void; onDeleted: (id: number) => void }`. The confirm button is disabled until the typed text equals the agent name exactly.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/__tests__/ConfirmDeleteModal.test.tsx`:

```typescript
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ConfirmDeleteModal } from "../components/ConfirmDeleteModal";

vi.mock("../api", () => ({ deleteAgent: vi.fn() }));
import { deleteAgent } from "../api";

const agent = { id: 7, name: "Doomed", status: "running", instructions: "",
  cash_usd: "100", equity: "100", return_pct: "0", duration_start: "", duration_end: "" };

beforeEach(() => vi.mocked(deleteAgent).mockReset());

describe("ConfirmDeleteModal", () => {
  it("keeps confirm disabled until the exact name is typed", () => {
    render(<ConfirmDeleteModal agent={agent} onClose={() => {}} onDeleted={() => {}} />);
    const confirm = screen.getByRole("button", { name: /elimina/i });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/conferma/i), { target: { value: "Doom" } });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/conferma/i), { target: { value: "Doomed" } });
    expect(confirm).not.toBeDisabled();
  });

  it("calls deleteAgent and onDeleted on confirm", async () => {
    const onDeleted = vi.fn();
    vi.mocked(deleteAgent).mockResolvedValue(undefined as never);
    render(<ConfirmDeleteModal agent={agent} onClose={() => {}} onDeleted={onDeleted} />);
    fireEvent.change(screen.getByLabelText(/conferma/i), { target: { value: "Doomed" } });
    fireEvent.click(screen.getByRole("button", { name: /elimina/i }));
    await waitFor(() => expect(deleteAgent).toHaveBeenCalledWith(7));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(7));
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- ConfirmDeleteModal`
Expected: FAIL — component file does not exist.

- [ ] **Step 3: Implement `ConfirmDeleteModal`**

Create `frontend/src/components/ConfirmDeleteModal.tsx`:

```typescript
import { useState } from "react";
import { deleteAgent, type Agent } from "../api";

type Props = { agent: Agent; onClose: () => void; onDeleted: (id: number) => void };

export function ConfirmDeleteModal({ agent, onClose, onDeleted }: Props) {
  const [confirmText, setConfirmText] = useState("");
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState(false);
  const matches = confirmText === agent.name;

  async function confirm() {
    if (!matches || deleting) return;
    setDeleting(true);
    setError("");
    try {
      await deleteAgent(agent.id);
      onDeleted(agent.id);
    } catch {
      setError("eliminazione fallita");
      setDeleting(false);
    }
  }

  return (
    <div className="modal-overlay" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" onMouseDown={(e) => e.stopPropagation()}>
        <h2>Elimina «{agent.name}»</h2>
        <p>Questa azione è irreversibile. Verranno cancellati definitivamente posizioni,
          operazioni, equity, eventi e memoria di questo agente.</p>
        <label htmlFor="confirm-name">Scrivi <b>{agent.name}</b> per confermare</label>
        <input id="confirm-name" value={confirmText} autoFocus
          onChange={(e) => setConfirmText(e.target.value)} />
        {error && <p className="modal-error">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="btn-ghost" onClick={onClose}>Annulla</button>
          <button type="button" className="btn-danger" disabled={!matches || deleting}
            onClick={confirm}>Elimina</button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- ConfirmDeleteModal`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ConfirmDeleteModal.tsx frontend/src/__tests__/ConfirmDeleteModal.test.tsx
git commit -m "feat(frontend): ConfirmDeleteModal with typed confirmation"
```

---

### Task 8: Frontend — wire controls into the dashboard + styles

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: `AgentFormModal`, `ConfirmDeleteModal`, `createAgent`/`updateAgent`/`deleteAgent` (via the modals), `getAgents`.

- [ ] **Step 1: Add modal state and controls to `App.tsx`**

In `frontend/src/App.tsx`:

Add imports near the existing component imports:

```typescript
import { AgentFormModal } from "./components/AgentFormModal";
import { ConfirmDeleteModal } from "./components/ConfirmDeleteModal";
```

Add modal state inside `App`, after the existing `useState` hooks:

```typescript
  const [modal, setModal] = useState<"create" | "edit" | "delete" | null>(null);
```

Add a refetch helper inside `App` (reuse it after mutations):

```typescript
  const reloadAgents = () => getAgents().then(setAgents).catch(() => {});
```

Add the "+ nuovo agente" button to the `agents-bar` section (after the `agents.map(...)`), and also an empty-state CTA when there are no agents. Replace the existing `{agents.length > 0 && ( ... )}` block so a create button always shows:

```tsx
      <section className="agents-bar">
        {agents.map((a) => {
          const ret = Number(a.return_pct);
          return (
            <button
              key={a.id}
              className={`agent-tile${a.id === selId ? " sel" : ""}`}
              onClick={() => setSelId(a.id)}
            >
              <div className="name">{a.name}</div>
              <div className="eq num">{usd(Number(a.equity))}</div>
              <div className="ret"><Return pct={ret} /></div>
            </button>
          );
        })}
        <button className="agent-tile add" onClick={() => setModal("create")}>
          + nuovo agente
        </button>
      </section>
```

In the `agent-header` section, add edit/delete controls after the `<span className="meta">…</span>`:

```tsx
            <div className="agent-actions">
              <button className="btn-ghost" onClick={() => setModal("edit")}>modifica</button>
              <button className="btn-ghost danger" onClick={() => setModal("delete")}>elimina</button>
            </div>
```

At the end of the top-level `<div className="app">`, before its closing tag, render the modals:

```tsx
      {modal === "create" && (
        <AgentFormModal
          mode="create"
          onClose={() => setModal(null)}
          onSaved={(a) => { setModal(null); reloadAgents(); setSelId(a.id); }}
        />
      )}
      {modal === "edit" && sel && (
        <AgentFormModal
          mode="edit"
          agent={sel}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); reloadAgents(); }}
        />
      )}
      {modal === "delete" && sel && (
        <ConfirmDeleteModal
          agent={sel}
          onClose={() => setModal(null)}
          onDeleted={(id) => {
            setModal(null);
            setSelId((cur) => (cur === id ? null : cur));
            reloadAgents();
          }}
        />
      )}
```

- [ ] **Step 2: Add styles to `index.css`**

Append to `frontend/src/index.css`. The file already defines these CSS variables in `:root` — reuse them exactly (do NOT introduce hardcoded hex colours): `--bg`, `--surface`, `--surface-2`, `--border`, `--ink`, `--muted`, `--faint`, `--accent`, `--accent-ink`, `--neg`, `--neg-bg`, `--r` (radius). Keep it quiet, no neon:

```css
.agent-tile.add {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  border-style: dashed;
}
.agent-actions { display: flex; gap: 8px; margin-top: 8px; }
.btn-ghost {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--ink);
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
  font: inherit;
}
.btn-ghost.danger { color: var(--neg); border-color: var(--neg); }
.btn-primary {
  background: var(--accent);
  border: 1px solid var(--accent);
  color: var(--accent-ink);
  padding: 4px 12px;
  border-radius: 6px;
  cursor: pointer;
  font: inherit;
}
.btn-danger {
  background: transparent;
  border: 1px solid var(--neg);
  color: var(--neg);
  padding: 4px 12px;
  border-radius: 6px;
  cursor: pointer;
  font: inherit;
}
.btn-primary:disabled, .btn-danger:disabled { opacity: 0.5; cursor: not-allowed; }
.modal-overlay {
  position: fixed;
  inset: 0;
  background: oklch(0 0 0 / 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 20px;
  width: min(440px, 92vw);
  max-height: 90vh;
  overflow: auto;
  color: var(--ink);
}
.modal h2 { margin: 0 0 12px; }
.modal label { display: block; margin: 10px 0 4px; font-size: 0.85rem; color: var(--muted); }
.modal input, .modal textarea, .modal select {
  width: 100%;
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--ink);
  padding: 6px 8px;
  border-radius: 6px;
  font: inherit;
  box-sizing: border-box;
}
.modal-note { font-size: 0.8rem; color: var(--muted); margin: 10px 0 0; }
.modal-error { color: var(--neg); font-size: 0.85rem; margin: 10px 0 0; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
@media (prefers-reduced-motion: no-preference) {
  .modal { animation: modal-in 120ms ease-out; }
  @keyframes modal-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
}
```

- [ ] **Step 3: Typecheck and run the full frontend suite**

Run: `cd frontend && npm run build && npm test`
Expected: build succeeds; all tests (existing + new) pass.

- [ ] **Step 4: Manual verification**

Run the app (`docker compose up` or the project's run method), then:
- Click "+ nuovo agente", fill the form, submit → new tile appears and is selected.
- Select an agent, click "modifica", change the name, save → header name updates.
- Click "elimina", type the name, confirm → agent disappears, selection moves to another agent (or none).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/index.css
git commit -m "feat(frontend): wire agent create/edit/delete controls into dashboard"
```

---

## Self-Review

**Spec coverage:**
- `universe` on create → Task 1. ✓
- `PATCH` rename → Task 2. ✓
- `DELETE` cascade → Task 3. ✓
- Scheduler per-agent universe → Task 4. ✓
- API client mutations → Task 5. ✓
- Create/edit form modal (strategy toggles model fields, name-only edit) → Task 6. ✓
- Delete confirmation modal (typed name) → Task 7. ✓
- Dashboard wiring + CSS + reduced-motion → Task 8. ✓
- Backend tests (create/validation/patch/delete/cascade/404) → Tasks 1–3. ✓
- Scheduler test → Task 4. ✓
- Frontend tests (form validation, strategy toggle, submit; delete confirm) → Tasks 6–7. ✓

**Type consistency:** `AgentCreateInput`, `createAgent`/`updateAgent`/`deleteAgent` signatures defined in Task 5 are used unchanged in Tasks 6–7. `AgentUpdate.name` (Task 2) matches the `{ name }` body sent by `updateAgent` (Task 5). `universe` literals `"TOP_50"`/`"TOP_100"` consistent across backend (Task 1), scheduler (Task 4), and form (Task 6).

**Non-goals respected:** no pause/stop/archive, no behavioural-field editing, no new model-required validation, no new agent knobs.
