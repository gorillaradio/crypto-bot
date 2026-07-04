# UI di completamento (Pipeline v2 — Fase 7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendere osservabile in dashboard ciò che pipeline-v2 ha aggiunto dietro le quinte — decisioni archiviate, feed osservazioni news, market brief per-agente, P&L per posizione — senza toccare la pipeline né lo schema DB.

**Architecture:** Solo lettura. Nuovi endpoint FastAPI in `app/api/routes.py` che rispecchiano quelli esistenti (auth `require_viewer_or_admin`), nuovi schemi Pydantic in `app/api/schemas.py`, nuovi pannelli React (shadcn) nel dettaglio agente di `App.tsx`, funzioni client in `api.ts`. Pattern frontend: **vista pura testabile con props + wrapper di fetch** (come `PromptView`/`PromptPanel`). Nessuna migrazione.

**Tech Stack:** Backend Python/FastAPI/SQLAlchemy, test pytest. Frontend React 19 + TypeScript + Tailwind + shadcn/ui, test Vitest + @testing-library/react.

## Global Constraints

*(Ogni task include implicitamente questi vincoli. Valori copiati verbatim dallo spec.)*

- **I comandi si eseguono dalla repo root** `/Users/seb/Dev/gorillaradio/crypto-bot` (backend: `cd backend && .venv/bin/pytest …`; frontend: `cd frontend && npx vitest …`).
- **Zero migrazioni, nessuna nuova tabella/colonna DB.** La **single Alembic head `49407193a9ac` resta invariata** (verifica in finalizzazione).
- **`build_agent_context` NON si tocca** (lo usa il monitor `preview.py`). Il P&L usa una via leggera dedicata (prezzi dei soli simboli detenuti via `get_universe_snapshot`), non `build_agent_context`.
- **Tutti i nuovi endpoint di lettura dietro `Depends(require_viewer_or_admin)`.**
- **Tutti i test backend usano la fixture `db_session`** (`Base.metadata.create_all` su SQLite in-memory) **e un market stub** (`FakeMarketPreview`/`FailingMarketPreview`, già in `test_api.py`). **Mai Binance reale, mai migrazioni.**
- **Formula P&L = `(last - avg) / avg * 100`** (identica a `context.py:71`); `None` se il prezzo manca o `avg == 0`.
- **L'endpoint posizioni degrada a cost-only** (campi P&L `None`) se la chiamata market fallisce — **mai 502**.
- **L'endpoint brief ritorna `null` (200)** se non esiste un brief valido; **502** se la chiamata market per l'universo fallisce (come `get_prompt`).
- **L'endpoint brief risolve l'universo con `await market.get_top_symbols("USDT", universe_size(agent))`** — la STESSA chiamata di `build_trader_context`, così i simboli degli highlights (forma pair, es. `SOLUSDT`) combaciano col filtro `filter_brief_for`.
- **Il feed osservazioni è globale** (`GET /observations`, nessun filtro universo, nessuna chiamata market).
- **Datetime UTC-aware**; ordinamento via `ORDER BY … desc` (SQL, sicuro su SQLite), mai confronti datetime in Python.
- **Frontend:** vista pura (unit-test con props) + wrapper di fetch. I "badge" sono `<span>` con classi Tailwind (`text-xs px-1.5 py-0.5 rounded`); **non esiste un primitive `Badge`**. Colori su/giù: classi globali `pos`/`neg` (come `App.tsx`).
- **Nessuna nuova dipendenza** (backend o frontend).

## File Structure

**Backend**
- Modifica `backend/app/api/schemas.py` — estende `PositionOut` e `AgentOut`; aggiunge `ObservationOut`, `HighlightOut`, `MarketBriefOut`.
- Modifica `backend/app/api/routes.py` — estende `_agent_out`; `get_positions` diventa async + P&L; aggiunge `get_observations` e `get_brief`; nuovi import.
- Test `backend/tests/test_api.py` — nuovi test accanto agli esistenti (+ aggiorna il test posizioni esistente perché resti ermetico).

**Frontend**
- Modifica `frontend/src/api.ts` — tipi + funzioni client.
- Modifica `frontend/src/components/PositionsTable.tsx` — colonne Valore + P&L.
- Crea `frontend/src/components/BrainBadge.tsx`.
- Crea `frontend/src/components/DecisionsPanel.tsx`.
- Crea `frontend/src/components/ObservationsFeed.tsx`.
- Crea `frontend/src/components/MarketBriefPanel.tsx` (`BriefView` pura + `MarketBriefPanel` wrapper).
- Modifica `frontend/src/App.tsx` — stato, poll, montaggio pannelli, badge brain.
- Crea test in `frontend/src/__tests__/`.

---

### Task 1: `brain_version` in AgentOut (backend)

**Files:**
- Modify: `backend/app/api/schemas.py` (`AgentOut`)
- Modify: `backend/app/api/routes.py` (`_agent_out`)
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `Agent.brain_version` (colonna già esistente, `models.py:33`).
- Produces: `AgentOut.brain_version: str` — consumato dal frontend (Task 6, 9).

- [ ] **Step 1: Write the failing test** — aggiungi in `test_api.py` (dopo `test_agent_detail_reports_equity_and_return`):

```python
def test_agent_out_includes_brain_version(db_session):
    agent = Agent(name="BV", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"), brain_version="v2")
    db_session.add(agent); db_session.commit()
    client = _client(db_session)
    body = client.get(f"/api/agents/{agent.id}").json()
    assert body["brain_version"] == "v2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_api.py::test_agent_out_includes_brain_version -v`
