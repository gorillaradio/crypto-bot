# Redesign Attività + Posizioni + striscia salute — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eventi strutturati (payload JSON) end-to-end e tre viste ridisegnate: diario Attività "fatto → motivo", Posizioni con storico chiuse, striscia salute in testa alla pagina.

**Architecture:** Il backend scrive un `payload` strutturato accanto a `message` su ogni evento (decision/trade/reflection); una migrazione backfilla gli eventi storici riusando le regex oggi nel frontend. Le posizioni tracciano `opened_at`/`invested_usd`/`realized_usd`; alla chiusura totale l'evento SELL porta `position_summary` (biografia completa) — lo storico CHIUSE si legge dagli eventi, nessuna tabella nuova. Il frontend smette di riparsare stringhe: EventsFeed riscritto payload-driven, PositionsTable esteso, HealthStrip nuovo.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (Postgres in prod, sqlite nei test), React + TypeScript + Tailwind/shadcn + vitest.

**Spec:** `docs/superpowers/specs/2026-07-09-attivita-posizioni-salute-redesign-design.md`

## Global Constraints

- Colore = esito e nient'altro: classi `pos`/`neg` (verde/rosso) SOLO su P&L; pill `VENDITA`/`ACQUISTO`/stato neutre grigie; striscia salute mai verde (grigio/ambra/rosso).
- Niente frecce ▲▼ né emoji nel diario.
- Voce dell'agente (note, rationale) in inglese verbatim, mai riscritta.
- Le stringhe `message` degli eventi NON cambiano (log/debug/fallback); si aggiunge solo `payload`.
- I Decimal nei payload JSON si serializzano come stringhe (`str(decimal)`); il frontend li converte con `Number()`.
- P&L realizzato: stessa formula di oggi, lordo fee, contro costo medio.
- Nessuna modifica alla logica di trading o al learning loop: solo registrazione aggiuntiva.
- Convenzioni test esistenti: backend `db_session` fixture (sqlite in-memory), frontend testing-library + vitest.
- Comandi test: backend `cd backend && .venv/bin/python -m pytest tests/<file> -q` · frontend `cd frontend && npx vitest run src/__tests__/<file>`.
- Commit frequenti, messaggi in stile repo (`feat:`, `fix:`, `docs:`), footer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Colonne nuove su Event e Position + migrazione schema

**Files:**
- Modify: `backend/app/db/models.py:36-45` (Position), `backend/app/db/models.py:68-75` (Event)
- Create: `backend/alembic/versions/a1f2e3d4c5b6_event_payload_position_lifecycle.py`
- Test: `backend/tests/test_models_payload.py`

**Interfaces:**
- Produces: `Event.payload: dict | None`; `Position.opened_at: datetime | None`, `Position.invested_usd: Decimal`, `Position.realized_usd: Decimal`. I task 2-5 li usano con questi nomi esatti.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_models_payload.py
from datetime import datetime, timezone
from decimal import Decimal
from app.db.models import Event, Position


def test_event_payload_roundtrip(db_session):
    e = Event(agent_id=1, kind="trade", message="BUY 1 X @ $1 (fee $0.001)",
              payload={"side": "BUY", "qty": "1", "nested": {"a": 1}})
    db_session.add(e); db_session.commit()
    row = db_session.query(Event).one()
    assert row.payload["side"] == "BUY"
    assert row.payload["nested"] == {"a": 1}


def test_event_payload_defaults_to_none(db_session):
    e = Event(agent_id=1, kind="decision", message="x")
    db_session.add(e); db_session.commit()
    assert db_session.query(Event).one().payload is None


def test_position_lifecycle_columns(db_session):
    now = datetime.now(timezone.utc)
    p = Position(agent_id=1, symbol="BTCUSDT", quantity=Decimal("1"),
                 avg_price=Decimal("100"), opened_at=now,
                 invested_usd=Decimal("100"), realized_usd=Decimal("0"))
    db_session.add(p); db_session.commit()
    row = db_session.query(Position).one()
    assert row.invested_usd == Decimal("100")
    assert row.realized_usd == Decimal("0")
    assert row.opened_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_models_payload.py -q`
Expected: FAIL — `TypeError: 'payload' is an invalid keyword argument for Event` (e analogo per Position).

- [ ] **Step 3: Add columns to the models**

In `backend/app/db/models.py`, aggiungi `JSON` all'import esistente da `sqlalchemy` (riga in testa al file, accanto a `String`, `Numeric`, ecc.). Poi:

```python
class Position(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    symbol: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    avg_price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    breach_armed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    move_armed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Vita della posizione: quando è nata, quanto ci è entrato (somma dei BUY),
    # quanto è già stato incassato dalle vendite parziali (lordo fee).
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invested_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False,
                                                  default=Decimal("0"), server_default="0")
    realized_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False,
                                                  default=Decimal("0"), server_default="0")
    agent: Mapped["Agent"] = relationship(back_populates="positions")
```

```python
class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    kind: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(String)
    # Dati strutturati dell'evento (forma per kind, vedi spec); message resta il log leggibile.
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cycle_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_models_payload.py -q`
Expected: PASS (3 passed). Poi l'intera suite: `.venv/bin/python -m pytest -q` → nessuna regressione.

- [ ] **Step 5: Write the Alembic migration**

```python
# backend/alembic/versions/a1f2e3d4c5b6_event_payload_position_lifecycle.py
"""event payload + position lifecycle columns

Revision ID: a1f2e3d4c5b6
Revises: 7b8c9d0e1f2a
Create Date: 2026-07-09
"""
import sqlalchemy as sa
from alembic import op

revision: str = "a1f2e3d4c5b6"
down_revision: str | None = "7b8c9d0e1f2a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("payload", sa.JSON(), nullable=True))
    op.add_column("positions", sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("positions", sa.Column("invested_usd", sa.Numeric(20, 8),
                                         nullable=False, server_default="0"))
    op.add_column("positions", sa.Column("realized_usd", sa.Numeric(20, 8),
                                         nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("positions", "realized_usd")
    op.drop_column("positions", "invested_usd")
    op.drop_column("positions", "opened_at")
    op.drop_column("events", "payload")
```

- [ ] **Step 6: Verify single head**

Run: `cd backend && .venv/bin/python -m alembic heads`
Expected: una sola head, `a1f2e3d4c5b6`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/a1f2e3d4c5b6_event_payload_position_lifecycle.py backend/tests/test_models_payload.py
git commit -m "feat: event payload + position lifecycle columns"
```

---

### Task 2: Engine — payload sui trade e ciclo di vita della posizione

**Files:**
- Modify: `backend/app/trading/engine.py` (execute_buy, execute_sell, imports)
- Test: `backend/tests/test_engine.py` (aggiunte in coda)

**Interfaces:**
- Consumes: colonne Task 1.
- Produces: `execute_buy(session, agent, symbol, usd_amount, ask, cycle_id=None, rationale=None)` e `execute_sell(session, agent, symbol, quantity, bid, cycle_id=None, rationale=None)` — nuovo kwarg `rationale`. Payload evento trade BUY: `{side, symbol, qty, price, fee, usd_value, rationale, position: "new"|"increase"}`. SELL: BUY-keys + `{fraction, avg_cost, realized_pnl_pct, realized_pnl_usd}` e, a chiusura totale, `position_summary: {opened_at, closed_at, held_minutes, invested_usd, realized_total_usd, realized_total_pct}`. Tutti i numeri come stringhe.

- [ ] **Step 1: Write the failing tests (append to test_engine.py)**

```python
# --- payload strutturato e ciclo di vita posizione (spec 2026-07-09) ---
from app.db.models import Event


def test_buy_writes_structured_payload_and_opens_lifecycle(db_session):
    agent = _agent(db_session, "100")
    execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), ask=Decimal("100"),
                cycle_id="c1", rationale="momentum")
    ev = db_session.query(Event).filter_by(kind="trade").one()
    p = ev.payload
    assert p["side"] == "BUY" and p["symbol"] == "BTCUSDT"
    assert p["usd_value"] == "50" and p["rationale"] == "momentum"
    assert p["position"] == "new"
    pos = db_session.query(Position).one()
    assert pos.opened_at is not None
    assert pos.invested_usd == Decimal("50")
    assert pos.realized_usd == Decimal("0")


def test_rebuy_marks_increase_and_accumulates_invested(db_session):
    agent = _agent(db_session, "200")
    execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), ask=Decimal("100"))
    first_opened = db_session.query(Position).one().opened_at
    execute_buy(db_session, agent, "BTCUSDT", Decimal("30"), ask=Decimal("120"))
    pos = db_session.query(Position).one()
    assert pos.invested_usd == Decimal("80")
    assert pos.opened_at == first_opened          # il riacquisto non riapre la vita
    last = db_session.query(Event).filter_by(kind="trade").order_by(Event.id.desc()).first()
    assert last.payload["position"] == "increase"


def test_partial_sell_payload_has_fraction_and_realized(db_session):
    agent = _agent(db_session, "100")
    execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), ask=Decimal("100"))
    execute_sell(db_session, agent, "BTCUSDT", Decimal("0.25"), bid=Decimal("120"),
                 rationale="take profit")
    ev = db_session.query(Event).filter_by(kind="trade").order_by(Event.id.desc()).first()
    p = ev.payload
    assert p["side"] == "SELL"
    assert Decimal(p["fraction"]) == Decimal("0.5")            # 0.25 di 0.5
    assert Decimal(p["realized_pnl_pct"]) == Decimal("20")     # (120-100)/100
    assert Decimal(p["realized_pnl_usd"]) == Decimal("5")      # 20 * 0.25
    assert "position_summary" not in p                          # parziale: niente biografia
    pos = db_session.query(Position).one()
    assert pos.realized_usd == Decimal("5")


def test_full_close_payload_carries_position_summary(db_session):
    agent = _agent(db_session, "100")
    execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), ask=Decimal("100"))
    execute_sell(db_session, agent, "BTCUSDT", Decimal("0.25"), bid=Decimal("120"))
    execute_sell(db_session, agent, "BTCUSDT", Decimal("0.25"), bid=Decimal("140"))
    ev = db_session.query(Event).filter_by(kind="trade").order_by(Event.id.desc()).first()
    s = ev.payload["position_summary"]
    assert s["opened_at"] is not None and s["closed_at"] is not None
    assert s["held_minutes"] >= 0
    assert Decimal(s["invested_usd"]) == Decimal("50")
    # vita intera: +5 (prima parziale) +10 (chiusura) = 15 → 30% dell'investito
    assert Decimal(s["realized_total_usd"]) == Decimal("15")
    assert Decimal(s["realized_total_pct"]) == Decimal("30")
    assert db_session.query(Position).first() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_engine.py -q`
Expected: i 4 nuovi FAIL (`TypeError: unexpected keyword argument 'rationale'`), i preesistenti PASS.

- [ ] **Step 3: Implement in engine.py**

Sostituisci integralmente `execute_buy` ed `execute_sell` (e aggiungi gli import in testa):

```python
from datetime import datetime, timezone
from decimal import Decimal
from app.core.config import settings
from app.db.models import Agent, Position, Trade, Event
```

```python
def execute_buy(session, agent: Agent, symbol: str, usd_amount: Decimal, ask: Decimal,
                cycle_id: str | None = None, rationale: str | None = None) -> Trade:
    notional = usd_amount
    fee = notional * settings.fee_rate
    total_cost = notional + fee
    if total_cost > agent.cash_usd:
        raise ValueError("cash insufficiente")
    quantity = notional / ask
    agent.cash_usd = agent.cash_usd - total_cost

    pos = _get_position(session, agent.id, symbol)
    is_new = pos is None
    if is_new:
        pos = Position(agent_id=agent.id, symbol=symbol, quantity=quantity, avg_price=ask,
                       opened_at=datetime.now(timezone.utc),
                       invested_usd=notional, realized_usd=Decimal("0"))
        session.add(pos)
    else:
        new_qty = pos.quantity + quantity
        pos.avg_price = (pos.avg_price * pos.quantity + ask * quantity) / new_qty
        pos.quantity = new_qty
        pos.invested_usd = (pos.invested_usd or Decimal("0")) + notional

    trade = Trade(agent_id=agent.id, symbol=symbol, side="BUY",
                  quantity=quantity, price=ask, fee=fee)
    session.add(trade)
    payload = {"side": "BUY", "symbol": symbol, "qty": str(quantity), "price": str(ask),
               "fee": str(fee), "usd_value": str(notional), "rationale": rationale,
               "position": "new" if is_new else "increase"}
    session.add(Event(agent_id=agent.id, kind="trade", cycle_id=cycle_id, payload=payload,
                      message=f"BUY {_fmt_qty(quantity)} {symbol} @ ${_fmt_price(ask)} (fee ${_fmt_price(fee)})"))
    session.commit()
    return trade


def execute_sell(session, agent: Agent, symbol: str, quantity: Decimal, bid: Decimal,
                 cycle_id: str | None = None, rationale: str | None = None) -> Trade:
    pos = _get_position(session, agent.id, symbol)
    if pos is None or quantity > pos.quantity:
        raise ValueError("quantità insufficiente")
    notional = quantity * bid
    fee = notional * settings.fee_rate
    agent.cash_usd = agent.cash_usd + (notional - fee)

    fraction = quantity / pos.quantity
    avg_cost = pos.avg_price
    realized_pct = (((bid - avg_cost) / avg_cost) * Decimal("100")) if avg_cost else Decimal("0")
    realized_usd = (bid - avg_cost) * quantity
    pos.realized_usd = (pos.realized_usd or Decimal("0")) + realized_usd

    payload = {"side": "SELL", "symbol": symbol, "qty": str(quantity), "price": str(bid),
               "fee": str(fee), "usd_value": str(notional), "rationale": rationale,
               "fraction": str(fraction), "avg_cost": str(avg_cost),
               "realized_pnl_pct": str(realized_pct), "realized_pnl_usd": str(realized_usd)}

    pos.quantity = pos.quantity - quantity
    if pos.quantity <= 0:
        now = datetime.now(timezone.utc)
        invested = pos.invested_usd or None
        total = pos.realized_usd
        payload["position_summary"] = {
            "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
            "closed_at": now.isoformat(),
            "held_minutes": (int((now - pos.opened_at).total_seconds() // 60)
                             if pos.opened_at else None),
            "invested_usd": str(invested) if invested is not None else None,
            "realized_total_usd": str(total),
            "realized_total_pct": (str((total / invested) * Decimal("100"))
                                   if invested else None),
        }
        session.delete(pos)

    trade = Trade(agent_id=agent.id, symbol=symbol, side="SELL",
                  quantity=quantity, price=bid, fee=fee)
    session.add(trade)
    session.add(Event(agent_id=agent.id, kind="trade", cycle_id=cycle_id, payload=payload,
                      message=f"SELL {_fmt_qty(quantity)} {symbol} @ ${_fmt_price(bid)} (fee ${_fmt_price(fee)})"))
    session.commit()
    return trade
```

Nota: posizioni pre-migrazione hanno `opened_at=None` e `invested_usd=0` → i rami `or Decimal("0")` / `if pos.opened_at` / `if invested` degradano a `None` nel summary senza esplodere (il Task 4 backfilla comunque i valori reali).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_engine.py -q`
Expected: PASS tutti. Attenzione al test su `fraction == 0.5`: 0.25/0.5 in Decimal dà `0.5` esatto.

- [ ] **Step 5: Run the whole backend suite**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: PASS (i chiamanti passano `rationale` solo dal Task 3; il default `None` mantiene la compatibilità).

- [ ] **Step 6: Commit**

```bash
git add backend/app/trading/engine.py backend/tests/test_engine.py
git commit -m "feat: structured trade payloads + position lifecycle in engine"
```

---

### Task 3: Runtime — payload su decision e reflection, rationale dentro il trade

**Files:**
- Modify: `backend/app/agents/runtime.py:212-326` (`_run_decision_llm`, `_append_rationale`)
- Test: `backend/tests/test_runtime.py` (aggiunte in coda)

**Interfaces:**
- Consumes: `execute_buy/execute_sell(..., rationale=...)` dal Task 2.
- Produces: payload evento `decision`: `{status: "ok"|"error", note, executed, skipped: [{type, symbol, reason}], skipped_count, errors, trigger, wake_reason, detail?}`. Payload evento `reflection`: `{status: "ok"|"invalid"|"error", distilled?, detail?}`. Gli eventi `reasoning` NON vengono più scritti (il rationale viaggia nel payload del trade).

- [ ] **Step 1: Write the failing tests (append to test_runtime.py)**

```python
# --- payload strutturati su decision/reflection (spec 2026-07-09) ---

async def test_decision_event_payload_records_skip_reasons(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[
        Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("50"), rationale="ok buy"),
        Action(type="BUY", symbol="DOGEUSDT", usd_amount=Decimal("50"), rationale="x"),   # fuori universo
        Action(type="SELL", symbol="ETHUSDT", rationale="x"),                              # mai posseduta
    ], note="testing skips")
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision))
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").one()
    p = ev.payload
    assert p["status"] == "ok" and p["note"] == "testing skips"
    assert p["executed"] == 1 and p["errors"] == 0
    assert p["skipped_count"] == 2
    reasons = {(s["type"], s["symbol"]): s["reason"] for s in p["skipped"]}
    assert reasons[("BUY", "DOGEUSDT")] == "coin fuori universo"
    assert reasons[("SELL", "ETHUSDT")] == "posizione inesistente"


