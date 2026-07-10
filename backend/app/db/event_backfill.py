"""Backfill una-tantum dei payload sugli eventi storici (migrazione c4d5e6f7a8b9).

Le regex sono quelle che il frontend usava per riparsare i message; vivono qui
da ora in poi, usate solo dal backfill. Gli eventi nuovi nascono già col payload.
"""
import re
from decimal import Decimal

DECISION_RE = re.compile(
    r"^ciclo decisione( fuori ciclo)? \(LLM\): ([\s\S]*) — (\d+) operazioni, (\d+) saltate, (\d+) errori$")
DECISION_ERR_RE = re.compile(r"^ciclo decisione( fuori ciclo)? \(LLM\): errore — ([\s\S]*)$")
TRADE_RE = re.compile(r"^(BUY|SELL) (\S+) (\S+) @ \$(\S+) \(fee \$(\S+)\)$")
DISTILL_RE = re.compile(r"^memoria distillata: (\w+)$")


def payload_for(kind: str, message: str) -> dict:
    """Payload strutturato ricavato dal message; {"raw": message} se non interpretabile."""
    if kind == "decision":
        err = DECISION_ERR_RE.match(message)
        if err:
            return {"status": "error", "detail": err.group(2),
                    "wake_reason": "fuori ciclo" if err.group(1) else None}
        ok = DECISION_RE.match(message)
        if ok:
            note = "" if ok.group(2) == "(no note)" else ok.group(2)
            return {"status": "ok", "note": note, "executed": int(ok.group(3)),
                    "skipped": [], "skipped_count": int(ok.group(4)),
                    "errors": int(ok.group(5)), "trigger": None,
                    "wake_reason": "fuori ciclo" if ok.group(1) else None}
    elif kind == "trade":
        m = TRADE_RE.match(message)
        if m:
            return {"side": m.group(1), "symbol": m.group(3), "qty": m.group(2),
                    "price": m.group(4), "fee": m.group(5), "rationale": None}
    elif kind == "reasoning":
        return {"raw": message}
    elif kind == "reflection":
        if message.startswith("memoria aggiornata"):
            return {"status": "ok"}
        d = DISTILL_RE.match(message)
        if d:
            return {"status": "ok", "distilled": d.group(1)}
        if message.startswith("reflection: risposta non valida"):
            return {"status": "invalid"}
        if message.startswith("reflection: errore"):
            return {"status": "error",
                    "detail": message.removeprefix("reflection: errore — ")}
    return {"raw": message}


def fold_rationales(rows: list[tuple[int, str, str | None, dict]]) -> dict[int, dict]:
    """rows = (id, kind, cycle_id, payload) in ordine di id (cronologico).
    Un reasoning segue il suo trade nello stesso ciclo: sposta il testo nel
    payload del trade e marca il reasoning come folded. Ritorna {id: payload} da aggiornare."""
    updates: dict[int, dict] = {}
    pending: tuple[int, dict] | None = None   # ultimo trade senza rationale
    current_cycle: str | None = None
    for eid, kind, cycle_id, payload in rows:
        if cycle_id != current_cycle:
            current_cycle, pending = cycle_id, None
        if kind == "trade" and "side" in payload:
            pending = (eid, payload)
        elif kind == "reasoning" and pending is not None and cycle_id is not None:
            trade_id, trade_payload = pending
            trade_payload = {**trade_payload, "rationale": payload["raw"]}
            updates[trade_id] = trade_payload
            updates[eid] = {**payload, "folded": True}
            pending = None
    return updates


def replay_positions(trades: list) -> dict[tuple[int, str], dict]:
    """Rigioca i trade in ordine cronologico e ricava, per le posizioni ancora aperte,
    la vita corrente: opened_at (ultimo passaggio 0→>0), invested_usd, realized_usd."""
    state: dict[tuple[int, str], dict] = {}
    for t in sorted(trades, key=lambda t: (t.timestamp, t.id or 0)):
        key = (t.agent_id, t.symbol)
        s = state.get(key)
        if t.side == "BUY":
            if s is None or s["qty"] <= 0:
                s = {"qty": Decimal("0"), "avg": Decimal("0"),
                     "opened_at": t.timestamp, "invested_usd": Decimal("0"),
                     "realized_usd": Decimal("0")}
                state[key] = s
            new_qty = s["qty"] + t.quantity
            s["avg"] = ((s["avg"] * s["qty"] + t.price * t.quantity) / new_qty) if new_qty else Decimal("0")
            s["qty"] = new_qty
            s["invested_usd"] += t.quantity * t.price
        elif t.side == "SELL" and s is not None:
            s["realized_usd"] += (t.price - s["avg"]) * t.quantity
            s["qty"] -= t.quantity
            if s["qty"] <= 0:
                del state[key]
    return {k: {"opened_at": v["opened_at"], "invested_usd": v["invested_usd"],
                "realized_usd": v["realized_usd"]}
            for k, v in state.items() if v["qty"] > 0}
