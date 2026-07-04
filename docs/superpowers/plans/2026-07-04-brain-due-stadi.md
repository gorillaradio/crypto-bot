# Brain a due stadi (Pipeline v2 — Fase 6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Spezzare il prompt decisionale monolitico in due stadi — un **analyst** condiviso per ciclo che produce un *market brief* strutturato (persistito, riusato da tutti gli agenti v2), e un **trader** per-agente che decide su brief + portafoglio + memoria — dietro un flag per-agente `brain_version` che tiene il brain v1 intatto come baseline dell'A/B.

**Architecture:** L'analyst gira una volta nel ciclo orario (`_decision_tick`, solo se ∃ agente v2), scrive un `MarketBrief` (payload + audit Fase-1). Il trader v2 costruisce un context corto (`build_trader_context`: brief filtrato + posizioni live + memoria, **senza** snapshot universo) e riusa la macchina di `evaluate` con `render_trader_prompt`. Le sveglie di Fase 5 riusano l'ultimo brief valido (nessun analyst fuori ciclo, salvo cold-start bootstrap una tantum). Il v1 resta sul percorso attuale, byte-identico.

**Tech Stack:** Python 3.13, SQLAlchemy 2 (Mapped), Alembic, Pydantic v2, pytest (asyncio auto mode, in-memory SQLite via `create_all`), OpenRouter via `make_adapter`.

## Global Constraints

- **Branch:** `pipeline-v2` (long-lived). **NO push / merge / PR without explicit user request** — auto-deploy è su `main`, nulla arriva in prod fino al merge finale delle 6 fasi. Paper trading.
- **Design di riferimento:** `docs/superpowers/specs/2026-07-04-brain-due-stadi-design.md` (7 decisioni chiuse).
- **v1 byte-identico:** il brain v1 (monolite `evaluate`/`render_prompt`) è la **baseline dell'A/B**; il suo output prompt NON deve cambiare. Refactor ammessi solo se preservano l'output (test v1 esistenti restano verdi).
- **Additivo only:** ogni colonna/knob nuovo è additivo con default; `Agent.brain_version` default `"v1"` ⇒ gli agenti esistenti non cambiano comportamento. Nessuna firma esistente perde retrocompatibilità.
- **Tests use `Base.metadata.create_all`, mai le migrazioni.** Ogni migrazione = mirror a mano del modello. Smoke up/down su SQLite usa-e-getta nella finalizzazione (Task 12). **Single Alembic head** (nuova migrazione con `down_revision = '940cbbd9c670'`).
- **Datetime UTC-aware:** mai confrontare un `datetime` Python contro una colonna `DateTime` **in SQL** su SQLite (tz droppato → confronto lessicografico sbagliato). Filtra in SQL solo per id/uguaglianza/`isnot`, ordina per colonna, e confronta le finestre in Python via `_as_utc` (come `app/eval/scoring_job.py`). Qui l'ordinamento `created_at desc` in SQL è ammesso (è ordinamento, non confronto con un datetime Python).
- **Watermark news loss-free (Fase 5):** NON reintrodurre l'avanzamento di `Agent.last_seen_observation_id` a ogni decisione. Resta come in Fase 5 (solo sulla sveglia news, in `run_heartbeat`). Questa fase non tocca quel codice.
- **`_base`/USDT coupling** (`feeds/query.py`) invariato: i chiamanti passano universi `USDT`.
- **`analyst_model`:** lo slug OpenRouter di default (`deepseek/deepseek-v4-pro`) va **verificato al wiring/deploy** — è un env var; non asserirlo come fatto.
- **Model per task** è indicato nell'header di ogni task.
- **Base commit per la review finale:** `d5423d0` (i commit Fase 6 partono da qui). Scope review finale = `d5423d0..HEAD`, **NON** `main...pipeline-v2`.

---

## File Structure

**Nuovi file**
- `backend/app/brain/analyst_schema.py` — shape del brief: `Highlight`, `MarketBriefSchema` (Pydantic), `AnalystResult` (dataclass, gemello di `DecisionResult`).
- `backend/app/brain/analyst.py` — `AnalystContext`, `render_analyst_prompt`, `run_analyst` (mirror di `evaluate`).
- `backend/app/brain/brief_store.py` — `persist_brief`, `latest_valid_brief`, `filter_brief_for` (persistenza/riuso/filtro del `MarketBrief`).
- `backend/tests/test_analyst_schema.py`, `test_analyst.py`, `test_brief_store.py`, `test_brain_trader_prompt.py`, `test_brain_v2_dispatch.py`, `test_analyst_orchestration.py`.

**Modifiche**
- `backend/app/db/models.py` — `Agent.brain_version`; nuovo modello `MarketBrief`.
- `backend/app/core/config.py` — knob `analyst_model`, `brief_max_highlights`, `analyst_news_limit`.
- `backend/app/brain/context.py` — `HighlightView`, `MarketBriefView`, `DecisionContext.brief`, param `brief` in `build_context`.
- `backend/app/brain/prompt.py` — `render_trader_prompt`.
- `backend/app/brain/__init__.py` — refactor `_evaluate_with` + `evaluate_trader` (v1 `evaluate` output-invariato).
- `backend/app/agents/runtime.py` — `run_analyst_cycle`, `get_or_bootstrap_brief`, `build_trader_context`, dispatch per `brain_version` in `run_decision`/`run_decision_guarded`, `_build_decision_context`, guardrail BUY su `symbols`.
- `backend/app/scheduler/jobs.py` — preambolo analyst in `_decision_tick`.
- `backend/app/api/schemas.py`, `routes.py` — `brain_version` in `AgentCreate` + `create_agent`.
- `backend/alembic/versions/<rev>_brain_due_stadi.py` — migrazione (mirror a mano).

---

## Task 1: Config knob + modelli (`Agent.brain_version`, `MarketBrief`) + migrazione  [sonnet]

**Files:**
- Modify: `backend/app/core/config.py` (dopo il blocco `--- brain v1 ---`, ~riga 29)
- Modify: `backend/app/db/models.py` (`Agent`, ~riga 31; nuovo modello in fondo, dopo `Observation`)
- Create: `backend/alembic/versions/<rev>_brain_due_stadi.py`
- Test: `backend/tests/test_analyst_schema.py` (blocco settings/model — sì, i primi test DB stanno qui per comodità; il grosso dei test schema è nel Task 2)

**Interfaces:**
- Produces: `settings.analyst_model: str`, `settings.brief_max_highlights: int`, `settings.analyst_news_limit: int`; `Agent.brain_version: str` (default `"v1"`); modello `MarketBrief` (tabella `market_briefs`) con campi `id, cycle_id, parsed_brief, system_prompt, user_prompt, raw_response, parse_status, model_provider, model_name, latency_ms, created_at`.

- [ ] **Step 1: Write the failing test**

Crea `backend/tests/test_analyst_schema.py`:

```python
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.core.config import settings
from app.db.models import Agent, MarketBrief


def _agent(session, **kw):
    a = Agent(name="T", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("100"), **kw)
    session.add(a); session.commit()
    return a


def test_brain_v2_settings_present():
    assert settings.analyst_model == "deepseek/deepseek-v4-pro"
    assert settings.brief_max_highlights == 15
    assert settings.analyst_news_limit == 30


def test_agent_brain_version_defaults_v1(db_session):
    assert _agent(db_session).brain_version == "v1"


def test_agent_brain_version_can_be_v2(db_session):
    assert _agent(db_session, brain_version="v2").brain_version == "v2"


def test_market_brief_insert_and_nullable_payload(db_session):
    b = MarketBrief(cycle_id="c1", parsed_brief=None, system_prompt="s", user_prompt="u",
                    raw_response=None, parse_status="failed",
                    model_provider="openrouter", model_name="deepseek/deepseek-v4-pro",
                    latency_ms=12)
    db_session.add(b); db_session.commit()
    assert b.id is not None and b.parsed_brief is None and b.created_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_analyst_schema.py -q`
