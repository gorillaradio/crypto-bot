from app.db.models import MemoryEntry
from app.brain.context import MemoryView, PolicyLine, PolicyMemoryView
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.brain.memory import MemoryUpdate, PolicyEdit

NARRATIVE_SECTIONS = ("coin_theses", "trade_lessons", "strategy_notes")
SECTIONS = (*NARRATIVE_SECTIONS, "self_policy")
SECTION_CAPS = {"coin_theses": 8, "trade_lessons": 10, "strategy_notes": 5, "self_policy": 8}


def _active_q(session, agent_id: int, section: str):
    return (session.query(MemoryEntry)
            .filter_by(agent_id=agent_id, section=section, active=True)
            .order_by(MemoryEntry.created_at.asc(), MemoryEntry.id.asc()))


def append_entries(session, agent_id: int, section: str, contents: list[str],
                   cycle_id: str | None = None) -> list[MemoryEntry]:
    seen = {e.content for e in _active_q(session, agent_id, section).all()}
    added: list[MemoryEntry] = []
    for raw in contents:
        content = raw.strip()
        if not content or content in seen:
            continue
        row = MemoryEntry(agent_id=agent_id, section=section, content=content,
                          cycle_id=cycle_id, active=True)
        session.add(row)
        added.append(row)
        seen.add(content)
    return added


def active_entries(session, agent_id: int, section: str) -> list[MemoryEntry]:
    return _active_q(session, agent_id, section).all()


def active_count(session, agent_id: int, section: str) -> int:
    return _active_q(session, agent_id, section).count()


def policy_ref(row: MemoryEntry) -> str:
    return f"P{row.id}"


def _policy_id(ref: str) -> int | None:
    if not ref or not ref.startswith("P"):
        return None
    try:
        return int(ref[1:])
    except ValueError:
        return None


def policy_row_for_ref(session, agent_id: int, ref: str) -> MemoryEntry | None:
    row_id = _policy_id(ref)
    if row_id is None:
        return None
    return (session.query(MemoryEntry)
            .filter_by(id=row_id, agent_id=agent_id, section="self_policy", active=True)
            .first())


def policy_view(session, agent_id: int) -> PolicyMemoryView:
    rows = _active_q(session, agent_id, "self_policy").all()
    cap = SECTION_CAPS["self_policy"]
    recent = rows[-cap:] if len(rows) > cap else rows
    return PolicyMemoryView(active=[PolicyLine(policy_ref(row), row.content) for row in recent])


def compact_view(session, agent_id: int) -> MemoryView:
    def text(section: str) -> str:
        rows = _active_q(session, agent_id, section).all()
        cap = SECTION_CAPS[section]
        recent = rows[-cap:] if len(rows) > cap else rows      # most-recent N, chronological
        return "\n".join(e.content for e in recent)
    return MemoryView(coin_theses=text("coin_theses"),
                      trade_lessons=text("trade_lessons"),
                      strategy_notes=text("strategy_notes"))


def _validate_policy_edits(session, agent_id: int, edits: list["PolicyEdit"]) -> None:
    active_count_now = active_count(session, agent_id, "self_policy")
    net_new = 0
    for edit in edits:
        if edit.op == "add":
            if not edit.text.strip():
                raise ValueError("policy add requires text")
            net_new += 1
        elif edit.op == "retire":
            if not edit.policy_ref or policy_row_for_ref(session, agent_id, edit.policy_ref) is None:
                raise ValueError(f"invalid policy ref: {edit.policy_ref}")
            net_new -= 1
        elif edit.op == "replace":
            if not edit.policy_ref or policy_row_for_ref(session, agent_id, edit.policy_ref) is None:
                raise ValueError(f"invalid policy ref: {edit.policy_ref}")
            if not edit.text.strip():
                raise ValueError("policy replace requires text")
        else:
            raise ValueError(f"invalid policy op: {edit.op}")
    if active_count_now + net_new > SECTION_CAPS["self_policy"]:
        raise ValueError("self_policy cap exceeded")


def _apply_policy_edits(session, agent_id: int, edits: list["PolicyEdit"], cycle_id: str | None) -> None:
    for edit in edits:
        if edit.op == "add":
            append_entries(session, agent_id, "self_policy", [edit.text], cycle_id=cycle_id)
        elif edit.op == "retire":
            row = policy_row_for_ref(session, agent_id, edit.policy_ref or "")
            if row is None:
                raise ValueError(f"invalid policy ref: {edit.policy_ref}")
            row.active = False
        elif edit.op == "replace":
            row = policy_row_for_ref(session, agent_id, edit.policy_ref or "")
            if row is None:
                raise ValueError(f"invalid policy ref: {edit.policy_ref}")
            row.active = False
            append_entries(session, agent_id, "self_policy", [edit.text], cycle_id=cycle_id)


def apply_memory_update(session, agent_id: int, update: "MemoryUpdate",
                        cycle_id: str | None = None) -> None:
    _validate_policy_edits(session, agent_id, update.policy_edits)
    for section in NARRATIVE_SECTIONS:
        append_entries(session, agent_id, section, getattr(update, section), cycle_id=cycle_id)
    _apply_policy_edits(session, agent_id, update.policy_edits, cycle_id)


def apply_distillation(session, agent_id: int, section: str, compacted: list[str],
                       cycle_id: str | None = None) -> None:
    for e in _active_q(session, agent_id, section).all():
        e.active = False
    for raw in compacted:
        content = raw.strip()
        if content:
            session.add(MemoryEntry(agent_id=agent_id, section=section, content=content,
                                    cycle_id=cycle_id, active=True))
