# Agent Memory v1 — Long-term memory + event-driven reflection

**Status:** Design approved 2026-06-28. Ready for implementation planning.

## Goal

Give each agent a **persistent long-term memory** that it reads on every decision and **rewrites by reflecting on its own closed trades**. The memory holds three fixed, capped sections — *coin theses*, *trade lessons*, *strategy notes* — so the agent accumulates a point of view about the coins it trades, the mistakes it makes, and its own behavioural patterns, instead of starting blind every cycle.

This realizes the north-star principle "watch the agent change its mind": the sections are surfaced read-only in the dashboard, so a human can see the agent's view evolve.

**Explicitly in scope (v1):**
- A `agent_memory` table (one row per `(agent_id, section)`).
- Reading the three sections into the decision prompt, alongside the existing `recent_events`.
- A **reflection** LLM call, triggered when an agent **closes a trade (a SELL)**, that rewrites the three sections under hard caps.

**Explicitly out of scope (parked):**
- A self-written scratchpad ("what I'm watching / current plan") as a distinct short-term memory — for v1 short-term memory stays the existing `recent_events`.
- **Periodic** reflection (scheduled cleanup/reordering) — only event-driven reflection in v1.
- A dedicated cheaper reflection model — reflection reuses the agent's own model.

## Architecture

Memory lives in the DB and is read/written by the runtime; the `brain/` package stays pure (no DB access). Two new pure responsibilities go into the brain package — *rendering* memory into the decision prompt, and *building/validating* the reflection call.

```
run_decision (runtime)
   ├─ load agent_memory rows  ─────────────► MemoryView (3 strings)
   ├─ build_context(... memory=MemoryView)  ─► DecisionContext (now carries memory)
   ├─ brain.decide → execute actions (unchanged)
   └─ if any SELL executed this cycle:
        reflect(memory, closed_trades, portfolio, agent_model)   ← new brain logic
          ├─ build_reflection_prompt
          ├─ adapter call (same provider/model as the agent)
          └─ parse + enforce caps  → MemoryUpdate (3 capped string sections)
        └─ runtime writes the 3 sections back to agent_memory
```

The runtime remains the orchestrator and the only component that touches the DB. The brain receives plain data and returns plain data, exactly like the existing decision path.

## Components & Interfaces

### 1. `db/models.py` — new `AgentMemory` table

```python
class AgentMemory(Base):
    __tablename__ = "agent_memory"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    section: Mapped[str] = mapped_column(String(40))   # "coin_theses" | "trade_lessons" | "strategy_notes"
    content: Mapped[str] = mapped_column(String, default="")  # newline-separated lines
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    __table_args__ = (UniqueConstraint("agent_id", "section", name="uq_agent_memory_section"),)
```

- Three section keys are stable code identifiers; Italian display labels live in the dashboard.
- A missing row = an empty section (reflection has not run yet). No need to pre-seed.

**Alembic migration:** new revision, `down_revision = "b2c3d4e5f6a7"` (current head). Creates the table + unique constraint.

### 2. `brain/context.py` — memory carried into the decision

```python
@dataclass
class MemoryView:
    coin_theses: str      # newline-separated lines, may be ""
    trade_lessons: str
    strategy_notes: str

@dataclass
class DecisionContext:
    ...                   # existing fields unchanged
    memory: MemoryView    # new
```

`build_context(...)` gains a `memory: MemoryView` keyword argument and stores it on the context. Existing callers in tests pass an empty `MemoryView` when not relevant.

### 3. `brain/prompt.py` — render memory into the decision prompt

`render_prompt` appends a **Memory** block to the user message (after Recent events), only including non-empty sections:

```
Your memory (you wrote this; update your behaviour accordingly):
Coin theses:
  - <line>
Trade lessons:
  - <line>
Strategy notes:
  - <line>
```

The system prompt gains one sentence explaining the memory is the agent's own prior reflection. No change to the decision JSON shape.

### 4. `brain/memory.py` (new) — reflection logic (pure)

```python
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
    coin_theses: list[str]
    trade_lessons: list[str]
    strategy_notes: list[str]

def build_reflection_prompt(memory: MemoryView, closed: list[ClosedTrade],
                            held_symbols: list[str], instructions: str) -> tuple[str, str]:
    ...   # returns (system, user); instructs the model to REWRITE the 3 sections within the caps

def parse_reflection(raw: str) -> MemoryUpdate:
    ...   # JSON parse + Pydantic validate

def enforce_caps(update: MemoryUpdate) -> MemoryView:
    ...   # truncate each list to its cap, join with "\n" → MemoryView strings
```

