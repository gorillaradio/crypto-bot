from datetime import datetime, timezone, timedelta
from decimal import Decimal
from app.db.event_backfill import payload_for, fold_rationales, replay_positions
from app.db.models import Trade


def test_decision_message_parses_to_payload():
    p = payload_for("decision", "ciclo decisione (LLM): hold and wait — 1 operazioni, 2 saltate, 0 errori")
    assert p == {"status": "ok", "note": "hold and wait", "executed": 1,
                 "skipped": [], "skipped_count": 2, "errors": 0,
                 "trigger": None, "wake_reason": None}


def test_out_of_cycle_and_error_decisions():
    p = payload_for("decision", "ciclo decisione fuori ciclo (LLM): sell all — 1 operazioni, 0 saltate, 0 errori")
    assert p["wake_reason"] == "fuori ciclo"
    e = payload_for("decision", "ciclo decisione (LLM): errore — timeout LLM")
    assert e == {"status": "error", "detail": "timeout LLM", "wake_reason": None}


def test_trade_message_parses_and_no_note_normalizes():
    p = payload_for("trade", "BUY 378 ACTUSDT @ $0.0132 (fee $0.005)")
    assert p == {"side": "BUY", "symbol": "ACTUSDT", "qty": "378",
                 "price": "0.0132", "fee": "0.005", "rationale": None}
    n = payload_for("decision", "ciclo decisione (LLM): (no note) — 0 operazioni, 0 saltate, 0 errori")
    assert n["note"] == ""


def test_reflection_and_unknown_fall_back():
    assert payload_for("reflection", "memoria aggiornata dopo trade chiuso") == {"status": "ok"}
    assert payload_for("reflection", "memoria distillata: self_policy") == {"status": "ok", "distilled": "self_policy"}
    assert payload_for("reflection", "reflection: risposta non valida, memoria invariata") == {"status": "invalid"}
    assert payload_for("reflection", "reflection: errore — boom")["status"] == "error"
    assert payload_for("trade", "qualcosa di non riconoscibile") == {"raw": "qualcosa di non riconoscibile"}


def test_fold_rationales_pairs_reasoning_to_previous_trade():
    rows = [
        (1, "decision", "c1", {"status": "ok"}),
        (2, "trade", "c1", {"side": "BUY", "symbol": "ACTUSDT", "rationale": None}),
        (3, "reasoning", "c1", {"raw": "momentum continues"}),
        (4, "reasoning", "c1", {"raw": "loose thought"}),          # senza trade libero → resta
        (5, "reasoning", "c2", {"raw": "other cycle"}),            # altro ciclo → non accoppia
    ]
    updates = fold_rationales(rows)
    assert updates[2]["rationale"] == "momentum continues"
    assert updates[3] == {"raw": "momentum continues", "folded": True}
    assert 4 not in updates or updates[4].get("folded") is not True
    assert 5 not in updates or updates[5].get("folded") is not True


def _t(agent_id, symbol, side, qty, price, ts):
    return Trade(agent_id=agent_id, symbol=symbol, side=side, quantity=Decimal(qty),
                 price=Decimal(price), fee=Decimal("0"), timestamp=ts)


def test_replay_positions_reconstructs_open_lifecycle():
    t0 = datetime(2026, 7, 1, tzinfo=timezone.utc)
    trades = [
        _t(1, "AUSDT", "BUY", "10", "1", t0),                      # apre: invested 10
        _t(1, "AUSDT", "SELL", "10", "2", t0 + timedelta(hours=1)),  # chiude tutto (+10)
        _t(1, "AUSDT", "BUY", "5", "2", t0 + timedelta(hours=2)),  # riapre: vita nuova
        _t(1, "AUSDT", "SELL", "2", "3", t0 + timedelta(hours=3)),  # parziale: +2 realized
        _t(1, "BUSDT", "BUY", "1", "7", t0),
    ]
    out = replay_positions(trades)
    a = out[(1, "AUSDT")]
    assert a["opened_at"] == t0 + timedelta(hours=2)               # la vita corrente, non la prima
    assert a["invested_usd"] == Decimal("10")                      # 5 × 2
    assert a["realized_usd"] == Decimal("2")                       # (3-2) × 2
    assert out[(1, "BUSDT")]["invested_usd"] == Decimal("7")
