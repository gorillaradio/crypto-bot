from decimal import Decimal
from datetime import datetime, timedelta, timezone
from app.db.models import DecisionRecord


def movement_change(first: Decimal, last: Decimal) -> Decimal:
    """Signed price move over a window: (last - first) / first. 0 when first <= 0."""
    if first <= 0:
        return Decimal("0")
    return (last - first) / first


_EVENT_TRIGGERS = ("movement", "news")


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def count_recent_event_wakes(session, agent_id: int) -> int:
    """Discretionary (movement+news) decision cycles for this agent in the last hour.
    Time window compared in Python (never in SQL) per the UTC-aware discipline."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    rows = (session.query(DecisionRecord)
            .filter(DecisionRecord.agent_id == agent_id,
                    DecisionRecord.kind == "decision",
                    DecisionRecord.trigger.in_(_EVENT_TRIGGERS))
            .all())
    return sum(1 for r in rows if _as_utc(r.created_at) >= cutoff)