The reflection prompt instructs: rewrite (do not append) each section; keep theses to ~1 line per coin for coins held or watched; new lessons replace the oldest/weakest when full; respect the caps. Caps are also enforced structurally in `enforce_caps`, so an over-long model response is truncated, never trusted blindly.

### 5. `agents/runtime.py` — wiring

**Read (before building context):**
```python
mem_rows = {r.section: r.content for r in
            session.query(AgentMemory).filter_by(agent_id=agent.id).all()}
memory = MemoryView(
    coin_theses=mem_rows.get("coin_theses", ""),
    trade_lessons=mem_rows.get("trade_lessons", ""),
    strategy_notes=mem_rows.get("strategy_notes", ""),
)
ctx = build_context(..., memory=memory)
```

**Reflect (after the action loop):** collect a `ClosedTrade` for each executed SELL (capturing `avg_cost` from the position *before* the sell, and the realized P&L). If at least one SELL executed this cycle, run **one** reflection call (the whole memory is rewritten regardless of how many sells happened):

```python
if closed_trades:
    try:
        held_symbols = [p.symbol for p in agent.positions]
        sys, usr = build_reflection_prompt(memory, closed_trades, held_symbols, agent.instructions)
        raw = adapter.complete_json(sys, usr)       # same adapter/model as the decision
        new_mem = enforce_caps(parse_reflection(raw))
        _persist_memory(session, agent.id, new_mem) # upsert the 3 rows
        session.add(Event(agent_id=agent.id, kind="reflection",
                          message="memoria aggiornata dopo trade chiuso"))
    except Exception as exc:
        session.add(Event(agent_id=agent.id, kind="reflection",
                          message=f"reflection: errore — {exc}"))
    session.commit()
```

Reflection failure is **non-fatal and isolated** — it writes a `reflection` error event and leaves the existing memory untouched, never raising into the scheduler loop (same guarantee the decision path already gives).

Capturing `avg_cost` requires reading `held[symbol].avg_price` *before* `execute_sell` mutates/removes the position. The realized P&L pct = `(sell_price - avg_cost) / avg_cost * 100`.

### 6. Dashboard — read-only memory panel

- **API:** extend the agent detail payload (or add `GET /api/agents/{id}/memory`) to return the three sections.
- **Frontend:** a "Memoria" panel per agent showing the three sections (Tesi per coin / Lezioni dai trade / Note di strategia) as lists, refreshed with the rest of the dashboard. No editing.

## Data flow

1. Decision cycle starts → runtime loads the 3 memory rows → `MemoryView`.
2. `build_context` carries `MemoryView`; `render_prompt` injects non-empty sections into the decision prompt.
3. Agent decides; actions execute under the existing guardrails.
4. For each executed SELL, runtime records a `ClosedTrade` (with realized P&L from the pre-sell avg cost).
5. If ≥1 SELL closed: one reflection call rewrites the 3 sections → caps enforced → upserted into `agent_memory` → a `reflection` event logged.
6. Dashboard reads `agent_memory` and shows the panel.

## Error handling

- **Reflection failure** (provider error, malformed JSON, validation failure): caught, logged as a `reflection` event, existing memory preserved. Never propagates.
- **Over-cap model output:** truncated by `enforce_caps`; not an error.
- **Empty / first-run memory:** rendered as omitted sections in the prompt; no special-casing beyond "skip empty section".
- **No SELL in a cycle:** no reflection call (pure read path, unchanged cost).

## Testing (offline, fake adapters)

- **Migration:** table + unique constraint created; upsert replaces a section rather than duplicating it.
- **Read path:** `build_context` + `render_prompt` include memory lines when present, omit empty sections.
- **Caps:** `enforce_caps` truncates 9→8 / 11→10 / 6→5 and joins correctly.
- **Reflection trigger:** a fake decision that SELLs fires exactly one reflection call; a HOLD/BUY-only cycle fires none.
- **Realized P&L:** computed from the pre-sell avg cost (sell above cost → positive pct, below → negative).
- **Reflection failure isolation:** a fake adapter that raises / returns garbage → memory unchanged, `reflection` error event written, scheduler loop unaffected.
- **Multiple SELLs in one cycle:** a single reflection call, not one per sell.

## Out of scope (parked for later)

- Self-written scratchpad short-term memory.
- Periodic (scheduled) reflection and cross-section cleanup.
- A dedicated cheaper reflection model per agent.
