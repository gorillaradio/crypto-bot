from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import ForeignKey, Numeric, String, DateTime, UniqueConstraint, Boolean
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
    # Every agent runs through the OpenRouter gateway; the model is chosen via model_name
    # (a "vendor/model" slug, e.g. "deepseek/deepseek-v4-flash").
    model_provider: Mapped[str] = mapped_column(String(40), default="openrouter")
    model_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    positions: Mapped[list["Position"]] = relationship(back_populates="agent")


class Position(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    symbol: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    avg_price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    breach_armed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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
    cycle_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AgentMemory(Base):
    __tablename__ = "agent_memory"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    section: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(String, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    __table_args__ = (UniqueConstraint("agent_id", "section", name="uq_agent_memory_section"),)


class ShareLink(Base):
    __tablename__ = "share_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
