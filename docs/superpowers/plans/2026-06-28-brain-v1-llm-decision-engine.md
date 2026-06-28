# Brain v1 — LLM Decision Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the SMA placeholder with a per-agent, provider-agnostic LLM "brain" that returns a structured list of buy/sell/hold actions with rationale each decision cycle.

**Architecture:** A new `backend/app/brain/` package (schema → context → prompt → providers → decide) sits between `agents/runtime.py` and the LLM providers (Anthropic SDK; OpenAI SDK pointed at DeepSeek/GLM base URLs). The runtime branches on `agent.strategy` (`"sma"` keeps the blind baseline; `"llm"` calls the brain), then executes the returned actions through the existing trading engine under hard guardrails (cash + min-trade). The brain is pure (no DB/network); the runtime gathers data and executes.

**Tech Stack:** Python 3.12+, Pydantic v2, SQLAlchemy/Alembic, `openai` SDK (DeepSeek/GLM), `anthropic` SDK (Anthropic), pytest. Spec: `docs/superpowers/specs/2026-06-28-brain-v1-llm-decision-engine.md`.

## Global Constraints

- All money math in `decimal.Decimal`, never float.
- The brain never touches the DB or makes Binance calls — it receives a built `DecisionContext` and returns a `Decision`. The runtime gathers data and executes trades.
- Guardrails are enforced in code, not trusted to the model: skip BUY if `amount < min_trade_usd` (default `5`) or `amount > cash`; ignore symbols not in the agent's universe; SELL only what is held.
- On any LLM failure or invalid output → no trades this cycle, write a `decision` event recording the error; never raise into the runtime loop.
- Provider-agnostic: `agent.strategy` ∈ {`"sma"`, `"llm"`}; for `"llm"`, `agent.model_provider` ∈ {`"anthropic"`, `"deepseek"`, `"glm"`} + `agent.model_name`. Keys/base_urls from env via `settings`.
- All tests run offline (fake adapters, fake market) — no live LLM, no live Binance.
- Exact model IDs / pricing / provider base URLs are verified on the web at the START of Task 5 (do not hardcode unverified values without the verification step).

---

## File Structure

```
backend/app/
├── core/config.py        # MODIFY: provider base_urls + key env, min_trade_usd, decision_buy_default_usd
├── db/models.py          # MODIFY: Agent gains strategy, model_provider, model_name
├── alembic/versions/*    # CREATE: migration adding the 3 Agent columns
├── api/schemas.py        # MODIFY: AgentCreate gains strategy/model_provider/model_name
├── api/routes.py         # MODIFY: create_agent persists the new fields
├── market/binance.py     # MODIFY: add get_universe_snapshot()
├── brain/
│   ├── __init__.py       # CREATE: decide(context, adapter) -> Decision
│   ├── schema.py         # CREATE: Action, Decision (Pydantic)
│   ├── context.py        # CREATE: PositionView, CoinSnapshot, DecisionContext, build_context()
│   ├── prompt.py         # CREATE: render_prompt(ctx) -> (system, user)
│   └── providers.py      # CREATE: ProviderAdapter, AnthropicAdapter, OpenAICompatAdapter, make_adapter()
└── agents/runtime.py     # MODIFY: run_decision branches on agent.strategy; llm path
backend/pyproject.toml    # MODIFY: add openai, anthropic
```

---

## Task 1: Agent config plumbing (deps, settings, model fields, migration, API)

**Files:**
- Modify: `backend/pyproject.toml` (add `openai>=1.40`, `anthropic>=0.40`)
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/<rev>_agent_strategy_fields.py`
- Modify: `backend/app/api/schemas.py`, `backend/app/api/routes.py`
- Test: `backend/tests/test_models.py`, `backend/tests/test_api.py`

**Interfaces:**
- Produces: `Agent.strategy: str` (default `"llm"`), `Agent.model_provider: str | None`, `Agent.model_name: str | None`. `settings.min_trade_usd: Decimal`, `settings.decision_buy_default_usd: Decimal` (property = initial_capital_usd/10), `settings.provider_base_url(provider) -> str`, `settings.provider_api_key(provider) -> str`. `AgentCreate` gains `strategy`, `model_provider`, `model_name`.

- [ ] **Step 1: Add deps to `backend/pyproject.toml`** — add `"openai>=1.40"` and `"anthropic>=0.40"` to `dependencies`, then `backend/.venv/bin/pip install -e backend`.

- [ ] **Step 2: Extend `backend/app/core/config.py`**

```python
from decimal import Decimal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://crypto:crypto@postgres:5432/crypto"
    initial_capital_usd: Decimal = Decimal("100")
    fee_rate: Decimal = Decimal("0.001")
    heartbeat_seconds: int = 300
    decision_seconds: int = 3600
    universe_default: str = "TOP_100"

    # --- brain v1 ---
    min_trade_usd: Decimal = Decimal("5")

    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    glm_api_key: str = ""
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"  # verify at Task 5

    @property
    def decision_buy_default_usd(self) -> Decimal:
        return self.initial_capital_usd / Decimal("10")

    def provider_api_key(self, provider: str) -> str:
        return {"anthropic": self.anthropic_api_key,
                "deepseek": self.deepseek_api_key,
                "glm": self.glm_api_key}[provider]

    def provider_base_url(self, provider: str) -> str:
        return {"deepseek": self.deepseek_base_url,
                "glm": self.glm_base_url}.get(provider, "")


