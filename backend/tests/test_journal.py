from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.db.models import Agent, MemoryEntry
from app.brain import journal


def _agent(session):
    a = Agent(name="J", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1), cash_usd=Decimal("100"))
    session.add(a); session.commit()
    return a


def test_append_entries_inserts_active_rows_with_cycle(db_session):
    a = _agent(db_session)
    added = journal.append_entries(db_session, a.id, "coin_theses", ["BTC: bull", "ETH: flat"], cycle_id="c1")
    db_session.commit()
    assert len(added) == 2
    rows = journal.active_entries(db_session, a.id, "coin_theses")
    assert [r.content for r in rows] == ["BTC: bull", "ETH: flat"]   # oldest-first
    assert all(r.active and r.cycle_id == "c1" for r in rows)


def test_append_entries_skips_blank_and_exact_duplicates(db_session):
    a = _agent(db_session)
    journal.append_entries(db_session, a.id, "coin_theses", ["BTC: bull"], cycle_id="c1")
    db_session.commit()
    added = journal.append_entries(db_session, a.id, "coin_theses",
                                   ["BTC: bull", "  ", "BTC: bear"], cycle_id="c2")
    db_session.commit()
    assert [r.content for r in added] == ["BTC: bear"]               # dup + blank dropped
    assert journal.active_count(db_session, a.id, "coin_theses") == 2


def test_compact_view_joins_active_entries_per_section(db_session):
    a = _agent(db_session)
    journal.append_entries(db_session, a.id, "coin_theses", ["BTC: bull", "ETH: flat"])
    journal.append_entries(db_session, a.id, "strategy_notes", ["patient"])
    db_session.commit()
    view = journal.compact_view(db_session, a.id)
    assert view.coin_theses == "BTC: bull\nETH: flat"
    assert view.strategy_notes == "patient"
    assert view.trade_lessons == ""                                  # empty section → empty string


def test_compact_view_caps_to_most_recent_n(db_session):
    a = _agent(db_session)
    cap = journal.SECTION_CAPS["strategy_notes"]                     # 5
    journal.append_entries(db_session, a.id, "strategy_notes",
                           [f"note{i}" for i in range(cap + 3)])      # 8 entries
    db_session.commit()
    lines = journal.compact_view(db_session, a.id).strategy_notes.split("\n")
    assert len(lines) == cap                                         # capped at 5
    assert lines[0] == "note3" and lines[-1] == "note7"              # the most-recent 5, chronological


def test_apply_distillation_supersedes_old_and_inserts_compacted(db_session):
    a = _agent(db_session)
    journal.append_entries(db_session, a.id, "strategy_notes", ["old1", "old2", "old3"], cycle_id="c1")
    db_session.commit()
    journal.apply_distillation(db_session, a.id, "strategy_notes", ["merged"], cycle_id="c2")
    db_session.commit()
    active = journal.active_entries(db_session, a.id, "strategy_notes")
    assert [r.content for r in active] == ["merged"]                 # only the compacted line is active
    superseded = db_session.query(MemoryEntry).filter_by(
        agent_id=a.id, section="strategy_notes", active=False).count()
    assert superseded == 3                                           # nothing deleted, old rows kept


def test_policy_view_returns_active_policy_refs(db_session):
    a = _agent(db_session)
    journal.append_entries(db_session, a.id, "self_policy",
                           ["Do not re-enter recent losers.", "Require fresh evidence for overrides."])
    db_session.commit()

    view = journal.policy_view(db_session, a.id)

    rows = journal.active_entries(db_session, a.id, "self_policy")
    assert [p.ref for p in view.active] == [f"P{rows[0].id}", f"P{rows[1].id}"]
    assert [p.content for p in view.active] == [
        "Do not re-enter recent losers.",
        "Require fresh evidence for overrides.",
    ]


def test_policy_view_excludes_inactive_rows(db_session):
    a = _agent(db_session)
    journal.append_entries(db_session, a.id, "self_policy", ["active", "retired"])
    db_session.commit()
    rows = journal.active_entries(db_session, a.id, "self_policy")
    rows[1].active = False
    db_session.commit()

    view = journal.policy_view(db_session, a.id)

    assert [(p.ref, p.content) for p in view.active] == [(f"P{rows[0].id}", "active")]


def test_policy_row_for_ref_is_agent_scoped(db_session):
    a1 = _agent(db_session)
    a2 = _agent(db_session)
    journal.append_entries(db_session, a1.id, "self_policy", ["a1 policy"])
    db_session.commit()
    row = journal.active_entries(db_session, a1.id, "self_policy")[0]

    assert journal.policy_row_for_ref(db_session, a1.id, f"P{row.id}") == row
    assert journal.policy_row_for_ref(db_session, a2.id, f"P{row.id}") is None
    assert journal.policy_row_for_ref(db_session, a1.id, "not-a-ref") is None