async def test_trade_rationale_lives_in_trade_payload_no_reasoning_events(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[
        Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("50"), rationale="momentum play"),
    ], note="buy")
    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision))
    trade_ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="trade").one()
    assert trade_ev.payload["rationale"] == "momentum play"
    assert db_session.query(Event).filter_by(agent_id=agent.id, kind="reasoning").count() == 0


async def test_decision_error_event_payload(db_session, monkeypatch):
    agent = _llm_agent(db_session)
    market = FakeMarketLLM([], Decimal("100"), (Decimal("99"), Decimal("101")))
    def boom(ctx, adapter): raise RuntimeError("LLM timeout")
    await run_decision(db_session, agent, market, ["BTCUSDT"], brain_decide=boom)
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="decision").one()
    assert ev.payload["status"] == "error"
    assert "LLM timeout" in ev.payload["detail"]
```

Nota per l'implementatore: se `Action`/`Decision` richiedono altri campi obbligatori, copia la costruzione dai test esistenti nello stesso file (es. `test_policy_violation_...`) — la forma sopra segue quelle già in uso.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_runtime.py -q`
Expected: i 3 nuovi FAIL (payload `None`, evento reasoning presente), i preesistenti PASS.

- [ ] **Step 3: Implement in runtime.py**

In `_run_decision_llm`:

1. Ramo errore (righe ~219-223) — aggiungi il payload:

```python
    except Exception as exc:
        session.add(Event(agent_id=agent.id, kind="decision", cycle_id=cycle_id,
                          payload={"status": "error", "detail": str(exc),
                                   "wake_reason": (str(wake_reason) if wake_reason else None)},
                          message=f"ciclo decisione (LLM): errore — {exc}"))
        session.commit()
        return
```

2. Loop azioni (righe ~229-266) — sostituisci il contatore `skipped` con una lista di motivi e passa il rationale all'engine; l'intero loop diventa:

```python
    held = {p.symbol: p for p in agent.positions}
    actions = errors = 0
    skipped: list[dict] = []
    closed_trades: list[ClosedTrade] = []
    for action in decision.actions:
        try:
            if action.type == "BUY" and action.symbol in universe_symbols:
                amount = action.usd_amount or settings.decision_buy_default_usd
                # The fee is charged on top of the notional, so the most the agent
                # can actually spend is cash / (1 + fee_rate). Clamp the request down
                # to that (rounded down to the cash scale) so an all-in BUY executes
                # instead of erroring out in execute_buy when the fee tips it over cash.
                affordable = (agent.cash_usd / (Decimal("1") + settings.fee_rate)
                              ).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                if amount > affordable:
                    amount = affordable
                if amount < settings.min_trade_usd:
                    skipped.append({"type": "BUY", "symbol": action.symbol,
                                    "reason": "importo sotto il minimo"})
                    continue
                _bid, ask = await market.get_book_ticker(action.symbol)
                execute_buy(session, agent, action.symbol, amount, ask,
                            cycle_id=cycle_id, rationale=action.rationale)
                session.refresh(agent)
                held = {p.symbol: p for p in agent.positions}; actions += 1
            elif action.type == "SELL" and action.symbol in held:
                frac = action.fraction if action.fraction is not None else Decimal("1")
                qty = held[action.symbol].quantity * frac
                if qty <= 0:
                    skipped.append({"type": "SELL", "symbol": action.symbol,
                                    "reason": "quantità nulla"})
                    continue
                avg_cost = held[action.symbol].avg_price
                bid, _ask = await market.get_book_ticker(action.symbol)
                execute_sell(session, agent, action.symbol, qty, bid,
                             cycle_id=cycle_id, rationale=action.rationale)
                realized = ((bid - avg_cost) / avg_cost * Decimal("100")) if avg_cost else Decimal("0")
                closed_trades.append(ClosedTrade(symbol=action.symbol, qty=qty, sell_price=bid,
                                                 avg_cost=avg_cost, realized_pnl_pct=realized))
                held = {p.symbol: p for p in agent.positions}; actions += 1
            else:
                skipped.append({"type": action.type, "symbol": action.symbol,
                                "reason": ("coin fuori universo" if action.type == "BUY"
                                           else "posizione inesistente")})
        except Exception:
            errors += 1
```

3. Evento decision (righe ~273-274) — aggiungi il payload, message invariato nel formato (usa `len(skipped)`):

```python
    session.add(Event(agent_id=agent.id, kind="decision", cycle_id=cycle_id,
                      payload={"status": "ok", "note": decision.note or "",
                               "executed": actions, "skipped": skipped,
                               "skipped_count": len(skipped), "errors": errors,
                               "trigger": trigger,
                               "wake_reason": (str(wake_reason) if wake_reason else None)},
                      message=f"{kind_label}: {note} — {actions} operazioni, {len(skipped)} saltate, {errors} errori"))
```

4. Eventi reflection — aggiungi i payload ai 4 `session.add(Event(...))` esistenti:
   - `memoria aggiornata dopo trade chiuso` → `payload={"status": "ok"}`
   - `memoria distillata: {section}` → `payload={"status": "ok", "distilled": section}`
   - `reflection: risposta non valida...` → `payload={"status": "invalid"}`
   - `reflection: errore — {exc}` → `payload={"status": "error", "detail": str(exc)}`

5. Elimina la funzione `_append_rationale` (righe ~324-326) e ogni sua chiamata — il rationale ora entra nell'engine.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_runtime.py -q`
Expected: PASS. Se un test preesistente asseriva l'esistenza di eventi `reasoning`, aggiornalo alla nuova semantica (rationale nel payload del trade).

- [ ] **Step 5: Run the whole backend suite + commit**

Run: `cd backend && .venv/bin/python -m pytest -q` → PASS.

```bash
git add backend/app/agents/runtime.py backend/tests/test_runtime.py
git commit -m "feat: structured decision/reflection payloads, rationale folded into trades"
```

---

### Task 4: Backfill degli eventi storici e delle posizioni aperte

**Files:**
- Create: `backend/app/db/event_backfill.py`
- Create: `backend/alembic/versions/b2c3d4e5f6a7_backfill_event_payloads.py`
- Test: `backend/tests/test_event_backfill.py`