settings = Settings()
```

- [ ] **Step 3: Write the failing model test** in `backend/tests/test_models.py`

```python
def test_agent_strategy_fields_default_and_persist(db_session):
    from datetime import datetime, timezone
    from app.db.models import Agent
    a = Agent(name="L", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"),
              model_provider="deepseek", model_name="deepseek-chat")
    db_session.add(a); db_session.commit()
    assert a.strategy == "llm"          # default
    assert a.model_provider == "deepseek"
    assert a.model_name == "deepseek-chat"
```

- [ ] **Step 4: Run it — expect FAIL** (`AttributeError`/unexpected kwarg). `backend/.venv/bin/pytest backend/tests/test_models.py -v`

- [ ] **Step 5: Add columns to `Agent` in `backend/app/db/models.py`** (after `universe`)

```python
    strategy: Mapped[str] = mapped_column(String(20), default="llm")
    model_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
```

- [ ] **Step 6: Run model test — expect PASS.**

- [ ] **Step 7: Hand-write the migration** `backend/alembic/versions/<rev>_agent_strategy_fields.py` (pick a new revision id, set `down_revision` to the current head from `backend/.venv/bin/alembic heads`)

```python
"""agent strategy fields"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "<CURRENT_HEAD>"   # set from `alembic heads`
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("agents", sa.Column("strategy", sa.String(length=20), nullable=False, server_default="llm"))
    op.add_column("agents", sa.Column("model_provider", sa.String(length=40), nullable=True))
    op.add_column("agents", sa.Column("model_name", sa.String(length=80), nullable=True))

def downgrade():
    op.drop_column("agents", "model_name")
    op.drop_column("agents", "model_provider")
    op.drop_column("agents", "strategy")
```

- [ ] **Step 8: Extend `AgentCreate` in `backend/app/api/schemas.py`**

```python
class AgentCreate(BaseModel):
    name: str
    instructions: str = ""
    duration_days: int = 7
    strategy: str = "llm"
    model_provider: str | None = None
    model_name: str | None = None
```

- [ ] **Step 9: Persist the fields in `create_agent` (`backend/app/api/routes.py`)** — add to the `Agent(...)` constructor: `strategy=payload.strategy, model_provider=payload.model_provider, model_name=payload.model_name,`.

- [ ] **Step 10: Write the failing API test** in `backend/tests/test_api.py`

```python
def test_create_llm_agent_persists_model_fields(db_session):
    client = _client(db_session)
    resp = client.post("/api/agents", json={
        "name": "Brainy", "instructions": "buy low", "duration_days": 7,
        "strategy": "llm", "model_provider": "deepseek", "model_name": "deepseek-chat"})
    assert resp.status_code == 201
    from app.db.models import Agent
    a = db_session.query(Agent).filter_by(name="Brainy").one()
    assert a.strategy == "llm" and a.model_provider == "deepseek" and a.model_name == "deepseek-chat"
```

- [ ] **Step 11: Run the full backend suite — expect PASS.** `backend/.venv/bin/pytest backend/tests -q`

- [ ] **Step 12: Commit**

```bash
git add backend/pyproject.toml backend/app/core/config.py backend/app/db/models.py backend/alembic backend/app/api backend/tests
git commit -m "feat(brain): agent strategy/model config, settings, deps, migration"
```

---

## Task 2: `brain/schema.py` — Action & Decision

**Files:**
- Create: `backend/app/brain/__init__.py` (empty for now), `backend/app/brain/schema.py`
- Test: `backend/tests/test_brain_schema.py`

**Interfaces:**
- Produces: `Action(type: Literal["BUY","SELL","HOLD"], symbol: str|None, usd_amount: Decimal|None, fraction: Decimal|None, rationale: str)`, `Decision(actions: list[Action], note: str)`. `Decision.model_validate_json(str)` parses model output.

- [ ] **Step 1: Write the failing test** `backend/tests/test_brain_schema.py`

```python
from decimal import Decimal
from app.brain.schema import Action, Decision


def test_decision_parses_from_json():
    raw = '{"actions":[{"type":"BUY","symbol":"BTCUSDT","usd_amount":"10","rationale":"dip"}],"note":"cautious"}'
    d = Decision.model_validate_json(raw)
    assert d.note == "cautious"
    assert d.actions[0].type == "BUY"
    assert d.actions[0].usd_amount == Decimal("10")
    assert d.actions[0].fraction is None


def test_action_defaults():
    a = Action(type="HOLD")
    assert a.symbol is None and a.usd_amount is None and a.fraction is None and a.rationale == ""


def test_empty_decision():
    d = Decision()
    assert d.actions == [] and d.note == ""
```

- [ ] **Step 2: Run — expect FAIL** (ModuleNotFoundError). `backend/.venv/bin/pytest backend/tests/test_brain_schema.py -v`

- [ ] **Step 3: Create `backend/app/brain/__init__.py`** (empty) and `backend/app/brain/schema.py`

```python
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel


class Action(BaseModel):
    type: Literal["BUY", "SELL", "HOLD"]
    symbol: str | None = None
    usd_amount: Decimal | None = None
    fraction: Decimal | None = None
    rationale: str = ""


class Decision(BaseModel):
    actions: list[Action] = []
    note: str = ""
```

- [ ] **Step 4: Run — expect PASS (3 tests).**

- [ ] **Step 5: Commit**

```bash
git add backend/app/brain/__init__.py backend/app/brain/schema.py backend/tests/test_brain_schema.py
git commit -m "feat(brain): Action/Decision schema"
```

---

## Task 3: `brain/context.py` — DecisionContext + build_context

**Files:**
- Create: `backend/app/brain/context.py`
- Test: `backend/tests/test_brain_context.py`

**Interfaces:**
- Consumes: nothing from the project (pure dataclasses + Decimal).
- Produces:
  - `PositionView(symbol, quantity, avg_price, last_price, unrealized_pnl_pct)` (dataclass)
  - `CoinSnapshot(symbol, price, pct_24h)` (dataclass)
  - `DecisionContext(instructions, cash_usd, equity_usd, positions: list[PositionView], universe: list[CoinSnapshot], recent_events: list[str])` (dataclass)
  - `build_context(*, instructions: str, cash_usd: Decimal, holdings: list[tuple[str, Decimal, Decimal, Decimal]], universe: list[CoinSnapshot], recent_events: list[str]) -> DecisionContext` — `holdings` tuples are `(symbol, quantity, avg_price, last_price)`; computes `unrealized_pnl_pct` per holding and `equity_usd = cash + Σ qty*last_price`.

- [ ] **Step 1: Write the failing test** `backend/tests/test_brain_context.py`

```python
from decimal import Decimal
from app.brain.context import build_context, CoinSnapshot


def test_build_context_computes_equity_and_pnl():
    ctx = build_context(
        instructions="be bold",
        cash_usd=Decimal("50"),
        holdings=[("BTCUSDT", Decimal("0.5"), Decimal("100"), Decimal("120"))],
        universe=[CoinSnapshot(symbol="BTCUSDT", price=Decimal("120"), pct_24h=Decimal("3.5"))],
        recent_events=["BUY 0.5 BTCUSDT"],
    )
    assert ctx.instructions == "be bold"
    assert ctx.equity_usd == Decimal("110")          # 50 + 0.5*120
    assert ctx.positions[0].unrealized_pnl_pct == Decimal("20")  # (120-100)/100*100
    assert ctx.universe[0].symbol == "BTCUSDT"
    assert ctx.recent_events == ["BUY 0.5 BTCUSDT"]
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Create `backend/app/brain/context.py`**

```python
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class PositionView:
    symbol: str
    quantity: Decimal
    avg_price: Decimal
    last_price: Decimal
    unrealized_pnl_pct: Decimal


@dataclass
class CoinSnapshot:
    symbol: str
    price: Decimal
    pct_24h: Decimal


@dataclass
class DecisionContext:
    instructions: str
    cash_usd: Decimal
    equity_usd: Decimal
    positions: list[PositionView]
    universe: list[CoinSnapshot]
    recent_events: list[str]


def build_context(*, instructions, cash_usd, holdings, universe, recent_events) -> DecisionContext:
    positions: list[PositionView] = []
    equity = cash_usd
    for symbol, quantity, avg_price, last_price in holdings:
        pnl = ((last_price - avg_price) / avg_price * Decimal("100")) if avg_price else Decimal("0")
        positions.append(PositionView(symbol, quantity, avg_price, last_price, pnl))
        equity += quantity * last_price
    return DecisionContext(
        instructions=instructions, cash_usd=cash_usd, equity_usd=equity,
        positions=positions, universe=universe, recent_events=recent_events,
    )
```

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit**

```bash
git add backend/app/brain/context.py backend/tests/test_brain_context.py
git commit -m "feat(brain): decision context builder"
```

---

## Task 4: `brain/prompt.py` — render_prompt

**Files:**
- Create: `backend/app/brain/prompt.py`
- Test: `backend/tests/test_brain_prompt.py`

**Interfaces:**
- Consumes: `DecisionContext`, `PositionView`, `CoinSnapshot` (Task 3).
- Produces: `render_prompt(ctx: DecisionContext) -> tuple[str, str]` returning `(system, user)`. System includes the agent instructions, the trading rules, and the required JSON output shape. User is the rendered context (deterministic: universe sorted by symbol).

- [ ] **Step 1: Write the failing test** `backend/tests/test_brain_prompt.py`

```python
from decimal import Decimal
from app.brain.context import build_context, CoinSnapshot
from app.brain.prompt import render_prompt


def _ctx():
    return build_context(
        instructions="favor blue chips",
        cash_usd=Decimal("100"),
        holdings=[],
        universe=[CoinSnapshot("ETHUSDT", Decimal("3000"), Decimal("-1")),
                  CoinSnapshot("BTCUSDT", Decimal("60000"), Decimal("2"))],
        recent_events=["decision: 0 ops"],
    )


def test_prompt_includes_instructions_rules_and_format():
    system, user = render_prompt(_ctx())
    assert "favor blue chips" in system
    assert "JSON" in system and '"actions"' in system   # output format described
    assert "cash" in user.lower()


def test_universe_rendered_sorted_and_deterministic():
    system1, user1 = render_prompt(_ctx())
    system2, user2 = render_prompt(_ctx())
    assert user1 == user2                                # deterministic
    assert user1.index("BTCUSDT") < user1.index("ETHUSDT")  # sorted by symbol
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Create `backend/app/brain/prompt.py`**

```python
from app.brain.context import DecisionContext

_SYSTEM = """You are an autonomous paper-trading agent managing a simulated crypto portfolio.
Real market prices are used; trades incur fees and bid/ask spread. You may only hold coins
listed in the universe. Server-side guardrails enforce limits, so impossible actions are dropped.

