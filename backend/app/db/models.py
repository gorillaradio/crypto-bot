from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import ForeignKey, Numeric, String, DateTime, UniqueConstraint, Boolean, Integer, JSON
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
    # Capitale con cui l'agente è partito. Immutabile: è il denominatore del rendimento.
    # settings.initial_capital_usd ne è solo il seed alla creazione.
    initial_capital_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    universe: Mapped[str] = mapped_column(String(20), default="TOP_100")
    # Every agent runs through the OpenRouter gateway; the model is chosen via model_name
    # (a "vendor/model" slug, e.g. "deepseek/deepseek-v4-flash").
    model_provider: Mapped[str] = mapped_column(String(40), default="openrouter")
    model_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # News wake bookmark: highest Observation.id this agent has already "seen"
    # (present in a prior decision's prompt). NULL = never decided yet.
    last_seen_observation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)

    positions: Mapped[list["Position"]] = relationship(back_populates="agent")


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
    # Dati strutturati dell'evento (forma per kind, vedi spec); message resta il log leggibile.
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cycle_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ShareLink(Base):
    __tablename__ = "share_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DecisionRecord(Base):
    __tablename__ = "decision_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    cycle_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(20))            # "decision" | "reflection"
    trigger: Mapped[str] = mapped_column(String(20))  # "schedule" | "breach" | "movement" | "news"
    system_prompt: Mapped[str] = mapped_column(String)
    user_prompt: Mapped[str] = mapped_column(String)
    raw_response: Mapped[str | None] = mapped_column(String, nullable=True)
    parsed_output: Mapped[str | None] = mapped_column(String, nullable=True)
    parse_status: Mapped[str] = mapped_column(String(10))    # "ok" | "repaired" | "failed"
    model_provider: Mapped[str] = mapped_column(String(40))
    model_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class BenchmarkBasis(Base):
    __tablename__ = "benchmark_basis"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), unique=True, index=True)
    universe_json: Mapped[str] = mapped_column(String)          # JSON list of frozen symbols
    start_prices_json: Mapped[str] = mapped_column(String)      # JSON {symbol: "price"} at start
    initial_capital: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BenchmarkSnapshot(Base):
    __tablename__ = "benchmark_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))               # hodl_btc | equal_weight | random_p10|p50|p90
    equity_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class DecisionScore(Base):
    __tablename__ = "decision_scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    decision_record_id: Mapped[int] = mapped_column(ForeignKey("decision_records.id"), index=True)
    window: Mapped[str] = mapped_column(String(8))    # label finestra (settings.scoring_windows, es. "24h" | "7d")
    n_actions: Mapped[int] = mapped_column(Integer)
    n_hits: Mapped[int] = mapped_column(Integer)
    avg_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    reflected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("decision_record_id", "window", name="uq_decision_score_window"),)


class MemoryEntry(Base):
    __tablename__ = "memory_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    section: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(String)
    cycle_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class Observation(Base):
    __tablename__ = "observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(60))                    # e.g. "CoinDesk"
    kind: Mapped[str] = mapped_column(String(20), default="news")      # "news" | "market_signal" (v2)
    title: Mapped[str] = mapped_column(String)                         # normalized headline
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    symbols_json: Mapped[str] = mapped_column(String, default="[]")    # JSON list of base symbols; "[]" = market-wide
    dedup_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # MUST be written UTC-aware: SQLite drops tzinfo, so any datetime ordering/compare
    # is correct only while every writer stores UTC. Sole writer today: app/feeds/rss.py.
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


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