**Interfaces:**
- Consumes: colonne Task 1.
- Produces: `payload_for(kind: str, message: str) -> dict` (parsing puro); `fold_rationales(rows: list[tuple[int, str, str|None, dict]]) -> dict[int, dict]` dove le tuple sono `(id, kind, cycle_id, payload)` in ordine di id e il risultato mappa id→payload aggiornato; `replay_positions(trades: list) -> dict[tuple[int, str], dict]` che da righe Trade ordinate per timestamp ricava `{(agent_id, symbol): {"opened_at", "invested_usd", "realized_usd"}}` per le posizioni ancora aperte.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_event_backfill.py
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from app.db.event_backfill import payload_for, fold_rationales, replay_positions
from app.db.models import Trade


def test_decision_message_parses_to_payload():
    p = payload_for("decision", "ciclo decisione (LLM): hold and wait — 1 operazioni, 2 saltate, 0 errori")
    assert p == {"status": "ok", "note": "hold and wait", "executed": 1,
                 "skipped": [], "skipped_count": 2, "errors": 0,
                 "trigger": None, "wake_reason": None}


def test_out_of_cycle_and_error_decisions():
    p = payload_for("decision", "ciclo decisione fuori ciclo (LLM): sell all — 1 operazioni, 0 saltate, 0 errori")
    assert p["wake_reason"] == "fuori ciclo"
    e = payload_for("decision", "ciclo decisione (LLM): errore — timeout LLM")
    assert e == {"status": "error", "detail": "timeout LLM", "wake_reason": None}


def test_trade_message_parses_and_no_note_normalizes():
    p = payload_for("trade", "BUY 378 ACTUSDT @ $0.0132 (fee $0.005)")
    assert p == {"side": "BUY", "symbol": "ACTUSDT", "qty": "378",
                 "price": "0.0132", "fee": "0.005", "rationale": None}
    n = payload_for("decision", "ciclo decisione (LLM): (no note) — 0 operazioni, 0 saltate, 0 errori")
    assert n["note"] == ""


def test_reflection_and_unknown_fall_back():
    assert payload_for("reflection", "memoria aggiornata dopo trade chiuso") == {"status": "ok"}
    assert payload_for("reflection", "memoria distillata: self_policy") == {"status": "ok", "distilled": "self_policy"}
    assert payload_for("reflection", "reflection: risposta non valida, memoria invariata") == {"status": "invalid"}
    assert payload_for("reflection", "reflection: errore — boom")["status"] == "error"
    assert payload_for("trade", "qualcosa di non riconoscibile") == {"raw": "qualcosa di non riconoscibile"}


def test_fold_rationales_pairs_reasoning_to_previous_trade():
    rows = [
        (1, "decision", "c1", {"status": "ok"}),
        (2, "trade", "c1", {"side": "BUY", "symbol": "ACTUSDT", "rationale": None}),
        (3, "reasoning", "c1", {"raw": "momentum continues"}),
        (4, "reasoning", "c1", {"raw": "loose thought"}),          # senza trade libero → resta
        (5, "reasoning", "c2", {"raw": "other cycle"}),            # altro ciclo → non accoppia
    ]
    updates = fold_rationales(rows)
    assert updates[2]["rationale"] == "momentum continues"
    assert updates[3] == {"raw": "momentum continues", "folded": True}
    assert 4 not in updates or updates[4].get("folded") is not True
    assert 5 not in updates or updates[5].get("folded") is not True


def _t(agent_id, symbol, side, qty, price, ts):
    return Trade(agent_id=agent_id, symbol=symbol, side=side, quantity=Decimal(qty),
                 price=Decimal(price), fee=Decimal("0"), timestamp=ts)


def test_replay_positions_reconstructs_open_lifecycle():
    t0 = datetime(2026, 7, 1, tzinfo=timezone.utc)
    trades = [
        _t(1, "AUSDT", "BUY", "10", "1", t0),                      # apre: invested 10
        _t(1, "AUSDT", "SELL", "10", "2", t0 + timedelta(hours=1)),  # chiude tutto (+10)
        _t(1, "AUSDT", "BUY", "5", "2", t0 + timedelta(hours=2)),  # riapre: vita nuova
        _t(1, "AUSDT", "SELL", "2", "3", t0 + timedelta(hours=3)),  # parziale: +2 realized
        _t(1, "BUSDT", "BUY", "1", "7", t0),
    ]
    out = replay_positions(trades)
    a = out[(1, "AUSDT")]
    assert a["opened_at"] == t0 + timedelta(hours=2)               # la vita corrente, non la prima
    assert a["invested_usd"] == Decimal("10")                      # 5 × 2
    assert a["realized_usd"] == Decimal("2")                       # (3-2) × 2
    assert out[(1, "BUSDT")]["invested_usd"] == Decimal("7")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_event_backfill.py -q`
Expected: FAIL — `ModuleNotFoundError: app.db.event_backfill`.

- [ ] **Step 3: Implement event_backfill.py**

```python
# backend/app/db/event_backfill.py
"""Backfill una-tantum dei payload sugli eventi storici (migrazione b2c3d4e5f6a7).

Le regex sono quelle che il frontend usava per riparsare i message; vivono qui
da ora in poi, usate solo dal backfill. Gli eventi nuovi nascono già col payload.
"""
import re
from datetime import datetime
from decimal import Decimal

DECISION_RE = re.compile(
    r"^ciclo decisione( fuori ciclo)? \(LLM\): ([\s\S]*) — (\d+) operazioni, (\d+) saltate, (\d+) errori$")
DECISION_ERR_RE = re.compile(r"^ciclo decisione( fuori ciclo)? \(LLM\): errore — ([\s\S]*)$")
TRADE_RE = re.compile(r"^(BUY|SELL) (\S+) (\S+) @ \$(\S+) \(fee \$(\S+)\)$")
DISTILL_RE = re.compile(r"^memoria distillata: (\w+)$")


def payload_for(kind: str, message: str) -> dict:
    """Payload strutturato ricavato dal message; {"raw": message} se non interpretabile."""
    if kind == "decision":
        err = DECISION_ERR_RE.match(message)
        if err:
            return {"status": "error", "detail": err.group(2),
                    "wake_reason": "fuori ciclo" if err.group(1) else None}
        ok = DECISION_RE.match(message)
        if ok:
            note = "" if ok.group(2) == "(no note)" else ok.group(2)
            return {"status": "ok", "note": note, "executed": int(ok.group(3)),
                    "skipped": [], "skipped_count": int(ok.group(4)),
                    "errors": int(ok.group(5)), "trigger": None,
                    "wake_reason": "fuori ciclo" if ok.group(1) else None}
    elif kind == "trade":
        m = TRADE_RE.match(message)
        if m:
            return {"side": m.group(1), "symbol": m.group(3), "qty": m.group(2),
                    "price": m.group(4), "fee": m.group(5), "rationale": None}
    elif kind == "reasoning":
        return {"raw": message}
    elif kind == "reflection":
        if message.startswith("memoria aggiornata"):
            return {"status": "ok"}
        d = DISTILL_RE.match(message)
        if d:
            return {"status": "ok", "distilled": d.group(1)}
        if message.startswith("reflection: risposta non valida"):
            return {"status": "invalid"}
        if message.startswith("reflection: errore"):
            return {"status": "error",
                    "detail": message.removeprefix("reflection: errore — ")}
    return {"raw": message}


def fold_rationales(rows: list[tuple[int, str, str | None, dict]]) -> dict[int, dict]:
    """rows = (id, kind, cycle_id, payload) in ordine di id (cronologico).
    Un reasoning segue il suo trade nello stesso ciclo: sposta il testo nel
    payload del trade e marca il reasoning come folded. Ritorna {id: payload} da aggiornare."""
    updates: dict[int, dict] = {}
    pending: tuple[int, dict] | None = None   # ultimo trade senza rationale
    current_cycle: str | None = None
    for eid, kind, cycle_id, payload in rows:
        if cycle_id != current_cycle:
            current_cycle, pending = cycle_id, None
        if kind == "trade" and "side" in payload:
            pending = (eid, payload)
        elif kind == "reasoning" and pending is not None and cycle_id is not None:
            trade_id, trade_payload = pending
            trade_payload = {**trade_payload, "rationale": payload["raw"]}
            updates[trade_id] = trade_payload
            updates[eid] = {**payload, "folded": True}
            pending = None
    return updates


def replay_positions(trades: list) -> dict[tuple[int, str], dict]:
    """Rigioca i trade in ordine cronologico e ricava, per le posizioni ancora aperte,
    la vita corrente: opened_at (ultimo passaggio 0→>0), invested_usd, realized_usd."""
    state: dict[tuple[int, str], dict] = {}
    for t in sorted(trades, key=lambda t: (t.timestamp, t.id or 0)):
        key = (t.agent_id, t.symbol)
        s = state.get(key)
        if t.side == "BUY":
            if s is None or s["qty"] <= 0:
                s = {"qty": Decimal("0"), "avg": Decimal("0"),
                     "opened_at": t.timestamp, "invested_usd": Decimal("0"),
                     "realized_usd": Decimal("0")}
                state[key] = s
            new_qty = s["qty"] + t.quantity
            s["avg"] = ((s["avg"] * s["qty"] + t.price * t.quantity) / new_qty) if new_qty else Decimal("0")
            s["qty"] = new_qty
            s["invested_usd"] += t.quantity * t.price
        elif t.side == "SELL" and s is not None:
            s["realized_usd"] += (t.price - s["avg"]) * t.quantity
            s["qty"] -= t.quantity
            if s["qty"] <= 0:
                del state[key]
    return {k: {"opened_at": v["opened_at"], "invested_usd": v["invested_usd"],
                "realized_usd": v["realized_usd"]}
            for k, v in state.items() if v["qty"] > 0}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_event_backfill.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Write the data migration**

```python
# backend/alembic/versions/b2c3d4e5f6a7_backfill_event_payloads.py
"""backfill event payloads + position lifecycle from history

Revision ID: b2c3d4e5f6a7
Revises: a1f2e3d4c5b6
Create Date: 2026-07-09
"""
import sqlalchemy as sa
from alembic import op

from app.db.event_backfill import payload_for, fold_rationales, replay_positions

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1f2e3d4c5b6"
branch_labels = None
depends_on = None

events = sa.table("events",
                  sa.column("id", sa.Integer), sa.column("kind", sa.String),
                  sa.column("message", sa.String), sa.column("cycle_id", sa.String),
                  sa.column("payload", sa.JSON))
positions = sa.table("positions",
                     sa.column("id", sa.Integer), sa.column("agent_id", sa.Integer),
                     sa.column("symbol", sa.String),
                     sa.column("opened_at", sa.DateTime(timezone=True)),
                     sa.column("invested_usd", sa.Numeric),
                     sa.column("realized_usd", sa.Numeric))


def upgrade() -> None:
    conn = op.get_bind()

    # 1) payload da message, per tutti gli eventi senza payload
    rows = conn.execute(sa.select(events.c.id, events.c.kind, events.c.message,
                                  events.c.cycle_id)
                        .where(events.c.payload.is_(None))
                        .order_by(events.c.id)).fetchall()
    parsed = [(r.id, r.kind, r.cycle_id, payload_for(r.kind, r.message)) for r in rows]
    for eid, _kind, _cyc, payload in parsed:
        conn.execute(events.update().where(events.c.id == eid).values(payload=payload))

    # 2) rationale dei reasoning dentro il trade che li precede (stesso ciclo)
    for eid, payload in fold_rationales(parsed).items():
        conn.execute(events.update().where(events.c.id == eid).values(payload=payload))

    # 3) vita delle posizioni aperte, rigiocata dallo storico trades
    trades = [t for t in
              conn.execute(sa.select(sa.table("trades",
                  sa.column("id", sa.Integer), sa.column("agent_id", sa.Integer),
                  sa.column("symbol", sa.String), sa.column("side", sa.String),
                  sa.column("quantity", sa.Numeric), sa.column("price", sa.Numeric),
                  sa.column("timestamp", sa.DateTime(timezone=True))))).fetchall()]
    life = replay_positions(trades)
    for row in conn.execute(sa.select(positions.c.id, positions.c.agent_id,
                                      positions.c.symbol)).fetchall():
        info = life.get((row.agent_id, row.symbol))
        if info:
            conn.execute(positions.update().where(positions.c.id == row.id).values(
                opened_at=info["opened_at"], invested_usd=info["invested_usd"],
                realized_usd=info["realized_usd"]))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(events.update().values(payload=None))
    conn.execute(positions.update().values(opened_at=None, invested_usd=0, realized_usd=0))
```