Expected: FAIL (`AttributeError`/`ImportError`: no `analyst_model`, no `MarketBrief`, no `brain_version`).

- [ ] **Step 3: Add the config knobs**

In `backend/app/core/config.py`, subito dopo `min_trade_usd: Decimal = Decimal("5")`:

```python

    # --- brain v2 (Fase 6) ---
    analyst_model: str = "deepseek/deepseek-v4-pro"   # OpenRouter slug — verify at wiring/deploy
    brief_max_highlights: int = 15
    analyst_news_limit: int = 30
```

- [ ] **Step 4: Add the model changes**

In `backend/app/db/models.py`, dentro `Agent` dopo `last_seen_observation_id` (~riga 31):

```python
    # Brain version: "v1" = monolithic prompt (baseline), "v2" = analyst+trader two-stage.
    brain_version: Mapped[str] = mapped_column(String(10), nullable=False,
                                               default="v1", server_default="v1")
```

In fondo al file, dopo la classe `Observation`:

```python


class MarketBrief(Base):
    __tablename__ = "market_briefs"
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[str] = mapped_column(String(32), index=True)
    # Parsed brief JSON (regime/highlights/key_news). NULL when the analyst parse failed
    # → latest_valid_brief() skips it. Present rows (parse ok/repaired) are reusable.
    parsed_brief: Mapped[str | None] = mapped_column(String, nullable=True)
    # Audit (Fase 1 parity): the analyst call is recorded here, not in DecisionRecord,
    # because it is shared/per-cycle, not per-agent.
    system_prompt: Mapped[str] = mapped_column(String)
    user_prompt: Mapped[str] = mapped_column(String)
    raw_response: Mapped[str | None] = mapped_column(String, nullable=True)
    parse_status: Mapped[str] = mapped_column(String(10))    # "ok" | "repaired" | "failed"
    model_provider: Mapped[str] = mapped_column(String(40))
    model_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_analyst_schema.py -q`
Expected: PASS (4 test).

- [ ] **Step 6: Write the migration (hand-mirrored; smoke-tested in Task 12)**

Genera lo scheletro per avere un revision id valido e datato:

Run: `cd backend && .venv/bin/alembic revision -m "brain due stadi columns"`

Poi **sostituisci** `down_revision`, `upgrade`, `downgrade` del file generato con:

```python
down_revision: Union[str, Sequence[str], None] = '940cbbd9c670'


def upgrade() -> None:
    op.add_column("agents",
        sa.Column("brain_version", sa.String(length=10), nullable=False, server_default="v1"))
    op.create_table(
        "market_briefs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cycle_id", sa.String(length=32), nullable=False),
        sa.Column("parsed_brief", sa.String(), nullable=True),
        sa.Column("system_prompt", sa.String(), nullable=False),
        sa.Column("user_prompt", sa.String(), nullable=False),
        sa.Column("raw_response", sa.String(), nullable=True),
        sa.Column("parse_status", sa.String(length=10), nullable=False),
        sa.Column("model_provider", sa.String(length=40), nullable=False),
        sa.Column("model_name", sa.String(length=80), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_market_briefs_cycle_id", "market_briefs", ["cycle_id"])
    op.create_index("ix_market_briefs_created_at", "market_briefs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_market_briefs_created_at", table_name="market_briefs")
    op.drop_index("ix_market_briefs_cycle_id", table_name="market_briefs")
    op.drop_table("market_briefs")
    op.drop_column("agents", "brain_version")
```

Verifica singola head: `cd backend && .venv/bin/alembic heads` → deve stampare **una** sola revision (la nuova).

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/config.py backend/app/db/models.py backend/alembic/versions backend/tests/test_analyst_schema.py
git commit -m "feat(brain-v2): brain_version flag + MarketBrief table + config knobs + migration"
```

---

## Task 2: Analyst schema (`analyst_schema.py`)  [haiku]

**Files:**
- Create: `backend/app/brain/analyst_schema.py`
- Test: `backend/tests/test_analyst_schema.py` (aggiungi al file del Task 1)

**Interfaces:**
- Produces: `Highlight(BaseModel){symbol:str, snapshot:str, signal:Literal["bullish","bearish","neutral"], note:str}`; `MarketBriefSchema(BaseModel){regime:str, highlights:list[Highlight], key_news:list[str]}`; `AnalystResult` (dataclass){brief:MarketBriefSchema, system, user, raw, parse_status, latency_ms}.

- [ ] **Step 1: Write the failing test**

Aggiungi in coda a `backend/tests/test_analyst_schema.py`:

```python
from app.brain.analyst_schema import Highlight, MarketBriefSchema


def test_parses_full_brief():
    raw = ('{"regime":"risk-on, BTC leads","highlights":'
           '[{"symbol":"SOLUSDT","snapshot":"$182 (+9.4% 24h)","signal":"bullish","note":"momentum"}],'
           '"key_news":["Fed holds rates"]}')
    b = MarketBriefSchema.model_validate_json(raw)
    assert b.regime.startswith("risk-on")
    assert b.highlights[0].symbol == "SOLUSDT" and b.highlights[0].signal == "bullish"
    assert b.key_news == ["Fed holds rates"]


def test_defaults_empty():
    b = MarketBriefSchema.model_validate_json("{}")
    assert b.regime == "" and b.highlights == [] and b.key_news == []


