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