Nota: `replay_positions` accede a `.agent_id/.symbol/...` per attributo — le Row di SQLAlchemy 2 li espongono; l'import di `Trade` non è necessario, rimuovilo se il linter si lamenta.

- [ ] **Step 6: Verify migration runs on a scratch DB**

Run (dalla dir `backend`, con un Postgres locale di prova o il DB di sviluppo docker):
`cd backend && .venv/bin/python -m alembic upgrade head`
Expected: exit 0, nessuna eccezione; `alembic heads` → solo `b2c3d4e5f6a7`. Verifica a campione: `SELECT kind, payload FROM events ORDER BY id DESC LIMIT 5;` → payload valorizzati.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/event_backfill.py backend/alembic/versions/b2c3d4e5f6a7_backfill_event_payloads.py backend/tests/test_event_backfill.py
git commit -m "feat: backfill structured payloads onto historical events and open positions"
```

---

### Task 5: API — payload esposto, posizioni estese, storico chiuse, intervallo ciclo

**Files:**
- Modify: `backend/app/api/schemas.py` (EventOut, PositionOut, AgentOut, + ClosedPositionOut)
- Modify: `backend/app/api/routes.py` (`_agent_out`, `get_positions`, + endpoint closed)
- Test: `backend/tests/test_api.py` (aggiunte in coda)

**Interfaces:**
- Consumes: payload Task 2 (position_summary), colonne Task 1, `settings.decision_seconds`.
- Produces: `EventOut.payload: dict | None`; `PositionOut.opened_at: datetime | None`, `PositionOut.realized_usd: Decimal`; `AgentOut.decision_seconds: int`; `GET /api/agents/{id}/positions/closed -> list[ClosedPositionOut]` con campi `{symbol, opened_at, closed_at, held_minutes, invested_usd, realized_total_usd, realized_total_pct, close_cycle_id}` (dal più recente).

- [ ] **Step 1: Write the failing tests (append to test_api.py)**

Segui lo stile dei test esistenti nel file per client/fixture (c'è già un TestClient autenticato; riusa gli helper presenti — leggili prima di scrivere). I casi da coprire:

```python
def test_events_expose_payload(client_admin, db_session):
    # crea un agente via POST /api/agents, poi inserisci un Event con payload dict
    # e verifica che GET /api/agents/{id}/events ritorni payload identico
    ...


def test_positions_expose_lifecycle_fields(client_admin, db_session):
    # inserisci una Position con opened_at/realized_usd e verifica che
    # GET /api/agents/{id}/positions includa opened_at e realized_usd
    ...


def test_closed_positions_read_from_events(client_admin, db_session):
    # inserisci un Event kind="trade" con payload contenente position_summary
    # (symbol="SYNUSDT", realized_total_usd="2.80", ...) e uno senza summary;
    # GET /api/agents/{id}/positions/closed → 1 riga, campi del summary,
    # close_cycle_id == cycle_id dell'evento
    ...


def test_agent_out_carries_decision_seconds(client_admin):
    # GET /api/agents → ogni agente ha decision_seconds == settings.decision_seconds
    ...
