# Ingestion news (Pipeline v2 — Fase 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring real information into the decision prompt — a new `Observation` table stores normalized crypto-news headlines tagged with the coins they mention; a polling job reads crypto-native RSS feeds every ~15 min, deduplicates, tags by symbol, and persists; each agent's decision prompt gains a compact, capped "Recent crypto news" section filtered to its universe.

**Architecture:** A new append-only table `Observation` (one row per news item: `source`, `kind`, `title`, `url`, `symbols_json`, `dedup_hash`, `published_at`). A new package `app/feeds/` owns everything news-specific: `rss.py` (fetch feeds over httpx + parse with feedparser → `FeedItem`s), `symbols.py` (pure text→coin matcher over a curated term map), `ingest.py` (dedup + match + insert `Observation`s), `query.py` (recent observations filtered to an agent's universe → `ObservationView`s). A 4th global scheduler tick (`_news_poll_tick`) mirrors `_scoring_tick`: it runs the ingestion and is self-isolating — a feed error never breaks the scheduler. The decision path is extended exactly the way Fase 3 added memory: `DecisionContext` gains an `observations` field, `build_context` a keyword, `render_prompt` a conditional section, and `build_agent_context` queries the DB and passes the list in. Prompt shape is otherwise frozen. Backend-only (no dashboard in v1).

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (typed `Mapped`), Alembic, httpx (already a dep), **feedparser (new dep)**, APScheduler, pytest (SQLite in-memory via `conftest.db_session`, httpx mocked via `respx`). No LLM is involved in Fase 4 — the relevance filter is pure string matching, by committente decision.

## Global Constraints

- **Branch:** all work continues on the long-lived `pipeline-v2` branch. Never commit to `main`, never push, no PR until the user explicitly asks. (Auto-deploy runs on push to `main`; nothing reaches prod until the final merge of all 6 phases — intended, paper trading.)
- **Alembic head is `945d65d0ab6f`** (`drop_agent_memory`). This plan adds **one** migration: `down_revision = '945d65d0ab6f'`, creating `observations`.
- **Tests never run migrations** — `conftest.db_session` builds tables with `Base.metadata.create_all`. A new model is testable the moment `app/db/models.py` changes. The migration is a hand-written mirror of the model, verified separately against a throwaway SQLite DB in Task 9.
- **Match existing style:** long-text columns use bare `String` (no length), like `Event.message`. Lists of symbols are stored as a JSON string in a `String` column, exactly like `BenchmarkBasis.universe_json`. Timestamps are `DateTime(timezone=True), default=_now` (Python-side default; every insert goes through the ORM). A uniqueness guard mirrors `ShareLink.token` (`unique=True, index=True`).
- **Source = crypto-native RSS, single source for v1 (committente decision, 2026-07-03):** CoinDesk + Cointelegraph + CryptoSlate public feeds. NewsData.io was rejected (12-hour delay on the free tier + paywall-trap risk). A dedicated macro feed / GDELT is explicitly deferred — the macro that moves crypto arrives through the crypto outlets' own Policy/Markets coverage. Adding a second source later is a localized change behind the adapter.
- **Relevance filter = pure symbol match, no LLM (committente decision):** match a coin's **name** and **ticker** (the base asset `BTC`, never the trading pair `BTCUSDT`) in the item's title+summary text. Market-wide items that name no coin are **kept** as no-symbol observations — that is where the macro lives.
- **Polling ~15 min:** `news_poll_seconds` default `900`, mirroring `scoring_seconds`.
- **Failure isolation is mandatory:** `_news_poll_tick` wraps its work in try/except + `session.rollback()` and logs, exactly like `_scoring_tick`. One dead feed inside a poll is skipped without sinking the others.
- **Retention: keep everything.** No TTL, no pruning (matches Fase 1's "keep everything" decision; volumes are tiny). The prompt only ever reads the most-recent handful, so table growth never bloats the prompt.
- **SQLite naive-datetime gotcha:** `recent_observations_for` selects and orders by `published_at` in SQL and never compares datetimes in Python, so it sidesteps the naive/aware mismatch that `app/eval/scoring_job.py` guards against with `_as_utc`. Do not add a Python-side time-window filter.
- **New dependency:** `feedparser>=6.0` added to `backend/pyproject.toml` `[project].dependencies`. It is pure-python, ubiquitous, and handles the RSS/Atom/date/namespace variance across the three outlets far more robustly than hand-rolled `xml.etree`. It is only ever fed strings we already fetched via httpx (so tests stay offline via `respx`).

## Design decisions locked with committente (2026-07-03)

1. **Provider:** crypto-native RSS (CoinDesk, Cointelegraph, CryptoSlate). Not NewsData.io (stale + trap), not GDELT (generalist; deferred). One source for v1.
2. **Schema:** related symbols as a JSON-encoded list in a `String` column (`symbols_json`); dedup by a SHA-256 hash of the item URL (fallback `source|title` when URL is absent); keep-all retention.
3. **Prompt:** a new conditional "Recent crypto news" section, up to `RECENT_OBS_LIMIT` (12) most-recent matching items, one line each (`date · source · title [symbols|market]`), title truncated for a soft token cap. Omitted entirely when empty. Prompt shape otherwise frozen.
4. **Filter:** name + base-ticker text match; market-wide (no-symbol) items kept.
5. **Adapter home:** `app/feeds/`; global 15-min tick; dedup on re-poll via the unique `dedup_hash`; failure-isolated tick.

## Branch & Setup

Before Task 1:

```bash
cd /Users/seb/Dev/gorillaradio/crypto-bot
git switch pipeline-v2                              # already exists; Fasi 1–3 are here
git status                                          # expect: clean
cd backend && .venv/bin/python -m pytest -q          # sanity: 188 green before we start
cd ../frontend && npx vitest run                     # sanity: 41 green (frontend untouched this phase)
```

Baseline: **188 backend tests green**, **41 frontend tests green**, Alembic head `945d65d0ab6f`, working tree clean.

> All backend commands below use the venv interpreter explicitly: `.venv/bin/python`, `.venv/bin/pytest`, `.venv/bin/alembic`, `.venv/bin/pip` (run from `backend/`).

---

## Part A — `Observation` table (foundation; additive)

### Task 1: `Observation` model + migration (create)

**Files:**
- Modify: `backend/app/db/models.py` (append `Observation`)
- Create: `backend/alembic/versions/<generated>_observations.py`
- Test: `backend/tests/test_models.py` (append two tests)

**Interfaces:**
- Produces `app.db.models.Observation`: `id:int, source:str(60), kind:str(20, default "news"), title:str, url:str|None, symbols_json:str(default "[]"), dedup_hash:str(64, unique, indexed), published_at:datetime(indexed), created_at:datetime(default _now, indexed)`. `dedup_hash` carries the only uniqueness guard.

- [ ] **Step 1: Write the failing model tests**

Append to `backend/tests/test_models.py` (top already imports `datetime, timezone, timedelta`, `Decimal`, and `Agent`):

```python
def test_observation_persists_with_defaults(db_session):
    from app.db.models import Observation
    obs = Observation(source="CoinDesk", title="Bitcoin ETF sees record inflows",
                      url="https://x/1", dedup_hash="h1",
                      published_at=datetime(2026, 7, 3, 10, 30, tzinfo=timezone.utc))
    db_session.add(obs); db_session.commit(); db_session.refresh(obs)
    assert obs.id is not None and obs.created_at is not None
    assert obs.kind == "news"            # default kind
    assert obs.symbols_json == "[]"      # default: market-wide until tagged


def test_observation_dedup_hash_is_unique(db_session):
    from app.db.models import Observation
    import pytest
    from sqlalchemy.exc import IntegrityError
    now = datetime(2026, 7, 3, 10, 30, tzinfo=timezone.utc)
    db_session.add(Observation(source="CoinDesk", title="a", dedup_hash="dup", published_at=now))
    db_session.commit()
    db_session.add(Observation(source="Cointelegraph", title="b", dedup_hash="dup", published_at=now))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_models.py -q`
Expected: FAIL with `ImportError: cannot import name 'Observation'`.

- [ ] **Step 3: Add the model**

Append to `backend/app/db/models.py` (imports already include `String`, `DateTime`, `ForeignKey`, `Boolean`, `Integer`; `_now` is defined at the top):

```python
class Observation(Base):
    __tablename__ = "observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(60))                    # e.g. "CoinDesk"
    kind: Mapped[str] = mapped_column(String(20), default="news")      # "news" | "market_signal" (v2)
    title: Mapped[str] = mapped_column(String)                         # normalized headline
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    symbols_json: Mapped[str] = mapped_column(String, default="[]")    # JSON list of base symbols; "[]" = market-wide
    dedup_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_models.py -q`
Expected: PASS (existing model tests + the two new ones).

- [ ] **Step 5: Generate the migration skeleton**

Run: `cd backend && .venv/bin/alembic revision -m "observations"`
Expected: creates `backend/alembic/versions/<hash>_observations.py` with `down_revision = '945d65d0ab6f'` prefilled (it is the current head). If it is NOT prefilled to `945d65d0ab6f`, set it by hand.

- [ ] **Step 6: Fill in the migration (DDL mirror of the model; no backfill — new table)**

Replace the generated `upgrade()`/`downgrade()` bodies:

```python
def upgrade() -> None:
    op.create_table(
        "observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("symbols_json", sa.String(), nullable=False),
        sa.Column("dedup_hash", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_observations_dedup_hash", "observations", ["dedup_hash"], unique=True)
    op.create_index("ix_observations_published_at", "observations", ["published_at"])
    op.create_index("ix_observations_created_at", "observations", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_observations_created_at", table_name="observations")
    op.drop_index("ix_observations_published_at", table_name="observations")
    op.drop_index("ix_observations_dedup_hash", table_name="observations")
    op.drop_table("observations")
```

- [ ] **Step 7: Verify the migration head is single and current**

Run: `cd backend && .venv/bin/alembic heads`
Expected: exactly one head — the new `<hash>` (observations). (Full upgrade/downgrade smoke-test is Task 9.)

- [ ] **Step 8: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/*_observations.py backend/tests/test_models.py
git commit -m "feat(db): Observation table (news/market_signal) + migration"
```

---

## Part B — Feed adapter + symbol matcher (pure units; no DB, no wiring)

### Task 2: symbol matcher (`app/feeds/symbols.py`)

**Files:**
- Create: `backend/app/feeds/__init__.py` (empty package marker)
- Create: `backend/app/feeds/symbols.py`
- Test: `backend/tests/test_feeds_symbols.py`

**Interfaces:**
- Produces `app.feeds.symbols.match_symbols(text: str) -> list[str]` — returns the sorted list of base symbols whose name/ticker appears in `text` (case-insensitive, word-boundary). Empty list = no coin named (market-wide).
- Produces `app.feeds.symbols.COIN_TERMS: dict[str, list[str]]` — base symbol → lowercase match terms. Extensible; precision-favoring (ambiguous bare tickers omitted, name-only).

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_feeds_symbols.py`)

```python
from app.feeds.symbols import match_symbols


def test_matches_coin_name_and_safe_ticker():
    assert match_symbols("Bitcoin ETF sees record inflows") == ["BTC"]
    assert match_symbols("BTC breaks 100k") == ["BTC"]


def test_matches_multiple_and_sorts():
    assert match_symbols("Ethereum and Solana lead the rally") == ["ETH", "SOL"]


def test_market_wide_headline_matches_nothing():
    assert match_symbols("Crypto market sheds $200B after Fed holds rates") == []


def test_word_boundary_avoids_false_positive():
    # "solar" must not match SOL; "nearest" must not match NEAR
    assert match_symbols("New solar mining farm opens; nearest grid strained") == []


def test_case_insensitive_and_empty_text():
    assert match_symbols("ethereum upgrade") == ["ETH"]
    assert match_symbols("") == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_feeds_symbols.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.feeds'`.

- [ ] **Step 3: Create the package marker and the matcher**

Create empty `backend/app/feeds/__init__.py`.

Create `backend/app/feeds/symbols.py`:

```python
import re

# base symbol -> lowercase match terms. Names are high-precision and always included.
# A bare ticker is added ONLY when it is not a common English word (BTC/ETH/XRP/…);
# ambiguous tickers (SOL/OP/NEAR/TON/UNI/LINK/DOT/…) are matched by name only.
# Extend this map as the universe grows; every new entry deserves a precision test.
COIN_TERMS: dict[str, list[str]] = {
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "ether", "eth"],
    "SOL": ["solana"],
    "XRP": ["xrp", "ripple"],
    "BNB": ["bnb"],
    "ADA": ["cardano", "ada"],
    "DOGE": ["dogecoin"],
    "AVAX": ["avalanche", "avax"],
    "LINK": ["chainlink"],
    "MATIC": ["polygon", "matic"],
    "POL": ["polygon"],
    "DOT": ["polkadot"],
    "TRX": ["tron", "trx"],
    "LTC": ["litecoin", "ltc"],
    "SHIB": ["shiba inu", "shib"],
    "UNI": ["uniswap"],
    "ATOM": ["cosmos", "atom"],
    "XLM": ["stellar", "xlm"],
    "NEAR": ["near protocol"],
    "APT": ["aptos", "apt"],
    "ARB": ["arbitrum", "arb"],
    "OP": ["optimism"],
    "SUI": ["sui network"],
    "TON": ["toncoin"],
    "XMR": ["monero", "xmr"],
    "AAVE": ["aave"],
    "MKR": ["maker dao", "makerdao"],
    "INJ": ["injective"],
    "FIL": ["filecoin"],
    "HBAR": ["hedera", "hbar"],
}


def match_symbols(text: str) -> list[str]:
    t = (text or "").lower()
    hits: list[str] = []
    for base, terms in COIN_TERMS.items():
        for term in terms:
            if re.search(r"\b" + re.escape(term) + r"\b", t):
                hits.append(base)
                break
    return sorted(hits)
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_feeds_symbols.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/feeds/__init__.py backend/app/feeds/symbols.py backend/tests/test_feeds_symbols.py
git commit -m "feat(feeds): pure symbol matcher (name+safe-ticker, market-wide = empty)"
```

### Task 3: RSS adapter (`app/feeds/rss.py`) + feedparser dependency

**Files:**
- Modify: `backend/pyproject.toml` (add `feedparser>=6.0` to `[project].dependencies`)
- Create: `backend/app/feeds/rss.py`
- Test: `backend/tests/test_feeds_rss.py`

**Interfaces:**
- Produces `app.feeds.rss.FeedItem` (dataclass): `source:str, title:str, url:str|None, summary:str, published_at:datetime`.
- Produces `app.feeds.rss.parse_feed(source: str, xml: str) -> list[FeedItem]` — pure; items with no parseable date are skipped (deterministic).
- Produces `app.feeds.rss.DEFAULT_FEEDS: list[tuple[str, str]]` — `(source_label, url)` for the three outlets.
- Produces `app.feeds.rss.RssFeedAdapter(feeds=DEFAULT_FEEDS, timeout=10)` with `async fetch(self) -> list[FeedItem]` — fetches each feed over httpx; a feed that errors is skipped, the rest still return.

- [ ] **Step 1: Install feedparser into the venv and add the dependency**

Run: `cd backend && .venv/bin/pip install "feedparser>=6.0"`
Then edit `backend/pyproject.toml`, adding one line inside `[project].dependencies` (after `"apscheduler>=3.10",`):

```toml
  "feedparser>=6.0",
```

- [ ] **Step 2: Write the failing tests** (`backend/tests/test_feeds_rss.py`)

```python
import httpx, respx
from datetime import timezone
from app.feeds.rss import parse_feed, RssFeedAdapter, FeedItem

RSS_A = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>CoinDesk</title>
<item><title>Bitcoin ETF sees record inflows</title><link>https://a/1</link>
<pubDate>Fri, 03 Jul 2026 10:30:00 +0000</pubDate><description>BTC up</description></item>
<item><title>Solana network upgrade goes live</title><link>https://a/2</link>
<pubDate>Fri, 03 Jul 2026 09:00:00 +0000</pubDate><description>SOL news</description></item>
</channel></rss>"""

RSS_NO_DATE = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>X</title>
<item><title>No date here</title><link>https://a/3</link></item>
</channel></rss>"""


def test_parse_feed_extracts_items():
    items = parse_feed("CoinDesk", RSS_A)
    assert [i.title for i in items] == ["Bitcoin ETF sees record inflows",
                                        "Solana network upgrade goes live"]
    assert items[0].source == "CoinDesk" and items[0].url == "https://a/1"
    assert items[0].published_at.tzinfo is not None
    assert items[0].published_at.astimezone(timezone.utc).hour == 10


def test_parse_feed_skips_undated_items():
    assert parse_feed("X", RSS_NO_DATE) == []


@respx.mock
async def test_fetch_aggregates_all_feeds():
    respx.get("https://feed-a/").mock(return_value=httpx.Response(200, text=RSS_A))
    respx.get("https://feed-b/").mock(return_value=httpx.Response(200, text=RSS_A))
    adapter = RssFeedAdapter(feeds=[("A", "https://feed-a/"), ("B", "https://feed-b/")])
    items = await adapter.fetch()
    assert len(items) == 4                      # 2 per feed
    assert {i.source for i in items} == {"A", "B"}


@respx.mock
async def test_fetch_skips_a_broken_feed():
    respx.get("https://ok/").mock(return_value=httpx.Response(200, text=RSS_A))
    respx.get("https://down/").mock(return_value=httpx.Response(503))
    adapter = RssFeedAdapter(feeds=[("OK", "https://ok/"), ("DOWN", "https://down/")])
    items = await adapter.fetch()
    assert len(items) == 2 and {i.source for i in items} == {"OK"}   # broken feed skipped, other survives
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_feeds_rss.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.feeds.rss'`.

- [ ] **Step 4: Write the adapter** (`backend/app/feeds/rss.py`)

```python
from dataclasses import dataclass
from datetime import datetime, timezone
import httpx
import feedparser


@dataclass
class FeedItem:
    source: str
    title: str
    url: str | None
    summary: str
    published_at: datetime


# (source label, feed url) — crypto-native, single source for v1. Macro arrives via these outlets.
DEFAULT_FEEDS: list[tuple[str, str]] = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("CryptoSlate", "https://cryptoslate.com/feed/"),
]


def _entry_time(entry) -> datetime | None:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if t is None:
        return None
    return datetime(*t[:6], tzinfo=timezone.utc)


def parse_feed(source: str, xml: str) -> list[FeedItem]:
    parsed = feedparser.parse(xml)
    out: list[FeedItem] = []
    for e in parsed.entries:
        when = _entry_time(e)
        if when is None:
            continue                                  # undated → cannot place in time, skip
        out.append(FeedItem(
            source=source,
            title=(e.get("title") or "").strip(),
            url=e.get("link"),
            summary=(e.get("summary") or "").strip(),
            published_at=when,
        ))
    return out


class RssFeedAdapter:
    def __init__(self, feeds: list[tuple[str, str]] = DEFAULT_FEEDS, timeout: int = 10):
        self.feeds = feeds
        self.timeout = timeout

    async def fetch(self) -> list[FeedItem]:
        items: list[FeedItem] = []
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            for source, url in self.feeds:
                try:
                    resp = await c.get(url)
                    resp.raise_for_status()
                except Exception:
                    continue                          # one dead feed never sinks the batch
                items.extend(parse_feed(source, resp.text))
        return items
```

- [ ] **Step 5: Run to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_feeds_rss.py -q`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/app/feeds/rss.py backend/tests/test_feeds_rss.py
git commit -m "feat(feeds): RSS adapter (httpx fetch + feedparser parse, per-feed failure isolation)"
```

---

## Part C — Ingestion job + scheduler tick

### Task 4: ingestion job (`app/feeds/ingest.py`)

**Files:**
- Create: `backend/app/feeds/ingest.py`
- Test: `backend/tests/test_feeds_ingest.py`

**Interfaces:**
- Consumes `RssFeedAdapter.fetch()` → `list[FeedItem]` (Task 3), `match_symbols` (Task 2), `Observation` (Task 1).
- Produces `app.feeds.ingest.dedup_hash(item: FeedItem) -> str` — SHA-256 hex of `item.url`, or of `f"{item.source}|{item.title}"` when url is falsy.
- Produces `app.feeds.ingest.ingest_observations(session, adapter) -> int` (async) — fetches, dedups (in-batch set + DB `dedup_hash` lookup), tags via `match_symbols(title+" "+summary)`, inserts `Observation(kind="news", …)`, commits, returns the count of new rows.

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_feeds_ingest.py`)

```python
from datetime import datetime, timezone
import json
from app.db.models import Observation
from app.feeds.rss import FeedItem
from app.feeds.ingest import ingest_observations


class FakeAdapter:
    def __init__(self, items): self._items = items
    async def fetch(self): return list(self._items)


def _item(title, url, summary="", src="CoinDesk", h=10):
    return FeedItem(source=src, title=title, url=url, summary=summary,
                    published_at=datetime(2026, 7, 3, h, 0, tzinfo=timezone.utc))


async def test_ingest_inserts_and_tags_symbols(db_session):
    adapter = FakeAdapter([
        _item("Bitcoin ETF sees record inflows", "https://a/1"),
        _item("Fed holds rates, crypto slips", "https://a/2"),      # market-wide → no symbol
    ])
    n = await ingest_observations(db_session, adapter)
    assert n == 2
    btc = db_session.query(Observation).filter_by(url="https://a/1").one()
    assert json.loads(btc.symbols_json) == ["BTC"] and btc.kind == "news"
    macro = db_session.query(Observation).filter_by(url="https://a/2").one()
    assert json.loads(macro.symbols_json) == []                     # kept as market-wide


async def test_ingest_is_idempotent_across_repolls(db_session):
    adapter = FakeAdapter([_item("Solana upgrade", "https://a/9")])
    assert await ingest_observations(db_session, adapter) == 1
    assert await ingest_observations(db_session, adapter) == 0       # same url → deduped
    assert db_session.query(Observation).count() == 1


async def test_ingest_dedups_within_one_batch(db_session):
    adapter = FakeAdapter([_item("Same", "https://a/x"), _item("Same", "https://a/x")])
    assert await ingest_observations(db_session, adapter) == 1
    assert db_session.query(Observation).count() == 1


async def test_ingest_hashes_on_source_title_when_url_missing(db_session):
    adapter = FakeAdapter([_item("Untitled link", None), _item("Untitled link", None)])
    assert await ingest_observations(db_session, adapter) == 1       # identical source+title → one row
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_feeds_ingest.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.feeds.ingest'`.

- [ ] **Step 3: Write the ingestion job** (`backend/app/feeds/ingest.py`)

```python
import hashlib
import json
from app.db.models import Observation
from app.feeds.symbols import match_symbols


def dedup_hash(item) -> str:
    basis = item.url or f"{item.source}|{item.title}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


async def ingest_observations(session, adapter) -> int:
    items = await adapter.fetch()
    seen: set[str] = set()
    written = 0
    for item in items:
        h = dedup_hash(item)
        if h in seen:
            continue                                          # in-batch duplicate
        seen.add(h)
        if session.query(Observation).filter_by(dedup_hash=h).first():
            continue                                          # already stored on a prior poll
        symbols = match_symbols(f"{item.title} {item.summary}")
        session.add(Observation(
            source=item.source, kind="news", title=item.title, url=item.url,
            symbols_json=json.dumps(symbols), dedup_hash=h,
            published_at=item.published_at))
        written += 1
    session.commit()
    return written
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_feeds_ingest.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/feeds/ingest.py backend/tests/test_feeds_ingest.py
git commit -m "feat(feeds): ingest job — dedup (in-batch + DB) + symbol tagging + persist"
```

### Task 5: scheduler tick + config

**Files:**
- Modify: `backend/app/core/config.py` (add `news_poll_seconds`)
- Modify: `backend/app/scheduler/jobs.py` (add `_news_poll_tick`, register it)
- Test: `backend/tests/test_scheduler_jobs.py` (append one test)

**Interfaces:**
- Consumes `RssFeedAdapter` (Task 3), `ingest_observations` (Task 4), `settings.news_poll_seconds`.
- Produces `app.scheduler.jobs._news_poll_tick()` (async) — self-isolating global tick: creates a `RssFeedAdapter`, opens `get_session()`, runs `ingest_observations`, on error logs + `session.rollback()`. Registered in `start_scheduler()` on `settings.news_poll_seconds`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_scheduler_jobs.py` (top already imports `datetime, timezone, timedelta`, `Decimal`, `jobs`, `Agent`; `_running_agent` and `_CtxSession` are defined in the file):

```python
async def test_news_poll_tick_ingests_observations(db_session, monkeypatch):
    from app.db.models import Observation
    from app.feeds.rss import FeedItem

    class FakeAdapter:
        async def fetch(self):
            return [FeedItem(source="CoinDesk", title="Bitcoin rallies", url="https://n/1",
                             summary="", published_at=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc))]

    monkeypatch.setattr(jobs, "get_session", lambda: _CtxSession(db_session))
    monkeypatch.setattr(jobs, "RssFeedAdapter", lambda: FakeAdapter())

    await jobs._news_poll_tick()
    obs = db_session.query(Observation).one()
    assert obs.title == "Bitcoin rallies" and obs.source == "CoinDesk"


async def test_news_poll_tick_survives_ingest_error(db_session, monkeypatch):
    from app.db.models import Observation

    class BrokenAdapter:
        async def fetch(self): raise RuntimeError("feeds down")

    monkeypatch.setattr(jobs, "get_session", lambda: _CtxSession(db_session))
    monkeypatch.setattr(jobs, "RssFeedAdapter", lambda: BrokenAdapter())

    await jobs._news_poll_tick()                       # must NOT raise
    assert db_session.query(Observation).count() == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_scheduler_jobs.py -q`
Expected: FAIL with `AttributeError: module 'app.scheduler.jobs' has no attribute '_news_poll_tick'` (or `RssFeedAdapter`).

- [ ] **Step 3: Add the config setting**

In `backend/app/core/config.py`, after the `scoring_seconds` line, add:

```python
    news_poll_seconds: int = 900     # poll crypto news feeds every 15 min
```

- [ ] **Step 4: Add the tick and register it**

In `backend/app/scheduler/jobs.py`, add to the imports block (after the existing `from app.eval.scoring_job import score_matured_decisions`):

```python
from app.feeds.rss import RssFeedAdapter
from app.feeds.ingest import ingest_observations
```

Add the tick (next to `_scoring_tick`):

```python
async def _news_poll_tick():
    adapter = RssFeedAdapter()
    with get_session() as session:
        try:
            await ingest_observations(session, adapter)
        except Exception as exc:
            logger.error("news poll tick failed: %s", exc)
            session.rollback()
```

In `start_scheduler()`, after the scoring job registration, add:

```python
    _scheduler.add_job(_news_poll_tick, "interval", seconds=settings.news_poll_seconds)
```

- [ ] **Step 5: Run to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_scheduler_jobs.py -q`
Expected: PASS (existing scoring-tick test + the two new ones).

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/config.py backend/app/scheduler/jobs.py backend/tests/test_scheduler_jobs.py
git commit -m "feat(scheduler): _news_poll_tick every 15 min (failure-isolated, global)"
```

---

## Part D — Prompt integration (context field → render → build_agent_context)

### Task 6: `ObservationView` + `DecisionContext.observations` + `build_context` keyword

**Files:**
- Modify: `backend/app/brain/context.py`
- Test: `backend/tests/test_brain_context.py` (append two tests)

**Interfaces:**
- Produces `app.brain.context.ObservationView` (dataclass): `source:str, title:str, published_at:datetime, symbols:list[str]`.
- Extends `DecisionContext` with `observations: list[ObservationView] = field(default_factory=list)` (last field, default empty → all existing constructions stay valid).
- Extends `build_context(*, …, observations=None, …)` — passes `observations or []` through.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_brain_context.py` (top already imports `Decimal`, `build_context`, `CoinSnapshot`):

```python
def test_build_context_carries_observations():
    from datetime import datetime, timezone
    from app.brain.context import ObservationView
    obs = [ObservationView(source="CoinDesk", title="Bitcoin ETF inflows",
                           published_at=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
                           symbols=["BTC"])]
    ctx = build_context(instructions="x", cash_usd=Decimal("10"), holdings=[],
                        universe=[], recent_events=[], observations=obs)
    assert ctx.observations[0].title == "Bitcoin ETF inflows"
    assert ctx.observations[0].symbols == ["BTC"]


def test_build_context_defaults_observations_empty():
    ctx = build_context(instructions="x", cash_usd=Decimal("10"),
                        holdings=[], universe=[], recent_events=[])
    assert ctx.observations == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_brain_context.py -q`
Expected: FAIL with `ImportError: cannot import name 'ObservationView'`.

- [ ] **Step 3: Implement**

In `backend/app/brain/context.py`, update the imports at the top:

```python
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
```

Add the view (near `CoinSnapshot`):

```python
@dataclass
class ObservationView:
    source: str
    title: str
    published_at: datetime
    symbols: list[str]
```

Add the field to `DecisionContext` (as the last field, after `wake_reason`):

```python
    observations: list["ObservationView"] = field(default_factory=list)
```

Update `build_context`'s signature and its return. Change the signature to include `observations=None` (before `wake_reason=None` is fine):

```python
def build_context(*, instructions, cash_usd, holdings, universe, recent_events, memory=None, observations=None, wake_reason=None) -> DecisionContext:
```

And in the returned `DecisionContext(...)`, add:

```python
        observations=observations or [],
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_brain_context.py -q`
Expected: PASS (existing context tests + the two new ones).

- [ ] **Step 5: Commit**

```bash
git add backend/app/brain/context.py backend/tests/test_brain_context.py
git commit -m "feat(context): ObservationView + DecisionContext.observations (additive, default empty)"
```

### Task 7: `render_prompt` — conditional "Recent crypto news" section

**Files:**
- Modify: `backend/app/brain/prompt.py`
- Test: `backend/tests/test_brain_prompt.py` (append two tests)

**Interfaces:**
- Consumes `ctx.observations: list[ObservationView]` (Task 6). Renders a conditional section; omitted entirely when the list is empty (so every existing prompt test stays green). Title truncated to 160 chars as a soft token cap. Format per line: `  - MM-DD HH:MM Source: Title [SYM1, SYM2]` (or `[market]` when no symbols).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_brain_prompt.py` (top already imports `Decimal`, `build_context`, `CoinSnapshot`, `render_prompt`):

```python
def test_prompt_includes_observations_when_present():
    from datetime import datetime, timezone
    from app.brain.context import ObservationView
    ctx = build_context(
        instructions="x", cash_usd=Decimal("100"), holdings=[], universe=[], recent_events=[],
        observations=[
            ObservationView("CoinDesk", "Bitcoin ETF sees record inflows",
                            datetime(2026, 7, 3, 10, 30, tzinfo=timezone.utc), ["BTC"]),
            ObservationView("Cointelegraph", "Fed holds rates",
                            datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc), []),
        ],
    )
    _system, user = render_prompt(ctx)
    assert "Recent crypto news" in user
    assert "Bitcoin ETF sees record inflows" in user
    assert "[BTC]" in user
    assert "[market]" in user                      # no-symbol item labelled market-wide


def test_prompt_omits_news_section_when_empty():
    system, user = render_prompt(build_context(
        instructions="x", cash_usd=Decimal("100"), holdings=[], universe=[], recent_events=[]))
    assert "Recent crypto news" not in user         # empty → section fully omitted
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_brain_prompt.py -q`
Expected: FAIL on `test_prompt_includes_observations_when_present` (`"Recent crypto news" not in user`).

- [ ] **Step 3: Implement**

In `backend/app/brain/prompt.py`, inside `render_prompt`, after the "Recent events" block and before the `mem = ctx.memory` line, insert:

```python
    if ctx.observations:
        lines += ["", "Recent crypto news (headlines; context only, not advice):"]
        for o in ctx.observations:
            when = o.published_at.strftime("%m-%d %H:%M")
            title = o.title if len(o.title) <= 160 else o.title[:157] + "..."
            tag = f"[{', '.join(o.symbols)}]" if o.symbols else "[market]"
            lines.append(f"  - {when} {o.source}: {title} {tag}")
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_brain_prompt.py -q`
Expected: PASS (all existing prompt tests + the two new ones). If any existing test fails, the section was not made conditional — fix before proceeding.

- [ ] **Step 5: Commit**

```bash
git add backend/app/brain/prompt.py backend/tests/test_brain_prompt.py
git commit -m "feat(prompt): conditional Recent crypto news section (capped, omitted when empty)"
```

### Task 8: recent-observations query + wire into `build_agent_context`

**Files:**
- Create: `backend/app/feeds/query.py`
- Modify: `backend/app/agents/runtime.py` (`build_agent_context`)
- Test: `backend/tests/test_feeds_query.py` (new), `backend/tests/test_runtime.py` (append one test)

**Interfaces:**
- Produces `app.feeds.query.RECENT_OBS_LIMIT = 12`.
- Produces `app.feeds.query.recent_observations_for(session, universe_symbols, limit=RECENT_OBS_LIMIT) -> list[ObservationView]` — returns up to `limit` most-recent `Observation`s (by `published_at` desc, `id` desc) whose tagged symbols intersect the universe's **base** assets, plus all market-wide (empty-symbol) items. Maps trading pairs to base by stripping a known quote suffix (`USDT`/`USDC`/`BUSD`/`USD`).
- Consumes in `build_agent_context`: after building `universe`, call `recent_observations_for(session, [c.symbol for c in universe])` and pass `observations=` into `build_context`.

- [ ] **Step 1: Write the failing query tests** (`backend/tests/test_feeds_query.py`)

```python
from datetime import datetime, timezone
import json
from app.db.models import Observation
from app.feeds.query import recent_observations_for


def _obs(session, title, symbols, h, url):
    session.add(Observation(source="CoinDesk", kind="news", title=title, url=url,
                            symbols_json=json.dumps(symbols), dedup_hash=url,
                            published_at=datetime(2026, 7, 3, h, 0, tzinfo=timezone.utc)))
    session.commit()


def test_returns_universe_matches_and_market_wide_only(db_session):
    _obs(db_session, "BTC news", ["BTC"], 12, "u/1")
    _obs(db_session, "ETH news", ["ETH"], 11, "u/2")       # not in universe → excluded
    _obs(db_session, "Macro news", [], 10, "u/3")          # market-wide → included
    out = recent_observations_for(db_session, ["BTCUSDT"])
    titles = [o.title for o in out]
    assert "BTC news" in titles and "Macro news" in titles
    assert "ETH news" not in titles


def test_orders_newest_first_and_limits(db_session):
    for i in range(15):
        _obs(db_session, f"n{i}", ["BTC"], 8, f"u/{i}")     # same hour; id desc breaks ties
    out = recent_observations_for(db_session, ["BTCUSDT"], limit=5)
    assert len(out) == 5
    assert out[0].title == "n14"                            # most-recently inserted first
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_feeds_query.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.feeds.query'`.

- [ ] **Step 3: Write the query** (`backend/app/feeds/query.py`)

```python
import json
from app.db.models import Observation
from app.brain.context import ObservationView

RECENT_OBS_LIMIT = 12
_QUOTES = ("USDT", "USDC", "BUSD", "USD")


def _base(symbol: str) -> str:
    for q in _QUOTES:
        if symbol.endswith(q):
            return symbol[: -len(q)]
    return symbol


def recent_observations_for(session, universe_symbols, limit: int = RECENT_OBS_LIMIT) -> list[ObservationView]:
    bases = {_base(s) for s in universe_symbols}
    rows = (session.query(Observation)
            .order_by(Observation.published_at.desc(), Observation.id.desc())
            .limit(limit * 6).all())                       # over-fetch, then filter in Python
    out: list[ObservationView] = []
    for r in rows:
        syms = json.loads(r.symbols_json or "[]")
        if syms and not (set(syms) & bases):
            continue                                       # tagged, but not for this universe
        out.append(ObservationView(source=r.source, title=r.title,
                                   published_at=r.published_at, symbols=syms))
        if len(out) >= limit:
            break
    return out
```

- [ ] **Step 4: Run to verify the query tests pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_feeds_query.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Write the failing wiring test**

Append to `backend/tests/test_runtime.py` (top already imports `Decimal`, `datetime/timezone/timedelta`, `build_agent_context`, `CoinSnapshot`, `journal`; `FakeMarketLLM` and `_llm_agent` are defined in the file):

```python
async def test_build_agent_context_includes_recent_observations(db_session):
    import json
    from app.db.models import Observation
    agent = _llm_agent(db_session)
    db_session.add_all([
        Observation(source="CoinDesk", kind="news", title="Bitcoin ETF inflows", url="o/1",
                    symbols_json=json.dumps(["BTC"]), dedup_hash="o/1",
                    published_at=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc)),
        Observation(source="CoinDesk", kind="news", title="Ethereum upgrade", url="o/2",
                    symbols_json=json.dumps(["ETH"]), dedup_hash="o/2",
                    published_at=datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc)),
    ])
    db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("110"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("110"), (Decimal("109"), Decimal("111")))
    ctx = await build_agent_context(db_session, agent, market, ["BTCUSDT"])
    titles = [o.title for o in ctx.observations]
    assert "Bitcoin ETF inflows" in titles          # universe = BTC → included
    assert "Ethereum upgrade" not in titles          # ETH not in this universe → excluded
```

- [ ] **Step 6: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_runtime.py::test_build_agent_context_includes_recent_observations -q`
Expected: FAIL (`ctx.observations` is empty — build_agent_context does not query yet).

- [ ] **Step 7: Wire the query into `build_agent_context`**

In `backend/app/agents/runtime.py`, add the import near the other `app.*` imports at the top:

```python
from app.feeds.query import recent_observations_for
```

Inside `build_agent_context`, after `memory = journal.compact_view(session, agent.id)` and before the `return build_context(...)`, add:

```python
    observations = recent_observations_for(session, [c.symbol for c in universe])
```

Then add `observations=observations,` to the `build_context(...)` call (alongside `memory=memory`):

```python
    return build_context(instructions=agent.instructions, cash_usd=agent.cash_usd,
                         holdings=holdings, universe=universe, recent_events=recent,
                         memory=memory, observations=observations, wake_reason=wake_reason)
```

- [ ] **Step 8: Run to verify it passes (and nothing regressed)**

Run: `cd backend && .venv/bin/python -m pytest tests/test_runtime.py tests/test_feeds_query.py -q`
Expected: PASS (all runtime tests incl. the new one + the query tests).

- [ ] **Step 9: Commit**

```bash
git add backend/app/feeds/query.py backend/app/agents/runtime.py backend/tests/test_feeds_query.py backend/tests/test_runtime.py
git commit -m "feat(feeds): recent-observations query, wired into build_agent_context (universe-filtered + market-wide)"
```

---

## Part E — Finalization

### Task 9: full-suite green + migration smoke-test + whole-branch review + tracker + memory

**Files:**
- Modify: `docs/superpowers/plans/2026-07-02-pipeline-v2-roadmap.md` (Tracker row 4 → ✅)
- (Review artifacts are scratch, not committed.)

- [ ] **Step 1: Full backend suite green**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: **188 + 24 new = 212 backend tests green** (T1 +2, T2 +5, T3 +4, T4 +4, T5 +2, T6 +2, T7 +2, T8 +3 — treat the total as approximate; what matters is zero failures, zero errors).

- [ ] **Step 2: Frontend untouched, still green**

Run: `cd frontend && npx vitest run`
Expected: **41 green** (Fase 4 is backend-only).

- [ ] **Step 3: Migration smoke-test on a throwaway SQLite DB**

```bash
cd backend
rm -f /tmp/fase4_smoke.db
DATABASE_URL="sqlite:////tmp/fase4_smoke.db" .venv/bin/alembic upgrade head
DATABASE_URL="sqlite:////tmp/fase4_smoke.db" .venv/bin/python -c "import sqlalchemy as sa; e=sa.create_engine('sqlite:////tmp/fase4_smoke.db'); print('observations' in sa.inspect(e).get_table_names())"
DATABASE_URL="sqlite:////tmp/fase4_smoke.db" .venv/bin/alembic downgrade -1
DATABASE_URL="sqlite:////tmp/fase4_smoke.db" .venv/bin/python -c "import sqlalchemy as sa; e=sa.create_engine('sqlite:////tmp/fase4_smoke.db'); print('observations' in sa.inspect(e).get_table_names())"
rm -f /tmp/fase4_smoke.db
```
Expected: `True` after upgrade, `False` after downgrade, both alembic commands exit 0. (Confirm `app/core/config.py` reads `DATABASE_URL` via `database_url`; if the env override does not apply, run the smoke-test against the default DB URL instead and adapt.)

- [ ] **Step 4: Confirm single Alembic head**

Run: `cd backend && .venv/bin/alembic heads`
Expected: exactly one head (the observations migration).

- [ ] **Step 5: Whole-branch review on OPUS**

Scope the review to the **Fase 4 commits only** — base = Fase 3 tip (`12ff3e8`/`9c9360a`) → current HEAD. Do NOT diff `main...pipeline-v2` (that re-includes Fasi 1–3, already ✅).

```bash
git diff 9c9360a..HEAD > /private/tmp/.../scratchpad/review-fase4.diff   # use the session scratchpad path
```
Dispatch an opus review subagent over that diff. Focus areas: (1) failure isolation of `_news_poll_tick` (a feed/parse/DB error never breaks the scheduler); (2) prompt shape frozen — news section conditional, existing prompt tests untouched; (3) dedup correctness (in-batch + cross-poll, url vs source|title fallback); (4) the migration is a faithful mirror of the `Observation` model (columns, nullability, indexes, unique); (5) matcher precision (word-boundary, no bare-ticker false positives). Check the subagent's `tool_uses` > 0 and that citations match the diff; resolve any ⚠ "cannot verify from diff" items yourself.

- [ ] **Step 6: Roadmap tracker → ✅ and commit the plan + tracker**

Edit `docs/superpowers/plans/2026-07-02-pipeline-v2-roadmap.md`, row 4:

```markdown
| 4 — Ingestion news | ✅ fatta su `pipeline-v2` (non in main) | [2026-07-03-ingestion-news](2026-07-03-ingestion-news.md) | 9 task, crypto-native RSS (CoinDesk/Cointelegraph/CryptoSlate), Observation table + poll tick + prompt section; feedparser dep; 212 backend + 41 frontend verdi |
```

```bash
git add docs/superpowers/plans/2026-07-03-ingestion-news.md docs/superpowers/plans/2026-07-02-pipeline-v2-roadmap.md
git commit -m "docs(pipeline): Fase 4 plan + tracker → ✅ (ingestion news on pipeline-v2)"
```

- [ ] **Step 7: Update project memory**

Update `MEMORY.md` / `build-status.md`: Fase 4 done on `pipeline-v2` (crypto-native RSS source; `Observation` table; 15-min poll tick; news section in decision prompt; new `feedparser` dep; one migration on `945d65d0ab6f`; NOT in main). Next = Fase 5 (trigger engine), which reads `Observation`s to wake agents on symbol-relevant news.

- [ ] **Step 8: Report completion to the user** (do NOT push/merge — awaits the final merge of all 6 phases)

---

## Self-Review (run before execution)

**Spec coverage** (roadmap Fase 4 "Deliverable"): `Observation` table with source/kind/symbols/content/timestamp/dedup-hash → Task 1 ✅. First feed adapter (one source) → Task 3 ✅. Polling job in the scheduler → Task 5 ✅. Recent observations enter the decision prompt (new section, token cap) → Tasks 6–8 ✅. Free-only + pre-LLM symbol match + ~15 min → Global Constraints + Task 2/5 ✅. Fase 5 synergy (per-symbol match) → `symbols_json` + `recent_observations_for` support it (query is by base symbol; Fase 5 can reuse the same tag data) ✅.

**Type consistency:** `FeedItem` (Task 3) consumed by `dedup_hash`/`ingest_observations` (Task 4) ✅. `ObservationView(source, title, published_at, symbols)` defined in Task 6, produced by `recent_observations_for` (Task 8), consumed by `render_prompt` (Task 7) ✅. `match_symbols` (Task 2) consumed by Task 4 ✅. `Observation` fields identical across model (Task 1), migration (Task 1), ingest (Task 4), query (Task 8) ✅.

**Placeholder scan:** every code step contains complete code; every command has expected output. No TBD/TODO.

**Known follow-ups (out of scope for v1, noted honestly):** matcher term map is a curated starter (extend per universe growth; ambiguous tickers are name-only by design); no dashboard for observations (backend-only per roadmap); dedicated macro/GDELT source deferred behind the adapter; `kind="market_signal"` column exists but is unused until Fase 5.
