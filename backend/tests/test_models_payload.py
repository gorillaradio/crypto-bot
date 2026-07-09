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