```

Scrivi i 4 test per esteso (i `...` sopra indicano solo che il setup segue gli helper del file, non che il codice va lasciato vuoto).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api.py -q`
Expected: i nuovi FAIL (campo mancante / 404 sull'endpoint), i preesistenti PASS.

- [ ] **Step 3: Implement schemas**

In `schemas.py`:

```python
class EventOut(BaseModel):
    timestamp: datetime
    kind: str
    message: str
    payload: dict | None = None
    cycle_id: str | None = None


class PositionOut(BaseModel):
    symbol: str
    quantity: Decimal
    avg_price: Decimal
    cost_basis: Decimal
    last_price: Decimal | None = None
    unrealized_pnl_pct: Decimal | None = None
    market_value: Decimal | None = None
    opened_at: datetime | None = None
    realized_usd: Decimal = Decimal("0")


class ClosedPositionOut(BaseModel):
    symbol: str
    opened_at: datetime | None = None
    closed_at: datetime
    held_minutes: int | None = None
    invested_usd: Decimal | None = None
    realized_total_usd: Decimal
    realized_total_pct: Decimal | None = None
    close_cycle_id: str | None = None
```

E su `AgentOut` aggiungi `decision_seconds: int`.

- [ ] **Step 4: Implement routes**

In `routes.py`:
- `_agent_out(...)`: aggiungi `decision_seconds=settings.decision_seconds`.
- `get_positions`: nel costruttore `PositionOut(...)` aggiungi `opened_at=p.opened_at, realized_usd=p.realized_usd or Decimal("0")`.
- Nuovo endpoint dopo `get_positions`:

```python
@router.get("/agents/{agent_id}/positions/closed", response_model=list[ClosedPositionOut])
def get_closed_positions(agent_id: int, session=Depends(session_dep),
                         _: str = Depends(require_viewer_or_admin)):
    # Lo storico vive negli eventi di chiusura totale (payload.position_summary);
    # il filtro JSON si fa in python: volumi piccoli (<=100 righe utili).
    rows = (session.query(Event)
            .filter_by(agent_id=agent_id, kind="trade")
            .order_by(Event.timestamp.desc(), Event.id.desc())
            .limit(500).all())
    out = []
    for e in rows:
        s = (e.payload or {}).get("position_summary")
        if not s:
            continue
        out.append(ClosedPositionOut(
            symbol=(e.payload or {}).get("symbol", ""),
            opened_at=datetime.fromisoformat(s["opened_at"]) if s.get("opened_at") else None,
            closed_at=datetime.fromisoformat(s["closed_at"]) if s.get("closed_at") else e.timestamp,
            held_minutes=s.get("held_minutes"),
            invested_usd=Decimal(s["invested_usd"]) if s.get("invested_usd") else None,
            realized_total_usd=Decimal(s.get("realized_total_usd") or "0"),
            realized_total_pct=Decimal(s["realized_total_pct"]) if s.get("realized_total_pct") else None,
            close_cycle_id=e.cycle_id,
        ))
        if len(out) >= 50:
            break
    return out
```

Aggiungi `ClosedPositionOut` all'import da `app.api.schemas`.

- [ ] **Step 5: Run tests to verify they pass + full suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api.py -q` → PASS, poi `.venv/bin/python -m pytest -q` → PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py backend/tests/test_api.py
git commit -m "feat: expose event payloads, position lifecycle, closed-position history API"
```

---

### Task 6: Frontend — tipi e fetch in api.ts

**Files:**
- Modify: `frontend/src/api.ts`

**Interfaces:**
- Consumes: API Task 5.
- Produces (usati dai Task 7-10): tipi `EventPayload`, `TradePayload`, `DecisionPayload`, `ReflectionPayload`, `RawPayload`, `PositionSummary`, `ClosedPosition`; `AgentEvent.payload?: EventPayload | null`; `Position.opened_at/realized_usd`; `Agent.decision_seconds`; `getClosedPositions(id: number): Promise<ClosedPosition[]>`.

- [ ] **Step 1: Add the types and fetch**

In `api.ts`, sostituisci `AgentEvent` e `Position`, estendi `Agent`, aggiungi i nuovi tipi e il fetch:

```ts
export type PositionSummary = {
  opened_at: string | null; closed_at: string; held_minutes: number | null;
  invested_usd: string | null; realized_total_usd: string; realized_total_pct: string | null;
};
export type TradePayload = {
  side: "BUY" | "SELL"; symbol: string; qty: string; price: string; fee: string;
  usd_value?: string; rationale?: string | null;
  position?: "new" | "increase";                       // solo BUY
  fraction?: string; avg_cost?: string;                // solo SELL
  realized_pnl_pct?: string; realized_pnl_usd?: string; // solo SELL (eventi nuovi)
  position_summary?: PositionSummary;                  // solo SELL a chiusura totale
};
export type SkippedAction = { type: string; symbol?: string | null; reason: string };
export type DecisionPayload = {
  status: "ok" | "error"; note?: string; executed?: number;
  skipped?: SkippedAction[]; skipped_count?: number; errors?: number;
  trigger?: string | null; wake_reason?: string | null; detail?: string;
};
export type ReflectionPayload = { status: "ok" | "invalid" | "error"; distilled?: string; detail?: string };
export type RawPayload = { raw: string; folded?: boolean };
export type EventPayload = TradePayload | DecisionPayload | ReflectionPayload | RawPayload;

export type AgentEvent = {
  timestamp: string; kind: string; message: string;
  payload?: EventPayload | null; cycle_id: string | null;
};

export type ClosedPosition = {
  symbol: string; opened_at: string | null; closed_at: string; held_minutes: number | null;
  invested_usd: string | null; realized_total_usd: string; realized_total_pct: string | null;
  close_cycle_id: string | null;
};
```

Su `Position` aggiungi `opened_at: string | null; realized_usd: string;` — su `Agent` aggiungi `decision_seconds: number;`. Poi, accanto a `getPositions`:

```ts
export const getClosedPositions = (id: number) =>
  get<ClosedPosition[]>(`/api/agents/${id}/positions/closed`);
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc -b --noEmit` (o `npm run build`)
Expected: errori SOLO nei file che i task successivi riscrivono (EventsFeed usa ancora il vecchio shape? no — `payload` è opzionale, quindi zero errori attesi). Se compaiono errori, sistemali qui.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api.ts
git commit -m "feat: typed event payloads and closed-positions fetch in frontend api"
```

---

### Task 7: EventsFeed riscritto — la storia "fatto → motivo"

**Files:**
- Rewrite: `frontend/src/components/EventsFeed.tsx`
- Rewrite: `frontend/src/__tests__/EventsFeed.test.tsx`
- Modify: `frontend/src/index.css` (classi `.side-pill`, `.why-label`, `.quote`, aggiornamento sezione feed)

**Interfaces:**
- Consumes: `AgentEvent.payload` (Task 6), `PolicyLine` da api.ts.
- Produces: `EventsFeed({ events, policy }: { events: AgentEvent[]; policy: PolicyLine[] })` — nuova prop `policy` (per i tooltip P####). Il Task 10 aggiorna il chiamante.

**Regole di rendering (dal mockup v7 e spec):**
- Blocchi per ciclo (adiacenza di `cycle_id`, come oggi), separatori giorno (`dayLabel`), filtro `tutto / solo operazioni` + contatore nel `feed-bar`.
- Cicli consecutivi SENZA operazioni e con decision `status:"ok"` → un gruppo: `10:29–10:34 · Nessuna mossa (2 cicli)` smorzato, PERCHÉ = nota del ciclo più recente, `<details>` con l'elenco (ora + nota) dei singoli.
- Ciclo con operazioni: ora → righe operazione → PERCHÉ (quote) → `<details>` dettagli.
  - Riga SELL: pill grigia `VENDITA` + symbol (senza suffisso USDT) + (`venduto il N%` solo se `fraction < 0.995`) + `· +X,X% +$Y` colorati con `pos`/`neg`. SELL legacy senza `realized_pnl_pct`: solo pill + symbol + qty@price in grigio.
  - Riga BUY: pill `ACQUISTO` + symbol + `~$V` grigio + `nuova posizione`/`posizione aumentata` (da `payload.position`; legacy senza: niente etichetta).
  - Dettagli: qty, prezzo, fee, avg_cost (se SELL), rationale per operazione.
- PERCHÉ: label maiuscoletto `PERCHÉ` + nota inglese tra virgolette; i riferimenti `P\d+` diventano `<abbr>` con `title` = testo della policy da `policy` (match su `ref`).
- Decision `status:"error"` → blocco con fact `Ciclo fallito` in rosso + detail.
- `wake_reason` non nullo → pill grigia `risveglio` accanto all'ora.
- Trade con `cycle_id === null` (guardrail) → blocco con fact-quiet `Intervento automatico (guardrail)` sopra le righe operazione.
- Eventi `reflection` → MAI renderizzati (dominio della striscia salute).
- Eventi `reasoning` con `payload.folded` → saltati; senza folded → riga quote smorzata nel blocco del loro ciclo.
- Payload `{raw}` o assente → riga grezza smorzata (`message` così com'è).
- MAI classi colore su pill o frazioni; `pos`/`neg` solo su percentuali e importi P&L.
- **Ancore per i link incrociati**: ogni blocco ciclo ha `id={"cycle-" + cycle_id}` (ometti per i gruppi senza cycle_id); il symbol nelle righe operazione è `<a className="op-sym" href={"#pos-" + sym(p.symbol)}>` — porta alla riga della posizione. (Nel codice del componente sotto, applica queste due modifiche a `CycleBlock`/`OpRow`.)

- [ ] **Step 1: Write the failing tests (rewrite EventsFeed.test.tsx)**

```tsx
import { render, screen, within, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { EventsFeed } from "../components/EventsFeed";
import type { AgentEvent, EventPayload, PolicyLine } from "../api";

const ev = (
  kind: string, payload: EventPayload | null, cycle_id: string | null,
  timestamp = "2026-07-09T09:40:39Z", message = "raw message",
): AgentEvent => ({ timestamp, kind, message, cycle_id, payload });

const decision = (note: string, cycle: string, ts: string, extra: object = {}): AgentEvent =>
  ev("decision", { status: "ok", note, executed: 0, skipped: [], skipped_count: 0,
                   errors: 0, trigger: "schedule", wake_reason: null, ...extra }, cycle, ts);

const POLICY: PolicyLine[] = [{ ref: "P3329", content: "Take profit oltre +12% sulle micro-cap" }];

describe("EventsFeed (payload-driven)", () => {
  it("raggruppa i cicli fermi consecutivi in un blocco unico con la nota più recente", () => {
    const events = [
      decision("waiting for setups", "c3", "2026-07-09T10:34:00Z"),
      decision("still cautious", "c2", "2026-07-09T10:29:00Z"),
      decision("buys ACT", "c1", "2026-07-09T10:21:00Z", { executed: 1 }),
    ];
    // c1 ha un trade → non raggruppabile
    events.push(ev("trade", { side: "BUY", symbol: "ACTUSDT", qty: "378", price: "0.0132",
                              fee: "0.005", usd_value: "5", rationale: "momentum",
                              position: "new" }, "c1", "2026-07-09T10:21:01Z"));
    const { container } = render(<EventsFeed events={events} policy={[]} />);
    expect(screen.getByText(/nessuna mossa/i)).toBeInTheDocument();
    expect(screen.getByText(/2 cicli/)).toBeInTheDocument();
    expect(screen.getByText(/waiting for setups/)).toBeInTheDocument();   // nota più recente
    expect(container.textContent).toContain("10:29");                     // range orario
  });

  it("vendita: pill neutra, P&L colorato, quota solo se parziale", () => {
    const events = [
      decision("lock profits", "c1", "2026-07-09T10:21:00Z", { executed: 2 }),
      ev("trade", { side: "SELL", symbol: "SPELLUSDT", qty: "144788", price: "0.00012",
                    fee: "0.01", usd_value: "17", rationale: "target exceeded per P3329",
                    fraction: "0.5", avg_cost: "0.000104",
                    realized_pnl_pct: "15.2", realized_pnl_usd: "2.20" }, "c1"),
      ev("trade", { side: "SELL", symbol: "SYNUSDT", qty: "48.79", price: "0.4626",
                    fee: "0.02", usd_value: "22", rationale: "same", fraction: "1",
                    avg_cost: "0.4054", realized_pnl_pct: "14.1",
                    realized_pnl_usd: "2.80" }, "c1"),
    ];
    const { container } = render(<EventsFeed events={events} policy={POLICY} />);
    expect(screen.getAllByText("VENDITA")).toHaveLength(2);
    expect(screen.getByText(/venduto il 50%/)).toBeInTheDocument();
    expect(screen.queryByText(/venduto il 100%/)).not.toBeInTheDocument();
    const pnl = screen.getByText(/\+15[.,]20%/);   // pct() formatta a 2 decimali
    expect(pnl.closest(".pos")).not.toBeNull();
    // la pill non deve avere classi di colore esito
    const pill = screen.getAllByText("VENDITA")[0];
    expect(pill.className).not.toMatch(/pos|neg/);
  });

  it("acquisto: valore grigio e natura della posizione, nessun P&L", () => {
    const events = [
      decision("entering", "c1", "2026-07-09T10:10:00Z", { executed: 1 }),
      ev("trade", { side: "BUY", symbol: "SPELLUSDT", qty: "289575", price: "0.000103",
                    fee: "0.03", usd_value: "29", rationale: "momentum",
                    position: "new" }, "c1"),
    ];
    render(<EventsFeed events={events} policy={[]} />);
    expect(screen.getByText("ACQUISTO")).toBeInTheDocument();
    expect(screen.getByText(/nuova posizione/)).toBeInTheDocument();
    expect(screen.getByText(/~\$29/)).toBeInTheDocument();
  });

  it("il PERCHÉ cita la nota e risolve i riferimenti policy in tooltip", () => {
    const events = [
      decision("exit per P3329 discipline", "c1", "2026-07-09T10:21:00Z", { executed: 1 }),
      ev("trade", { side: "SELL", symbol: "AUSDT", qty: "1", price: "2", fee: "0",
                    usd_value: "2", rationale: null, fraction: "1", avg_cost: "1",
                    realized_pnl_pct: "100", realized_pnl_usd: "1" }, "c1"),
    ];
    render(<EventsFeed events={events} policy={POLICY} />);
    const ref = screen.getByText("P3329");
    expect(ref).toHaveAttribute("title", "Take profit oltre +12% sulle micro-cap");
  });

  it("niente eventi reflection nel diario; reasoning folded saltati", () => {
    const events = [
      ev("reflection", { status: "error", detail: "boom" }, "c1"),
      decision("note", "c1", "2026-07-09T10:00:00Z"),
      ev("reasoning", { raw: "folded thought", folded: true }, "c1"),
    ];
    render(<EventsFeed events={events} policy={[]} />);
    expect(screen.queryByText(/riflessione/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/boom/)).not.toBeInTheDocument();
    expect(screen.queryByText(/folded thought/)).not.toBeInTheDocument();
  });

  it("ciclo in errore: fatto rosso con dettaglio", () => {
    render(<EventsFeed events={[
      ev("decision", { status: "error", detail: "timeout LLM", wake_reason: null }, "c1"),
    ]} policy={[]} />);
    expect(screen.getByText(/ciclo fallito/i)).toBeInTheDocument();
    expect(screen.getByText(/timeout LLM/)).toBeInTheDocument();
  });

  it("payload raw o assente: riga grezza smorzata", () => {
    render(<EventsFeed events={[
      ev("trade", { raw: "SELL strano non parsato" }, null),
      ev("decision", null, "c9", "2026-07-09T08:00:00Z", "messaggio antico"),
    ]} policy={[]} />);
    expect(screen.getByText(/SELL strano non parsato/)).toBeInTheDocument();
    expect(screen.getByText(/messaggio antico/)).toBeInTheDocument();
  });

  it("filtro 'solo operazioni' nasconde i gruppi d'attesa", () => {
    const events = [
      decision("wait", "c2", "2026-07-09T10:30:00Z"),
      decision("buys", "c1", "2026-07-09T10:00:00Z", { executed: 1 }),
      ev("trade", { side: "BUY", symbol: "AUSDT", qty: "1", price: "1", fee: "0",
                    usd_value: "1", rationale: null, position: "new" }, "c1"),
    ];
    render(<EventsFeed events={events} policy={[]} />);
    expect(screen.getByText(/nessuna mossa/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /solo operazioni/i }));
    expect(screen.queryByText(/nessuna mossa/i)).not.toBeInTheDocument();
    expect(screen.getByText("ACQUISTO")).toBeInTheDocument();
  });

  it("risveglio e guardrail marcati, empty state invariato", () => {
    const { rerender } = render(<EventsFeed events={[
      decision("woke", "c1", "2026-07-09T10:00:00Z", { wake_reason: "breach BTC" }),
    ]} policy={[]} />);
    expect(screen.getByText("risveglio")).toBeInTheDocument();
    rerender(<EventsFeed events={[
      ev("trade", { side: "SELL", symbol: "BUSDT", qty: "1", price: "1", fee: "0",
                    usd_value: "1", rationale: null, fraction: "1", avg_cost: "2",
                    realized_pnl_pct: "-50", realized_pnl_usd: "-1" }, null),
    ]} policy={[]} />);
    expect(screen.getByText(/guardrail/i)).toBeInTheDocument();
    rerender(<EventsFeed events={[]} policy={[]} />);
    expect(screen.getByText(/nessuna attività/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/__tests__/EventsFeed.test.tsx`
Expected: FAIL (il componente attuale non ha la prop `policy` né il rendering payload).

- [ ] **Step 3: Rewrite EventsFeed.tsx**

Riscrivi il componente payload-driven. Struttura completa:

```tsx
import { useMemo, useState } from "react";
import type { AgentEvent, DecisionPayload, PolicyLine, RawPayload, TradePayload } from "../api";
import { hm, dayLabel, usd, pct, price, qty } from "@/lib/format";

/* Il diario risponde a "è successo questo → per questo motivo".
   Fatti in italiano generati dai payload; la voce dell'agente (inglese) è la citazione. */

type Op = { p: TradePayload; ts: string };
type Block =
  | { type: "cycle"; key: string; ts: string; head: DecisionPayload | null;
      ops: Op[]; looseWhys: string[]; guardrail: boolean; raws: string[] }
  | { type: "wait-group"; key: string; from: string; to: string;
      cycles: { ts: string; note: string }[] };

const isTrade = (p: unknown): p is TradePayload =>
  !!p && typeof p === "object" && "side" in (p as object);
const isRaw = (p: unknown): p is RawPayload =>
  !!p && typeof p === "object" && "raw" in (p as object);

function buildBlocks(events: AgentEvent[]): Block[] {
  // adiacenza di cycle_id (eventi dal più recente), come il vecchio buildCycles
  const groups: { cycleId: string | null; events: AgentEvent[] }[] = [];
  for (const e of events) {
    const last = groups[groups.length - 1];
    if (e.cycle_id && last && last.cycleId === e.cycle_id) last.events.push(e);
    else groups.push({ cycleId: e.cycle_id, events: [e] });
  }
  const cycles: Extract<Block, { type: "cycle" }>[] = groups.map((g, i) => {
    const chrono = [...g.events].reverse();
    const decision = chrono.find((e) => e.kind === "decision");
    const ops: Op[] = [];
    const looseWhys: string[] = [];
    const raws: string[] = [];
    for (const e of chrono) {
      if (e.kind === "reflection") continue;                     // dominio striscia salute
      const p = e.payload;
      if (e.kind === "trade" && isTrade(p)) ops.push({ p, ts: e.timestamp });
      else if (e.kind === "reasoning" && isRaw(p)) { if (!p.folded) looseWhys.push(p.raw); }
      else if (e.kind === "decision" && p && !isRaw(p)) { /* head, sotto */ }
      else raws.push(isRaw(p) ? p.raw : e.message);              // legacy/non interpretato
    }
    const head = decision && decision.payload && !isRaw(decision.payload)
      ? (decision.payload as DecisionPayload) : null;
    // (un decision con payload null/raw è già finito in `raws` dentro il loop)
    return { type: "cycle" as const, key: g.cycleId ?? `solo-${i}`,
             ts: (decision ?? g.events[0]).timestamp, head, ops, looseWhys,
             guardrail: !g.cycleId, raws };
  });

  // cicli fermi consecutivi (ok, senza ops né righe grezze) → gruppo unico
  const out: Block[] = [];
  for (const c of cycles) {
    const idle = c.head?.status === "ok" && c.ops.length === 0 && c.raws.length === 0 && !c.guardrail;
    const prev = out[out.length - 1];
    if (idle && prev?.type === "wait-group") {
      prev.cycles.push({ ts: c.ts, note: c.head?.note ?? "" });
      prev.from = c.ts;                                          // eventi desc: from = più vecchio
    } else if (idle) {
      out.push({ type: "wait-group", key: `w-${c.key}`, from: c.ts, to: c.ts,
                 cycles: [{ ts: c.ts, note: c.head?.note ?? "" }] });
    } else out.push(c);
  }
  return out;
}

/* PERCHÉ: la citazione, coi riferimenti P#### risolti in tooltip. */
function Quote({ text, policy }: { text: string; policy: PolicyLine[] }) {
  if (!text) return <span className="quote-none">nessuna nota dall'agente</span>;
  const parts = text.split(/(P\d{1,6})/g);
  return (
    <span className="quote">
      {parts.map((part, i) => {
        const hit = /^P\d{1,6}$/.test(part) ? policy.find((l) => l.ref === part) : undefined;
        return hit
          ? <abbr key={i} className="policy-ref" title={hit.content}>{part}</abbr>
          : <span key={i}>{part}</span>;
      })}
    </span>
  );
}

function Why({ note, policy }: { note: string; policy: PolicyLine[] }) {
  return (
    <p className="why-line">
      <span className="why-label">PERCHÉ</span> <Quote text={note} policy={policy} />
    </p>
  );
}

const sym = (s: string) => s.replace(/USDT$/, "");
const pnlCls = (n: number) => (n >= 0 ? "pos" : "neg");

function OpRow({ op, policy }: { op: Op; policy: PolicyLine[] }) {
  const p = op.p;
  const sell = p.side === "SELL";
  const frac = p.fraction != null ? Number(p.fraction) : null;
  const partial = sell && frac != null && frac < 0.995;
  const pnlPct = p.realized_pnl_pct != null ? Number(p.realized_pnl_pct) : null;
  const pnlUsd = p.realized_pnl_usd != null ? Number(p.realized_pnl_usd) : null;
  return (
    <li className="op-row">
      <span className="side-pill">{sell ? "VENDITA" : "ACQUISTO"}</span>
      <span className="op-sym">{sym(p.symbol)}</span>
      {partial && <span className="op-frac num">venduto il {Math.round(frac! * 100)}%</span>}
      {sell && pnlPct != null && (
        <span className={`num ${pnlCls(pnlPct)}`}>
          {pct(pnlPct)}{pnlUsd != null && <> {pnlUsd >= 0 ? "+" : "−"}{usd(Math.abs(pnlUsd))}</>}
        </span>
      )}
      {!sell && p.usd_value != null && (
        <span className="op-frac num">
          ~{usd(p.usd_value)}
          {p.position === "new" && " · nuova posizione"}
          {p.position === "increase" && " · posizione aumentata"}
        </span>
      )}
      {sell && pnlPct == null && (
        <span className="op-frac num">{qty(p.qty)} @ {price(p.price)}</span>
      )}
      <details className="op-details">
        <summary>dettagli</summary>
        <p className="num">
          qty {qty(p.qty)} @ {price(p.price)} · fee {usd(p.fee)}
          {p.avg_cost != null && <> · costo medio {price(p.avg_cost)}</>}
        </p>
        {p.rationale && <Quote text={p.rationale} policy={policy} />}
      </details>
    </li>
  );
}

function CycleBlock({ c, policy }: { c: Extract<Block, { type: "cycle" }>; policy: PolicyLine[] }) {
  const err = c.head?.status === "error";
  return (
    <li className="cycle">
      <header className="cycle-head">
        <time className="cycle-time num">{hm(c.ts)}</time>
        {c.head?.wake_reason && <span className="badge">risveglio</span>}
        {c.guardrail && <span className="badge">guardrail</span>}
        {err && <span className="fact is-err">Ciclo fallito{c.head?.detail ? ` — ${c.head.detail}` : ""}</span>}
      </header>
      {c.guardrail && c.ops.length > 0 && (
        <p className="fact-quiet">Intervento automatico (guardrail)</p>
      )}
      {c.ops.length > 0 && (
        <ul className="cycle-ops">{c.ops.map((op, i) => <OpRow key={i} op={op} policy={policy} />)}</ul>
      )}
      {c.head?.status === "ok" && c.ops.length === 0 && !c.guardrail && (
        <p className="fact-quiet">Nessuna mossa</p>
      )}
      {c.head?.status === "ok" && <Why note={c.head.note ?? ""} policy={policy} />}
      {c.looseWhys.map((w, i) => <p key={i} className="why-line"><Quote text={w} policy={policy} /></p>)}
      {c.raws.map((r, i) => <p key={`r-${i}`} className="raw-line">{r}</p>)}
    </li>
  );
}

function WaitGroup({ g, policy }: { g: Extract<Block, { type: "wait-group" }>; policy: PolicyLine[] }) {
  const newest = g.cycles[0];
  const range = g.cycles.length > 1 ? `${hm(g.from)}–${hm(g.to)}` : hm(g.to);
  return (
    <li className="cycle waitrow">
      <header className="cycle-head">
        <time className="cycle-time num">{range}</time>
        <span className="fact-quiet">
          Nessuna mossa{g.cycles.length > 1 && <span className="num"> ({g.cycles.length} cicli)</span>}
        </span>
      </header>
      <Why note={newest.note} policy={policy} />
      {g.cycles.length > 1 && (
        <details className="op-details">
          <summary>i singoli cicli</summary>
          <ul>{g.cycles.map((c, i) => (
            <li key={i} className="raw-line"><span className="num">{hm(c.ts)}</span> — <Quote text={c.note} policy={policy} /></li>
          ))}</ul>
        </details>
      )}
    </li>
  );
}

const plural = (n: number, uno: string, tanti: string) => `${n} ${n === 1 ? uno : tanti}`;

export function EventsFeed({ events, policy }: { events: AgentEvent[]; policy: PolicyLine[] }) {
  const [onlyTrades, setOnlyTrades] = useState(false);
  const blocks = useMemo(() => buildBlocks(events), [events]);
  const { cycleCount, tradeCount } = useMemo(() => ({
    cycleCount: blocks.reduce((n, b) => n + (b.type === "wait-group" ? b.cycles.length : 1), 0),
    tradeCount: blocks.reduce((n, b) => n + (b.type === "cycle" ? b.ops.length : 0), 0),
  }), [blocks]);

  if (!events.length)
    return <p className="empty">Ancora nessuna attività. L'agente è in osservazione.</p>;

  const visible = onlyTrades
    ? blocks.filter((b) => b.type === "cycle" && b.ops.length > 0)
    : blocks;

  const days: { label: string; blocks: Block[] }[] = [];
  for (const b of visible) {
    const label = dayLabel(b.type === "wait-group" ? b.to : b.ts);
    const last = days[days.length - 1];
    if (last && last.label === label) last.blocks.push(b);
    else days.push({ label, blocks: [b] });
  }

  return (
    <div className="feed">
      <div className="feed-bar">
        <span className="feed-count num">
          {plural(cycleCount, "ciclo", "cicli")} · {plural(tradeCount, "operazione", "operazioni")}
        </span>
        <div className="seg" role="group" aria-label="Filtra il diario">
          <button type="button" aria-pressed={!onlyTrades} onClick={() => setOnlyTrades(false)}>tutto</button>
          <button type="button" aria-pressed={onlyTrades} onClick={() => setOnlyTrades(true)}>solo operazioni</button>
        </div>
      </div>
      {visible.length === 0 ? (
        <p className="empty">Nessun ciclo con operazioni, finora: l'agente ha sempre scelto di non muoversi.</p>
      ) : (
        <div className="feed-scroll">
          {days.map((d) => (
            <section key={d.label} className="feed-day">
              <h3 className="day-label">{d.label}</h3>
              <ol className="cycles">
                {d.blocks.map((b) => b.type === "wait-group"
                  ? <WaitGroup key={b.key} g={b} policy={policy} />
                  : <CycleBlock key={b.key} c={b} policy={policy} />)}
              </ol>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
```

Nota sull'ESITO in dollari nella riga SELL: usa `pct()` per la percentuale e per l'importo componi segno + `usd(abs)` come nel codice sopra (l'helper `usd` non gestisce il segno).

- [ ] **Step 4: Update index.css**

Nella sezione feed di `frontend/src/index.css` (righe ~254-290), aggiungi/aggiorna mantenendo le classi ancora usate (`.feed-bar`, `.feed-count`, `.feed-scroll`, `.cycles`, `.cycle`, `.cycle-head`, `.cycle-time`, `.day-label`, `.badge`, `.seg`, `.empty`) e sostituendo quelle morte (`.cycle-note*`, `.cycle-moves`, `.move*`, `.chip*` se non usate altrove — verifica con grep prima di rimuovere):

```css
/* fatto → motivo */
.fact { font-size: 13.5px; font-weight: 600; }
.fact.is-err { color: var(--neg); }
.fact-quiet { color: var(--muted-foreground); font-size: 13px; font-weight: 500; }
.waitrow { opacity: .72; }
.side-pill {
  display: inline-block; min-width: 72px; text-align: center;
  font-size: 10px; letter-spacing: .09em; font-weight: 700;
  color: var(--muted-foreground); background: var(--secondary);
  border-radius: 4px; padding: 2px 6px; margin-right: 8px;
}
.op-row { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin: 3px 0; }
.op-sym { font-weight: 700; }
.op-frac { color: var(--muted-foreground); font-size: 12.5px; }
.why-line { margin-top: 4px; font-size: 13px; }
.why-label { color: var(--muted-foreground); opacity: .7; font-size: 10.5px; letter-spacing: .1em; font-weight: 700; }
.quote { color: var(--muted-foreground); font-style: italic; }
.quote::before { content: "“"; } .quote::after { content: "”"; }
.quote-none { color: var(--muted-foreground); font-style: italic; opacity: .7; }
.policy-ref { text-decoration: underline dotted; cursor: help; font-style: normal; }
.raw-line { color: var(--muted-foreground); font-size: 12px; opacity: .8; }
.op-details { font-size: 12px; color: var(--muted-foreground); }
.op-details summary { cursor: pointer; font-size: 11.5px; }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/__tests__/EventsFeed.test.tsx`
Expected: PASS. Il typecheck fallirà su `App.tsx` (prop `policy` mancante) solo se strict — in tal caso passa `policy={[]}` temporaneamente in App.tsx e annota che il Task 10 lo completa.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/EventsFeed.tsx frontend/src/__tests__/EventsFeed.test.tsx frontend/src/index.css frontend/src/App.tsx
git commit -m "feat: rewrite EventsFeed as payload-driven fact→reason diary"
```

---

### Task 8: Posizioni — tabella APERTE estesa + storico CHIUSE

**Files:**
- Modify: `frontend/src/components/PositionsTable.tsx`
- Create: `frontend/src/components/ClosedPositionsTable.tsx`
- Modify: `frontend/src/__tests__/PositionsTable.test.tsx` (aggiunte)
- Create: `frontend/src/__tests__/ClosedPositionsTable.test.tsx`

**Interfaces:**
- Consumes: `Position.opened_at/realized_usd`, `AgentEvent` (per la colonna Storia), `ClosedPosition` (Task 6).
- Produces: `PositionsTable({ positions, events }: { positions: Position[]; events: AgentEvent[] })` — nuova prop `events`; `ClosedPositionsTable({ closed }: { closed: ClosedPosition[] })`. Il Task 10 aggiorna il chiamante.

**Regole (mockup v7):**
- APERTE — colonne: Coin (con sotto `aperta <dayShort> <hm>` se `opened_at`), Andamento 24h (Sparkline, invariata), Storia, Valore, Non realizzato, Già incassato.
  - Storia: dai trade events del symbol con `timestamp >= opened_at`: SELL con `fraction < 0.995` → `−N% alle HH:MM`; BUY con `position === "increase"` → `aumentata alle HH:MM`; uniti con `·`; vuota → `—`.
  - Già incassato: `realized_usd` con classe `pos`/`neg`; `$0.00` → `—` grigio.
  - Riga dettaglio espandibile (chevron sulla riga, stato React `expanded: Set<string>`): quantità, costo medio, prezzo attuale, costo totale — la tabella racconta, il dettaglio rende conto.
  - Quantità, Prezzo medio e Costo ESCONO dalle colonne principali (retrocesse nel dettaglio).
- CHIUSE (`ClosedPositionsTable`) — colonne: Coin, Arco (`<dayShort+hm apertura> → <dayShort+hm chiusura>`; se `opened_at` null: `? → …`), Tenuta (`held_minutes` formattati: `<60` → `N min`, `<48h` → `N ore`, altrimenti `N g`), Investito (`~$X` o `—`), Esito (`+X,X% (+$Y)` colorato). Vuota → `<p className="empty">Nessuna posizione chiusa finora.</p>`.
- **Ancore**: ogni riga APERTE ha `id={"pos-" + symbol senza USDT}` (target dei link dal diario); nella cella Arco delle CHIUSE, se `close_cycle_id` non è null aggiungi sotto un link `<a className="text-xs" href={"#cycle-" + close_cycle_id}>perché chiusa ›</a>` che salta al blocco di Attività. Il rimando "perché aperta" è FUORI SCOPE v1: il `position_summary` non porta il cycle_id di apertura (richiederebbe una colonna in più su Position) — annotato come limite noto.

- [ ] **Step 1: Write the failing tests**

In `PositionsTable.test.tsx` aggiungi (adattando gli oggetti Position esistenti nel file ai nuovi campi):

```tsx
it("mostra storia e già incassato, e retrocede i numeri contabili nel dettaglio", () => {
  const positions = [{
    symbol: "SPELLUSDT", quantity: "290419", avg_price: "0.000103",
    cost_basis: "30", last_price: "0.000104", unrealized_pnl_pct: "1.4",
    market_value: "30.10", opened_at: "2026-07-09T10:10:00Z", realized_usd: "2.20",
  }];
  const events = [{
    timestamp: "2026-07-09T10:21:00Z", kind: "trade", message: "", cycle_id: "c1",
    payload: { side: "SELL", symbol: "SPELLUSDT", qty: "1", price: "0.00012",
               fee: "0", fraction: "0.5", avg_cost: "0.000103",
               realized_pnl_pct: "15", realized_pnl_usd: "2.20" },
  }, {
    timestamp: "2026-07-09T10:26:00Z", kind: "trade", message: "", cycle_id: "c2",
    payload: { side: "BUY", symbol: "SPELLUSDT", qty: "1", price: "0.0001",
               fee: "0", usd_value: "15", position: "increase" },
  }] as AgentEvent[];
  render(<PositionsTable positions={positions as Position[]} events={events} />);
  expect(screen.getByText(/−50% alle/)).toBeInTheDocument();
  expect(screen.getByText(/aumentata alle/)).toBeInTheDocument();
  expect(screen.getByText(/\$2\.20/)).toBeInTheDocument();
  expect(screen.queryByText("Quantità")).not.toBeInTheDocument();   // colonna retrocessa
  fireEvent.click(screen.getByRole("button", { name: /dettagli/i }));
  expect(screen.getByText(/costo medio/i)).toBeInTheDocument();
});
```

In `ClosedPositionsTable.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ClosedPositionsTable } from "../components/ClosedPositionsTable";
import type { ClosedPosition } from "../api";

const row: ClosedPosition = {
  symbol: "SYNUSDT", opened_at: "2026-07-09T10:10:00Z", closed_at: "2026-07-09T10:21:00Z",
  held_minutes: 11, invested_usd: "20", realized_total_usd: "2.80",
  realized_total_pct: "14.1", close_cycle_id: "c1",
};

describe("ClosedPositionsTable", () => {
  it("racconta l'arco: tempi, tenuta, investito, esito colorato", () => {
    render(<ClosedPositionsTable closed={[row]} />);
    expect(screen.getByText("SYN")).toBeInTheDocument();
    expect(screen.getByText(/11 min/)).toBeInTheDocument();
    expect(screen.getByText(/~\$20/)).toBeInTheDocument();
    const esito = screen.getByText(/\+14[.,]1/);
    expect(esito.closest(".pos")).not.toBeNull();
  });

  it("perdita in rosso", () => {
    render(<ClosedPositionsTable closed={[{ ...row, realized_total_usd: "-0.9",
                                            realized_total_pct: "-3.1" }]} />);
    expect(screen.getByText(/−3[.,]1/).closest(".neg")).not.toBeNull();
  });

  it("empty state", () => {
    render(<ClosedPositionsTable closed={[]} />);
    expect(screen.getByText(/nessuna posizione chiusa/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/__tests__/PositionsTable.test.tsx src/__tests__/ClosedPositionsTable.test.tsx`
Expected: FAIL (prop events inesistente; modulo ClosedPositionsTable inesistente).

- [ ] **Step 3: Implement**

`PositionsTable.tsx` — mantieni lo stile tabellare esistente (`thBase`/`tdBase`, Sparkline) e:
- aggiungi prop `events: AgentEvent[]`;
- costruisci la storia per symbol:

```tsx
function storia(events: AgentEvent[], symbol: string, openedAt: string | null): string {
  if (!openedAt) return "—";
  const items: string[] = [];
  for (const e of [...events].reverse()) {           // eventi desc → cronologico
    if (e.kind !== "trade" || !e.payload || !("side" in e.payload)) continue;
    const p = e.payload as TradePayload;
    if (p.symbol !== symbol || e.timestamp < openedAt) continue;
    if (p.side === "SELL" && p.fraction != null && Number(p.fraction) < 0.995)
      items.push(`−${Math.round(Number(p.fraction) * 100)}% alle ${hm(e.timestamp)}`);
    if (p.side === "BUY" && p.position === "increase")
      items.push(`aumentata alle ${hm(e.timestamp)}`);
  }
  return items.length ? items.join(" · ") : "—";
}
```

- colonne: Coin (+ sub `aperta {dayShort(opened_at)} {hm(opened_at)}`), Andamento 24h, Storia, Valore, Non realizzato, Già incassato, più una colonnina con bottone `dettagli` (aria-label "dettagli") che espande una `TableRow` aggiuntiva `colSpan` con: `quantità {qty} · costo medio {price(avg_price)} · prezzo attuale {price(last_price) o "—"} · costo totale {usd(cost_basis)}`.
- Già incassato: `Number(realized_usd) === 0 ? "—" : <span className={pos/neg}>{segno}{usd(abs)}</span>`.

`ClosedPositionsTable.tsx` — nuova, stessa struttura Table shadcn:

```tsx
import type { ClosedPosition } from "../api";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usd, pct, hm, dayShort } from "@/lib/format";

const held = (m: number | null) =>
  m == null ? "—" : m < 60 ? `${m} min` : m < 2880 ? `${Math.round(m / 60)} ore` : `${Math.round(m / 1440)} g`;

const when = (t: string | null) => (t ? `${dayShort(t)} ${hm(t)}` : "?");

export function ClosedPositionsTable({ closed }: { closed: ClosedPosition[] }) {
  if (!closed.length) return <p className="empty">Nessuna posizione chiusa finora.</p>;
  return (
    <Table className="tabular-nums font-mono">
      <TableHeader>
        <TableRow>
          <TableHead className="text-left text-xs">Coin</TableHead>
          <TableHead className="text-left text-xs">Arco</TableHead>
          <TableHead className="text-right text-xs">Tenuta</TableHead>
          <TableHead className="text-right text-xs">Investito</TableHead>
          <TableHead className="text-right text-xs">Esito</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {closed.map((c, i) => {
          const usdVal = Number(c.realized_total_usd);
          const cls = usdVal >= 0 ? "pos" : "neg";
          return (
            <TableRow key={`${c.symbol}-${c.closed_at}-${i}`}>
              <TableCell className="text-left font-semibold">{c.symbol.replace(/USDT$/, "")}</TableCell>
              <TableCell className="text-left text-xs">{when(c.opened_at)} → {when(c.closed_at)}</TableCell>
              <TableCell className="text-right text-xs">{held(c.held_minutes)}</TableCell>
              <TableCell className="text-right text-xs">{c.invested_usd ? `~${usd(c.invested_usd)}` : "—"}</TableCell>
              <TableCell className="text-right text-xs">
                <span className={cls}>
                  {c.realized_total_pct != null && `${pct(c.realized_total_pct)} `}
                  ({usdVal >= 0 ? "+" : "−"}{usd(Math.abs(usdVal))})
                </span>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass + commit**

Run: `cd frontend && npx vitest run src/__tests__/PositionsTable.test.tsx src/__tests__/ClosedPositionsTable.test.tsx` → PASS.

```bash
git add frontend/src/components/PositionsTable.tsx frontend/src/components/ClosedPositionsTable.tsx frontend/src/__tests__/PositionsTable.test.tsx frontend/src/__tests__/ClosedPositionsTable.test.tsx
git commit -m "feat: positions table with lifecycle story + closed positions history"
```

---

### Task 9: HealthStrip — la striscia salute

**Files:**
- Create: `frontend/src/components/HealthStrip.tsx`
- Create: `frontend/src/__tests__/HealthStrip.test.tsx`
- Modify: `frontend/src/index.css` (classi `.strip*`)

**Interfaces:**
- Consumes: `AgentEvent.payload` (DecisionPayload/ReflectionPayload), `Agent.decision_seconds`.
- Produces: `HealthStrip({ events, decisionSeconds }: { events: AgentEvent[]; decisionSeconds: number })`.

**Regole (mockup salute-v1):**
- Item 1 — vita del loop: età dell'ultimo evento `kind==="decision"`. `età > 1.5 × decisionSeconds` → rosso `loop fermo da X min` + bordo rosso sulla striscia; altrimenti grigio `ultimo ciclo X min fa`. Nessun evento decision → grigio `nessun ciclo ancora`.
- Item 2 — riflessioni di OGGI (`isToday`): count di `kind==="reflection"` con `payload.status` `invalid`/`error`. 0 → grigio `riflessioni ok`; >0 → ambra `N riflessioni scartate oggi` (title = detail dell'ultima).
- Item 3 — azioni saltate di oggi: somma `payload.skipped_count` dei decision di oggi. 0 → grigio `0 saltate oggi`; >0 → ambra con `title` = motivi uniti (`skipped[].reason (symbol)`, se presenti).
- Item 4 — errori di oggi: somma `payload.errors` dei decision + count dei decision con `status==="error"`. 0 → grigio; >0 → rosso `N errori` (+ bordo rosso).
- Mai verde. Pallini: grigio `.dot-ok`, ambra `.dot-warn`, rosso `.dot-err`.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/__tests__/HealthStrip.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { HealthStrip } from "../components/HealthStrip";
import type { AgentEvent } from "../api";

const minutesAgo = (m: number) => new Date(Date.now() - m * 60000).toISOString();

const dec = (ts: string, extra: object = {}): AgentEvent => ({
  timestamp: ts, kind: "decision", message: "", cycle_id: "c",
  payload: { status: "ok", note: "", executed: 0, skipped: [], skipped_count: 0,
             errors: 0, trigger: "schedule", wake_reason: null, ...extra },
});

describe("HealthStrip", () => {
  it("tutto a posto: riga muta senza ambra né rosso", () => {
    const { container } = render(
      <HealthStrip events={[dec(minutesAgo(3))]} decisionSeconds={3600} />);
    expect(screen.getByText(/ultimo ciclo/)).toBeInTheDocument();
    expect(screen.getByText(/riflessioni ok/)).toBeInTheDocument();
    expect(container.querySelector(".dot-warn")).toBeNull();
    expect(container.querySelector(".dot-err")).toBeNull();
  });

  it("degradi in ambra: saltate e riflessione scartata, coi motivi nel title", () => {
    const events: AgentEvent[] = [
      dec(minutesAgo(2), { skipped_count: 3,
        skipped: [{ type: "BUY", symbol: "DOGEUSDT", reason: "coin fuori universo" }] }),
      { timestamp: minutesAgo(5), kind: "reflection", message: "", cycle_id: "c",
        payload: { status: "invalid" } },
    ];
    const { container } = render(<HealthStrip events={events} decisionSeconds={3600} />);
    expect(screen.getByText(/3 saltate oggi/)).toBeInTheDocument();
    expect(screen.getByText(/1 riflessione scartata oggi/)).toBeInTheDocument();
    expect(screen.getByText(/3 saltate oggi/)).toHaveAttribute("title",
      expect.stringContaining("coin fuori universo"));
    expect(container.querySelectorAll(".dot-warn").length).toBeGreaterThan(0);
    expect(container.querySelector(".dot-err")).toBeNull();
  });

  it("rottura in rosso: loop fermo oltre l'intervallo atteso", () => {
    const { container } = render(
      <HealthStrip events={[dec(minutesAgo(120))]} decisionSeconds={3600} />);
    expect(screen.getByText(/loop fermo da/)).toBeInTheDocument();
    expect(container.querySelector(".dot-err")).not.toBeNull();
    expect(container.querySelector(".strip.is-broken")).not.toBeNull();
  });

  it("errori di esecuzione in rosso", () => {
    const { container } = render(
      <HealthStrip events={[dec(minutesAgo(1), { errors: 1 })]} decisionSeconds={3600} />);
    expect(screen.getByText(/1 errore/)).toBeInTheDocument();
    expect(container.querySelector(".dot-err")).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/__tests__/HealthStrip.test.tsx`
Expected: FAIL — modulo inesistente.

- [ ] **Step 3: Implement HealthStrip.tsx**

```tsx
import { useMemo } from "react";
import type { AgentEvent, DecisionPayload, ReflectionPayload, SkippedAction } from "../api";
import { isToday } from "@/lib/format";

/* Parametri vitali della macchina. Tre toni: grigio (normale), ambra (degrado),
   rosso (rottura). Mai verde: quello appartiene al profitto. */

const isDecision = (e: AgentEvent): e is AgentEvent & { payload: DecisionPayload } =>
  e.kind === "decision" && !!e.payload && "status" in e.payload && !("side" in e.payload);
const isReflection = (e: AgentEvent): e is AgentEvent & { payload: ReflectionPayload } =>
  e.kind === "reflection" && !!e.payload && "status" in e.payload;

function Item({ tone, children, title }: {
  tone: "ok" | "warn" | "err"; children: React.ReactNode; title?: string;
}) {
  return (
    <span className="strip-item" title={title}>
      <span className={`dot dot-${tone}`} aria-hidden="true" />
      <span className={tone === "warn" ? "warn-t" : tone === "err" ? "err-t" : undefined}>
        {children}
      </span>
    </span>
  );
}

export function HealthStrip({ events, decisionSeconds }: {
  events: AgentEvent[]; decisionSeconds: number;
}) {
  const s = useMemo(() => {
    const lastDecision = events.find((e) => e.kind === "decision");
    const ageMin = lastDecision
      ? Math.floor((Date.now() - new Date(lastDecision.timestamp).getTime()) / 60000)
      : null;
    const stale = ageMin != null && ageMin * 60 > decisionSeconds * 1.5;

    const today = events.filter((e) => isToday(e.timestamp));
    const badReflections = today.filter(
      (e) => isReflection(e) && e.payload.status !== "ok");
    const decisionsToday = today.filter(isDecision);
    const skipped = decisionsToday.reduce((n, e) => n + (e.payload.skipped_count ?? 0), 0);
    const skipReasons = decisionsToday
      .flatMap((e) => e.payload.skipped ?? [])
      .map((sk: SkippedAction) => `${sk.reason}${sk.symbol ? ` (${sk.symbol.replace(/USDT$/, "")})` : ""}`);
    const errors = decisionsToday.reduce((n, e) => n + (e.payload.errors ?? 0), 0)
      + decisionsToday.filter((e) => e.payload.status === "error").length;
    return { ageMin, stale, badReflections, skipped, skipReasons, errors };
  }, [events, decisionSeconds]);

  const broken = s.stale || s.errors > 0;
  return (
    <div className={`strip${broken ? " is-broken" : ""}`} role="status" aria-label="Salute dell'agente">
      {s.ageMin == null ? (
        <Item tone="ok">nessun ciclo ancora</Item>
      ) : s.stale ? (
        <Item tone="err">loop fermo da {s.ageMin} min <span className="strip-hint">(atteso ogni ~{Math.round(decisionSeconds / 60)} min)</span></Item>
      ) : (
        <Item tone="ok">ultimo ciclo {s.ageMin} min fa</Item>
      )}
      {s.badReflections.length === 0 ? (
        <Item tone="ok">riflessioni ok</Item>
      ) : (
        <Item tone="warn" title={(s.badReflections[0].payload as ReflectionPayload).detail}>
          {s.badReflections.length} {s.badReflections.length === 1 ? "riflessione scartata" : "riflessioni scartate"} oggi
        </Item>
      )}
      <Item tone={s.skipped > 0 ? "warn" : "ok"} title={s.skipReasons.join(" · ") || undefined}>
        {s.skipped} saltate oggi
      </Item>
      <Item tone={s.errors > 0 ? "err" : "ok"}>
        {s.errors} {s.errors === 1 ? "errore" : "errori"}
      </Item>
    </div>
  );
}
```

E in `index.css`:

```css
/* striscia salute: grigio quando tutto va, ambra sui degradi, rosso su rottura. Mai verde. */
.strip {
  display: flex; flex-wrap: wrap; gap: 18px; align-items: center;
  background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 8px 14px; font-size: 12.5px; color: var(--muted-foreground);
}
.strip.is-broken { border-color: color-mix(in srgb, var(--neg) 45%, var(--border)); }
.strip-item { display: inline-flex; align-items: center; gap: 6px; }
.strip .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.strip .dot-ok { background: var(--border); }
.strip .dot-warn { background: var(--warn); }
.strip .dot-err { background: var(--neg); }
.strip .warn-t { color: var(--warn); }
.strip .err-t { color: var(--neg); font-weight: 600; }
.strip-hint { color: var(--muted-foreground); font-weight: 400; }
```

(Le variabili `--warn`, `--neg`, `--warn-bg`, `--neg-bg` esistono già — sono usate da `.badge-*`/`.chip-*`.)

- [ ] **Step 4: Run tests to verify they pass + commit**

Run: `cd frontend && npx vitest run src/__tests__/HealthStrip.test.tsx` → PASS.

```bash
git add frontend/src/components/HealthStrip.tsx frontend/src/__tests__/HealthStrip.test.tsx frontend/src/index.css
git commit -m "feat: health strip with loop liveness, reflections, skips and errors"
```

---

### Task 10: App.tsx — integrazione e cablaggio

**Files:**
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: tutto (Task 6-9).

- [ ] **Step 1: Wire everything**

In `App.tsx`:
1. Import: `HealthStrip`, `ClosedPositionsTable`, `getClosedPositions`, `type ClosedPosition`.
2. Stato: `const [closedPositions, setClosedPositions] = useState<ClosedPosition[]>([]);`
3. Nel `load()` del poll per-agente (dopo `getPositions(...)`): `getClosedPositions(selId).then(setClosedPositions).catch(onErr);` e resetta `setClosedPositions([])` accanto agli altri reset.
4. Striscia salute subito DOPO la `<section>` delle card di sintesi (dopo la riga `</section>` delle Stat):

```tsx
<HealthStrip events={events} decisionSeconds={sel.decision_seconds} />
```

5. Card Posizioni:

```tsx
<PanelHead title="Posizioni" hint="cosa ha in portafoglio adesso, e la vita delle posizioni chiuse" />
<PositionsTable positions={positions} events={events} />
<h3 className="text-xs font-semibold text-muted-foreground mt-5 mb-2 tracking-wide">CHIUSE</h3>
<ClosedPositionsTable closed={closedPositions} />
```

6. Card Attività: `<EventsFeed events={events} policy={memory?.self_policy ?? []} />` (rimuovendo l'eventuale `policy={[]}` provvisorio del Task 7).

- [ ] **Step 2: Typecheck + full frontend suite**

Run: `cd frontend && npm run build && npx vitest run`
Expected: build ok; tutti i test PASS (aggiorna eventuali test App/snapshot rotti dal nuovo markup).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: wire health strip, closed positions and policy tooltips into dashboard"
```

---

### Task 11: Verifica end-to-end locale

**Files:** nessuno nuovo (verifica).

- [ ] **Step 1: Backend completo**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: tutto PASS.

- [ ] **Step 2: Migrazione sul DB di sviluppo**

Con lo stack docker locale attivo (`docker compose up -d db` o come da compose del repo):
`cd backend && .venv/bin/python -m alembic upgrade head`
Expected: applica `a1f2e3d4c5b6` + `b2c3d4e5f6a7` senza errori. Controllo a campione (psql):
`SELECT kind, payload IS NOT NULL FROM events ORDER BY id DESC LIMIT 10;` → payload popolati;
`SELECT symbol, opened_at, invested_usd, realized_usd FROM positions;` → valorizzati per le posizioni con storico trades.

- [ ] **Step 3: Verifica visiva (criteri di successo della spec)**

Avvia backend+frontend locali e verifica sul dashboard, con dati veri:
1. cicli fermi consecutivi → un blocco solo; 2. vendite con % e $ sulla riga; 3. parziale visibile in Attività E su "già incassato"; 4. storico CHIUSE coerente; 5. `grep -rn "RegExp\|\.exec(" frontend/src/components/EventsFeed.tsx` → nessuna regex di parsing message (le uniche regex ammesse: `replace(/USDT$/)` e il match `P\d+`); 6. striscia in testa; 7. verde/rosso solo su P&L e rotture.

- [ ] **Step 4: Commit finale (solo se emergono fix)**

```bash
git add -A && git commit -m "fix: end-to-end polish after local verification"
```

Poi apri la PR verso main (il deploy parte SOLO al merge): titolo `feat: structured events + Attività/Posizioni/salute redesign`.
