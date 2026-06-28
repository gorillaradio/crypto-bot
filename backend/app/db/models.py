from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import ForeignKey, Numeric, String, DateTime
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
