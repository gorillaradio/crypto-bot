# Agent CRUD UI — Design

**Date:** 2026-06-29
**Status:** Approved (pending spec review)

## Goal

Give the user a way to **create, edit, and delete** trading agents directly from
the dashboard. Today agents can only be created via raw `POST /api/agents`; there
is no UI, and no update/delete endpoints exist at all.

## Scope decisions (agreed)

| Topic | Decision |
|---|---|
| UI surface | **Modal dialogs** over the existing dashboard. No router, no second "mode". |
| Editable on an existing agent | **`name` only.** Everything else is immutable after creation — to change behaviour you create a new agent. |
| Delete | **Hard delete** with a typed confirmation. Cascades to all related rows. Irreversible. |
| Create form fields | `name`, `instructions`, `duration_days`, `strategy`, `model_provider`, `model_name`, **`universe`**. |
| Universe | **Real, per-agent.** The scheduler is changed so each agent uses its own `universe`. |

### Non-goals
- No pause/stop/archive action (out of scope for CRUD).
- No editing of behavioural fields after creation.
- No new validation that `model_*` is required when `strategy == "llm"` — backend
  stays as lenient as it is today; the form guides the user instead.
- No new agent knobs (decision cadence, event-driven wakeup) — those remain parked.

## Backend changes

All in `backend/app/`. No DB migration required (the `universe` column already exists).

### 1. `api/schemas.py`
- `AgentCreate`: add `universe: Literal["TOP_50", "TOP_100"] = "TOP_100"`.
- New `AgentUpdate(BaseModel)`: single field `name: str`.

### 2. `api/routes.py`
- `create_agent`: use `payload.universe` instead of `settings.universe_default`.
- New `PATCH /agents/{agent_id}` → `update_agent`: 404 if missing; set `agent.name`;
  commit; return `_agent_out`.
- New `DELETE /agents/{agent_id}` → `delete_agent`: 404 if missing. The FKs have **no
  `ON DELETE CASCADE`**, so explicitly delete child rows first
  (`Position`, `Trade`, `EquitySnapshot`, `Event`, `AgentMemory` filtered by
  `agent_id`), then the agent. Commit. Return `204 No Content`.

### 3. `scheduler/jobs.py` — make universe real
`_decision_tick` currently fetches **one** symbol list from the global
`settings.universe_default` and applies it to every agent. Change it to:
- Collect the running agents.
- Determine the distinct universe sizes needed (`TOP_50` → 50, `TOP_100` → 100).
- Fetch the top symbols **once per distinct size** (cache in a dict to avoid
  redundant Binance calls).
- Pass each agent the symbol list matching its own `agent.universe`.

`settings.universe_default` remains the default for newly created agents that don't
specify a universe and as a fallback.

## Frontend changes

All in `frontend/src/`.

### 1. `api.ts`
- New input type `AgentCreateInput` (name, instructions, duration_days, strategy,
  model_provider, model_name, universe).
- `createAgent(input)` → `POST /api/agents`.
- `updateAgent(id, { name })` → `PATCH /api/agents/:id`.
- `deleteAgent(id)` → `DELETE /api/agents/:id`.
- Add a small `mutate` helper (parallels existing `get`) for non-GET requests.

### 2. New components
- **`AgentFormModal.tsx`** — used for both create and edit.
  - **Create mode:** all fields. `strategy` select (`sma` / `llm`); when `llm`,
    show `model_provider` select (`anthropic` / `deepseek` / `glm` / `openrouter`)
    and `model_name` text input; when `sma`, hide the model fields. `universe`
    select (`TOP_50` / `TOP_100`). `duration_days` number. Client-side validation:
    name required, duration_days ≥ 1.
  - **Edit mode:** only the `name` field is editable; the rest are shown read-only
    (or omitted) with a one-line note that behavioural fields can't be changed.
- **`ConfirmDeleteModal.tsx`** — shows the agent name and a warning that all history
  (positions, trades, equity, events, memory) will be permanently deleted. The
  primary button is enabled only after the user types the agent's name.

### 3. `App.tsx`
- "**+ nuovo agente**" control in the `agents-bar` (and an empty-state CTA when
  there are no agents yet).
- Per-agent **edit** and **delete** controls in the `agent-header` of the selected
  agent (not on every tile, to keep the bar clean).
- Modal open/close state; on successful mutation, re-run `getAgents()` and adjust
  `selId` (e.g. after delete, select the first remaining agent or none).

### 4. `index.css`
- Modal/overlay styles consistent with the control-room aesthetic (PRODUCT.md):
  quiet, dense, honest — no neon, no SaaS-template chrome. Respect
  `prefers-reduced-motion` for any open/close transition.

## Data flow

```
User clicks "+ nuovo agente"
  → AgentFormModal (create) → createAgent() → POST /api/agents
  → on 201: close modal, refetch agents, select the new agent

User clicks "modifica" on selected agent
  → AgentFormModal (edit, name only) → updateAgent() → PATCH /api/agents/:id
  → on 200: close modal, refetch agents

User clicks "elimina" on selected agent
  → ConfirmDeleteModal (type name to confirm) → deleteAgent() → DELETE /api/agents/:id
  → on 204: close modal, refetch agents, reselect
```

## Error handling
- Mutations surface a non-blocking error message inside the modal (e.g. "creazione
  fallita"); the modal stays open so the user can retry. Existing dashboard polling
  already swallows transient GET errors and continues.

## Testing

### Backend (`backend/tests/test_api.py`)
- Create with `universe="TOP_50"` persists and is returned/stored correctly.
- Create with default universe → `TOP_100`.
- Validation: missing `name` → 422; invalid `strategy` → 422; invalid `universe`
  → 422; invalid `model_provider` → 422.
- `PATCH` renames an agent; 404 for missing agent.
- `DELETE` removes the agent **and** its child rows (assert `Position`/`Trade`/
  `EquitySnapshot`/`Event`/`AgentMemory` for that `agent_id` are gone); returns 204;
  404 for missing agent.

### Scheduler (`backend/tests/test_jobs.py` or extend existing)
- With two running agents on different universes, `_decision_tick` passes each the
  symbol list matching its own `universe` (assert the fetch sizes / per-agent args).

### Frontend (`frontend/src/__tests__/`)
- `AgentFormModal`: name-required validation blocks submit; `llm` shows model
  fields and `sma` hides them; successful submit calls `createAgent` with the right
  payload (mock the api module, matching the existing vitest + testing-library style).
- `ConfirmDeleteModal`: confirm button stays disabled until the name is typed
  correctly, then calls `deleteAgent`.

## Files touched
- `backend/app/api/schemas.py`
- `backend/app/api/routes.py`
- `backend/app/scheduler/jobs.py`
- `backend/tests/test_api.py` (+ scheduler test)
- `frontend/src/api.ts`
- `frontend/src/App.tsx`
- `frontend/src/index.css`
- `frontend/src/components/AgentFormModal.tsx` (new)
- `frontend/src/components/ConfirmDeleteModal.tsx` (new)
- `frontend/src/__tests__/AgentFormModal.test.tsx` (new)
- `frontend/src/__tests__/ConfirmDeleteModal.test.tsx` (new)