Your operator's instructions:
{instructions}

Decide what to do this cycle. Respond with ONLY a JSON object of this exact shape:
{{"actions": [{{"type": "BUY"|"SELL"|"HOLD", "symbol": "<SYMBOL or null>",
  "usd_amount": "<USD to spend on BUY, or null>", "fraction": "<0-1 of position to SELL, or null>",
  "rationale": "<one short sentence>"}}], "note": "<one-line thesis for this cycle>"}}
Use BUY with usd_amount to open/add, SELL with fraction (1 = all) to reduce/close, HOLD to do nothing.
Numbers must be JSON strings. Output JSON only, no prose."""


def render_prompt(ctx: DecisionContext) -> tuple[str, str]:
    system = _SYSTEM.format(instructions=ctx.instructions or "(none provided)")

    lines = [f"Cash: ${ctx.cash_usd}", f"Equity: ${ctx.equity_usd}", "", "Open positions:"]
    if ctx.positions:
        for p in ctx.positions:
            lines.append(f"  {p.symbol}: qty {p.quantity} @ avg ${p.avg_price}, "
                         f"now ${p.last_price} ({p.unrealized_pnl_pct:+.2f}%)")
    else:
        lines.append("  (none)")

    lines += ["", "Market (universe):"]
    for c in sorted(ctx.universe, key=lambda c: c.symbol):
        lines.append(f"  {c.symbol}: ${c.price} ({c.pct_24h:+.2f}% 24h)")

    lines += ["", "Recent events:"]
    lines += [f"  - {e}" for e in ctx.recent_events] or ["  (none)"]

    return system, "\n".join(lines)
```

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit**

```bash
git add backend/app/brain/prompt.py backend/tests/test_brain_prompt.py
git commit -m "feat(brain): deterministic prompt rendering"
```

---

## Task 5: `brain/providers.py` — adapters + make_adapter

**FIRST:** verify on the web the current DeepSeek and GLM OpenAI-compatible **base URLs**, an inexpensive **model id** for each, and that they support `response_format={"type":"json_object"}`. Update `config.py` base-url defaults from Task 1 if they differ. Record what you used in the commit message.

**Files:**
- Create: `backend/app/brain/providers.py`
- Test: `backend/tests/test_brain_providers.py`

**Interfaces:**
- Consumes: `settings` (Task 1).
- Produces:
  - `class ProviderAdapter(Protocol)` with `complete_json(self, system: str, user: str) -> str`
  - `class OpenAICompatAdapter` — `__init__(self, client, model: str)`; `complete_json` calls `client.chat.completions.create(model=..., messages=[system,user], response_format={"type":"json_object"})` and returns `resp.choices[0].message.content`
  - `class AnthropicAdapter` — `__init__(self, client, model: str)`; `complete_json` calls `client.messages.create(model=..., max_tokens=2000, system=system, messages=[{"role":"user","content":user}])` and returns `resp.content[0].text`
  - `make_adapter(provider: str, model: str) -> ProviderAdapter` — builds the real SDK client from `settings` (Anthropic SDK for `"anthropic"`; OpenAI SDK with `base_url`+key for `"deepseek"`/`"glm"`)

- [ ] **Step 1: Write the failing test** `backend/tests/test_brain_providers.py` (fakes mimic the SDK surfaces — no network)

```python
from app.brain.providers import OpenAICompatAdapter, AnthropicAdapter, make_adapter


class _FakeOpenAI:
    def __init__(self): self.last = None
    class _Chat:
        def __init__(self, outer): self.completions = outer
    def chat(self): ...
    # build nested shape: client.chat.completions.create(...)
    @property
    def chat(self):
        outer = self
        class Completions:
            def create(self, **kw):
                outer.last = kw
                class M: content = '{"actions":[],"note":"ok"}'
                class C: message = M()
                class R: choices = [C()]
                return R()
        class Chat: completions = Completions()
        return Chat()


def test_openai_adapter_returns_content_and_sends_json_mode():
    fake = _FakeOpenAI()
    out = OpenAICompatAdapter(fake, "deepseek-chat").complete_json("sys", "usr")
    assert out == '{"actions":[],"note":"ok"}'
    assert fake.last["response_format"] == {"type": "json_object"}
    assert fake.last["model"] == "deepseek-chat"


class _FakeAnthropic:
    def __init__(self): self.last = None
    @property
    def messages(self):
        outer = self
        class Messages:
            def create(self, **kw):
                outer.last = kw
                class B: text = '{"actions":[],"note":"a"}'
                class R: content = [B()]
                return R()
        return Messages()


def test_anthropic_adapter_returns_text():
    fake = _FakeAnthropic()
    out = AnthropicAdapter(fake, "claude-haiku-4-5").complete_json("sys", "usr")
    assert out == '{"actions":[],"note":"a"}'
    assert fake.last["system"] == "sys"


def test_make_adapter_selects_type():
    assert isinstance(make_adapter("deepseek", "deepseek-chat"), OpenAICompatAdapter)
    assert isinstance(make_adapter("glm", "glm-4"), OpenAICompatAdapter)
    assert isinstance(make_adapter("anthropic", "claude-haiku-4-5"), AnthropicAdapter)
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Create `backend/app/brain/providers.py`**

```python
from typing import Protocol
from app.core.config import settings


class ProviderAdapter(Protocol):
    def complete_json(self, system: str, user: str) -> str: ...


class OpenAICompatAdapter:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def complete_json(self, system: str, user: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content


class AnthropicAdapter:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def complete_json(self, system: str, user: str) -> str:
        resp = self.client.messages.create(
            model=self.model, max_tokens=2000,
            system=system, messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text


def make_adapter(provider: str, model: str) -> ProviderAdapter:
    if provider == "anthropic":
        import anthropic
        return AnthropicAdapter(anthropic.Anthropic(api_key=settings.provider_api_key(provider)), model)
    import openai
    client = openai.OpenAI(api_key=settings.provider_api_key(provider),
                           base_url=settings.provider_base_url(provider))
    return OpenAICompatAdapter(client, model)
```

- [ ] **Step 4: Run — expect PASS (3 tests).** (`make_adapter` constructs SDK clients with placeholder keys; no network call is made at construction.)

- [ ] **Step 5: Commit** (note the verified base URLs / model ids in the message)

```bash
git add backend/app/brain/providers.py backend/tests/test_brain_providers.py backend/app/core/config.py
git commit -m "feat(brain): provider adapters (anthropic + openai-compatible deepseek/glm)"
```

---

## Task 6: `brain/__init__.py` — decide()

**Files:**
- Modify: `backend/app/brain/__init__.py`
- Test: `backend/tests/test_brain_decide.py`

**Interfaces:**
- Consumes: `render_prompt` (Task 4), `Decision` (Task 2), `ProviderAdapter` (Task 5), `DecisionContext` (Task 3).
- Produces: `decide(ctx: DecisionContext, adapter: ProviderAdapter) -> Decision`. Validates adapter JSON into `Decision`; on failure, one repair retry; on still-failure or adapter exception, returns `Decision(actions=[], note="...error...")` (never raises).

- [ ] **Step 1: Write the failing test** `backend/tests/test_brain_decide.py`

```python
from decimal import Decimal
from app.brain import decide
from app.brain.context import build_context


def _ctx():
    return build_context(instructions="x", cash_usd=Decimal("100"),
                         holdings=[], universe=[], recent_events=[])


class _Adapter:
    def __init__(self, outputs): self.outputs = list(outputs); self.calls = 0
    def complete_json(self, system, user):
        self.calls += 1
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def test_decide_parses_valid_json():
    d = decide(_ctx(), _Adapter(['{"actions":[{"type":"HOLD","rationale":"wait"}],"note":"n"}']))
    assert d.actions[0].type == "HOLD" and d.note == "n"


def test_decide_repairs_then_succeeds():
    a = _Adapter(["not json", '{"actions":[],"note":"recovered"}'])
    d = decide(_ctx(), a)
    assert d.note == "recovered" and a.calls == 2


def test_decide_gives_up_to_empty_decision():
    d = decide(_ctx(), _Adapter(["bad", "still bad"]))
    assert d.actions == [] and "fail" in d.note.lower()


def test_decide_handles_adapter_exception():
    d = decide(_ctx(), _Adapter([RuntimeError("boom")]))
    assert d.actions == [] and "error" in d.note.lower()
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `decide` in `backend/app/brain/__init__.py`**

```python
from app.brain.schema import Decision
from app.brain.context import DecisionContext
from app.brain.prompt import render_prompt


def decide(ctx: DecisionContext, adapter) -> Decision:
    system, user = render_prompt(ctx)
    try:
        raw = adapter.complete_json(system, user)
    except Exception as exc:  # network / provider error
        return Decision(actions=[], note=f"brain error: {exc}")

    try:
        return Decision.model_validate_json(raw)
    except Exception as first_err:
        try:
            raw2 = adapter.complete_json(
                system, user + f"\n\nYour previous reply was not valid JSON for the schema "
                               f"({first_err}). Reply with ONLY the corrected JSON object.")
            return Decision.model_validate_json(raw2)
        except Exception as second_err:
            return Decision(actions=[], note=f"decision parse failed: {second_err}")
```

- [ ] **Step 4: Run — expect PASS (4 tests).**

- [ ] **Step 5: Commit**

```bash
git add backend/app/brain/__init__.py backend/tests/test_brain_decide.py
git commit -m "feat(brain): decide() with validation + repair retry + safe fallback"
```

---

## Task 7: Market universe snapshot

**Files:**
- Modify: `backend/app/market/binance.py`
- Test: `backend/tests/test_binance.py`

**Interfaces:**
- Consumes: existing `BinanceClient._get`.
- Produces: `async get_universe_snapshot(self, symbols: list[str]) -> list[CoinSnapshot]` — one `/api/v3/ticker/24hr` call, filtered to `symbols`, returning `CoinSnapshot(symbol, price=Decimal(lastPrice), pct_24h=Decimal(priceChangePercent))`. Preserves the order of `symbols`.

- [ ] **Step 1: Write the failing test** in `backend/tests/test_binance.py`

```python
@respx.mock
async def test_get_universe_snapshot_filters_and_parses():
    respx.get(f"{BASE}/api/v3/ticker/24hr").mock(
        return_value=httpx.Response(200, json=[
            {"symbol": "BTCUSDT", "lastPrice": "60000.0", "priceChangePercent": "2.5"},
            {"symbol": "ETHUSDT", "lastPrice": "3000.0", "priceChangePercent": "-1.0"},
            {"symbol": "JUNKUSDT", "lastPrice": "1.0", "priceChangePercent": "0"},
        ])
    )
    from app.brain.context import CoinSnapshot
    snap = await BinanceClient().get_universe_snapshot(["ETHUSDT", "BTCUSDT"])
    assert [c.symbol for c in snap] == ["ETHUSDT", "BTCUSDT"]   # order preserved
    assert snap[1].price == Decimal("60000.0")
    assert snap[1].pct_24h == Decimal("2.5")
    assert isinstance(snap[0], CoinSnapshot)
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Add the method to `backend/app/market/binance.py`** (import `CoinSnapshot` at top: `from app.brain.context import CoinSnapshot`)

```python
    async def get_universe_snapshot(self, symbols: list[str]) -> list["CoinSnapshot"]:
        data = await self._get("/api/v3/ticker/24hr", {})
        by_symbol = {d["symbol"]: d for d in data}
        out = []
        for s in symbols:
            d = by_symbol.get(s)
            if d is None:
                continue
            out.append(CoinSnapshot(symbol=s, price=Decimal(d["lastPrice"]),
                                    pct_24h=Decimal(d["priceChangePercent"])))
        return out
```

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit**

```bash
git add backend/app/market/binance.py backend/tests/test_binance.py
git commit -m "feat(market): universe snapshot (price + 24h change) for the brain"
```

---

## Task 8: Runtime LLM path

**Files:**
- Modify: `backend/app/agents/runtime.py`
- Test: `backend/tests/test_runtime.py`

**Interfaces:**
- Consumes: `build_context` (Task 3), `decide` (Task 6), `make_adapter` (Task 5), `Decision`/`Action` (Task 2), `execute_buy`/`execute_sell` (engine), `market.get_universe_snapshot`/`get_price`/`get_book_ticker`, `settings`.
- Produces: updated `run_decision` that branches on `agent.strategy`. For `"llm"`: gather snapshot + holdings + recent events → `build_context` → `decide(ctx, make_adapter(agent.model_provider, agent.model_name))` → execute actions under guardrails → write a `decision` summary event. SMA path unchanged. `decide` is also importable as a parameter default to allow injection in tests: `run_decision(session, agent, market, symbols, buy_usd, *, brain_decide=decide)`.

- [ ] **Step 1: Write the failing test** in `backend/tests/test_runtime.py`

```python
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.db.models import Agent, Position, Trade, Event
from app.agents.runtime import run_decision
from app.brain.context import CoinSnapshot
from app.brain.schema import Decision, Action


class FakeMarketLLM:
    def __init__(self, snapshot, price, book):
        self._snap, self._price, self._book = snapshot, price, book
    async def get_universe_snapshot(self, symbols): return self._snap
    async def get_price(self, symbol): return self._price
    async def get_book_ticker(self, symbol): return self._book


def _llm_agent(session):
    a = Agent(name="B", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("100"), strategy="llm",
              model_provider="deepseek", model_name="deepseek-chat")
    session.add(a); session.commit()
    return a


async def test_llm_path_executes_buy_with_guardrails(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[
        Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("50"), rationale="dip"),
        Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("2"), rationale="too small"),   # < min_trade
        Action(type="BUY", symbol="NOTINUNIVERSE", usd_amount=Decimal("10"), rationale="x"),     # not in universe
    ], note="testing")
    await run_decision(db_session, agent, market, ["BTCUSDT"], Decimal("10"),
                       brain_decide=lambda ctx, adapter: decision)
    buys = db_session.query(Trade).filter_by(agent_id=agent.id, side="BUY").all()
    assert len(buys) == 1                            # only the valid $50 buy
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").one()
    assert "testing" in ev.message


async def test_llm_path_sells_held_fraction(db_session):
    agent = _llm_agent(db_session)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("2"))]
    market = FakeMarketLLM(snap, Decimal("120"), (Decimal("120"), Decimal("121")))
    decision = Decision(actions=[Action(type="SELL", symbol="BTCUSDT", fraction=Decimal("0.5"))], note="trim")
    await run_decision(db_session, agent, market, ["BTCUSDT"], Decimal("10"),
                       brain_decide=lambda ctx, adapter: decision)
    pos = db_session.query(Position).filter_by(agent_id=agent.id, symbol="BTCUSDT").one()
    assert pos.quantity == Decimal("0.5")
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Update `backend/app/agents/runtime.py`** — keep `run_heartbeat` and the SMA branch of `run_decision`; add the llm branch. Full new `run_decision`:

```python
from decimal import Decimal
from app.core.config import settings
from app.db.models import EquitySnapshot, Event
from app.trading.engine import execute_buy, execute_sell
from app.agents.strategy import decide_signal, guardrail_action
from app.brain import decide as brain_decide_default
from app.brain.context import build_context
from app.brain.providers import make_adapter


# run_heartbeat stays unchanged (see existing file)


async def run_decision(session, agent, market, symbols, buy_usd: Decimal, *, brain_decide=brain_decide_default) -> None:
    if agent.strategy == "sma":
        await _run_decision_sma(session, agent, market, symbols, buy_usd)
    else:
        await _run_decision_llm(session, agent, market, symbols, brain_decide)


async def _run_decision_sma(session, agent, market, symbols, buy_usd: Decimal) -> None:
    held = {p.symbol: p for p in agent.positions}
    actions = errors = 0
    for symbol in symbols:
        try:
            closes = await market.get_klines(symbol, "1h", 50)
            signal = decide_signal(closes)
            if signal == "BUY" and agent.cash_usd >= buy_usd:
                _bid, ask = await market.get_book_ticker(symbol)
                execute_buy(session, agent, symbol, buy_usd, ask); actions += 1
            elif signal == "SELL" and symbol in held:
                bid, _ask = await market.get_book_ticker(symbol)
                execute_sell(session, agent, symbol, held[symbol].quantity, bid); actions += 1
        except Exception:
            errors += 1
    session.add(Event(agent_id=agent.id, kind="decision",
                      message=f"ciclo decisione (SMA): {actions} operazioni su {len(symbols)} simboli, {errors} errori"))
    session.commit()


async def _run_decision_llm(session, agent, market, symbols, brain_decide) -> None:
    universe = await market.get_universe_snapshot(symbols)
    universe_symbols = {c.symbol for c in universe}

    holdings = []
    for pos in agent.positions:
        last = await market.get_price(pos.symbol)
        holdings.append((pos.symbol, pos.quantity, pos.avg_price, last))

    recent = [e.message for e in (
        session.query(Event).filter_by(agent_id=agent.id)
        .order_by(Event.timestamp.desc()).limit(10).all())]

    ctx = build_context(instructions=agent.instructions, cash_usd=agent.cash_usd,
                        holdings=holdings, universe=universe, recent_events=recent)
    adapter = make_adapter(agent.model_provider or "anthropic", agent.model_name or "")
    decision = brain_decide(ctx, adapter)

    held = {p.symbol: p for p in agent.positions}
    actions = skipped = errors = 0
    for action in decision.actions:
        try:
            if action.type == "BUY" and action.symbol in universe_symbols:
                amount = action.usd_amount or settings.decision_buy_default_usd
                if amount < settings.min_trade_usd or amount > agent.cash_usd:
                    skipped += 1; continue
                _bid, ask = await market.get_book_ticker(action.symbol)
                t = execute_buy(session, agent, action.symbol, amount, ask)
                _append_rationale(session, agent, action.rationale); actions += 1
            elif action.type == "SELL" and action.symbol in held:
                frac = action.fraction if action.fraction is not None else Decimal("1")
                qty = held[action.symbol].quantity * frac
                if qty <= 0:
                    skipped += 1; continue
                bid, _ask = await market.get_book_ticker(action.symbol)
                execute_sell(session, agent, action.symbol, qty, bid)
                _append_rationale(session, agent, action.rationale)
                held = {p.symbol: p for p in agent.positions}; actions += 1
            else:
                skipped += 1
        except Exception:
            errors += 1
    note = decision.note or "(no note)"
    session.add(Event(agent_id=agent.id, kind="decision",
                      message=f"ciclo decisione (LLM): {note} — {actions} operazioni, {skipped} saltate, {errors} errori"))
    session.commit()


def _append_rationale(session, agent, rationale: str) -> None:
    if rationale:
        session.add(Event(agent_id=agent.id, kind="reasoning", message=rationale))
```

> Note: the SMA branch is the prior `run_decision` body, moved verbatim into `_run_decision_sma` (with the existing per-symbol try/except and summary event). Confirm the existing SMA tests still pass unchanged.

- [ ] **Step 4: Run the runtime tests — expect PASS** (2 new + existing). `backend/.venv/bin/pytest backend/tests/test_runtime.py -v`

- [ ] **Step 5: Run the full backend suite — expect PASS.** `backend/.venv/bin/pytest backend/tests -q`

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/runtime.py backend/tests/test_runtime.py
git commit -m "feat(brain): runtime LLM decision path with guardrails + reasoning events"
```

---

## Self-Review

**Spec coverage:**
- Provider-agnostic interface (Anthropic + OpenAI-compat) → Task 5. ✅
- Context builder (instructions active, portfolio, universe snapshot, recent events) → Task 3 + Task 7 (snapshot) + Task 8 (assembly). ✅
- Structured output (actions + note) → Task 2; validation + repair + safe fallback → Task 6. ✅
- Runtime integration replacing SMA; SMA kept as selectable baseline → Task 8 + Task 1 (`strategy` field). ✅
- Guardrails (cash + min-trade, universe-only, sell-what's-held) enforced in code → Task 8 + Task 1 (`min_trade_usd`, `decision_buy_default_usd`). ✅
- Per-agent model config (`strategy`, `model_provider`, `model_name`) + env keys/base_urls → Task 1. ✅
- Rationale → events; cycle note → decision event ("show the reasoning") → Task 8. ✅
- Resilience (no raise into loop; error → HOLD + event) → Task 6 + Task 8. ✅
- Offline tests (fake adapters/market) → all test tasks. ✅
- Deps `openai` + `anthropic` → Task 1. ✅
- Out of scope (memory, news, benchmarks) → not in any task. ✅

**Known follow-ups (accepted, not in this plan):** `pct_1h` dropped from the snapshot (only `pct_24h` is a direct Binance field, per the spec note); the brain call is synchronous inside async `run_decision` (acceptable for v1, same blocking caveat already noted for the scheduler); exact provider model ids/pricing verified at Task 5.

**Placeholder scan:** no TBD/"handle errors"/vague steps — every code step has concrete code; the only deferred value is the verified base-url/model-id, gated explicitly at the top of Task 5.

**Type consistency:** `CoinSnapshot` defined in Task 3, consumed by Tasks 4/7/8; `build_context(*, instructions, cash_usd, holdings, universe, recent_events)` signature identical across Tasks 3/8; `decide(ctx, adapter)` signature identical across Tasks 6/8; `complete_json(system, user)` identical across Tasks 5/6; `Decision`/`Action` fields identical across Tasks 2/6/8.
