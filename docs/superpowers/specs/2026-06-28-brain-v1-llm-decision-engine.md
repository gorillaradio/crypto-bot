# Brain v1 — LLM Decision Engine (provider-agnostic)

**Status:** Design approved 2026-06-28. Ready for implementation planning.

## Goal

Replace the placeholder SMA rule with a real LLM "brain": once per decision cycle, an agent sends its portfolio + a market snapshot + its instructions to a language model and receives a structured list of buy/sell/hold actions **with rationale**. The model is chosen **per agent** behind a provider-agnostic interface (Anthropic + OpenAI-compatible providers such as DeepSeek and GLM), so two agents can differ *only by model* — a clean experiment dimension. Long-term memory, reflection, news ingestion, and benchmarks are explicitly out of scope for v1.

This realizes the north-star principle "show the reasoning": every action carries the model's stated reason, surfaced in the dashboard activity feed.

## Architecture

A new `backend/app/brain/` package holds the decision logic, sitting between `agents/runtime.py` and the providers:

```
run_decision (runtime)
   └─ strategy selector  ── "sma"  → existing strategy.decide_signal (kept as blind baseline)
                          └ "llm"  → brain.decide(context, agent_model_config)
                                        ├─ context_builder  → DecisionContext
                                        ├─ provider adapter → raw JSON text
                                        │     ├ AnthropicAdapter   (anthropic SDK)
                                        │     └ OpenAICompatAdapter (openai SDK + base_url)  ← DeepSeek, GLM
                                        └─ validate → Decision  (Pydantic; HOLD + error event on failure)
   └─ execute actions via trading/engine with guardrails (cash + min-trade)
```

The runtime stays the orchestrator; the brain is pure decision-making and never touches the DB directly (it receives a built context and returns a `Decision`). Execution stays in `trading/engine.py`.

## Components & Interfaces

### 1. `brain/schema.py` — data shapes

```python
from decimal import Decimal
from pydantic import BaseModel
from typing import Literal

class Action(BaseModel):
    type: Literal["BUY", "SELL", "HOLD"]
    symbol: str | None = None          # required for BUY/SELL, None for a pure HOLD
    usd_amount: Decimal | None = None  # for BUY: how much USD to spend
    fraction: Decimal | None = None    # for SELL: fraction of the held position (0–1); default 1 (sell all)
    rationale: str = ""

class Decision(BaseModel):
    actions: list[Action]
    note: str = ""                     # one-line thesis for the whole cycle
```

### 2. `brain/context.py` — `build_context(agent, positions, market_snapshot, recent_events) -> DecisionContext`

`DecisionContext` is a plain structure the prompt is rendered from:
- `instructions`: agent.instructions (now ACTIVE — the steering for the model)
- `cash_usd`, `equity_usd`
- `positions`: list of {symbol, quantity, avg_price, last_price, unrealized_pnl_pct}
- `universe`: compact one-line-per-coin snapshot — {symbol, price, pct_1h, pct_24h} for the agent's universe (top50/100)
- `recent_events`: last N event messages (default 10) for short-term continuity (this is the only "memory" in v1)

The market snapshot is produced by the runtime from the Binance client (current prices + 24h/1h change). One line per coin is cheap in tokens, so the full universe is included.

### 3. `brain/prompt.py` — render the prompt

- **System prompt**: a fixed framing ("you are an autonomous paper-trading agent…"), the agent's `instructions`, the trading rules (fees/spread exist; you only hold coins in the universe; guardrails enforced server-side so impossible actions are dropped), and the **required output format** (the JSON schema for `Decision`).
- **User content**: the rendered `DecisionContext` (portfolio, positions, universe snapshot, recent events).
- Deterministic rendering (sorted keys, no timestamps in the cached prefix) so prompt caching can apply later.

### 4. `brain/providers.py` — provider-agnostic adapters

```python
class ProviderAdapter(Protocol):
    def complete_json(self, system: str, user: str) -> str: ...   # returns raw JSON text

class AnthropicAdapter:    # uses the `anthropic` SDK; model id from config
class OpenAICompatAdapter: # uses the `openai` SDK with base_url+api_key from config; DeepSeek / GLM
```