def test_signal_rejects_unknown():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Highlight.model_validate({"symbol": "BTCUSDT", "signal": "moon"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_analyst_schema.py -q`
Expected: FAIL (`ImportError`: no `analyst_schema`).

- [ ] **Step 3: Write the schema**

Crea `backend/app/brain/analyst_schema.py`:

```python
from dataclasses import dataclass
from typing import Literal
from pydantic import BaseModel


class Highlight(BaseModel):
    symbol: str
    snapshot: str = ""
    signal: Literal["bullish", "bearish", "neutral"] = "neutral"
    note: str = ""


class MarketBriefSchema(BaseModel):
    regime: str = ""
    highlights: list[Highlight] = []
    key_news: list[str] = []


@dataclass
class AnalystResult:
    brief: MarketBriefSchema
    system: str = ""
    user: str = ""
    raw: str | None = None
    parse_status: str = "ok"      # "ok" | "repaired" | "failed"
    latency_ms: int = 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_analyst_schema.py -q`
Expected: PASS (7 test totali nel file).

- [ ] **Step 5: Commit**

```bash
git add backend/app/brain/analyst_schema.py backend/tests/test_analyst_schema.py
git commit -m "feat(brain-v2): market brief pydantic schema + AnalystResult"
```

---

## Task 3: Analyst prompt + runner (`analyst.py`)  [sonnet]

**Files:**
- Create: `backend/app/brain/analyst.py`
- Test: `backend/tests/test_analyst.py`

**Interfaces:**
- Consumes: `MarketBriefSchema`, `AnalystResult` (Task 2); `CoinSnapshot`, `ObservationView` (context.py); `retry_user_suffix` (prompt.py); `settings.brief_max_highlights`.
- Produces: `AnalystContext(universe: list[CoinSnapshot], observations: list[ObservationView])`; `render_analyst_prompt(ctx) -> tuple[str, str]`; `run_analyst(ctx, adapter) -> AnalystResult`.

- [ ] **Step 1: Write the failing test**

Crea `backend/tests/test_analyst.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal
from app.brain.analyst import AnalystContext, render_analyst_prompt, run_analyst
from app.brain.context import CoinSnapshot, ObservationView


class _Adapter:
    def __init__(self, outputs): self.outputs = list(outputs); self.calls = 0
    def complete_json(self, system, user):
        self.calls += 1
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def _ctx():
    return AnalystContext(
        universe=[CoinSnapshot("BTCUSDT", Decimal("60000"), Decimal("2")),
                  CoinSnapshot("ETHUSDT", Decimal("3000"), Decimal("-1"))],
        observations=[ObservationView("CoinDesk", "Bitcoin ETF inflows",
                                      datetime(2026, 7, 4, 10, 0, tzinfo=timezone.utc), ["BTC"]),
                      ObservationView("Cointelegraph", "Fed holds rates",
                                      datetime(2026, 7, 4, 9, 0, tzinfo=timezone.utc), [])])


_OK = ('{"regime":"risk-on","highlights":[{"symbol":"BTCUSDT","snapshot":"$60000 (+2% 24h)",'
       '"signal":"bullish","note":"etf"}],"key_news":["Fed holds"]}')


def test_render_includes_universe_news_and_schema():
    system, user = render_analyst_prompt(_ctx())
    assert "JSON" in system and "highlights" in system and "15" in system   # cap surfaced
    assert "BTCUSDT" in user and "Bitcoin ETF inflows" in user
    assert "[market]" in user                                   # empty-symbol obs labelled
    assert user.index("BTCUSDT") < user.index("ETHUSDT")        # sorted by symbol


def test_run_analyst_ok_captures_raw_status_latency():
    r = run_analyst(_ctx(), _Adapter([_OK]))
    assert r.parse_status == "ok" and r.brief.regime == "risk-on"
    assert r.brief.highlights[0].symbol == "BTCUSDT"
    assert r.raw == _OK and r.system and r.user and r.latency_ms >= 0


def test_run_analyst_repairs_then_succeeds():
    a = _Adapter(["not json", _OK])
    r = run_analyst(_ctx(), a)
    assert r.parse_status == "repaired" and r.brief.regime == "risk-on" and a.calls == 2


def test_run_analyst_failed_keeps_empty_brief_and_last_raw():
    r = run_analyst(_ctx(), _Adapter(["bad", "still bad"]))
    assert r.parse_status == "failed" and r.brief.highlights == [] and r.raw == "still bad"


def test_run_analyst_provider_error_is_failed_null_raw():
    r = run_analyst(_ctx(), _Adapter([RuntimeError("boom")]))
    assert r.parse_status == "failed" and r.raw is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_analyst.py -q`
Expected: FAIL (`ImportError`: no `analyst`).

- [ ] **Step 3: Write the analyst**

Crea `backend/app/brain/analyst.py`:

```python
from dataclasses import dataclass
from time import perf_counter
from app.brain.analyst_schema import MarketBriefSchema, AnalystResult
from app.brain.context import CoinSnapshot, ObservationView
from app.brain.prompt import retry_user_suffix
from app.core.config import settings


@dataclass
class AnalystContext:
    universe: list[CoinSnapshot]
    observations: list[ObservationView]


_SYSTEM = """You are a crypto market analyst. Synthesize the market data and recent news into a
compact, structured brief that downstream trading agents will read. Surface only what matters now —
market regime plus the coins worth attention (movers, news-driven, opportunities/risks) — not a line
for every coin. Use the exact symbol shown (e.g. BTCUSDT). Respond with ONLY a JSON object of this
exact shape:
{{"regime": "<2-3 sentences: overall direction, BTC/ETH lead, risk sentiment, dominant theme>",
  "highlights": [{{"symbol": "<SYMBOL>", "snapshot": "<price and 24h move>",
    "signal": "bullish"|"bearish"|"neutral", "note": "<one sentence: momentum + any news + why it matters>"}}],
  "key_news": ["<market-wide item not tied to a single coin>"]}}
At most {max_highlights} highlights, most important first. Output JSON only, no prose."""


def render_analyst_prompt(ctx: AnalystContext) -> tuple[str, str]:
    system = _SYSTEM.format(max_highlights=settings.brief_max_highlights)
    lines = ["Market (top by market cap):"]
    for c in sorted(ctx.universe, key=lambda c: c.symbol):
        lines.append(f"  {c.symbol}: ${c.price} ({c.pct_24h:+.2f}% 24h)")
    lines += ["", "Recent crypto news (headlines):"]
    if ctx.observations:
        for o in ctx.observations:
            when = o.published_at.strftime("%m-%d %H:%M")
            tag = f"[{', '.join(o.symbols)}]" if o.symbols else "[market]"
            lines.append(f"  - {when} {o.source}: {o.title} {tag}")
    else:
        lines.append("  (none)")
    return system, "\n".join(lines)


def run_analyst(ctx: AnalystContext, adapter) -> AnalystResult:
    system, user = render_analyst_prompt(ctx)
    t0 = perf_counter()
    try:
        raw = adapter.complete_json(system, user)
    except Exception:                         # provider error — no response received
        return AnalystResult(MarketBriefSchema(), system, user, None, "failed",
                             int((perf_counter() - t0) * 1000))
    try:
        brief = MarketBriefSchema.model_validate_json(raw)
        return AnalystResult(brief, system, user, raw, "ok", int((perf_counter() - t0) * 1000))
    except Exception as first_err:
        raw2 = None
        try:
            raw2 = adapter.complete_json(system, user + retry_user_suffix(str(first_err)))
            brief = MarketBriefSchema.model_validate_json(raw2)
            return AnalystResult(brief, system, user, raw2, "repaired",
                                 int((perf_counter() - t0) * 1000))
        except Exception:
            return AnalystResult(MarketBriefSchema(), system, user,
                                 raw2 if raw2 is not None else raw, "failed",
                                 int((perf_counter() - t0) * 1000))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_analyst.py -q`
Expected: PASS (5 test).

- [ ] **Step 5: Commit**

```bash
git add backend/app/brain/analyst.py backend/tests/test_analyst.py
git commit -m "feat(brain-v2): analyst prompt + run_analyst (mirror of evaluate)"
```

---

## Task 4: Brief context plumbing (`context.py`)  [haiku]

**Files:**
- Modify: `backend/app/brain/context.py` (aggiungi le view; `DecisionContext`, ~riga 38; `build_context`, ~riga 50)
- Test: `backend/tests/test_brain_context.py` (aggiungi in coda)

**Interfaces:**
- Produces: `HighlightView(symbol, snapshot, signal, note)` (dataclass); `MarketBriefView(regime, highlights: list[HighlightView], key_news: list[str], as_of: datetime|None)` (dataclass); `DecisionContext.brief: MarketBriefView | None`; `build_context(..., brief=None)`.

- [ ] **Step 1: Write the failing test**

Aggiungi in coda a `backend/tests/test_brain_context.py`:

```python
def test_build_context_accepts_brief():
    from decimal import Decimal
    from app.brain.context import build_context, MarketBriefView, HighlightView
    brief = MarketBriefView(regime="risk-on",
                            highlights=[HighlightView("BTCUSDT", "$60000", "bullish", "etf")])
    ctx = build_context(instructions="x", cash_usd=Decimal("100"), holdings=[], universe=[],
                        recent_events=[], brief=brief)
    assert ctx.brief.regime == "risk-on" and ctx.brief.highlights[0].symbol == "BTCUSDT"


def test_build_context_brief_defaults_none():
    from decimal import Decimal
    from app.brain.context import build_context
    ctx = build_context(instructions="x", cash_usd=Decimal("100"), holdings=[], universe=[],
                        recent_events=[])
    assert ctx.brief is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_brain_context.py -q`
Expected: FAIL (`ImportError: MarketBriefView` / `TypeError` unexpected kwarg `brief`).

- [ ] **Step 3: Add the views + context field**

In `backend/app/brain/context.py`, dopo `ObservationView` (~riga 35), aggiungi:

```python


@dataclass
class HighlightView:
    symbol: str
    snapshot: str = ""
    signal: str = "neutral"
    note: str = ""


@dataclass
class MarketBriefView:
    regime: str = ""
    highlights: list[HighlightView] = field(default_factory=list)
    key_news: list[str] = field(default_factory=list)
    as_of: datetime | None = None
```

In `DecisionContext`, dopo `observations: ...` (~riga 47):

```python
    brief: "MarketBriefView | None" = None
```

In `build_context`, aggiungi il parametro e passalo. Firma (~riga 50) → aggiungi `brief=None` prima di `wake_reason=None`; nel `return DecisionContext(...)` aggiungi `brief=brief,`:

```python
def build_context(*, instructions, cash_usd, holdings, universe, recent_events, memory=None,
                  observations=None, brief=None, wake_reason=None) -> DecisionContext:
```
```python
        memory=memory or MemoryView(), observations=observations or [], brief=brief,
        wake_reason=wake_reason,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_brain_context.py -q`
Expected: PASS (tutti, inclusi i 2 nuovi).

- [ ] **Step 5: Commit**

```bash
git add backend/app/brain/context.py backend/tests/test_brain_context.py
git commit -m "feat(brain-v2): MarketBriefView + DecisionContext.brief plumbing"
```

---

## Task 5: Brief store (`brief_store.py`)  [sonnet]

**Files:**
- Create: `backend/app/brain/brief_store.py`
- Test: `backend/tests/test_brief_store.py`

**Interfaces:**
- Consumes: `MarketBrief` (Task 1); `AnalystResult` (Task 2); `MarketBriefView`, `HighlightView` (Task 4); `settings.analyst_model`.
- Produces: `persist_brief(session, cycle_id, result) -> MarketBrief`; `latest_valid_brief(session) -> MarketBrief | None`; `filter_brief_for(brief_row, universe_symbols) -> MarketBriefView`.

- [ ] **Step 1: Write the failing test**

Crea `backend/tests/test_brief_store.py`:

```python
from app.brain.analyst_schema import MarketBriefSchema, Highlight, AnalystResult
from app.brain.brief_store import persist_brief, latest_valid_brief, filter_brief_for


def _result(regime="risk-on", parse_status="ok"):
    brief = MarketBriefSchema(regime=regime, key_news=["Fed"], highlights=[
        Highlight(symbol="BTCUSDT", snapshot="$60000", signal="bullish", note="etf"),
        Highlight(symbol="XRPUSDT", snapshot="$0.5", signal="bearish", note="suit")])
    return AnalystResult(brief, system="s", user="u", raw="{}", parse_status=parse_status, latency_ms=7)


def test_persist_ok_writes_payload_and_audit(db_session):
    row = persist_brief(db_session, "c1", _result())
    assert row.id is not None and row.parse_status == "ok"
    assert row.parsed_brief and "risk-on" in row.parsed_brief
    assert row.model_provider == "openrouter" and row.system_prompt == "s"


def test_persist_failed_stores_null_payload(db_session):
    row = persist_brief(db_session, "c2", _result(parse_status="failed"))
    assert row.parsed_brief is None


def test_latest_valid_skips_failed_and_returns_newest(db_session):
    persist_brief(db_session, "c1", _result(regime="old"))
    persist_brief(db_session, "c2", _result(parse_status="failed"))   # newer but unusable
    latest = latest_valid_brief(db_session)
    assert latest is not None and "old" in latest.parsed_brief         # skips the failed one


def test_latest_valid_none_when_empty(db_session):
    assert latest_valid_brief(db_session) is None


def test_filter_for_universe(db_session):
    row = persist_brief(db_session, "c1", _result())
    view = filter_brief_for(row, ["BTCUSDT", "ETHUSDT"])   # XRP not in universe
    assert view.regime == "risk-on" and view.key_news == ["Fed"]
    assert [h.symbol for h in view.highlights] == ["BTCUSDT"]   # XRP filtered out
    assert view.highlights[0].signal == "bullish" and view.as_of is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_brief_store.py -q`
Expected: FAIL (`ImportError`: no `brief_store`).

- [ ] **Step 3: Write the store**

Crea `backend/app/brain/brief_store.py`:

```python
import json
from app.core.config import settings
from app.db.models import MarketBrief
from app.brain.context import MarketBriefView, HighlightView


def persist_brief(session, cycle_id: str, result) -> MarketBrief:
    """Write the analyst call to MarketBrief: parsed payload (NULL if parse failed) + Fase-1 audit."""
    row = MarketBrief(
        cycle_id=cycle_id,
        parsed_brief=(result.brief.model_dump_json() if result.parse_status != "failed" else None),
        system_prompt=result.system, user_prompt=result.user, raw_response=result.raw,
        parse_status=result.parse_status,
        model_provider="openrouter", model_name=settings.analyst_model,
        latency_ms=result.latency_ms)
    session.add(row)
    session.commit()
    return row


def latest_valid_brief(session) -> MarketBrief | None:
    """Most recent brief with a usable payload (parse ok/repaired). Ordering by created_at is a
    SQL ORDER BY, not a datetime comparison — safe on SQLite."""
    return (session.query(MarketBrief)
            .filter(MarketBrief.parsed_brief.isnot(None))
            .order_by(MarketBrief.created_at.desc(), MarketBrief.id.desc())
            .first())


def filter_brief_for(brief_row, universe_symbols) -> MarketBriefView:
    """Global brief → per-agent view: keep only highlights whose symbol is in the agent's universe;
    regime + key_news pass through."""
    data = json.loads(brief_row.parsed_brief)
    keep = set(universe_symbols)
    highlights = [HighlightView(symbol=h.get("symbol", ""), snapshot=h.get("snapshot", ""),
                                signal=h.get("signal", "neutral"), note=h.get("note", ""))
                  for h in data.get("highlights", []) if h.get("symbol") in keep]
    return MarketBriefView(regime=data.get("regime", ""), highlights=highlights,
                           key_news=data.get("key_news", []), as_of=brief_row.created_at)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_brief_store.py -q`
Expected: PASS (5 test; assicurati di aver tolto il segnaposto).

- [ ] **Step 5: Commit**

```bash
git add backend/app/brain/brief_store.py backend/tests/test_brief_store.py
git commit -m "feat(brain-v2): brief store — persist, latest-valid, per-universe filter"
```

---

## Task 6: Trader prompt + `evaluate_trader`  [sonnet]

**Files:**
- Modify: `backend/app/brain/prompt.py` (aggiungi `render_trader_prompt` dopo `render_prompt`)
- Modify: `backend/app/brain/__init__.py` (refactor `_evaluate_with` + `evaluate_trader`)
- Test: `backend/tests/test_brain_trader_prompt.py`

**Interfaces:**
- Consumes: `DecisionContext.brief` (Task 4); `_SYSTEM`, `retry_user_suffix` (prompt.py).
- Produces: `render_trader_prompt(ctx) -> tuple[str, str]`; `evaluate_trader(ctx, adapter) -> DecisionResult`; `_evaluate_with(ctx, adapter, render) -> DecisionResult` (interno).

- [ ] **Step 1: Write the failing test**

Crea `backend/tests/test_brain_trader_prompt.py`:

```python
from decimal import Decimal
from datetime import datetime, timezone
from app.brain.context import build_context, MarketBriefView, HighlightView
from app.brain.prompt import render_trader_prompt
from app.brain import evaluate_trader


class _Adapter:
    def __init__(self, outputs): self.outputs = list(outputs); self.calls = 0
    def complete_json(self, system, user):
        self.calls += 1
        return self.outputs.pop(0)


def _brief():
    return MarketBriefView(regime="risk-on, BTC leads",
                           highlights=[HighlightView("BTCUSDT", "$60000 (+2% 24h)", "bullish", "etf inflows")],
                           key_news=["Fed holds rates"],
                           as_of=datetime(2026, 7, 4, 14, 0, tzinfo=timezone.utc))


def _ctx(brief=None):
    return build_context(instructions="favor blue chips", cash_usd=Decimal("100"),
                         holdings=[], universe=[], recent_events=[], brief=brief,
                         wake_reason=None)


def test_trader_prompt_uses_brief_not_universe_table():
    system, user = render_trader_prompt(_ctx(_brief()))
    assert "favor blue chips" in system and '"actions"' in system   # same Decision contract
    assert "Regime: risk-on, BTC leads" in user
    assert "BTCUSDT" in user and "[bullish]" in user and "Fed holds rates" in user
    assert "Market (universe):" not in user                         # NO raw universe table


def test_trader_prompt_handles_missing_brief():
    system, user = render_trader_prompt(_ctx(None))
    assert "unavailable" in user.lower()


def test_trader_prompt_surfaces_wake_reason():
    ctx = build_context(instructions="", cash_usd=Decimal("100"), holdings=[], universe=[],
                        recent_events=[], brief=_brief(),
                        wake_reason="SOLUSDT news: hack")
    _system, user = render_trader_prompt(ctx)
    assert "SOLUSDT news: hack" in user


def test_evaluate_trader_parses_decision():
    r = evaluate_trader(_ctx(_brief()),
                        _Adapter(['{"actions":[{"type":"HOLD","rationale":"wait"}],"note":"n"}']))
    assert r.parse_status == "ok" and r.decision.note == "n"
    assert "Regime:" in r.user            # the trader prompt was used
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_brain_trader_prompt.py -q`
Expected: FAIL (`ImportError`: no `render_trader_prompt` / `evaluate_trader`).

- [ ] **Step 3: Add `render_trader_prompt`**

In `backend/app/brain/prompt.py`, dopo `render_prompt` (prima di `retry_user_suffix`):

```python
def render_trader_prompt(ctx: DecisionContext) -> tuple[str, str]:
    """v2 trader prompt: brief (già filtrato) + posizioni live + memoria + wake_reason. Nessuna
    tabella universo (l'analyst ha già sintetizzato il mercato). Stesso contratto Decision del v1."""
    system = _SYSTEM.format(instructions=ctx.instructions or "(none provided)")

    lines = []
    if ctx.wake_reason:
        lines += [f"⚠ {ctx.wake_reason}", ""]
    lines += [f"Cash: ${ctx.cash_usd}", f"Equity: ${ctx.equity_usd}", "", "Open positions:"]
    if ctx.positions:
        for p in ctx.positions:
            lines.append(f"  {p.symbol}: qty {p.quantity} @ avg ${p.avg_price}, "
                         f"now ${p.last_price} ({p.unrealized_pnl_pct:+.2f}%)")
    else:
        lines.append("  (none)")

    b = ctx.brief
    if b is not None:
        when = f" (as of {b.as_of.strftime('%m-%d %H:%M')})" if b.as_of else ""
        lines += ["", f"Market brief{when}:", f"Regime: {b.regime or '(n/a)'}",
                  "", "Watchlist (your universe):"]
        if b.highlights:
            for h in b.highlights:
                lines.append(f"  {h.symbol} {h.snapshot} [{h.signal}] {h.note}")
        else:
            lines.append("  (nothing notable in your universe)")
        if b.key_news:
            lines += ["", "Market news:"] + [f"  - {n}" for n in b.key_news]
    else:
        lines += ["", "Market brief: (unavailable this cycle)"]

    # Memory block — identical output to render_prompt (v1). Duplicated deliberately to keep the v1
    # renderer untouched (baseline); a shared helper would refactor v1 code. ~10 lines.
    mem = ctx.memory
    mem_lines = []
    for label, text in (("Coin theses", mem.coin_theses),
                        ("Trade lessons", mem.trade_lessons),
                        ("Strategy notes", mem.strategy_notes)):
        rows = [l for l in text.splitlines() if l.strip()]
        if rows:
            mem_lines.append(f"{label}:")
            mem_lines += [f"  - {l}" for l in rows]
    if mem_lines:
        system = system + "\n\nYour memory below is your own prior reflection on past trades — treat it as your evolving view."
        lines += ["", "Your memory (you wrote this; update your behaviour accordingly):"] + mem_lines

    return system, "\n".join(lines)
```

- [ ] **Step 4: Refactor `evaluate` to share machinery + add `evaluate_trader`**

Sostituisci il corpo di `backend/app/brain/__init__.py` (mantieni `decide`):

```python
from time import perf_counter
from app.brain.schema import Decision, DecisionResult
from app.brain.context import DecisionContext
from app.brain.prompt import render_prompt, render_trader_prompt, retry_user_suffix


def _elapsed_ms(t0: float) -> int:
    return int((perf_counter() - t0) * 1000)


def _evaluate_with(ctx: DecisionContext, adapter, render) -> DecisionResult:
    system, user = render(ctx)
    t0 = perf_counter()
    try:
        raw = adapter.complete_json(system, user)
    except Exception as exc:  # network / provider error — no response received
        return DecisionResult(Decision(actions=[], note=f"brain error: {exc}"),
                              system, user, None, "failed", _elapsed_ms(t0))
    try:
        decision = Decision.model_validate_json(raw)
        return DecisionResult(decision, system, user, raw, "ok", _elapsed_ms(t0))
    except Exception as first_err:
        raw2 = None
        try:
            raw2 = adapter.complete_json(system, user + retry_user_suffix(str(first_err)))
            decision = Decision.model_validate_json(raw2)
            return DecisionResult(decision, system, user, raw2, "repaired", _elapsed_ms(t0))
        except Exception as second_err:
            return DecisionResult(
                Decision(actions=[], note=f"decision parse failed: {second_err}"),
                system, user, raw2 if raw2 is not None else raw, "failed", _elapsed_ms(t0))


def evaluate(ctx: DecisionContext, adapter) -> DecisionResult:
    return _evaluate_with(ctx, adapter, render_prompt)


def evaluate_trader(ctx: DecisionContext, adapter) -> DecisionResult:
    return _evaluate_with(ctx, adapter, render_trader_prompt)


def decide(ctx: DecisionContext, adapter) -> Decision:
    return evaluate(ctx, adapter).decision
```

- [ ] **Step 5: Run tests (new + v1 regression)**

Run: `cd backend && .venv/bin/pytest tests/test_brain_trader_prompt.py tests/test_brain_decide.py tests/test_brain_prompt.py -q`
Expected: PASS — i nuovi + **tutti** i test v1 esistenti (evaluate invariato).

- [ ] **Step 6: Commit**

```bash
git add backend/app/brain/prompt.py backend/app/brain/__init__.py backend/tests/test_brain_trader_prompt.py
git commit -m "feat(brain-v2): trader prompt + evaluate_trader (shared eval machinery, v1 output unchanged)"
```

---

## Task 7: Analyst orchestration — `run_analyst_cycle` + `get_or_bootstrap_brief`  [sonnet]

**Files:**
- Modify: `backend/app/agents/runtime.py` (nuove funzioni + import)
- Test: `backend/tests/test_analyst_orchestration.py`

**Interfaces:**
- Consumes: `run_analyst`, `AnalystContext` (Task 3); `persist_brief`, `latest_valid_brief` (Task 5); `recent_observations_for`; `make_adapter`; `settings.analyst_model`, `settings.analyst_news_limit`.
- Produces: `run_analyst_cycle(session, market, *, run=run_analyst, adapter=None) -> MarketBrief | None`; `get_or_bootstrap_brief(session, market, *, run_cycle=None) -> MarketBrief | None`.

- [ ] **Step 1: Write the failing test**

Crea `backend/tests/test_analyst_orchestration.py`:

```python
import pytest
from decimal import Decimal
from app.brain.context import CoinSnapshot
from app.brain.analyst_schema import MarketBriefSchema, Highlight, AnalystResult
from app.agents.runtime import run_analyst_cycle, get_or_bootstrap_brief
from app.brain.brief_store import latest_valid_brief

pytestmark = pytest.mark.asyncio


class _Market:
    def __init__(self): self.top_calls = 0
    async def get_top_symbols(self, quote, n): self.top_calls += 1; return ["BTCUSDT", "ETHUSDT"]
    async def get_universe_snapshot(self, symbols):
        return [CoinSnapshot(s, Decimal("100"), Decimal("1")) for s in symbols]


def _fake_run(status="ok"):
    def run(ctx, adapter):
        brief = MarketBriefSchema(regime="risk-on",
                                  highlights=[Highlight(symbol="BTCUSDT", signal="bullish")])
        return AnalystResult(brief, "s", "u", "{}", status, 5)
    return run


async def test_run_analyst_cycle_persists_and_returns_row(db_session):
    row = await run_analyst_cycle(db_session, _Market(), run=_fake_run(), adapter=object())
    assert row is not None and "risk-on" in row.parsed_brief
    assert latest_valid_brief(db_session) is not None


async def test_run_analyst_cycle_failed_persists_but_returns_none(db_session):
    row = await run_analyst_cycle(db_session, _Market(), run=_fake_run("failed"), adapter=object())
    assert row is None                                   # unusable → caller must not use it
    assert latest_valid_brief(db_session) is None        # audit row exists but has NULL payload


async def test_get_or_bootstrap_reuses_existing(db_session):
    await run_analyst_cycle(db_session, _Market(), run=_fake_run(), adapter=object())
    calls = {"n": 0}
    async def _cycle(session, market): calls["n"] += 1; return None
    row = await get_or_bootstrap_brief(db_session, _Market(), run_cycle=_cycle)
    assert row is not None and calls["n"] == 0           # reused, no bootstrap


async def test_get_or_bootstrap_runs_cycle_when_empty(db_session):
    calls = {"n": 0}
    async def _cycle(session, market):
        calls["n"] += 1
        return await run_analyst_cycle(session, market, run=_fake_run(), adapter=object())
    row = await get_or_bootstrap_brief(db_session, _Market(), run_cycle=_cycle)
    assert row is not None and calls["n"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_analyst_orchestration.py -q`
Expected: FAIL (`ImportError`: no `run_analyst_cycle`).

- [ ] **Step 3: Add imports + functions to `runtime.py`**

In cima a `backend/app/agents/runtime.py`, estendi gli import del brain:

```python
from app.brain import evaluate as brain_decide_default, evaluate_trader
from app.brain.analyst import AnalystContext, run_analyst
from app.brain.brief_store import persist_brief, latest_valid_brief, filter_brief_for
```
(La riga `from app.brain import evaluate as brain_decide_default` esistente va sostituita da quella sopra; le altre due sono nuove.)

Dopo `_position_move` (~riga 57), aggiungi le due funzioni:

```python
async def run_analyst_cycle(session, market, *, run=run_analyst, adapter=None):
    """One shared analyst call for the cycle: synthesize TOP_100 + recent news into a MarketBrief
    and persist it. Returns the row (usable) or None (analyst parse failed). Injectable run/adapter
    for tests."""
    symbols = await market.get_top_symbols("USDT", 100)
    snapshot = await market.get_universe_snapshot(symbols)
    observations = recent_observations_for(session, symbols, limit=settings.analyst_news_limit)
    ctx = AnalystContext(universe=snapshot, observations=observations)
    if adapter is None:
        adapter = make_adapter("openrouter", settings.analyst_model)
    result = run(ctx, adapter)
    row = persist_brief(session, uuid4().hex, result)
    return row if result.parse_status != "failed" else None


async def get_or_bootstrap_brief(session, market, *, run_cycle=None):
    """Latest valid brief, or bootstrap one via run_analyst_cycle if none exists yet (cold start).
    The only analyst run outside the hourly cycle."""
    brief = latest_valid_brief(session)
    if brief is not None:
        return brief
    if run_cycle is None:
        run_cycle = run_analyst_cycle
    return await run_cycle(session, market)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_analyst_orchestration.py -q`
Expected: PASS (4 test).

- [ ] **Step 5: Full suite (import wiring sanity)**

Run: `cd backend && .venv/bin/pytest -q`
Expected: PASS (nessuna regressione da import).

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/runtime.py backend/tests/test_analyst_orchestration.py
git commit -m "feat(brain-v2): analyst cycle orchestration + cold-start bootstrap"
```

---

## Task 8: `build_trader_context`  [sonnet]

**Files:**
- Modify: `backend/app/agents/runtime.py` (nuova funzione dopo `build_agent_context`)
- Test: `backend/tests/test_analyst_orchestration.py` (aggiungi in coda)

**Interfaces:**
- Consumes: `get_or_bootstrap_brief` (Task 7); `filter_brief_for` (Task 5); `journal.compact_view`; `build_context(brief=...)` (Task 4); `Event`.
- Produces: `build_trader_context(session, agent, market, symbols, *, wake_reason=None) -> DecisionContext` (universe vuoto, `brief` caricato+filtrato, posizioni live, memoria, eventi).

- [ ] **Step 1: Write the failing test**

Aggiungi in coda a `backend/tests/test_analyst_orchestration.py`:

```python
from datetime import datetime, timezone, timedelta
from app.db.models import Agent, Position
from app.agents.runtime import build_trader_context, run_analyst_cycle


def _agent(session):
    a = Agent(name="T", brain_version="v2", cash_usd=Decimal("100"),
              duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1))
    session.add(a); session.commit()
    return a


class _MarketPx(_Market):
    async def get_price(self, symbol): return Decimal("120")


async def test_trader_context_has_filtered_brief_no_universe(db_session):
    await run_analyst_cycle(db_session, _Market(), run=_fake_run(), adapter=object())  # BTCUSDT highlight
    agent = _agent(db_session)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    ctx = await build_trader_context(db_session, agent, _MarketPx(), ["BTCUSDT", "ETHUSDT"])
    assert ctx.universe == []                                  # no per-agent universe snapshot
    assert ctx.brief is not None and ctx.brief.regime == "risk-on"
    assert [h.symbol for h in ctx.brief.highlights] == ["BTCUSDT"]
    assert ctx.positions[0].last_price == Decimal("120")      # live-priced holding
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_analyst_orchestration.py -q`
Expected: FAIL (`ImportError`: no `build_trader_context`).

- [ ] **Step 3: Add `build_trader_context`**

In `backend/app/agents/runtime.py`, dopo `build_agent_context` (~riga 45):

```python
async def build_trader_context(session, agent, market, symbols, *, wake_reason=None):
    """v2 context: brief filtrato + posizioni live + memoria + eventi + wake_reason. NON scarica lo
    snapshot universo (l'analyst ha già sintetizzato il mercato una volta, condiviso). Il brief viene
    riusato (o bootstrap se non esiste ancora)."""
    holdings = []
    for pos in agent.positions:
        last = await market.get_price(pos.symbol)
        holdings.append((pos.symbol, pos.quantity, pos.avg_price, last))
    recent = [e.message for e in (
        session.query(Event).filter_by(agent_id=agent.id)
        .order_by(Event.timestamp.desc()).limit(10).all())]
    memory = journal.compact_view(session, agent.id)
    brief_row = await get_or_bootstrap_brief(session, market)
    brief = filter_brief_for(brief_row, symbols) if brief_row is not None else None
    return build_context(instructions=agent.instructions, cash_usd=agent.cash_usd,
                         holdings=holdings, universe=[], recent_events=recent,
                         memory=memory, brief=brief, wake_reason=wake_reason)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_analyst_orchestration.py -q`
Expected: PASS (5 test nel file).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/runtime.py backend/tests/test_analyst_orchestration.py
git commit -m "feat(brain-v2): build_trader_context (brief-based, no per-agent universe fetch)"
```

---

## Task 9: Dispatch per `brain_version` + guardrail su `symbols`  [sonnet]

**Files:**
- Modify: `backend/app/agents/runtime.py` (`run_decision`, `run_decision_guarded`, nuovo `_build_decision_context`, `_run_decision_llm`)
- Test: `backend/tests/test_brain_v2_dispatch.py`

**Interfaces:**
- Consumes: `evaluate_trader`, `brain_decide_default` (=evaluate); `build_trader_context`, `build_agent_context`.
- Produces: `_select_brain(agent)`; `_build_decision_context(session, agent, market, symbols, *, wake_reason)`; `run_decision`/`run_decision_guarded` risolvono il brain per versione quando `brain_decide is None`; `_run_decision_llm` usa `_build_decision_context` e il guardrail BUY su `symbols`.

- [ ] **Step 1: Write the failing test**

Crea `backend/tests/test_brain_v2_dispatch.py`:

```python
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.db.models import Agent, DecisionRecord
from app.brain.schema import Decision, Action, DecisionResult
from app.brain.context import build_context
from app.agents import runtime
from app.agents.runtime import _select_brain, run_decision

pytestmark = pytest.mark.asyncio


def _agent(session, brain_version="v1"):
    a = Agent(name="T", brain_version=brain_version, cash_usd=Decimal("1000"),
              model_name="deepseek/deepseek-v4-flash",
              duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1))
    session.add(a); session.commit()
    return a


def test_select_brain_by_version(db_session):
    from app.brain import evaluate, evaluate_trader
    assert _select_brain(_agent(db_session, "v1")) is evaluate
    assert _select_brain(_agent(db_session, "v2")) is evaluate_trader


class _MarketPx:
    async def get_price(self, symbol): return Decimal("100")
    async def get_book_ticker(self, symbol): return (Decimal("100"), Decimal("100"))


async def test_guard_uses_symbols_when_universe_empty(db_session, monkeypatch):
    """v2 ctx has an empty universe; the BUY guard must accept in-symbols and reject out-of-symbols."""
    agent = _agent(db_session, "v2")

    async def _fake_ctx(session, ag, market, symbols, *, wake_reason=None):
        return build_context(instructions="", cash_usd=ag.cash_usd, holdings=[], universe=[],
                             recent_events=[], brief=None, wake_reason=wake_reason)
    monkeypatch.setattr(runtime, "build_trader_context", _fake_ctx)

    def _brain(ctx, adapter):
        return DecisionResult(Decision(actions=[
            Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("10"), rationale="in"),
            Action(type="BUY", symbol="FAKEUSDT", usd_amount=Decimal("10"), rationale="out"),
        ], note="n"), "s", "u", "{}", "ok", 1)

    await run_decision(db_session, agent, _MarketPx(), ["BTCUSDT", "ETHUSDT"], brain_decide=_brain)
    rec = db_session.query(DecisionRecord).filter_by(kind="decision").first()
    assert rec is not None
    assert "1 operazioni" in db_session.query(runtime.Event).filter_by(kind="decision").first().message
    # BTCUSDT bought (in symbols), FAKEUSDT skipped (out of symbols)
    assert any(p.symbol == "BTCUSDT" for p in agent.positions)
    assert not any(p.symbol == "FAKEUSDT" for p in agent.positions)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_brain_v2_dispatch.py -q`
Expected: FAIL (`ImportError`: no `_select_brain`).

- [ ] **Step 3: Add `_select_brain` + `_build_decision_context`; wire dispatch**

In `backend/app/agents/runtime.py`, aggiungi (dopo `build_trader_context`):

```python
def _select_brain(agent):
    return evaluate_trader if agent.brain_version == "v2" else brain_decide_default


async def _build_decision_context(session, agent, market, symbols, *, wake_reason=None):
    if agent.brain_version == "v2":
        return await build_trader_context(session, agent, market, symbols, wake_reason=wake_reason)
    return await build_agent_context(session, agent, market, symbols, wake_reason=wake_reason)
```

In `run_decision` (firma ~riga 136): cambia il default `brain_decide=brain_decide_default` → `brain_decide=None` e risolvi:

```python
async def run_decision(session, agent, market, symbols, *, wake_reason=None, trigger=None,
                       brain_decide=None, reflect=run_reflection_result,
                       distill=run_distillation_result) -> None:
    if brain_decide is None:
        brain_decide = _select_brain(agent)
    cycle_id = uuid4().hex
    await _run_decision_llm(session, agent, market, symbols, brain_decide, reflect, distill,
                            cycle_id, wake_reason, trigger)
```

In `run_decision_guarded` (firma ~riga 155): stesso cambio di default a `brain_decide=None` (lo passa a `run_decision`, che risolve):

```python
async def run_decision_guarded(session, agent, market, symbols, *, wake_reason=None, trigger=None,
                               brain_decide=None, reflect=run_reflection_result,
                               distill=run_distillation_result) -> bool:
```

In `_run_decision_llm` (~riga 172-173): usa il context builder per versione e il guardrail su `symbols`:

```python
        ctx = await _build_decision_context(session, agent, market, symbols, wake_reason=wake_reason)
        universe_symbols = {c.symbol for c in ctx.universe} if ctx.universe else set(symbols)
```

- [ ] **Step 4: Run tests (new + runtime regression)**

Run: `cd backend && .venv/bin/pytest tests/test_brain_v2_dispatch.py tests/test_runtime.py -q`
Expected: PASS — i nuovi + tutti i test runtime esistenti (v1 usa `_select_brain` → `evaluate`, e il guardrail con `ctx.universe` non-vuoto resta identico al v1).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/runtime.py backend/tests/test_brain_v2_dispatch.py
git commit -m "feat(brain-v2): decision dispatch by brain_version + BUY guard on symbols list"
```

---

## Task 10: Preambolo analyst nel `_decision_tick`  [sonnet]

**Files:**
- Modify: `backend/app/scheduler/jobs.py` (`_decision_tick`, ~riga 28)
- Test: `backend/tests/test_scheduler_analyst.py`

**Interfaces:**
- Consumes: `run_analyst_cycle` (Task 7); `Agent`.
- Produces: `_decision_tick` esegue `run_analyst_cycle` una volta se ∃ agente running con `brain_version == "v2"`, prima del loop per-agente.

- [ ] **Step 1: Write the failing test**

Crea `backend/tests/test_scheduler_analyst.py`:

```python
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from app.db.models import Agent
from app.scheduler import jobs

pytestmark = pytest.mark.asyncio


def _agent(session, brain_version):
    a = Agent(name="T", brain_version=brain_version, status="running", cash_usd=Decimal("100"),
              model_name="m", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1))
    session.add(a); session.commit()
    return a


async def test_analyst_runs_once_when_v2_present(db_session, monkeypatch):
    _agent(db_session, "v1"); _agent(db_session, "v2")
    monkeypatch.setattr(jobs, "get_session", lambda: _ctxmgr(db_session))
    monkeypatch.setattr(jobs, "BinanceClient", lambda: object())
    monkeypatch.setattr(jobs, "run_decision_guarded", AsyncMock(return_value=True))
    monkeypatch.setattr(jobs, "universe_size", lambda a: 100)
    cycle = AsyncMock(return_value=None)
    monkeypatch.setattr(jobs, "run_analyst_cycle", cycle)
    # get_top_symbols is called inside the per-agent loop path; stub the market call there:
    monkeypatch.setattr(jobs, "_top_symbols_for", AsyncMock(return_value=["BTCUSDT"]), raising=False)
    await jobs._decision_tick()
    cycle.assert_awaited_once()


async def test_analyst_skipped_when_all_v1(db_session, monkeypatch):
    _agent(db_session, "v1")
    monkeypatch.setattr(jobs, "get_session", lambda: _ctxmgr(db_session))
    monkeypatch.setattr(jobs, "BinanceClient", lambda: object())
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

Nota per l'implementer: se il loop per-agente in `_decision_tick` chiama `market.get_top_symbols`, nel test il `market` è `object()` → adatta lo stub (es. una piccola classe market con `get_top_symbols` AsyncMock) invece di `_top_symbols_for`. L'invariante da testare è: `run_analyst_cycle` awaited una volta con v2 presente, mai con soli v1.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_scheduler_analyst.py -q`
Expected: FAIL (`run_analyst_cycle` non è ancora importato/chiamato in `jobs.py`).

- [ ] **Step 3: Wire the preamble**

In `backend/app/scheduler/jobs.py`, estendi l'import (~riga 8):

```python
from app.agents.runtime import (run_heartbeat, run_decision_guarded, universe_size,
                                 run_analyst_cycle)
```

Modifica `_decision_tick` (~riga 28): esegui l'analyst una volta se ∃ agente v2, prima del loop:

```python
async def _decision_tick():
    market = BinanceClient()
    symbols_cache: dict[int, list[str]] = {}
    with get_session() as session:
        agents = session.query(Agent).filter_by(status="running").all()
        if any(a.brain_version == "v2" for a in agents):
            try:
                await run_analyst_cycle(session, market)
            except Exception as exc:
                logger.error("analyst cycle failed: %s", exc)
                session.rollback()
        for agent in agents:
            try:
                n = universe_size(agent)
                if n not in symbols_cache:
                    symbols_cache[n] = await market.get_top_symbols("USDT", n)
                await run_decision_guarded(session, agent, market, symbols_cache[n])
            except Exception as exc:
                logger.error("decision tick failed for agent %s: %s", agent.id, exc)
                session.rollback()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_scheduler_analyst.py -q`
Expected: PASS (2 test).

- [ ] **Step 5: Commit**

```bash
git add backend/app/scheduler/jobs.py backend/tests/test_scheduler_analyst.py
git commit -m "feat(brain-v2): run the analyst once per decision cycle when a v2 agent is running"
```

---

## Task 11: Espone `brain_version` nell'API di creazione agente  [haiku]

**Files:**
- Modify: `backend/app/api/schemas.py` (`AgentCreate`, ~riga 7)
- Modify: `backend/app/api/routes.py` (`create_agent`, ~riga 49)
- Test: `backend/tests/test_api_agents.py` (aggiungi; se non esiste, crealo con lo stile esistente)

**Interfaces:**
- Consumes: `Agent.brain_version` (Task 1).
- Produces: `AgentCreate.brain_version: Literal["v1","v2"] = "v1"`; `create_agent` la passa all'`Agent`.

- [ ] **Step 1: Write the failing test**

Individua un test API esistente per lo stile del client/fixture (`grep -rl "TestClient\|create_agent\|/api/agents" backend/tests`). Aggiungi un test che crea un agente v2 e verifica che il DB lo persista come `"v2"`, e che il default sia `"v1"`. Esempio (adatta la fixture del client a quella esistente):

```python
def test_create_agent_defaults_v1(client_admin):
    r = client_admin.post("/api/agents", json={"name": "A", "model_name": "m"})
    assert r.status_code == 201
    # fetch the row and assert brain_version == "v1" (via db fixture o endpoint di dettaglio)


def test_create_agent_accepts_v2(client_admin, db_session):
    r = client_admin.post("/api/agents", json={"name": "B", "model_name": "m", "brain_version": "v2"})
    assert r.status_code == 201
    from app.db.models import Agent
    assert db_session.query(Agent).filter_by(name="B").one().brain_version == "v2"
```

Se non c'è una fixture client, testa direttamente la funzione `create_agent` con un `AgentCreate` costruito a mano e un `db_session`, asserendo `agent.brain_version`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_api_agents.py -q`
Expected: FAIL (`brain_version` ignorato/assente).

- [ ] **Step 3: Add the field + wire it**

In `backend/app/api/schemas.py`, in `AgentCreate` (dopo `universe`):

```python
    brain_version: Literal["v1", "v2"] = "v1"
```

In `backend/app/api/routes.py`, in `create_agent`, nella costruzione `Agent(...)` (dopo `universe=payload.universe,`):

```python
        brain_version=payload.brain_version,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_api_agents.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api_agents.py
git commit -m "feat(brain-v2): accept brain_version on agent creation (default v1)"
```

---

## Task 12: Finalizzazione (controller — non un subagent)

**Files:** nessuna modifica di prodotto; verifica, review, tracker, memoria.

- [ ] **Step 1: Full suite verde**

Run: `cd backend && .venv/bin/pytest -q` → tutti verdi (backend). Poi il frontend: `cd frontend && npm test -- --run` → 41 verdi (nessuna modifica frontend attesa; conferma non-regressione).
Annota i conteggi esatti.

- [ ] **Step 2: Smoke migrazione up/down su SQLite usa-e-getta**

```bash
cd backend && TMP=$(mktemp -d) && DATABASE_URL="sqlite:///$TMP/smoke.db" .venv/bin/alembic upgrade head \
  && DATABASE_URL="sqlite:///$TMP/smoke.db" .venv/bin/alembic downgrade -1 \
  && DATABASE_URL="sqlite:///$TMP/smoke.db" .venv/bin/alembic upgrade head && rm -rf "$TMP"
```
Verifica: nessun errore up→down→up; `alembic heads` → **single head** (la nuova revision). Conferma che il downgrade droppa `market_briefs` + colonna `brain_version`.

- [ ] **Step 3: Review finale whole-branch su OPUS**

Scope: `d5423d0..HEAD` (i commit Fase 6), **NON** `main...pipeline-v2`. Consegna al reviewer i Global Constraints verbatim + il roll-up dei Minor accumulati. Focus: v1 byte-identico (diff dei prompt v1), correttezza dispatch/guardrail, riuso-brief/cold-start, additività migrazione, disciplina UTC-aware, watermark loss-free non toccato.

- [ ] **Step 4: Fix Critical/Important, triage Minor**

Applica i fix con un subagent (test a copertura), logga i Minor accettati-per-v1. Re-review se serve.

- [ ] **Step 5: Aggiorna tracker + memoria**

- Roadmap `docs/superpowers/plans/2026-07-02-pipeline-v2-roadmap.md`: riga Fase 6 → ✅ (link a questo piano) + link al design doc.
- Ledger `.superpowers/sdd/progress.md`: "FASE 6 COMPLETE ✅" con HEAD + conteggi + esito review.
- Memoria `build-status.md`: aggiorna a "Fase 6 completa"; nota che restano Fase 7 (UI, inclusa la vista brief) e il merge finale delle 6 fasi.

---

## Self-Review (svolta in fase di scrittura)

**1. Copertura spec:** analyst (schema T2, runner T3), trader solo-brief (T6 + T8 universe vuoto), riuso puro + cold-start (T5 latest_valid + T7 bootstrap), cadenza per-ciclo/gate-v2 (T10), A/B flag (T1 colonna + T9 dispatch + T11 API), tabella MarketBrief persistenza+audit (T1 + T5), modello analyst fisso (T1 knob + T7 make_adapter). Migrazione additiva (T1) + smoke (T12). Vista brief UI → Fase 7 (fuori scope, per design). Nessun gap.

**2. Placeholder scan:** rimossi il test-residuo nel Task 5 e lo stub `pass` nel Task 7 (ora il codice è quello reale). Nessun TBD/TODO/"implement later" residuo.

**3. Type consistency:** `MarketBriefSchema` (pydantic, T2) vs `MarketBrief` (DB model, T1) vs `MarketBriefView`/`HighlightView` (context dataclass, T4) — nomi distinti per layer, usati coerentemente. `AnalystResult.brief` è `MarketBriefSchema`; `persist_brief` serializza `result.brief.model_dump_json()`; `filter_brief_for` legge il JSON e produce `MarketBriefView`. `evaluate_trader` firma `(ctx, adapter) -> DecisionResult` coerente con `_select_brain` e con l'iniezione `brain_decide`. `run_analyst_cycle`/`get_or_bootstrap_brief`/`build_trader_context` firme coerenti tra T7 e T8.

**Note operative per l'esecuzione:** verificare anchor+aritmetica di ogni task-brief contro il codice VIVO prima di dispatchare (gli shift di riga tra task rendono obsoleti gli anchor: correggere per-contenuto). Controllare `tool_uses`>0 dei reviewer e citazioni coerenti col diff.
