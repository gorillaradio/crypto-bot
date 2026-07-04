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
