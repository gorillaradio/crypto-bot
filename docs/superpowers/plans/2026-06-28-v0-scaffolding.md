# Crypto-Bot v0 ("Scheletro che respira") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Costruire la fetta verticale minima di crypto-bot: un agente legge prezzi reali da Binance, opera in paper-trading con una regola semplice, registra ogni mossa, ed espone stato e storico a una dashboard di monitoraggio.

**Architecture:** Monorepo con backend FastAPI (Python) che gira 24/7 e serve sia l'API REST sia la dashboard React buildata. Uno scheduler interno esegue due lavori periodici per agente: un *battito* (snapshot prezzi + guardrail, no LLM) e una *decisione* (regola semplice → operazioni). Stato e storico in PostgreSQL. La decisione LLM (Claude) e le fonti news NON sono in v0: la regola semplice è un placeholder sostituibile senza toccare il resto.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, httpx (async), APScheduler, Pydantic v2, pytest + pytest-asyncio. PostgreSQL 16. Frontend: Vite + React + TypeScript + shadcn/ui + Recharts. Docker + docker-compose (2 servizi: app + postgres). Test frontend: Vitest + React Testing Library.

## Global Constraints

- **Mai operazioni reali.** Solo paper-trading. Nessuna API key di trading, nessun endpoint Binance autenticato. Si usano solo endpoint pubblici di market data.
- **Matematica del denaro in `Decimal`**, mai `float`. Tutti i campi monetari (cash, prezzi, quantità, fee) usano `decimal.Decimal` in Python e `NUMERIC` in Postgres. Questo è un requisito di correttezza, non stilistico.
- **Valuta interna: USD/USDT.** Coppie Binance in USDT. EUR non è in v0.
- **Capitale iniziale: `100` USD** per agente (costante configurabile via env, default 100).
- **Costi di trading modellati:** fee taker `0.001` (0.1%) + spread bid/ask reale (compra all'ask, vende al bid). Slippage = `0` in v0 (stub documentato: trascurabile su coin liquide a piccole size).
- **Universo investibile:** due preset selezionabili, `TOP_50` / `TOP_100`, derivati per volume 24h da Binance. Default v0: `TOP_100`.
- **Cadenze (configurabili via env per poter "vedere risultati in fretta" in dev):** battito default `300`s (5 min), decisione default `3600`s (1 h). In dev si abbassano per osservare subito le operazioni.
- **Niente segreti nel repo.** Config via `.env` (con `.env.example` versionato).
- **Commit frequenti**, uno per task completato (minimo).

---

## File Structure

```
crypto-bot/
├── docs/
│   └── superpowers/plans/2026-06-28-v0-scaffolding.md
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app, monta API + static frontend, avvia scheduler
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   └── config.py        # Settings (pydantic-settings), legge .env
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── base.py          # engine, Session, Base declarative
│   │   │   └── models.py        # Agent, Position, Trade, EquitySnapshot, Event
│   │   ├── market/
│   │   │   ├── __init__.py
│   │   │   └── binance.py       # client httpx: prezzi, bid/ask, klines, top symbols
│   │   ├── trading/
│   │   │   ├── __init__.py
│   │   │   └── engine.py        # paper-trading: execute_buy/execute_sell con fee+spread
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── strategy.py      # regola semplice (SMA crossover) + guardrail
│   │   │   └── runtime.py       # run_heartbeat() / run_decision() per agente
│   │   ├── scheduler/
│   │   │   ├── __init__.py
│   │   │   └── jobs.py          # APScheduler: registra job battito/decisione
│   │   └── api/
│   │       ├── __init__.py
│   │       ├── schemas.py       # modelli Pydantic di risposta
│   │       └── routes.py        # endpoint REST
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py          # fixture: db di test, agente seed, market fake
│   │   ├── test_health.py
│   │   ├── test_models.py
│   │   ├── test_binance.py
│   │   ├── test_engine.py
│   │   ├── test_strategy.py
│   │   ├── test_runtime.py
│   │   └── test_api.py
│   ├── alembic/                 # migrazioni (alembic init)
│   ├── alembic.ini
│   └── pyproject.toml
├── frontend/                    # Vite + React + TS + shadcn + Recharts
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api.ts               # fetch verso il backend
│   │   ├── components/
│   │   │   ├── EquityChart.tsx
│   │   │   ├── PositionsTable.tsx
│   │   │   └── EventsFeed.tsx
│   │   └── __tests__/EquityChart.test.tsx
│   ├── package.json
│   └── vite.config.ts
├── Dockerfile                   # multi-stage: build frontend → copia in backend → run uvicorn
├── docker-compose.yml           # servizi: app, postgres (volume nominato)
├── .env.example
└── .gitignore
```

**Responsabilità per modulo:**
- `core/config.py` — unica fonte di verità per env/cadenze/costi.
- `db/` — schema persistente; cambia insieme alle migrazioni.
- `market/binance.py` — unico punto che parla con Binance; tutto il resto consuma la sua interfaccia.
- `trading/engine.py` — unica sede della matematica di esecuzione ordini (fee/spread).
- `agents/strategy.py` — la "regola"; punto di innesto futuro per Claude.
- `agents/runtime.py` — orchestrazione di un ciclo; non conosce APScheduler.
- `scheduler/jobs.py` — solo timing; chiama il runtime.
- `api/` — espone lo stato; nessuna logica di trading.

---

## Task 1: Scaffolding progetto + Postgres + health endpoint

**Files:**
- Create: `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/db/base.py`, `docker-compose.yml`, `Dockerfile`, `.env.example`, `.gitignore`
- Test: `backend/tests/__init__.py`, `backend/tests/conftest.py`, `backend/tests/test_health.py`

**Interfaces:**
- Produces: `app.main:app` (FastAPI instance); `app.core.config:settings` (Settings con `database_url`, `initial_capital_usd`, `fee_rate`, `heartbeat_seconds`, `decision_seconds`, `universe_default`); `app.db.base:Base`, `get_session()` (context manager), `engine`.

- [ ] **Step 1: Scrivi `backend/pyproject.toml`**

```toml
[project]
name = "crypto-bot"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.111",
  "uvicorn[standard]>=0.30",
  "sqlalchemy>=2.0",
  "alembic>=1.13",
  "psycopg[binary]>=3.1",
  "httpx>=0.27",
  "apscheduler>=3.10",
  "pydantic>=2.7",
  "pydantic-settings>=2.3",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "respx>=0.21"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Scrivi `backend/app/core/config.py`**

```python
from decimal import Decimal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://crypto:crypto@localhost:5432/crypto"
    initial_capital_usd: Decimal = Decimal("100")
    fee_rate: Decimal = Decimal("0.001")
    heartbeat_seconds: int = 300
    decision_seconds: int = 3600
    universe_default: str = "TOP_100"


settings = Settings()
```

- [ ] **Step 3: Scrivi `backend/app/db/base.py`**

```python
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

- [ ] **Step 4: Scrivi `backend/app/main.py` (solo health per ora)**

```python
from fastapi import FastAPI

app = FastAPI(title="crypto-bot")


@app.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 5: Scrivi `docker-compose.yml`**

```yaml
services:
  app:
    build: .
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      - postgres
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: crypto
      POSTGRES_PASSWORD: crypto
      POSTGRES_DB: crypto
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

- [ ] **Step 6: Scrivi `Dockerfile` (backend-only per ora; lo stage frontend si aggiunge nel Task 8)**

```dockerfile
FROM python:3.12-slim
WORKDIR /srv
COPY backend/pyproject.toml ./backend/
RUN pip install --no-cache-dir ./backend
COPY backend ./backend
WORKDIR /srv/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 7: Scrivi `.env.example` e `.gitignore`**

`.env.example`:
```
DATABASE_URL=postgresql+psycopg://crypto:crypto@postgres:5432/crypto
INITIAL_CAPITAL_USD=100
FEE_RATE=0.001
HEARTBEAT_SECONDS=300
DECISION_SECONDS=3600
UNIVERSE_DEFAULT=TOP_100
```
`.gitignore`:
```
.env
__pycache__/
*.pyc
node_modules/
frontend/dist/
.pytest_cache/
```

- [ ] **Step 8: Scrivi il test `backend/tests/test_health.py`**

```python
from fastapi.testclient import TestClient
from app.main import app


def test_health_returns_ok():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 9: Esegui il test (deve passare)**

Run: `cd backend && pip install -e ".[dev]" && pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add backend docker-compose.yml Dockerfile .env.example .gitignore
git commit -m "feat: scaffold backend, docker-compose with postgres, health endpoint"
```

---

## Task 2: Modelli DB + migrazione

**Files:**
- Create: `backend/app/db/models.py`
- Modify: inizializza `backend/alembic/` (via `alembic init`) e configura `alembic/env.py` per usare `app.db.base.Base` e `settings.database_url`
- Test: `backend/tests/test_models.py`, aggiorna `backend/tests/conftest.py`

**Interfaces:**
- Produces: classi ORM `Agent(id, name, instructions, duration_start, duration_end, status, cash_usd, created_at)`, `Position(id, agent_id, symbol, quantity, avg_price)`, `Trade(id, agent_id, symbol, side, quantity, price, fee, timestamp)`, `EquitySnapshot(id, agent_id, equity_usd, timestamp)`, `Event(id, agent_id, kind, message, timestamp)`. `side` è `"BUY"|"SELL"`. Campi monetari `Numeric`.

- [ ] **Step 1: Scrivi `backend/app/db/models.py`**

```python
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import ForeignKey, Numeric, String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    instructions: Mapped[str] = mapped_column(String, default="")
    duration_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")
    cash_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    universe: Mapped[str] = mapped_column(String(20), default="TOP_100")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    positions: Mapped[list["Position"]] = relationship(back_populates="agent")


class Position(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    symbol: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    avg_price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    agent: Mapped["Agent"] = relationship(back_populates="positions")


class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    symbol: Mapped[str] = mapped_column(String(20))
    side: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    fee: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    equity_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    kind: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
```

- [ ] **Step 2: Scrivi `backend/tests/conftest.py` (db di test con SQLite in-memory per velocità — i tipi Numeric/DateTime sono compatibili)**

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = Session()
    try:
        yield session
    finally:
        session.close()
```

- [ ] **Step 3: Scrivi il test `backend/tests/test_models.py`**

```python
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from app.db.models import Agent, Position


def test_agent_persists_with_decimal_cash(db_session):
    agent = Agent(
        name="Alpha",
        instructions="compra basso vendi alto",
        duration_start=datetime.now(timezone.utc),
        duration_end=datetime.now(timezone.utc) + timedelta(days=7),
        cash_usd=Decimal("100"),
    )
    db_session.add(agent)
    db_session.commit()
    assert agent.id is not None
    assert agent.cash_usd == Decimal("100")


def test_position_links_to_agent(db_session):
    agent = Agent(
        name="Beta", duration_start=datetime.now(timezone.utc),
        duration_end=datetime.now(timezone.utc), cash_usd=Decimal("100"),
    )
    db_session.add(agent)
    db_session.commit()
    pos = Position(agent_id=agent.id, symbol="BTCUSDT",
                   quantity=Decimal("0.001"), avg_price=Decimal("50000"))
    db_session.add(pos)
    db_session.commit()
    assert pos in agent.positions
```

- [ ] **Step 4: Esegui i test (devono passare)**

Run: `cd backend && pytest tests/test_models.py -v`
Expected: PASS (2 test)

- [ ] **Step 5: Inizializza Alembic e genera la migrazione iniziale**

Run:
```bash
cd backend && alembic init alembic
# in alembic/env.py: importa `from app.db.base import Base` e `from app.db import models`,
# imposta target_metadata = Base.metadata e l'url da settings.database_url
alembic revision --autogenerate -m "initial schema"
```
Expected: file di migrazione creato in `alembic/versions/` con le 5 tabelle.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models.py backend/tests backend/alembic backend/alembic.ini
git commit -m "feat: db models (agent, position, trade, equity, event) + initial migration"
```

---

## Task 3: Client market Binance

**Files:**
- Create: `backend/app/market/binance.py`
- Test: `backend/tests/test_binance.py`

**Interfaces:**
- Produces: `class BinanceClient` con metodi async:
  - `async get_price(symbol: str) -> Decimal`
  - `async get_book_ticker(symbol: str) -> tuple[Decimal, Decimal]` → `(bid, ask)`
  - `async get_klines(symbol: str, interval: str, limit: int) -> list[Decimal]` → lista di prezzi di chiusura
  - `async get_top_symbols(quote: str = "USDT", n: int = 100) -> list[str]` → simboli ordinati per `quoteVolume` 24h discendente
- Consuma: nulla del progetto (solo httpx verso `https://api.binance.com`).

- [ ] **Step 1: Scrivi il test `backend/tests/test_binance.py` (usa `respx` per mockare httpx)**

```python
import httpx, respx
from decimal import Decimal
from app.market.binance import BinanceClient

BASE = "https://api.binance.com"


@respx.mock
async def test_get_book_ticker_returns_bid_ask():
    respx.get(f"{BASE}/api/v3/ticker/bookTicker").mock(
        return_value=httpx.Response(200, json={"bidPrice": "100.5", "askPrice": "100.7"})
    )
    client = BinanceClient()
    bid, ask = await client.get_book_ticker("BTCUSDT")
    assert bid == Decimal("100.5")
    assert ask == Decimal("100.7")


@respx.mock
async def test_get_top_symbols_sorted_by_volume_usdt_only():
    respx.get(f"{BASE}/api/v3/ticker/24hr").mock(
        return_value=httpx.Response(200, json=[
            {"symbol": "BTCUSDT", "quoteVolume": "500"},
            {"symbol": "ETHUSDT", "quoteVolume": "900"},
            {"symbol": "FOOBTC", "quoteVolume": "9999"},
        ])
    )
    client = BinanceClient()
    top = await client.get_top_symbols("USDT", 2)
    assert top == ["ETHUSDT", "BTCUSDT"]


@respx.mock
async def test_get_klines_returns_close_prices():
    respx.get(f"{BASE}/api/v3/klines").mock(
        return_value=httpx.Response(200, json=[
            [0, "1", "2", "0.5", "1.5", "10", 0, "0", 0, "0", "0", "0"],
            [0, "1", "2", "0.5", "2.5", "10", 0, "0", 0, "0", "0", "0"],
        ])
    )
    client = BinanceClient()
    closes = await client.get_klines("BTCUSDT", "1h", 2)
    assert closes == [Decimal("1.5"), Decimal("2.5")]
```

- [ ] **Step 2: Esegui i test (devono fallire: modulo assente)**

Run: `cd backend && pytest tests/test_binance.py -v`
Expected: FAIL (ModuleNotFoundError: app.market.binance)

- [ ] **Step 3: Scrivi `backend/app/market/binance.py`**

```python
from decimal import Decimal
import httpx

BASE_URL = "https://api.binance.com"


class BinanceClient:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url

    async def _get(self, path: str, params: dict) -> object:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10) as c:
            resp = await c.get(path, params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_price(self, symbol: str) -> Decimal:
        data = await self._get("/api/v3/ticker/price", {"symbol": symbol})
        return Decimal(data["price"])

    async def get_book_ticker(self, symbol: str) -> tuple[Decimal, Decimal]:
        data = await self._get("/api/v3/ticker/bookTicker", {"symbol": symbol})
        return Decimal(data["bidPrice"]), Decimal(data["askPrice"])

    async def get_klines(self, symbol: str, interval: str, limit: int) -> list[Decimal]:
        data = await self._get(
            "/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit}
        )
        return [Decimal(row[4]) for row in data]  # index 4 = close

    async def get_top_symbols(self, quote: str = "USDT", n: int = 100) -> list[str]:
        data = await self._get("/api/v3/ticker/24hr", {})
        usdt = [d for d in data if d["symbol"].endswith(quote)]
        usdt.sort(key=lambda d: Decimal(d["quoteVolume"]), reverse=True)
        return [d["symbol"] for d in usdt[:n]]
```

- [ ] **Step 4: Esegui i test (devono passare)**

Run: `cd backend && pytest tests/test_binance.py -v`
Expected: PASS (3 test)

- [ ] **Step 5: Commit**

```bash
git add backend/app/market/binance.py backend/tests/test_binance.py
git commit -m "feat: binance market client (price, book ticker, klines, top symbols)"
```

---

## Task 4: Motore paper-trading (fee + spread)

**Files:**
- Create: `backend/app/trading/engine.py`
- Test: `backend/tests/test_engine.py`

**Interfaces:**
- Consuma: modelli `Agent`, `Position`, `Trade`, `Event` (Task 2); `settings.fee_rate` (Task 1).
- Produces:
  - `execute_buy(session, agent, symbol, usd_amount, ask) -> Trade` — compra `usd_amount` di `symbol` all'`ask`, applica fee; scala `agent.cash_usd`; crea/aggiorna `Position` (avg_price ponderato); registra `Trade` ed `Event`. Ritorna il Trade. Solleva `ValueError` se cash insufficiente.
  - `execute_sell(session, agent, symbol, quantity, bid) -> Trade` — vende `quantity` al `bid`, applica fee; accredita cash; riduce/elimina `Position`; registra `Trade` ed `Event`. Solleva `ValueError` se quantità > posseduto.
  - Tutta la matematica in `Decimal`. Slippage = 0 (nessun aggiustamento prezzo).

- [ ] **Step 1: Scrivi il test `backend/tests/test_engine.py`**

```python
import pytest
from decimal import Decimal
from datetime import datetime, timezone
from app.db.models import Agent, Position, Trade
from app.trading.engine import execute_buy, execute_sell


def _agent(session, cash="100"):
    a = Agent(name="T", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc), cash_usd=Decimal(cash))
    session.add(a); session.commit()
    return a


def test_buy_spends_cash_with_fee_and_creates_position(db_session):
    agent = _agent(db_session, "100")
    # compra 50 USD di BTC all'ask 100 → qty lorda 0.5, fee 0.1% sul nozionale
    trade = execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), ask=Decimal("100"))
    # nozionale 50, fee = 50 * 0.001 = 0.05, cash = 100 - 50 - 0.05
    assert agent.cash_usd == Decimal("49.95")
    assert trade.side == "BUY"
    assert trade.fee == Decimal("0.05")
    pos = db_session.query(Position).filter_by(agent_id=agent.id, symbol="BTCUSDT").one()
    assert pos.quantity == Decimal("0.5")
    assert pos.avg_price == Decimal("100")


def test_buy_raises_if_insufficient_cash(db_session):
    agent = _agent(db_session, "10")
    with pytest.raises(ValueError):
        execute_buy(db_session, agent, "BTCUSDT", Decimal("50"), ask=Decimal("100"))


def test_sell_credits_cash_with_fee_and_reduces_position(db_session):
    agent = _agent(db_session, "0")
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("0.5"), avg_price=Decimal("100")))
    db_session.commit()
    # vende 0.5 al bid 200 → nozionale 100, fee 0.1
    trade = execute_sell(db_session, agent, "BTCUSDT", Decimal("0.5"), bid=Decimal("200"))
    assert agent.cash_usd == Decimal("99.9")  # 100 - fee 0.1
    assert trade.side == "SELL"
    remaining = db_session.query(Position).filter_by(agent_id=agent.id, symbol="BTCUSDT").first()
    assert remaining is None  # posizione azzerata → rimossa


def test_sell_raises_if_not_enough_quantity(db_session):
    agent = _agent(db_session, "0")
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("0.1"), avg_price=Decimal("100")))
    db_session.commit()
    with pytest.raises(ValueError):
        execute_sell(db_session, agent, "BTCUSDT", Decimal("0.5"), bid=Decimal("200"))
```

- [ ] **Step 2: Esegui i test (devono fallire: modulo assente)**

Run: `cd backend && pytest tests/test_engine.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Scrivi `backend/app/trading/engine.py`**

```python
from decimal import Decimal
from app.core.config import settings
from app.db.models import Agent, Position, Trade, Event


def _get_position(session, agent_id, symbol):
    return session.query(Position).filter_by(agent_id=agent_id, symbol=symbol).first()


def execute_buy(session, agent: Agent, symbol: str, usd_amount: Decimal, ask: Decimal) -> Trade:
    notional = usd_amount
    fee = notional * settings.fee_rate
    total_cost = notional + fee
    if total_cost > agent.cash_usd:
        raise ValueError("cash insufficiente")
    quantity = notional / ask
    agent.cash_usd = agent.cash_usd - total_cost

    pos = _get_position(session, agent.id, symbol)
    if pos is None:
        pos = Position(agent_id=agent.id, symbol=symbol, quantity=quantity, avg_price=ask)
        session.add(pos)
    else:
        new_qty = pos.quantity + quantity
        pos.avg_price = (pos.avg_price * pos.quantity + ask * quantity) / new_qty
        pos.quantity = new_qty

    trade = Trade(agent_id=agent.id, symbol=symbol, side="BUY",
                  quantity=quantity, price=ask, fee=fee)
    session.add(trade)
    session.add(Event(agent_id=agent.id, kind="trade",
                      message=f"BUY {quantity} {symbol} @ {ask} (fee {fee})"))
    session.commit()
    return trade


def execute_sell(session, agent: Agent, symbol: str, quantity: Decimal, bid: Decimal) -> Trade:
    pos = _get_position(session, agent.id, symbol)
    if pos is None or quantity > pos.quantity:
        raise ValueError("quantità insufficiente")
    notional = quantity * bid
    fee = notional * settings.fee_rate
    agent.cash_usd = agent.cash_usd + (notional - fee)

    pos.quantity = pos.quantity - quantity
    if pos.quantity == 0:
        session.delete(pos)

    trade = Trade(agent_id=agent.id, symbol=symbol, side="SELL",
                  quantity=quantity, price=bid, fee=fee)
    session.add(trade)
    session.add(Event(agent_id=agent.id, kind="trade",
                      message=f"SELL {quantity} {symbol} @ {bid} (fee {fee})"))
    session.commit()
    return trade
```

- [ ] **Step 4: Esegui i test (devono passare)**

Run: `cd backend && pytest tests/test_engine.py -v`
Expected: PASS (4 test)

- [ ] **Step 5: Commit**

```bash
git add backend/app/trading/engine.py backend/tests/test_engine.py
git commit -m "feat: paper-trading engine with fee+spread, Decimal math"
```

---

## Task 5: Regola semplice (SMA crossover) + guardrail

**Files:**
- Create: `backend/app/agents/strategy.py`
- Test: `backend/tests/test_strategy.py`

**Interfaces:**
- Produces:
  - `sma(values: list[Decimal], window: int) -> Decimal | None` — media degli ultimi `window` valori, `None` se insufficienti.
  - `decide_signal(closes: list[Decimal], short: int = 5, long: int = 20) -> str` — ritorna `"BUY"|"SELL"|"HOLD"` confrontando SMA short vs long sull'ultima barra rispetto alla precedente (crossover). BUY su incrocio rialzista, SELL su incrocio ribassista, altrimenti HOLD.
  - `guardrail_action(avg_price: Decimal, last_price: Decimal, stop_loss: Decimal = Decimal("0.10"), take_profit: Decimal = Decimal("0.20")) -> str` — ritorna `"SELL"` se la posizione è sotto di `stop_loss` o sopra di `take_profit` rispetto a `avg_price`, altrimenti `"HOLD"`.
- Nessuna dipendenza dal DB o dalla rete: pura logica, facilmente testabile. **Punto di innesto futuro per Claude** (sostituire `decide_signal`).

- [ ] **Step 1: Scrivi il test `backend/tests/test_strategy.py`**

```python
from decimal import Decimal
from app.agents.strategy import sma, decide_signal, guardrail_action


def test_sma_none_if_insufficient():
    assert sma([Decimal("1"), Decimal("2")], 3) is None


def test_sma_average_of_last_window():
    assert sma([Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")], 2) == Decimal("3.5")


def test_decide_bullish_crossover_returns_buy():
    # short sale sopra long sull'ultima barra dopo essere stata sotto
    closes = [Decimal("10")] * 19 + [Decimal("5"), Decimal("100")]
    assert decide_signal(closes, short=2, long=5) == "BUY"


def test_decide_bearish_crossover_returns_sell():
    closes = [Decimal("10")] * 19 + [Decimal("100"), Decimal("1")]
    assert decide_signal(closes, short=2, long=5) == "SELL"


def test_decide_hold_when_no_cross():
    closes = [Decimal("10")] * 25
    assert decide_signal(closes, short=2, long=5) == "HOLD"


def test_guardrail_sells_on_stop_loss():
    assert guardrail_action(Decimal("100"), Decimal("85")) == "SELL"


def test_guardrail_sells_on_take_profit():
    assert guardrail_action(Decimal("100"), Decimal("125")) == "SELL"


def test_guardrail_holds_within_band():
    assert guardrail_action(Decimal("100"), Decimal("105")) == "HOLD"
```

- [ ] **Step 2: Esegui i test (devono fallire)**

Run: `cd backend && pytest tests/test_strategy.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Scrivi `backend/app/agents/strategy.py`**

```python
from decimal import Decimal


def sma(values: list[Decimal], window: int) -> Decimal | None:
    if len(values) < window:
        return None
    window_vals = values[-window:]
    return sum(window_vals) / Decimal(window)


def decide_signal(closes: list[Decimal], short: int = 5, long: int = 20) -> str:
    if len(closes) < long + 1:
        return "HOLD"
    short_now = sma(closes, short)
    long_now = sma(closes, long)
    short_prev = sma(closes[:-1], short)
    long_prev = sma(closes[:-1], long)
    if None in (short_now, long_now, short_prev, long_prev):
        return "HOLD"
    crossed_up = short_prev <= long_prev and short_now > long_now
    crossed_down = short_prev >= long_prev and short_now < long_now
    if crossed_up:
        return "BUY"
    if crossed_down:
        return "SELL"
    return "HOLD"


def guardrail_action(avg_price: Decimal, last_price: Decimal,
                     stop_loss: Decimal = Decimal("0.10"),
                     take_profit: Decimal = Decimal("0.20")) -> str:
    change = (last_price - avg_price) / avg_price
    if change <= -stop_loss or change >= take_profit:
        return "SELL"
    return "HOLD"
```

- [ ] **Step 4: Esegui i test (devono passare)**

Run: `cd backend && pytest tests/test_strategy.py -v`
Expected: PASS (8 test)

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/strategy.py backend/tests/test_strategy.py
git commit -m "feat: simple SMA-crossover strategy + guardrail (Claude swap point)"
```

---

## Task 6: Runtime agente (battito + decisione)

**Files:**
- Create: `backend/app/agents/runtime.py`, `backend/app/scheduler/jobs.py`
- Test: `backend/tests/test_runtime.py`

**Interfaces:**
- Consuma: `BinanceClient` (Task 3), `execute_buy/execute_sell` (Task 4), `decide_signal/guardrail_action` (Task 5), modelli (Task 2), `settings` (Task 1).
- Produces:
  - `async run_heartbeat(session, agent, market) -> None` — per ogni posizione: prende `last_price`, applica `guardrail_action`; se `SELL`, vende al bid. Poi calcola l'equity (cash + Σ posizioni a last_price) e scrive un `EquitySnapshot`.
  - `async run_decision(session, agent, market, symbols, buy_usd) -> None` — per ogni simbolo: prende `closes` via klines, calcola `decide_signal`; su `BUY` (se cash ≥ buy_usd) compra all'ask; su `SELL` (se posseduto) vende al bid. Registra un `Event` "decision" di sintesi.
  - `market` è un oggetto con l'interfaccia di `BinanceClient` (così nei test si inietta un fake).
- `scheduler/jobs.py` produce: `start_scheduler(app)` che registra job APScheduler a `settings.heartbeat_seconds` e `settings.decision_seconds` iterando sugli agenti `status="running"`.

- [ ] **Step 1: Scrivi il test `backend/tests/test_runtime.py` (market fake, niente rete)**

```python
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.db.models import Agent, Position, EquitySnapshot, Trade
from app.agents.runtime import run_heartbeat, run_decision


class FakeMarket:
    def __init__(self, price, book, closes):
        self._price, self._book, self._closes = price, book, closes
    async def get_price(self, symbol): return self._price
    async def get_book_ticker(self, symbol): return self._book
    async def get_klines(self, symbol, interval, limit): return self._closes


def _agent(session, cash="100"):
    a = Agent(name="R", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal(cash))
    session.add(a); session.commit()
    return a


async def test_heartbeat_writes_equity_snapshot(db_session):
    agent = _agent(db_session, "100")
    market = FakeMarket(price=Decimal("100"), book=(Decimal("99"), Decimal("101")), closes=[])
    await run_heartbeat(db_session, agent, market)
    snap = db_session.query(EquitySnapshot).filter_by(agent_id=agent.id).one()
    assert snap.equity_usd == Decimal("100")  # solo cash, nessuna posizione


async def test_heartbeat_sells_on_stop_loss(db_session):
    agent = _agent(db_session, "0")
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    # last price 80 → -20% → stop loss → vende al bid 80
    market = FakeMarket(price=Decimal("80"), book=(Decimal("80"), Decimal("81")), closes=[])
    await run_heartbeat(db_session, agent, market)
    trades = db_session.query(Trade).filter_by(agent_id=agent.id, side="SELL").all()
    assert len(trades) == 1


async def test_decision_buys_on_bullish_signal(db_session):
    agent = _agent(db_session, "100")
    closes = [Decimal("10")] * 19 + [Decimal("5"), Decimal("100")]
    market = FakeMarket(price=Decimal("100"), book=(Decimal("99"), Decimal("101")), closes=closes)
    await run_decision(db_session, agent, market, symbols=["BTCUSDT"], buy_usd=Decimal("50"))
    buys = db_session.query(Trade).filter_by(agent_id=agent.id, side="BUY").all()
    assert len(buys) == 1
```

- [ ] **Step 2: Esegui i test (devono fallire)**

Run: `cd backend && pytest tests/test_runtime.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Scrivi `backend/app/agents/runtime.py`**

```python
from decimal import Decimal
from app.db.models import EquitySnapshot, Event
from app.trading.engine import execute_buy, execute_sell
from app.agents.strategy import decide_signal, guardrail_action


async def run_heartbeat(session, agent, market) -> None:
    equity = agent.cash_usd
    for pos in list(agent.positions):
        last = await market.get_price(pos.symbol)
        if guardrail_action(pos.avg_price, last) == "SELL":
            bid, _ask = await market.get_book_ticker(pos.symbol)
            execute_sell(session, agent, pos.symbol, pos.quantity, bid)
        else:
            equity += pos.quantity * last
    session.add(EquitySnapshot(agent_id=agent.id, equity_usd=equity))
    session.commit()


async def run_decision(session, agent, market, symbols, buy_usd: Decimal) -> None:
    held = {p.symbol: p for p in agent.positions}
    actions = 0
    for symbol in symbols:
        closes = await market.get_klines(symbol, "1h", 50)
        signal = decide_signal(closes)
        if signal == "BUY" and agent.cash_usd >= buy_usd:
            _bid, ask = await market.get_book_ticker(symbol)
            execute_buy(session, agent, symbol, buy_usd, ask)
            actions += 1
        elif signal == "SELL" and symbol in held:
            bid, _ask = await market.get_book_ticker(symbol)
            execute_sell(session, agent, symbol, held[symbol].quantity, bid)
            actions += 1
    session.add(Event(agent_id=agent.id, kind="decision",
                      message=f"ciclo decisione: {actions} operazioni su {len(symbols)} simboli"))
    session.commit()
```

- [ ] **Step 4: Scrivi `backend/app/scheduler/jobs.py`**

```python
from decimal import Decimal
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.core.config import settings
from app.db.base import get_session
from app.db.models import Agent
from app.market.binance import BinanceClient
from app.agents.runtime import run_heartbeat, run_decision

_scheduler: AsyncIOScheduler | None = None


async def _heartbeat_tick():
    market = BinanceClient()
    with get_session() as session:
        for agent in session.query(Agent).filter_by(status="running").all():
            await run_heartbeat(session, agent, market)


async def _decision_tick():
    market = BinanceClient()
    n = 100 if settings.universe_default == "TOP_100" else 50
    symbols = await market.get_top_symbols("USDT", n)
    with get_session() as session:
        for agent in session.query(Agent).filter_by(status="running").all():
            buy_usd = settings.initial_capital_usd / Decimal("10")
            await run_decision(session, agent, market, symbols, buy_usd)


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(_heartbeat_tick, "interval", seconds=settings.heartbeat_seconds)
    _scheduler.add_job(_decision_tick, "interval", seconds=settings.decision_seconds)
    _scheduler.start()
    return _scheduler
```

- [ ] **Step 5: Esegui i test (devono passare)**

Run: `cd backend && pytest tests/test_runtime.py -v`
Expected: PASS (3 test)

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/runtime.py backend/app/scheduler/jobs.py backend/tests/test_runtime.py
git commit -m "feat: agent runtime (heartbeat+decision) and APScheduler jobs"
```

---

## Task 7: API REST (stato agenti, equity, eventi, create)

**Files:**
- Create: `backend/app/api/schemas.py`, `backend/app/api/routes.py`
- Modify: `backend/app/main.py` (include il router e avvia lo scheduler su startup)
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consuma: modelli (Task 2), `get_session` (Task 1), `start_scheduler` (Task 6).
- Produces endpoint:
  - `POST /api/agents` body `{name, instructions, duration_days}` → crea Agent con `cash_usd = settings.initial_capital_usd`, `duration_start = now`, `duration_end = now + duration_days`. Ritorna l'agente.
  - `GET /api/agents` → lista agenti con `equity` corrente (ultimo snapshot o cash).
  - `GET /api/agents/{id}` → dettaglio: agente, posizioni, ultimo equity.
  - `GET /api/agents/{id}/equity` → lista `{timestamp, equity_usd}` (curva).
  - `GET /api/agents/{id}/events` → ultimi 100 eventi desc.

- [ ] **Step 1: Scrivi il test `backend/tests/test_api.py` (override della dipendenza di sessione sul db di test)**

```python
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from fastapi.testclient import TestClient
from app.main import app
from app.api import routes
from app.db.models import Agent, EquitySnapshot


def _client(db_session):
    app.dependency_overrides[routes.session_dep] = lambda: db_session
    return TestClient(app)


def test_create_agent_starts_with_initial_capital(db_session):
    client = _client(db_session)
    resp = client.post("/api/agents", json={
        "name": "Alpha", "instructions": "x", "duration_days": 7})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Alpha"
    assert Decimal(str(body["cash_usd"])) == Decimal("100")


def test_get_agent_equity_returns_curve(db_session):
    agent = Agent(name="B", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    db_session.add(EquitySnapshot(agent_id=agent.id, equity_usd=Decimal("105")))
    db_session.commit()
    client = _client(db_session)
    resp = client.get(f"/api/agents/{agent.id}/equity")
    assert resp.status_code == 200
    assert resp.json()[0]["equity_usd"] == "105.00000000" or \
           Decimal(resp.json()[0]["equity_usd"]) == Decimal("105")
```

- [ ] **Step 2: Esegui i test (devono fallire)**

Run: `cd backend && pytest tests/test_api.py -v`
Expected: FAIL (ImportError / 404)

- [ ] **Step 3: Scrivi `backend/app/api/schemas.py`**

```python
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel


class AgentCreate(BaseModel):
    name: str
    instructions: str = ""
    duration_days: int = 7


class AgentOut(BaseModel):
    id: int
    name: str
    instructions: str
    status: str
    cash_usd: Decimal
    class Config: from_attributes = True


class EquityPoint(BaseModel):
    timestamp: datetime
    equity_usd: Decimal


class EventOut(BaseModel):
    timestamp: datetime
    kind: str
    message: str
```

- [ ] **Step 4: Scrivi `backend/app/api/routes.py`**

```python
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import Agent, EquitySnapshot, Event
from app.api.schemas import AgentCreate, AgentOut, EquityPoint, EventOut

router = APIRouter(prefix="/api")


def session_dep():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.post("/agents", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
def create_agent(payload: AgentCreate, session=Depends(session_dep)):
    now = datetime.now(timezone.utc)
    agent = Agent(name=payload.name, instructions=payload.instructions,
                  duration_start=now, duration_end=now + timedelta(days=payload.duration_days),
                  cash_usd=settings.initial_capital_usd, universe=settings.universe_default)
    session.add(agent); session.commit(); session.refresh(agent)
    return agent


@router.get("/agents", response_model=list[AgentOut])
def list_agents(session=Depends(session_dep)):
    return session.query(Agent).all()


@router.get("/agents/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: int, session=Depends(session_dep)):
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    return agent


@router.get("/agents/{agent_id}/equity", response_model=list[EquityPoint])
def get_equity(agent_id: int, session=Depends(session_dep)):
    rows = (session.query(EquitySnapshot)
            .filter_by(agent_id=agent_id)
            .order_by(EquitySnapshot.timestamp.asc()).all())
    return rows


@router.get("/agents/{agent_id}/events", response_model=list[EventOut])
def get_events(agent_id: int, session=Depends(session_dep)):
    return (session.query(Event).filter_by(agent_id=agent_id)
            .order_by(Event.timestamp.desc()).limit(100).all())
```

- [ ] **Step 5: Aggiorna `backend/app/main.py`**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.routes import router
from app.scheduler.jobs import start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield


app = FastAPI(title="crypto-bot", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 6: Esegui i test (devono passare)**

Run: `cd backend && pytest -v`
Expected: PASS (tutti i test del backend)

- [ ] **Step 7: Commit**

```bash
git add backend/app/api backend/app/main.py backend/tests/test_api.py
git commit -m "feat: REST API (agents CRUD-lite, equity curve, events) + scheduler on startup"
```

---

## Task 8: Dashboard React + servire da FastAPI

**Files:**
- Create: `frontend/` (Vite + React + TS + shadcn), `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/components/{EquityChart,PositionsTable,EventsFeed}.tsx`, `frontend/src/__tests__/EquityChart.test.tsx`
- Modify: `Dockerfile` (aggiunge stage di build frontend), `backend/app/main.py` (monta i file statici)
- Test: `frontend/src/__tests__/EquityChart.test.tsx`

**Interfaces:**
- Consuma: API del Task 7.
- Produces: SPA che mostra lista agenti, curva equity (Recharts), tabella posizioni, feed eventi.

- [ ] **Step 1: Inizializza il frontend**

Run:
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install && npm install recharts
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
# inizializza shadcn/ui seguendo la guida ufficiale (tailwind + components.json)
npx shadcn@latest init
```

- [ ] **Step 2: Scrivi `frontend/src/api.ts`**

```ts
const BASE = import.meta.env.VITE_API_BASE ?? "";

export type EquityPoint = { timestamp: string; equity_usd: string };
export type AgentEvent = { timestamp: string; kind: string; message: string };
export type Agent = { id: number; name: string; status: string; cash_usd: string };

export async function getAgents(): Promise<Agent[]> {
  return (await fetch(`${BASE}/api/agents`)).json();
}
export async function getEquity(id: number): Promise<EquityPoint[]> {
  return (await fetch(`${BASE}/api/agents/${id}/equity`)).json();
}
export async function getEvents(id: number): Promise<AgentEvent[]> {
  return (await fetch(`${BASE}/api/agents/${id}/events`)).json();
}
```

- [ ] **Step 3: Scrivi `frontend/src/components/EquityChart.tsx`**

```tsx
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import type { EquityPoint } from "../api";

export function EquityChart({ data }: { data: EquityPoint[] }) {
  const points = data.map((d) => ({
    t: new Date(d.timestamp).toLocaleString(),
    equity: Number(d.equity_usd),
  }));
  return (
    <div data-testid="equity-chart" style={{ width: "100%", height: 320 }}>
      <ResponsiveContainer>
        <LineChart data={points}>
          <XAxis dataKey="t" hide />
          <YAxis domain={["auto", "auto"]} />
          <Tooltip />
          <Line type="monotone" dataKey="equity" dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 4: Scrivi il test `frontend/src/__tests__/EquityChart.test.tsx`**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { EquityChart } from "../components/EquityChart";

describe("EquityChart", () => {
  it("renders the chart container with data", () => {
    render(<EquityChart data={[{ timestamp: "2026-06-28T00:00:00Z", equity_usd: "100" }]} />);
    expect(screen.getByTestId("equity-chart")).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Scrivi `PositionsTable.tsx`, `EventsFeed.tsx`, `App.tsx`**

`PositionsTable.tsx`:
```tsx
export function PositionsTable({ cash }: { cash: string }) {
  return (
    <div>
      <h3>Cash</h3>
      <p>{Number(cash).toFixed(2)} USD</p>
    </div>
  );
}
```
`EventsFeed.tsx`:
```tsx
import type { AgentEvent } from "../api";
export function EventsFeed({ events }: { events: AgentEvent[] }) {
  return (
    <ul>
      {events.map((e, i) => (
        <li key={i}>
          <small>{new Date(e.timestamp).toLocaleString()}</small> — [{e.kind}] {e.message}
        </li>
      ))}
    </ul>
  );
}
```
`App.tsx`:
```tsx
import { useEffect, useState } from "react";
import { getAgents, getEquity, getEvents, type Agent, type EquityPoint, type AgentEvent } from "./api";
import { EquityChart } from "./components/EquityChart";
import { PositionsTable } from "./components/PositionsTable";
import { EventsFeed } from "./components/EventsFeed";

export default function App() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [equity, setEquity] = useState<EquityPoint[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);

  useEffect(() => { getAgents().then(setAgents); }, []);
  useEffect(() => {
    if (!agents.length) return;
    const id = agents[0].id;
    const tick = () => { getEquity(id).then(setEquity); getEvents(id).then(setEvents); };
    tick();
    const h = setInterval(tick, 30000);
    return () => clearInterval(h);
  }, [agents]);

  return (
    <main style={{ maxWidth: 900, margin: "2rem auto" }}>
      <h1>crypto-bot</h1>
      {agents[0] && <PositionsTable cash={agents[0].cash_usd} />}
      <EquityChart data={equity} />
      <h3>Eventi</h3>
      <EventsFeed events={events} />
    </main>
  );
}
```

- [ ] **Step 6: Esegui il test frontend (deve passare)**

Run: `cd frontend && npx vitest run`
Expected: PASS (1 test)

- [ ] **Step 7: Aggiorna `Dockerfile` (multi-stage) e fai servire la build da FastAPI**

```dockerfile
FROM node:20-slim AS frontend
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm install
COPY frontend ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /srv
COPY backend/pyproject.toml ./backend/
RUN pip install --no-cache-dir ./backend
COPY backend ./backend
COPY --from=frontend /fe/dist ./backend/static
WORKDIR /srv/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```
In `backend/app/main.py` aggiungi (dopo `include_router`), servendo la SPA se la cartella esiste:
```python
import os
from fastapi.staticfiles import StaticFiles
_static = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(_static):
    app.mount("/", StaticFiles(directory=_static, html=True), name="static")
```

- [ ] **Step 8: Verifica end-to-end manuale**

Run:
```bash
cp .env.example .env
docker compose up --build -d
# applica le migrazioni dentro il container app:
docker compose exec app alembic upgrade head
# crea un agente e abbassa le cadenze in .env per vedere subito le operazioni
curl -X POST localhost:8000/api/agents -H 'content-type: application/json' \
  -d '{"name":"Alpha","instructions":"test","duration_days":7}'
# apri http://localhost:8000 e verifica che la dashboard mostri l'agente,
# la curva equity che si popola e il feed eventi.
```
Expected: dashboard raggiungibile, agente creato, snapshot equity che compaiono, eventi "decision"/"trade" nel feed.

- [ ] **Step 9: Commit**

```bash
git add frontend Dockerfile backend/app/main.py
git commit -m "feat: react+shadcn dashboard (equity chart, positions, events) served by FastAPI"
```

---

## Self-Review

**Spec coverage** (vs decisioni in memoria/north-star):
- Legge mercato reale → Task 3 (Binance). ✅
- Opera con regola semplice → Task 5 + Task 6. ✅
- Costi fee+spread, Decimal, slippage=0 → Task 4 + Global Constraints. ✅
- Universo top50/100 → `settings.universe_default` + Task 6. ✅ (preset; selezione per-agente in UI = fase futura, coerente coi "default ora, configurabili dopo")
- Cadenza battito/decisione configurabile → Task 1 (env) + Task 6 (APScheduler). ✅
- Modello agente minimale (nome, durata, istruzioni + stato) → Task 2 + Task 7. ✅
- "Notifica" v0 = feed eventi → Task 6 (Event) + Task 8 (EventsFeed). ✅
- Monitoraggio dashboard → Task 8. ✅
- Persistenza base su Postgres con volume → Task 1 + Task 2. ✅
- Claude/news ESCLUSI dalla v0 → `strategy.py` documentato come punto d'innesto. ✅ (coerente)
- Benchmark (S&P/NVDA) NON in v0 → coerente col parcheggio del punto 4. ✅

**Note / debiti conosciuti (accettati per v0):**
- `conftest.py` usa SQLite per i test (veloce); la produzione usa Postgres. I tipi `Numeric`/`DateTime(timezone=True)` sono compatibili; differenze sottili (es. precisione) restano sotto controllo perché la matematica è in `Decimal` lato Python.
- Selezione universo/cadenza per-agente via UI è fuori v0 (default da env), come deciso.
- Nessuna gestione "deploy durante run" / archiviazione agenti: parcheggiati come da decisioni.

**Placeholder scan:** nessun "TBD"/"handle edge cases" generico; ogni step di codice contiene codice reale.

**Type consistency:** `side` è sempre `"BUY"/"SELL"`; `decide_signal`→`"BUY"/"SELL"/"HOLD"`; firme di `execute_buy/execute_sell` coerenti tra Task 4, 6 e i test; `market` fake espone gli stessi metodi di `BinanceClient`.