Expected: FAIL (`KeyError: 'brain_version'` — il campo non è nella risposta).

- [ ] **Step 3: Write minimal implementation**

In `schemas.py`, aggiungi il campo a `AgentOut` (dopo `duration_end`):

```python
class AgentOut(BaseModel):
    id: int
    name: str
    instructions: str
    status: str
    cash_usd: Decimal
    equity: Decimal
    return_pct: Decimal
    duration_start: datetime
    duration_end: datetime
    brain_version: str
```

In `routes.py`, aggiungi al costruttore in `_agent_out` (dopo `duration_end=agent.duration_end,`):

```python
        duration_end=agent.duration_end,
        brain_version=agent.brain_version,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_api.py::test_agent_out_includes_brain_version -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api.py
git commit -m "feat(fase7): expose brain_version in AgentOut"
```

---

### Task 2: P&L per posizione (backend)

**Files:**
- Modify: `backend/app/api/schemas.py` (`PositionOut`)
- Modify: `backend/app/api/routes.py` (`get_positions`)
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `market_dep` → `BinanceClient.get_universe_snapshot(symbols) -> list[CoinSnapshot(symbol, price, pct_24h)]` (`binance.py:51`).
- Produces: `PositionOut` con `last_price: Decimal | None`, `unrealized_pnl_pct: Decimal | None`, `market_value: Decimal | None`.