- Each adapter is responsible for getting the model to emit JSON for the `Decision` schema (Anthropic: structured output / tool use; OpenAI-compatible: `response_format={"type":"json_object"}` + schema in the prompt). The adapter returns raw text; validation happens in the brain.
- Selection: `make_adapter(provider, model, ...)` reads `base_url` and the API-key env var per provider from settings.

### 5. `brain/__init__.py` — `decide(context, model_config) -> Decision`

- Render prompt → call adapter → parse+validate JSON into `Decision`.
- On parse/validation failure: **one repair retry** (re-prompt with the validation error). If it still fails, return `Decision(actions=[], note="<error>")` and let the runtime log an error event. Never raise into the runtime loop.

### 6. Config / model changes

`Agent` (DB model) gains:
- `strategy`: `"sma" | "llm"` (default `"llm"`; `"sma"` keeps the blind baseline available)
- `model_provider`: `str | None` (e.g. `"anthropic"`, `"deepseek"`, `"glm"`) — required when strategy is `"llm"`
- `model_name`: `str | None` — the provider's model id

`settings` (env) gains, per provider: base URL + API-key env name. Map: `anthropic` → `ANTHROPIC_API_KEY`; `deepseek` → `DEEPSEEK_API_KEY` + base_url; `glm` → `GLM_API_KEY` + base_url. A `min_trade_usd` guardrail constant (default `5`). A `decision_buy_default_usd` (default = initial_capital / 10) used only when the model omits an amount on a BUY.

During design/build we run a single cheapest model; the exact id/pricing/base_url are verified on the web at implementation time.

### 7. Runtime integration (`agents/runtime.py`)

`run_decision` branches on `agent.strategy`:
- `"sma"`: unchanged (existing SMA path).
- `"llm"`: build the market snapshot (universe one-liners + position last-prices), build context, call `brain.decide`, then execute each returned action through the engine **with guardrails**:
  - BUY: `usd_amount` (or `decision_buy_default_usd`); skip if `< min_trade_usd` or `> cash`. Execute at ask.
  - SELL: sell `fraction` (default 1) of the held position if held; skip otherwise. Execute at bid.
  - HOLD / unknown symbol / not-in-universe: skip.
  - Each executed action writes its `Trade`+`Event` (rationale appended to the event message). The cycle `note` and a summary (actions/skipped/errors) → a `decision` event.
- Per-action try/except continues on error (keep the existing per-symbol isolation philosophy). The whole cycle is wrapped so one bad agent can't break others.

## Error handling & resilience

- LLM call failure or invalid output → no trades, a `decision` event recording the error; the agent simply holds this cycle.
- Guardrails are enforced in code, not trusted to the model: cash ceiling and `min_trade_usd` floor; coins outside the universe are ignored; sizing clamped to available cash. The model cannot cause an impossible or unsafe (within the sim) trade.
- Costs already bounded by the configurable decision cadence (one call per agent per cycle).

## Testing

- **schema**: Action/Decision validation, defaults (fraction→1).
- **context**: `build_context` produces the expected structure from seeded agent/positions/snapshot.
- **prompt**: rendering is deterministic and includes instructions + output-format + universe lines.
- **providers**: adapters tested with a fake/stubbed client (no network) — assert the request shape and that JSON is returned; `make_adapter` selects the right adapter + env wiring.
- **brain.decide**: with a fake adapter returning (a) valid JSON → `Decision`; (b) malformed JSON → one repair retry; (c) still-bad → empty `Decision` with error note (no raise).
- **runtime (llm path)**: with a fake brain returning a BUY/SELL/HOLD mix, assert engine calls + guardrail skips (below min-trade, over-cash, not-in-universe) + events written + error isolation. SMA path unchanged tests still pass.
- All tests run offline (no live LLM, no live Binance) via fakes, consistent with the existing suite.

## Out of scope (later phases)

- Long-term memory + reflection (designed in deferred-design-decisions #3).
- News / information ingestion (the thesis core — separate spec).
- Benchmarks (S&P/NVDA lines).
- Per-position live P&L plumbing beyond what the snapshot already provides.
- Prompt caching optimization (design keeps the prompt cache-friendly but tuning is later).

## Dependencies

- `openai` (for DeepSeek/GLM OpenAI-compatible endpoints) and `anthropic` (for Anthropic) added to `backend/pyproject.toml`.
