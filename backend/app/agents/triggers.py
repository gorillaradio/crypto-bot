import json
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from app.db.models import DecisionRecord, Observation
from app.feeds.query import _base


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


_NEWS_SCAN_LIMIT = 50


def fresh_news_for(session, agent):
    """Newest Observation past the agent's bookmark that names a held base symbol.
    None if the agent holds nothing, nothing is newer, or nothing matches.
    Market-wide (empty symbols) never triggers a wake."""
    held = {_base(p.symbol) for p in agent.positions}
    if not held:
        return None
    watermark = agent.last_seen_observation_id or 0
    rows = (session.query(Observation)
            .filter(Observation.id > watermark)
            .order_by(Observation.id.desc())
            .limit(_NEWS_SCAN_LIMIT).all())
    for r in rows:                                 # id desc → first match is newest
        syms = json.loads(r.symbols_json or "[]")
        if syms and (set(syms) & held):
            return r
    return None