- [ ] **Step 1: Write the failing tests** — in `test_api.py`, subito dopo `test_get_positions_returns_holdings_with_cost_basis`. Nota: aggiungi **anche** `_use_fake_market()` al test esistente così resta ermetico (ora l'endpoint chiama il market):

Modifica il test esistente (aggiungi la riga `_use_fake_market()` prima della GET):

```python
def test_get_positions_returns_holdings_with_cost_basis(db_session):
    agent = Agent(name="P", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("0"))
    db_session.add(agent); db_session.commit()
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("0.5"), avg_price=Decimal("100")))
    db_session.commit()
    client = _client(db_session)
    _use_fake_market()                       # endpoint ora async + market_dep → stub, niente rete
    rows = client.get(f"/api/agents/{agent.id}/positions").json()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTCUSDT"
    assert Decimal(rows[0]["cost_basis"]) == Decimal("50.0")
```

Nuovi test:

```python
def test_get_positions_includes_live_pnl(db_session):
    agent = Agent(name="P", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("0"))
    db_session.add(agent); db_session.commit()
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("2"), avg_price=Decimal("100")))
    db_session.commit()
    client = _client(db_session)
    _use_fake_market([CoinSnapshot("BTCUSDT", Decimal("150"), Decimal("1"))])
    row = client.get(f"/api/agents/{agent.id}/positions").json()[0]
    assert Decimal(row["last_price"]) == Decimal("150")
    assert Decimal(row["unrealized_pnl_pct"]) == Decimal("50")     # (150-100)/100*100
    assert Decimal(row["market_value"]) == Decimal("300")          # 2*150


def test_get_positions_pnl_none_when_symbol_missing(db_session):
    agent = Agent(name="P", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("0"))
    db_session.add(agent); db_session.commit()
    db_session.add(Position(agent_id=agent.id, symbol="GONEUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    client = _client(db_session)
    _use_fake_market([CoinSnapshot("BTCUSDT", Decimal("150"), Decimal("1"))])  # snapshot senza GONEUSDT
    row = client.get(f"/api/agents/{agent.id}/positions").json()[0]
    assert row["last_price"] is None
    assert row["unrealized_pnl_pct"] is None
    assert row["market_value"] is None
    assert Decimal(row["cost_basis"]) == Decimal("100")


def test_get_positions_degrades_to_cost_only_when_market_fails(db_session):
    agent = Agent(name="P", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("0"))
    db_session.add(agent); db_session.commit()
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    client = _client(db_session)
    app.dependency_overrides[routes.market_dep] = lambda: FailingMarketPreview()
    resp = client.get(f"/api/agents/{agent.id}/positions")
    assert resp.status_code == 200                    # NON 502: le posizioni sono un pannello centrale
    row = resp.json()[0]
    assert row["last_price"] is None
    assert Decimal(row["cost_basis"]) == Decimal("100")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/test_api.py -k get_positions -v`
Expected: i nuovi 3 FALLISCONO (campi `last_price`/`unrealized_pnl_pct`/`market_value` assenti); il test esistente potrebbe ancora passare.

- [ ] **Step 3: Write minimal implementation**

In `schemas.py`, estendi `PositionOut`:

```python
class PositionOut(BaseModel):
    symbol: str
    quantity: Decimal
    avg_price: Decimal
    cost_basis: Decimal
    last_price: Decimal | None = None
    unrealized_pnl_pct: Decimal | None = None
    market_value: Decimal | None = None
```

In `routes.py`, sostituisci l'intero `get_positions` (attuale `routes.py:109-120`):

```python
@router.get("/agents/{agent_id}/positions", response_model=list[PositionOut])
async def get_positions(agent_id: int, session=Depends(session_dep),
                        market=Depends(market_dep), _: str = Depends(require_viewer_or_admin)):
    rows = session.query(Position).filter_by(agent_id=agent_id).all()
    prices: dict[str, Decimal] = {}
    if rows:
        try:
            snap = await market.get_universe_snapshot([p.symbol for p in rows])
            prices = {c.symbol: c.price for c in snap}
        except Exception:
            prices = {}                    # market down → degrada a cost-only, mai 502
    out = []
    for p in rows:
        last = prices.get(p.symbol)
        pnl = (((last - p.avg_price) / p.avg_price) * Decimal("100")
               if last is not None and p.avg_price else None)
        out.append(PositionOut(
            symbol=p.symbol, quantity=p.quantity, avg_price=p.avg_price,
            cost_basis=p.quantity * p.avg_price,
            last_price=last,
            unrealized_pnl_pct=pnl,
            market_value=(p.quantity * last) if last is not None else None,
        ))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_api.py -k get_positions -v`
Expected: tutti PASS (inclusi i 3 nuovi e l'esistente aggiornato).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api.py
git commit -m "feat(fase7): authoritative per-position P&L on positions endpoint"
```

---

### Task 3: Endpoint osservazioni (backend)

**Files:**
- Modify: `backend/app/api/schemas.py` (`ObservationOut`)
- Modify: `backend/app/api/routes.py` (import `json`, `Observation`, `ObservationOut`; `get_observations`)
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: modello `Observation` (`models.py:149`) — `source, title, url, symbols_json, published_at`.
- Produces: `GET /api/observations -> list[ObservationOut]` (globale, newest-first, limit 100).

- [ ] **Step 1: Write the failing tests** — in `test_api.py` (dopo i test decisioni):

```python
def test_get_observations_returns_recent_newest_first(db_session):
    from app.db.models import Observation
    db_session.add_all([
        Observation(source="CoinDesk", kind="news", title="old", url="http://a",
                    symbols_json='["BTC"]', dedup_hash="h1",
                    published_at=datetime(2026, 7, 1, tzinfo=timezone.utc)),
        Observation(source="Cointelegraph", kind="news", title="new", url=None,
                    symbols_json='[]', dedup_hash="h2",
                    published_at=datetime(2026, 7, 3, tzinfo=timezone.utc)),
    ])
    db_session.commit()
    client = _client(db_session)
    body = client.get("/api/observations").json()
    assert [o["title"] for o in body] == ["new", "old"]     # published_at desc
    assert body[0]["url"] is None and body[0]["symbols"] == []
    assert body[1]["source"] == "CoinDesk" and body[1]["symbols"] == ["BTC"]


def test_get_observations_empty(db_session):
    client = _client(db_session)
    assert client.get("/api/observations").json() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/test_api.py -k get_observations -v`
Expected: FAIL (404: la route `/api/observations` non esiste).

- [ ] **Step 3: Write minimal implementation**

In `schemas.py`:

```python
class ObservationOut(BaseModel):
    source: str
    title: str
    url: str | None = None
    published_at: datetime
    symbols: list[str]
```

In `routes.py`, aggiungi in cima `import json` (accanto agli altri import stdlib), aggiungi `Observation` alla riga di import da `app.db.models`, e `ObservationOut` alla riga di import da `app.api.schemas`. Poi aggiungi l'endpoint (dopo `get_events`):

```python
@router.get("/observations", response_model=list[ObservationOut])
def get_observations(session=Depends(session_dep), _: str = Depends(require_viewer_or_admin)):
    rows = (session.query(Observation)
            .order_by(Observation.published_at.desc(), Observation.id.desc())
            .limit(100).all())
    return [ObservationOut(source=o.source, title=o.title, url=o.url,
                           published_at=o.published_at, symbols=json.loads(o.symbols_json))
            for o in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_api.py -k get_observations -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api.py
git commit -m "feat(fase7): global recent observations endpoint"
```

---

### Task 4: Endpoint market brief (backend)

**Files:**
- Modify: `backend/app/api/schemas.py` (`HighlightOut`, `MarketBriefOut`)
- Modify: `backend/app/api/routes.py` (import `latest_valid_brief`/`filter_brief_for`/`universe_size`; `get_brief`)
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `latest_valid_brief(session) -> MarketBrief | None` e `filter_brief_for(row, universe_symbols) -> MarketBriefView(regime, highlights[HighlightView(symbol, snapshot, signal, note)], key_news, as_of)` (`brief_store.py`); `universe_size(agent) -> int` (`runtime.py:23`); `market.get_top_symbols("USDT", n) -> list[str]` (pair form).
- Produces: `GET /api/agents/{id}/brief -> MarketBriefOut | null`.

- [ ] **Step 1: Write the failing tests** — in `test_api.py`:

```python
def test_get_brief_returns_filtered_view(db_session):
    import json as _json
    from app.db.models import MarketBrief
    agent = Agent(name="B", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"), brain_version="v2")
    db_session.add(agent); db_session.commit()
    brief = {"regime": "risk-off",
             "highlights": [
                 {"symbol": "BTCUSDT", "snapshot": "s1", "signal": "bullish", "note": "n1"},
                 {"symbol": "SOLUSDT", "snapshot": "s2", "signal": "bearish", "note": "n2"}],
             "key_news": ["headline A"]}
    db_session.add(MarketBrief(cycle_id="c1", parsed_brief=_json.dumps(brief),
                               system_prompt="s", user_prompt="u", raw_response="r",
                               parse_status="ok", model_provider="openrouter",
                               model_name="m", latency_ms=10))
    db_session.commit()
    client = _client(db_session)
    _use_fake_market()                        # get_top_symbols → ["BTCUSDT"]
    body = client.get(f"/api/agents/{agent.id}/brief").json()
    assert body["regime"] == "risk-off"
    assert body["key_news"] == ["headline A"]
    assert [h["symbol"] for h in body["highlights"]] == ["BTCUSDT"]   # SOLUSDT fuori universo → filtrato
    assert body["highlights"][0]["signal"] == "bullish"


def test_get_brief_null_when_no_brief(db_session):
    agent = Agent(name="B", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    client = _client(db_session)
    _use_fake_market()
    resp = client.get(f"/api/agents/{agent.id}/brief")
    assert resp.status_code == 200 and resp.json() is None


def test_get_brief_404_when_agent_missing(db_session):
    client = _client(db_session)
    _use_fake_market()
    assert client.get("/api/agents/999/brief").status_code == 404


def test_get_brief_502_when_market_fails(db_session):
    import json as _json
    from app.db.models import MarketBrief
    agent = Agent(name="B", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    db_session.add(MarketBrief(cycle_id="c1",
                               parsed_brief=_json.dumps({"regime": "x", "highlights": [], "key_news": []}),
                               system_prompt="s", user_prompt="u", raw_response="r",
                               parse_status="ok", model_provider="openrouter", model_name="m", latency_ms=1))
    db_session.commit()
    client = _client(db_session)
    app.dependency_overrides[routes.market_dep] = lambda: FailingMarketPreview()
    assert client.get(f"/api/agents/{agent.id}/brief").status_code == 502
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/test_api.py -k get_brief -v`
Expected: FAIL (404: la route `/brief` non esiste).

- [ ] **Step 3: Write minimal implementation**

In `schemas.py`:

```python
class HighlightOut(BaseModel):
    symbol: str
    snapshot: str
    signal: str
    note: str


class MarketBriefOut(BaseModel):
    regime: str
    highlights: list[HighlightOut]
    key_news: list[str]
    as_of: datetime | None = None
```

In `routes.py`, aggiungi gli import (dopo gli altri import `app.*`):

```python
from app.brain.brief_store import latest_valid_brief, filter_brief_for
from app.agents.runtime import universe_size
```

e `MarketBriefOut, HighlightOut` alla riga di import da `app.api.schemas`. Poi l'endpoint (dopo `get_decisions`):

```python
@router.get("/agents/{agent_id}/brief", response_model=MarketBriefOut | None)
async def get_brief(agent_id: int, session=Depends(session_dep),
                    market=Depends(market_dep), _: str = Depends(require_viewer_or_admin)):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    row = latest_valid_brief(session)
    if row is None:
        return None
    try:
        symbols = await market.get_top_symbols("USDT", universe_size(agent))
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"brief unavailable: {exc}")
    view = filter_brief_for(row, symbols)
    return MarketBriefOut(
        regime=view.regime,
        highlights=[HighlightOut(symbol=h.symbol, snapshot=h.snapshot, signal=h.signal, note=h.note)
                    for h in view.highlights],
        key_news=view.key_news,
        as_of=view.as_of)
```

*(Nota: `app.agents.runtime` è già importato transitivamente via `app.agents.preview` — nessun ciclo di import.)*

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_api.py -k get_brief -v`
Expected: PASS (4 test).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api.py
git commit -m "feat(fase7): per-agent market brief endpoint (filtered, null/502 handling)"
```

---

### Task 5: Colonne Valore + P&L nella tabella posizioni (frontend)

**Files:**
- Modify: `frontend/src/api.ts` (tipo `Position`)
- Modify: `frontend/src/components/PositionsTable.tsx`
- Test: `frontend/src/__tests__/PositionsTable.test.tsx` (create)

**Interfaces:**
- Consumes: `Position` con `last_price`, `unrealized_pnl_pct`, `market_value` (string | null) — da Task 2.

- [ ] **Step 1: Write the failing test** — crea `frontend/src/__tests__/PositionsTable.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PositionsTable } from "../components/PositionsTable";
import type { Position } from "../api";

const pos = (over: Partial<Position> = {}): Position => ({
  symbol: "BTCUSDT", quantity: "2", avg_price: "100", cost_basis: "200",
  last_price: "150", unrealized_pnl_pct: "50", market_value: "300", ...over,
});

describe("PositionsTable", () => {
  it("shows P&L percent and market value", () => {
    render(<PositionsTable positions={[pos()]} />);
    expect(screen.getByText("+50.00%")).toBeInTheDocument();
    expect(screen.getByText("$300")).toBeInTheDocument();
  });

  it("shows a dash when P&L is unavailable", () => {
    render(<PositionsTable positions={[pos({ last_price: null, unrealized_pnl_pct: null, market_value: null })]} />);
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);   // Valore + P&L
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/PositionsTable.test.tsx`
Expected: FAIL (colonne assenti; type error su `last_price`).

- [ ] **Step 3: Write minimal implementation**

In `api.ts`, estendi il tipo `Position`:

```ts
export type Position = {
  symbol: string;
  quantity: string;
  avg_price: string;
  cost_basis: string;
  last_price: string | null;
  unrealized_pnl_pct: string | null;
  market_value: string | null;
};
```

In `PositionsTable.tsx`, aggiungi un formatter dopo `qty` (riga ~24):

```tsx
const pct = (s: string) => {
  const n = Number(s);
  return `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(2)}%`;
};
```

Aggiungi due `<TableHead>` dopo la colonna "Costo" (dopo la riga `<TableHead className={thBase}>Costo</TableHead>`):

```tsx
          <TableHead className={thBase}>Valore</TableHead>
          <TableHead className={thBase}>P&L</TableHead>
```

Aggiungi due `<TableCell>` dopo la cella del costo (dopo `<TableCell className={tdBase}>{usd(p.cost_basis)}</TableCell>`):

```tsx
            <TableCell className={tdBase}>{p.market_value == null ? "—" : usd(p.market_value)}</TableCell>
            <TableCell className={tdBase}>
              {p.unrealized_pnl_pct == null ? "—" : (
                <span className={Number(p.unrealized_pnl_pct) >= 0 ? "pos" : "neg"}>
                  {pct(p.unrealized_pnl_pct)}
                </span>
              )}
            </TableCell>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/PositionsTable.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/components/PositionsTable.tsx frontend/src/__tests__/PositionsTable.test.tsx
git commit -m "feat(fase7): value + P&L columns in positions table"
```

---

### Task 6: Badge brain version (frontend)

**Files:**
- Modify: `frontend/src/api.ts` (tipo `Agent`)
- Create: `frontend/src/components/BrainBadge.tsx`
- Modify: `frontend/src/App.tsx` (badge nell'header agente)
- Test: `frontend/src/__tests__/BrainBadge.test.tsx` (create)

**Interfaces:**
- Consumes: `Agent.brain_version: string` — da Task 1.
- Produces: `BrainBadge({ version })` — usato in `App.tsx` e concettualmente affine al note del brief (Task 9).

- [ ] **Step 1: Write the failing test** — crea `frontend/src/__tests__/BrainBadge.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { BrainBadge } from "../components/BrainBadge";

describe("BrainBadge", () => {
  it("labels the brain version", () => {
    render(<BrainBadge version="v2" />);
    expect(screen.getByText("brain v2")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/BrainBadge.test.tsx`
Expected: FAIL (`BrainBadge` non esiste).

- [ ] **Step 3: Write minimal implementation**

Crea `frontend/src/components/BrainBadge.tsx`:

```tsx
export function BrainBadge({ version }: { version: string }) {
  const v2 = version === "v2";
  return (
    <span
      className="text-xs px-1.5 py-0.5 rounded font-medium bg-muted text-muted-foreground"
      title={v2 ? "Brain a due stadi (analyst + trader)" : "Brain monolitico (baseline)"}
    >
      brain {version}
    </span>
  );
}
```

In `api.ts`, aggiungi al tipo `Agent` il campo `brain_version` (dopo `status`):

```ts
export type Agent = {
  id: number;
  name: string;
  status: string;
  brain_version: string;
  instructions: string;
  cash_usd: string;
  equity: string;
  return_pct: string;
  duration_start: string;
  duration_end: string;
};
```

In `App.tsx`, importa il componente (accanto agli altri import di `./components/...`):

```tsx
import { BrainBadge } from "./components/BrainBadge";
```

e rendilo accanto al nome agente. Sostituisci il blocco `<h1>…</h1>` (dentro `<div className="flex flex-wrap items-center gap-3">`) con:

```tsx
                <h1 className="text-2xl font-semibold leading-tight">{sel.name}</h1>
                <BrainBadge version={sel.brain_version} />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/BrainBadge.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/components/BrainBadge.tsx frontend/src/App.tsx frontend/src/__tests__/BrainBadge.test.tsx
git commit -m "feat(fase7): brain version badge in agent header"
```

---

### Task 7: Pannello decisioni (frontend)

**Files:**
- Modify: `frontend/src/api.ts` (tipo `Decision` + `getDecisions`)
- Create: `frontend/src/components/DecisionsPanel.tsx`
- Modify: `frontend/src/App.tsx` (stato + poll + Card)
- Test: `frontend/src/__tests__/DecisionsPanel.test.tsx` (create)

**Interfaces:**
- Consumes: endpoint esistente `GET /api/agents/{id}/decisions` → `DecisionRecordOut` (mostra un sottoinsieme di campi). `parsed_output` è JSON di `Decision{actions:[{type, symbol?}], note}` **solo** per `kind === "decision"`.
- Produces: `getDecisions(id) -> Promise<Decision[]>`; `DecisionsPanel({ decisions })` puro.

- [ ] **Step 1: Write the failing test** — crea `frontend/src/__tests__/DecisionsPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { DecisionsPanel } from "../components/DecisionsPanel";
import type { Decision } from "../api";

const dec = (over: Partial<Decision> = {}): Decision => ({
  id: 1, cycle_id: "c1", kind: "decision", trigger: "schedule",
  parsed_output: '{"actions":[{"type":"BUY","symbol":"SOLUSDT"},{"type":"HOLD"}],"note":""}',
  parse_status: "ok", model_name: "deepseek/x", latency_ms: 1200,
  created_at: "2026-07-04T10:00:00Z", ...over,
});

describe("DecisionsPanel", () => {
  it("summarizes decision actions compactly", () => {
    render(<DecisionsPanel decisions={[dec()]} />);
    expect(screen.getByText("BUY SOL, HOLD")).toBeInTheDocument();
    expect(screen.getByText("schedule")).toBeInTheDocument();
  });

  it("shows a dash for non-decision kinds", () => {
    render(<DecisionsPanel decisions={[dec({ kind: "reflection", parsed_output: null })]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("shows an empty hint with no decisions", () => {
    render(<DecisionsPanel decisions={[]} />);
    expect(screen.getByText(/nessuna decisione/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/DecisionsPanel.test.tsx`
Expected: FAIL (`DecisionsPanel` non esiste).

- [ ] **Step 3: Write minimal implementation**

In `api.ts`, aggiungi il tipo e la funzione (accanto agli altri `get*`):

```ts
export type Decision = {
  id: number;
  cycle_id: string;
  kind: string;
  trigger: string;
  parsed_output: string | null;
  parse_status: string;
  model_name: string | null;
  latency_ms: number;
  created_at: string;
};
export const getDecisions = (id: number) => get<Decision[]>(`/api/agents/${id}/decisions`);
```

Crea `frontend/src/components/DecisionsPanel.tsx`:

```tsx
import type { Decision } from "../api";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

const time = (t: string) =>
  new Date(t).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

// parsed_output è un Decision JSON solo per kind === "decision"
// (reflection/distillation portano altre forme) → riassunto "TYPE SYMBOL", o "—".
function actionsSummary(d: Decision): string {
  if (d.kind !== "decision" || !d.parsed_output) return "—";
  try {
    const parsed = JSON.parse(d.parsed_output) as { actions?: { type: string; symbol?: string | null }[] };
    const acts = parsed.actions ?? [];
    if (!acts.length) return "nessuna azione";
    return acts.map((a) => `${a.type}${a.symbol ? " " + a.symbol.replace(/USDT$/, "") : ""}`).join(", ");
  } catch {
    return "—";
  }
}

const tag = "text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground";

export function DecisionsPanel({ decisions }: { decisions: Decision[] }) {
  if (!decisions.length) return <p className="empty">Ancora nessuna decisione registrata.</p>;
  return (
    <Table className="tabular-nums">
      <TableHeader>
        <TableRow>
          <TableHead className="text-left text-xs">Quando</TableHead>
          <TableHead className="text-left text-xs">Tipo</TableHead>
          <TableHead className="text-left text-xs">Trigger</TableHead>
          <TableHead className="text-left text-xs">Azioni</TableHead>
          <TableHead className="text-left text-xs">Modello</TableHead>
          <TableHead className="text-right text-xs">Latenza</TableHead>
          <TableHead className="text-left text-xs">Parse</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {decisions.map((d) => (
          <TableRow key={d.id}>
            <TableCell className="text-left text-xs whitespace-nowrap">{time(d.created_at)}</TableCell>
            <TableCell className="text-left"><span className={tag}>{d.kind}</span></TableCell>
            <TableCell className="text-left"><span className={tag}>{d.trigger}</span></TableCell>
            <TableCell className="text-left text-xs">{actionsSummary(d)}</TableCell>
            <TableCell className="text-left text-xs">{d.model_name ?? "—"}</TableCell>
            <TableCell className="text-right text-xs">{d.latency_ms} ms</TableCell>
            <TableCell className="text-left"><span className={tag}>{d.parse_status}</span></TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
```

In `App.tsx`: importa `getDecisions`, `type Decision`, `DecisionsPanel`; aggiungi lo stato `const [decisions, setDecisions] = useState<Decision[]>([]);` (accanto a `positions`); nel blocco `load()` per-agente (quello con `getPositions(selId)…`) aggiungi:

```tsx
      getDecisions(selId).then(setDecisions).catch(onErr);
```

e monta una Card (dopo la Card "Memoria"):

```tsx
            <Card>
              <CardContent>
                <h2 className="text-sm font-semibold text-muted-foreground mb-3">Decisioni</h2>
                <DecisionsPanel decisions={decisions} />
              </CardContent>
            </Card>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/DecisionsPanel.test.tsx`
Expected: PASS (3 test).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/components/DecisionsPanel.tsx frontend/src/App.tsx frontend/src/__tests__/DecisionsPanel.test.tsx
git commit -m "feat(fase7): archived decisions panel"
```

---

### Task 8: Feed osservazioni (frontend)

**Files:**
- Modify: `frontend/src/api.ts` (tipo `Observation` + `getObservations`)
- Create: `frontend/src/components/ObservationsFeed.tsx`
- Modify: `frontend/src/App.tsx` (stato + poll + Card)
- Test: `frontend/src/__tests__/ObservationsFeed.test.tsx` (create)

**Interfaces:**
- Consumes: `GET /api/observations` → `ObservationOut` (Task 3).
- Produces: `getObservations() -> Promise<Observation[]>`; `ObservationsFeed({ observations })` puro.

- [ ] **Step 1: Write the failing test** — crea `frontend/src/__tests__/ObservationsFeed.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ObservationsFeed } from "../components/ObservationsFeed";
import type { Observation } from "../api";

const obs = (over: Partial<Observation> = {}): Observation => ({
  source: "CoinDesk", title: "BTC rallies", url: "http://x",
  published_at: "2026-07-04T09:00:00Z", symbols: ["BTC"], ...over,
});

describe("ObservationsFeed", () => {
  it("renders a headline as a link with its source and symbols", () => {
    render(<ObservationsFeed observations={[obs()]} />);
    const link = screen.getByText("BTC rallies");
    expect(link).toHaveAttribute("href", "http://x");
    expect(screen.getByText("CoinDesk")).toBeInTheDocument();
    expect(screen.getByText("BTC")).toBeInTheDocument();
  });

  it("renders a headline without url as plain text", () => {
    render(<ObservationsFeed observations={[obs({ url: null })]} />);
    expect(screen.getByText("BTC rallies").tagName).toBe("SPAN");
  });

  it("shows an empty hint", () => {
    render(<ObservationsFeed observations={[]} />);
    expect(screen.getByText(/nessuna osservazione/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/ObservationsFeed.test.tsx`
Expected: FAIL (`ObservationsFeed` non esiste).

- [ ] **Step 3: Write minimal implementation**

In `api.ts`:

```ts
export type Observation = {
  source: string;
  title: string;
  url: string | null;
  published_at: string;
  symbols: string[];
};
export const getObservations = () => get<Observation[]>("/api/observations");
```

Crea `frontend/src/components/ObservationsFeed.tsx`:

```tsx
import type { Observation } from "../api";

const time = (t: string) =>
  new Date(t).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

export function ObservationsFeed({ observations }: { observations: Observation[] }) {
  if (!observations.length) return <p className="empty">Nessuna osservazione recente.</p>;
  return (
    <ul className="flex flex-col gap-3">
      {observations.map((o, i) => (
        <li key={i} className="flex flex-col gap-0.5">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className="font-medium">{o.source}</span>
            <span>{time(o.published_at)}</span>
            {o.symbols.map((s) => (
              <span key={s} className="px-1 rounded bg-muted">{s}</span>
            ))}
          </div>
          {o.url ? (
            <a href={o.url} target="_blank" rel="noreferrer" className="text-sm hover:underline">{o.title}</a>
          ) : (
            <span className="text-sm">{o.title}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
```

In `App.tsx`: importa `getObservations`, `type Observation`, `ObservationsFeed`; stato `const [observations, setObservations] = useState<Observation[]>([]);`; nel `load()` per-agente aggiungi (il feed è globale ma rifetcharlo qui è innocuo e a costo zero — solo DB):

```tsx
      getObservations().then(setObservations).catch(onErr);
```

e monta una Card (dopo la Card "Decisioni"):

```tsx
            <Card>
              <CardContent>
                <h2 className="text-sm font-semibold text-muted-foreground mb-3">Osservazioni (news)</h2>
                <ObservationsFeed observations={observations} />
              </CardContent>
            </Card>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/ObservationsFeed.test.tsx`
Expected: PASS (3 test).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/components/ObservationsFeed.tsx frontend/src/App.tsx frontend/src/__tests__/ObservationsFeed.test.tsx
git commit -m "feat(fase7): global observations news feed"
```

---

### Task 9: Pannello market brief (frontend)

**Files:**
- Modify: `frontend/src/api.ts` (`Highlight`, `MarketBrief`, `getBrief`)
- Create: `frontend/src/components/MarketBriefPanel.tsx` (`BriefView` puro + `MarketBriefPanel` wrapper)
- Modify: `frontend/src/App.tsx` (Card + montaggio)
- Test: `frontend/src/__tests__/MarketBriefPanel.test.tsx` (create)

**Interfaces:**
- Consumes: `GET /api/agents/{id}/brief` → `MarketBriefOut | null` (Task 4); `Agent.brain_version` (Task 6) per la nota v1.
- Produces: `getBrief(id) -> Promise<MarketBrief | null>`; `BriefView({ brief })` puro + `MarketBriefPanel({ agentId, brainVersion })` wrapper.

- [ ] **Step 1: Write the failing test** — crea `frontend/src/__tests__/MarketBriefPanel.test.tsx` (testa la vista pura `BriefView`, come `PromptView.test.tsx`):

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { BriefView } from "../components/MarketBriefPanel";
import type { MarketBrief } from "../api";

const brief: MarketBrief = {
  regime: "risk-off",
  highlights: [{ symbol: "SOLUSDT", snapshot: "s", signal: "bullish", note: "breakout" }],
  key_news: ["ETF delayed"],
  as_of: "2026-07-04T10:00:00Z",
};

describe("BriefView", () => {
  it("renders regime, highlight and key news", () => {
    render(<BriefView brief={brief} />);
    expect(screen.getByText("risk-off")).toBeInTheDocument();
    expect(screen.getByText("SOL")).toBeInTheDocument();
    expect(screen.getByText(/breakout/)).toBeInTheDocument();
    expect(screen.getByText("ETF delayed")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/MarketBriefPanel.test.tsx`
Expected: FAIL (`MarketBriefPanel`/`BriefView` non esistono).

- [ ] **Step 3: Write minimal implementation**

In `api.ts`:

```ts
export type Highlight = { symbol: string; snapshot: string; signal: string; note: string };
export type MarketBrief = { regime: string; highlights: Highlight[]; key_news: string[]; as_of: string | null };
export const getBrief = (id: number) => get<MarketBrief | null>(`/api/agents/${id}/brief`);
```

Crea `frontend/src/components/MarketBriefPanel.tsx`:

```tsx
import { useEffect, useState } from "react";
import { getBrief, type MarketBrief } from "../api";

const signalMark = (s: string) => (s === "bullish" ? "🟢" : s === "bearish" ? "🔴" : "⚪");

export function BriefView({ brief }: { brief: MarketBrief }) {
  return (
    <div className="flex flex-col gap-3">
      <div>
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Regime</span>
        <p className="text-sm">{brief.regime || "—"}</p>
      </div>
      {brief.highlights.length > 0 && (
        <ul className="flex flex-col gap-1">
          {brief.highlights.map((h) => (
            <li key={h.symbol} className="text-sm">
              <span className="mr-1">{signalMark(h.signal)}</span>
              <span className="font-medium">{h.symbol.replace(/USDT$/, "")}</span>
              {h.note && <span className="text-muted-foreground"> — {h.note}</span>}
            </li>
          ))}
        </ul>
      )}
      {brief.key_news.length > 0 && (
        <ul className="flex flex-col gap-0.5 list-disc pl-4">
          {brief.key_news.map((n, i) => (
            <li key={i} className="text-xs text-muted-foreground">{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function MarketBriefPanel({ agentId, brainVersion }: { agentId: number; brainVersion: string }) {
  const [brief, setBrief] = useState<MarketBrief | null>(null);
  const [state, setState] = useState<"loading" | "error" | "ready">("loading");
  useEffect(() => {
    let alive = true;
    setState("loading");
    getBrief(agentId)
      .then((b) => { if (alive) { setBrief(b); setState("ready"); } })
      .catch(() => { if (alive) setState("error"); });
    return () => { alive = false; };
  }, [agentId]);

  return (
    <div className="flex flex-col gap-2">
      {brainVersion !== "v2" && (
        <p className="text-xs text-muted-foreground">
          Questo agente usa il brain v1 (monolitico) e non consuma il market brief.
        </p>
      )}
      {state === "loading" && <p className="text-sm text-muted-foreground">Carico il brief…</p>}
      {state === "error" && <p className="text-sm text-muted-foreground">Brief non disponibile.</p>}
      {state === "ready" && (brief
        ? <BriefView brief={brief} />
        : <p className="text-sm text-muted-foreground">Nessun brief ancora generato.</p>)}
    </div>
  );
}
```

In `App.tsx`: importa `MarketBriefPanel`; monta una Card (dopo la Card "Osservazioni"), keyed sull'agente selezionato:

```tsx
            {selId !== null && sel && (
              <Card>
                <CardContent>
                  <h2 className="text-sm font-semibold text-muted-foreground mb-3">Market brief</h2>
                  <MarketBriefPanel agentId={selId} brainVersion={sel.brain_version} />
                </CardContent>
              </Card>
            )}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/MarketBriefPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/components/MarketBriefPanel.tsx frontend/src/App.tsx frontend/src/__tests__/MarketBriefPanel.test.tsx
git commit -m "feat(fase7): per-agent market brief panel"
```

---

### Task 10: Finalizzazione Fase 7

**Files:** nessuna modifica di codice (solo verifica + tracker).

- [ ] **Step 1: Suite backend completa verde**

Run: `cd backend && .venv/bin/pytest -q`
Expected: tutti i test PASS (i 274 esistenti + i ~13 nuovi di Fase 7, nessun fallimento/errore).

- [ ] **Step 2: Suite frontend completa + build (type-check)**

Run: `cd frontend && npx vitest run`
Expected: tutti i test PASS (i 41 esistenti + i ~5 file nuovi di Fase 7).

Run: `cd frontend && npm run build`
Expected: `tsc -b` senza errori di tipo + build vite completata.

- [ ] **Step 3: Conferma zero migrazioni / single head invariata**

Run: `cd backend && .venv/bin/alembic heads`
Expected: **esattamente** `49407193a9ac (head)` — Fase 7 non ha aggiunto migrazioni.

- [ ] **Step 4: Aggiorna il tracker roadmap** — in `docs/superpowers/plans/2026-07-02-pipeline-v2-roadmap.md`, riga 7 della tabella: stato `⬜` → `🔨 in esecuzione su pipeline-v2` (o `✅` **solo dopo** il merge), aggiungi il link al piano e una nota sintetica (task, commit, conteggio test). Commit:

```bash
git add docs/superpowers/plans/2026-07-02-pipeline-v2-roadmap.md
git commit -m "docs(pipeline): Fase 7 UI di completamento — tracker"
```

- [ ] **Step 5: Handoff** — la **review finale whole-branch** e il **merge `pipeline-v2 → main`** (che auto-deploya) sono passi guidati dall'utente (sezione "Chiusura branch" della roadmap), fuori dallo scope di questo piano. Segnala che Fase 7 è pronta e che restano: review finale OPUS (scope `d5423d0..HEAD`) + merge delle 6 (ora 7) fasi.

---

## Self-Review

**1. Spec coverage** (ogni requisito dello spec → task):
- Pannello decisioni (sintesi compatta, decision+reflection, azioni da `parsed_output`) → **Task 7** ✓
- Feed osservazioni (globale recente) → **Task 3** (backend) + **Task 8** (frontend) ✓
- Vista market brief (per-agente filtrato, nota v1) → **Task 4** (backend) + **Task 9** (frontend, con `brain_version` da Task 6) ✓
- P&L per posizione (backend autorevole, via leggera, degrado cost-only) → **Task 2** (backend) + **Task 5** (frontend) ✓
- `brain_version` esposto + badge → **Task 1** (backend) + **Task 6** (frontend) ✓
- Zero migrazioni / single head invariata → **Task 10** verifica ✓
- Error handling (positions degrada, brief null/502) → **Task 2** + **Task 4** ✓
- Auth `require_viewer_or_admin` su tutti i nuovi endpoint → Task 2/3/4 ✓

**2. Placeholder scan:** nessun TBD/TODO; ogni step di codice mostra codice reale; ogni comando ha output atteso. ✓

**3. Type consistency:**
- Backend: `PositionOut`/`ObservationOut`/`MarketBriefOut`/`HighlightOut`/`AgentOut` definiti in Task 1-4 e usati con gli stessi nomi/campi negli endpoint. `get_universe_snapshot`, `get_top_symbols`, `latest_valid_brief`, `filter_brief_for`, `universe_size` usati con le firme verificate nel codice vivo.
- Frontend: i tipi TS (`Position`, `Agent`, `Decision`, `Observation`, `Highlight`, `MarketBrief`) in `api.ts` combaciano con gli schemi Pydantic (Decimal→string, datetime→string). `BriefView`/`MarketBriefPanel`, `DecisionsPanel`, `ObservationsFeed`, `BrainBadge`, `PositionsTable` esportati e importati con nomi coerenti. Le classi `pos`/`neg`/`empty` sono classi globali già in uso.

*(Nota di ordine: i task frontend consumano i rispettivi backend — 5→2, 6→1, 9→4+6. I task 1-4 (backend) vengono prima. Ogni edit di `App.tsx` è additivo e localizzato: usa gli ancoraggi per-contenuto indicati, non i numeri di riga, che shiftano tra un task e l'altro.)*
