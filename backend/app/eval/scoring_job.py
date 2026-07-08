import json
from datetime import datetime, timezone
from app.core.config import settings
from app.db.models import DecisionRecord, DecisionScore
from app.eval.scoring import score_decision


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ms(dt: datetime) -> int:
    return int(_as_utc(dt).timestamp() * 1000)


async def score_matured_decisions(session, market, now: datetime) -> int:
    now = _as_utc(now)
    written = 0
    records = (session.query(DecisionRecord)
               .filter(DecisionRecord.kind == "decision",
                       DecisionRecord.parse_status.in_(("ok", "repaired")))
               .all())
    # Finestre dalla config. Cambiare i label ri-scora le decisioni storiche mature
    # sotto le nuove finestre (il check `already` è per coppia decisione+label);
    # le righe con label di config precedenti restano nel DB e vengono ignorate dalle metriche.
    windows = settings.scoring_windows
    for rec in records:
        for window, delta in windows.items():
            if _as_utc(rec.created_at) + delta > now:
                continue
            already = (session.query(DecisionScore)
                       .filter_by(decision_record_id=rec.id, window=window).first())
            if already:
                continue
            actions = json.loads(rec.parsed_output or "{}").get("actions", [])
            symbols = {a.get("symbol") for a in actions
                       if a.get("type") in ("BUY", "SELL") and a.get("symbol")}
            p0: dict = {}
            p1: dict = {}
            for s in symbols:
                a0 = await market.get_price_at(s, _ms(rec.created_at))
                a1 = await market.get_price_at(s, _ms(_as_utc(rec.created_at) + delta))
                if a0 is not None:
                    p0[s] = a0
                if a1 is not None:
                    p1[s] = a1
            n, hits, avg = score_decision(actions, p0, p1)
            session.add(DecisionScore(decision_record_id=rec.id, window=window,
                                      n_actions=n, n_hits=hits, avg_return_pct=avg))
            written += 1
    session.commit()
    return written
