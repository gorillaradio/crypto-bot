import json
from dataclasses import dataclass
from datetime import datetime, timezone
from app.core.config import settings
from app.db.models import MarketBrief
from app.brain.context import MarketBriefView, HighlightView


@dataclass
class BriefLookup:
    row: MarketBrief | None
    unavailable_reason: str | None
    has_valid: bool


def persist_brief(session, cycle_id: str, result) -> MarketBrief:
    """Write the analyst call to MarketBrief: parsed payload (NULL if parse failed) + Fase-1 audit."""
    row = MarketBrief(
        cycle_id=cycle_id,
        parsed_brief=(result.brief.model_dump_json() if result.parse_status != "failed" else None),
        system_prompt=result.system, user_prompt=result.user, raw_response=result.raw,
        parse_status=result.parse_status,
        model_provider="openrouter", model_name=settings.analyst_model,
        latency_ms=result.latency_ms)
    session.add(row)
    session.commit()
    return row


def latest_valid_brief(session) -> MarketBrief | None:
    """Most recent brief with a usable payload (parse ok/repaired). Ordering by created_at is a
    SQL ORDER BY, not a datetime comparison — safe on SQLite."""
    return (session.query(MarketBrief)
            .filter(MarketBrief.parsed_brief.isnot(None))
            .order_by(MarketBrief.created_at.desc(), MarketBrief.id.desc())
            .first())


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _age_minutes(row: MarketBrief, now: datetime) -> int:
    return int((_as_utc(now) - _as_utc(row.created_at)).total_seconds() // 60)


def brief_lookup_for_prompt(session, now: datetime | None = None) -> BriefLookup:
    now = now or datetime.now(timezone.utc)
    row = latest_valid_brief(session)
    if row is None:
        return BriefLookup(row=None, unavailable_reason=None, has_valid=False)
    age = _age_minutes(row, now)
    if age > settings.market_brief_max_age_minutes:
        return BriefLookup(
            row=None,
            unavailable_reason=f"latest valid brief is stale by {age}m",
            has_valid=True,
        )
    return BriefLookup(row=row, unavailable_reason=None, has_valid=True)


def filter_brief_for(brief_row, universe_symbols) -> MarketBriefView:
    """Global brief → per-agent view: keep only highlights whose symbol is in the agent's universe;
    regime + key_news pass through."""
    data = json.loads(brief_row.parsed_brief)
    keep = set(universe_symbols)
    highlights = [HighlightView(symbol=h.get("symbol", ""), snapshot=h.get("snapshot", ""),
                                signal=h.get("signal", "neutral"), note=h.get("note", ""))
                  for h in data.get("highlights", []) if h.get("symbol") in keep]
    return MarketBriefView(regime=data.get("regime", ""), highlights=highlights,
                           key_news=data.get("key_news", []), as_of=brief_row.created_at)
