# Behavioral Learning Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an LLM-owned behavioral learning loop where the system stores facts and the agent updates self-policy through reflection.

**Architecture:** Keep the runtime as plumbing: it retrieves factual evidence, persists prompts/results, enforces only physical trade validity, and applies explicit LLM-authored memory edits. Add self-policy as a fourth append-only journal section, extend decision JSON with optional accountability fields, make stale briefs unavailable with exact age, and add a post-scoring learning tick that feeds raw `DecisionScore` facts into reflection.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy ORM, Alembic, Pydantic v2, pytest, SQLite in-memory tests.

## Global Constraints

- Do not implement fine-tuning, model training, or an expert-system risk manager.
- Runtime guardrails may enforce only physical validity: cash, fee, min trade, universe membership, and held-position sells.
- The system must not block, resize, skip, blacklist, cool down, or judge trades based on strategic memory or self-policy.
- The system may compute raw facts: realized P&L, brief age, matured scoring windows, and whether an action referenced a displayed policy ID.
- The LLM owns strategic judgment, policy alignment, override reasons, memory updates, and self-policy edits.
- Stale market briefs are treated as unavailable after the freshness threshold, with the exact age shown to the LLM.
- Reflection parsing is all-or-nothing for this slice.
- Existing `DecisionRecord` payloads without policy fields must remain parseable and scorable.

---

## File Structure

Modify these files:

- `backend/app/db/models.py` - add `DecisionScore.reflected_at`.
- `backend/app/core/config.py` - add `market_brief_max_age_minutes`.
- `backend/app/brain/context.py` - add policy and brief-unavailable context views.
- `backend/app/brain/journal.py` - add `self_policy` section, policy refs, and policy-edit application.
- `backend/app/brain/schema.py` - add optional action accountability fields.
- `backend/app/brain/prompt.py` - render self-policy separately and include policy fields in the JSON contract.
- `backend/app/brain/memory.py` - extend reflection input/output to include policy views and policy edits.
- `backend/app/brain/brief_store.py` - add freshness lookup helpers.
- `backend/app/agents/runtime.py` - pass policy/freshness context and apply reflection updates atomically.
- `backend/app/agents/preview.py` - keep prompt preview compatible with policy-aware reflection.
- `backend/app/scheduler/jobs.py` - add the learning tick after scoring.
- `backend/app/api/schemas.py` and `backend/app/api/routes.py` - no mutation endpoint; only adjust read models if tests require explicit policy visibility.

Create these files:

- `backend/alembic/versions/7b8c9d0e1f2a_decision_score_reflected_at.py` - migration for `decision_scores.reflected_at`.
- `backend/app/brain/learning.py` - pure outcome-reflection prompt/result logic.
- `backend/app/agents/learning.py` - DB orchestration for post-scoring learning reflection.
- `backend/tests/test_brain_learning.py` - pure learning prompt/result tests.
- `backend/tests/test_learning_job.py` - DB orchestration tests for learning reflection.

Test files to modify:

- `backend/tests/test_models.py`
- `backend/tests/test_journal.py`
- `backend/tests/test_brain_context.py`
- `backend/tests/test_brain_schema.py`
- `backend/tests/test_brain_trader_prompt.py`
- `backend/tests/test_brain_memory.py`
- `backend/tests/test_brief_store.py`
- `backend/tests/test_analyst_orchestration.py`
- `backend/tests/test_runtime.py`
- `backend/tests/test_preview.py`
- `backend/tests/test_scoring_job.py`
- `backend/tests/test_scheduler_jobs.py`

---

### Task 1: Persistence and Freshness Settings

**Files:**
- Create: `backend/alembic/versions/7b8c9d0e1f2a_decision_score_reflected_at.py`
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `DecisionScore.reflected_at: datetime | None`
- Produces: `settings.market_brief_max_age_minutes: int`

- [ ] **Step 1: Write failing model/config tests**

Add to `backend/tests/test_models.py`:

```python
def test_decision_score_reflected_at_defaults_to_none(db_session):
    from datetime import datetime, timezone, timedelta
    from decimal import Decimal
    from app.db.models import Agent, DecisionRecord, DecisionScore

    agent = Agent(name="R", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    rec = DecisionRecord(agent_id=agent.id, cycle_id="c", kind="decision", trigger="schedule",
                         system_prompt="s", user_prompt="u", raw_response="r",
                         parsed_output='{"actions":[]}', parse_status="ok",
                         model_provider="openrouter", model_name="m", latency_ms=1)
    db_session.add(rec); db_session.commit()

    score = DecisionScore(decision_record_id=rec.id, window="24h",
                          n_actions=0, n_hits=0, avg_return_pct=None)
    db_session.add(score); db_session.commit()

    assert score.reflected_at is None


def test_decision_score_reflected_at_can_be_set(db_session):
    from datetime import datetime, timezone, timedelta
    from decimal import Decimal
    from app.db.models import Agent, DecisionRecord, DecisionScore

    agent = Agent(name="R2", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    rec = DecisionRecord(agent_id=agent.id, cycle_id="c", kind="decision", trigger="schedule",
                         system_prompt="s", user_prompt="u", raw_response="r",
                         parsed_output='{"actions":[]}', parse_status="ok",
                         model_provider="openrouter", model_name="m", latency_ms=1)
    db_session.add(rec); db_session.commit()

    now = datetime.now(timezone.utc)
    score = DecisionScore(decision_record_id=rec.id, window="24h",
                          n_actions=0, n_hits=0, avg_return_pct=None,
                          reflected_at=now)
    db_session.add(score); db_session.commit()

    assert score.reflected_at == now
```

Add to the same file:

```python
def test_settings_exposes_market_brief_max_age_minutes():
    from app.core.config import settings

    assert settings.market_brief_max_age_minutes == 120
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_models.py::test_decision_score_reflected_at_defaults_to_none backend/tests/test_models.py::test_decision_score_reflected_at_can_be_set backend/tests/test_models.py::test_settings_exposes_market_brief_max_age_minutes -q
```

Expected: FAIL because `DecisionScore.reflected_at` and `settings.market_brief_max_age_minutes` do not exist.

- [ ] **Step 3: Add model/config fields**

In `backend/app/db/models.py`, update `DecisionScore`:

```python
class DecisionScore(Base):
    __tablename__ = "decision_scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    decision_record_id: Mapped[int] = mapped_column(ForeignKey("decision_records.id"), index=True)
    window: Mapped[str] = mapped_column(String(8))              # "24h" | "7d"
    n_actions: Mapped[int] = mapped_column(Integer)
    n_hits: Mapped[int] = mapped_column(Integer)
    avg_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    reflected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("decision_record_id", "window", name="uq_decision_score_window"),)
```

In `backend/app/core/config.py`, add near the brain v2 settings:

```python
    market_brief_max_age_minutes: int = 120
```

- [ ] **Step 4: Add Alembic migration**

Create `backend/alembic/versions/7b8c9d0e1f2a_decision_score_reflected_at.py`:

```python
"""decision score reflected_at

Revision ID: 7b8c9d0e1f2a
Revises: c89a7674625e
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7b8c9d0e1f2a"
down_revision: Union[str, Sequence[str], None] = "c89a7674625e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("decision_scores",
                  sa.Column("reflected_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("decision_scores", "reflected_at")
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_models.py::test_decision_score_reflected_at_defaults_to_none backend/tests/test_models.py::test_decision_score_reflected_at_can_be_set backend/tests/test_models.py::test_settings_exposes_market_brief_max_age_minutes -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models.py backend/app/core/config.py backend/alembic/versions/7b8c9d0e1f2a_decision_score_reflected_at.py backend/tests/test_models.py
git commit -m "feat: add learning reflection marker"
```

---

### Task 2: Self-Policy Journal View

**Files:**
- Modify: `backend/app/brain/context.py`
- Modify: `backend/app/brain/journal.py`
- Modify: `backend/app/agents/runtime.py`
- Test: `backend/tests/test_journal.py`

**Interfaces:**
- Produces: `PolicyLine(ref: str, content: str)`
- Produces: `PolicyMemoryView(active: list[PolicyLine])`
- Produces: `journal.NARRATIVE_SECTIONS`
- Produces: `journal.policy_view(session, agent_id) -> PolicyMemoryView`
- Produces: `journal.policy_row_for_ref(session, agent_id, ref) -> MemoryEntry | None`

- [ ] **Step 1: Write failing journal tests**

Add to `backend/tests/test_journal.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_journal.py::test_policy_view_returns_active_policy_refs backend/tests/test_journal.py::test_policy_view_excludes_inactive_rows backend/tests/test_journal.py::test_policy_row_for_ref_is_agent_scoped -q
```

Expected: FAIL because policy view helpers do not exist.

- [ ] **Step 3: Add policy view types**

In `backend/app/brain/context.py`, add:

```python
@dataclass
class PolicyLine:
    ref: str
    content: str


@dataclass
class PolicyMemoryView:
    active: list[PolicyLine] = field(default_factory=list)
```

- [ ] **Step 4: Add journal helpers**

In `backend/app/brain/journal.py`, update imports and constants:

```python
from app.db.models import MemoryEntry
from app.brain.context import MemoryView, PolicyLine, PolicyMemoryView

NARRATIVE_SECTIONS = ("coin_theses", "trade_lessons", "strategy_notes")
SECTIONS = (*NARRATIVE_SECTIONS, "self_policy")
SECTION_CAPS = {"coin_theses": 8, "trade_lessons": 10, "strategy_notes": 5, "self_policy": 8}
```

Add helpers below `active_count`:

```python
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
```

- [ ] **Step 5: Keep runtime distillation on narrative sections only**

In `backend/app/agents/runtime.py`, change both reflection loops from `journal.SECTIONS` to `journal.NARRATIVE_SECTIONS`:

```python
                for section in journal.NARRATIVE_SECTIONS:
                    journal.append_entries(session, agent.id, section,
                                           getattr(rr.entries, section), cycle_id=cycle_id)
                session.add(Event(agent_id=agent.id, kind="reflection", cycle_id=cycle_id,
                                  message="memoria aggiornata dopo trade chiuso"))
                for section in journal.NARRATIVE_SECTIONS:
                    if journal.active_count(session, agent.id, section) > journal.SECTION_CAPS[section]:
```

- [ ] **Step 6: Run tests to verify they pass**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_journal.py backend/tests/test_runtime.py::test_reflection_runs_once_on_sell_and_persists backend/tests/test_runtime.py::test_distillation_runs_when_section_over_cap -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/brain/context.py backend/app/brain/journal.py backend/app/agents/runtime.py backend/tests/test_journal.py
git commit -m "feat: add self-policy journal view"
```

---

### Task 3: Trader Policy Accountability Schema and Prompt

**Files:**
- Modify: `backend/app/brain/context.py`
- Modify: `backend/app/brain/schema.py`
- Modify: `backend/app/brain/prompt.py`
- Modify: `backend/app/agents/runtime.py`
- Test: `backend/tests/test_brain_context.py`
- Test: `backend/tests/test_brain_schema.py`
- Test: `backend/tests/test_brain_trader_prompt.py`
- Test: `backend/tests/test_runtime.py`

**Interfaces:**
- Consumes: `PolicyMemoryView`
- Produces: `DecisionContext.policy: PolicyMemoryView`
- Produces: `Action.policy_refs: list[str]`
- Produces: `Action.policy_alignment: "follows" | "violates" | "unrelated"`
- Produces: `Action.override_reason: str`

- [ ] **Step 1: Write failing schema/context/prompt tests**

Add to `backend/tests/test_brain_schema.py`:

```python
def test_action_policy_fields_are_optional_for_old_json():
    raw = '{"actions":[{"type":"BUY","symbol":"BTCUSDT","usd_amount":"10","rationale":"dip"}],"note":"n"}'
    d = Decision.model_validate_json(raw)

    assert d.actions[0].policy_refs == []
    assert d.actions[0].policy_alignment == "unrelated"
    assert d.actions[0].override_reason == ""


def test_action_parses_policy_accountability_fields():
    raw = ('{"actions":[{"type":"BUY","symbol":"BTCUSDT","usd_amount":"10",'
           '"policy_refs":["P1"],"policy_alignment":"violates",'
           '"override_reason":"fresh catalyst","rationale":"override"}],"note":"n"}')
    d = Decision.model_validate_json(raw)

    assert d.actions[0].policy_refs == ["P1"]
    assert d.actions[0].policy_alignment == "violates"
    assert d.actions[0].override_reason == "fresh catalyst"


def test_action_rejects_invalid_policy_alignment():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Action(type="HOLD", policy_alignment="maybe")
```

Add to `backend/tests/test_brain_context.py`:

```python
def test_build_context_carries_policy_view():
    from app.brain.context import build_context, PolicyLine, PolicyMemoryView

    policy = PolicyMemoryView(active=[PolicyLine("P10", "Wait for fresh evidence.")])
    ctx = build_context(instructions="", cash_usd=Decimal("100"),
                        holdings=[], recent_events=[], policy=policy)

    assert ctx.policy.active[0].ref == "P10"
    assert ctx.policy.active[0].content == "Wait for fresh evidence."
```

Add to `backend/tests/test_brain_trader_prompt.py`:

```python
def test_trader_prompt_renders_self_policy_separately():
    from app.brain.context import PolicyLine, PolicyMemoryView

    ctx = build_context(instructions="favor blue chips", cash_usd=Decimal("100"),
                        holdings=[], recent_events=[], brief=_brief(),
                        policy=PolicyMemoryView(active=[
                            PolicyLine("P7", "Do not re-enter losers without fresh evidence.")
                        ]))

    system, user = render_trader_prompt(ctx)

    assert "Your self-policy:" in user
    assert "P7: Do not re-enter losers without fresh evidence." in user
    assert "policy_refs" in system
    assert "policy_alignment" in system
    assert "override_reason" in system
    assert "not server-side strategic enforcement" in system
```

Add to `backend/tests/test_runtime.py`:

```python
async def test_policy_violation_disclosure_does_not_block_valid_buy(db_session):
    agent = _llm_agent(db_session)
    snap = [CoinSnapshot("BTCUSDT", Decimal("100"), Decimal("1"))]
    market = FakeMarketLLM(snap, Decimal("100"), (Decimal("99"), Decimal("101")))
    decision = Decision(actions=[
        Action(type="BUY", symbol="BTCUSDT", usd_amount=Decimal("50"),
               rationale="override",
               policy_refs=["P999"], policy_alignment="violates",
               override_reason="fresh catalyst")
    ], note="buy anyway")

    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision))

    assert db_session.query(Trade).filter_by(agent_id=agent.id, side="BUY").count() == 1
    rec = db_session.query(DecisionRecord).filter_by(agent_id=agent.id, kind="decision").one()
    assert '"policy_refs":["P999"]' in rec.parsed_output
    assert '"policy_alignment":"violates"' in rec.parsed_output
    assert '"override_reason":"fresh catalyst"' in rec.parsed_output
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_brain_schema.py::test_action_policy_fields_are_optional_for_old_json backend/tests/test_brain_schema.py::test_action_parses_policy_accountability_fields backend/tests/test_brain_schema.py::test_action_rejects_invalid_policy_alignment backend/tests/test_brain_context.py::test_build_context_carries_policy_view backend/tests/test_brain_trader_prompt.py::test_trader_prompt_renders_self_policy_separately backend/tests/test_runtime.py::test_policy_violation_disclosure_does_not_block_valid_buy -q
```

Expected: FAIL because policy fields/context do not exist.

- [ ] **Step 3: Extend `Action` schema**

In `backend/app/brain/schema.py`, update `Action`:

```python
class Action(BaseModel):
    type: Literal["BUY", "SELL", "HOLD"]
    symbol: str | None = None
    usd_amount: Decimal | None = None
    fraction: Decimal | None = None
    rationale: str = ""
    policy_refs: list[str] = []
    policy_alignment: Literal["follows", "violates", "unrelated"] = "unrelated"
    override_reason: str = ""
```

- [ ] **Step 4: Extend decision context**

In `backend/app/brain/context.py`, add to `DecisionContext`:

```python
    policy: PolicyMemoryView
    brief_unavailable_reason: str | None = None
```

Update `build_context` signature and return:

```python
def build_context(*, instructions, cash_usd, holdings, recent_events, memory=None,
                  policy=None, brief=None, wake_reason=None, brief_unavailable_reason=None) -> DecisionContext:
    positions: list[PositionView] = []
    equity = cash_usd
    for symbol, quantity, avg_price, last_price in holdings:
        pnl = ((last_price - avg_price) / avg_price * Decimal("100")) if avg_price else Decimal("0")
        positions.append(PositionView(symbol, quantity, avg_price, last_price, pnl))
        equity += quantity * last_price
    return DecisionContext(
        instructions=instructions, cash_usd=cash_usd, equity_usd=equity,
        positions=positions, recent_events=recent_events,
        memory=memory or MemoryView(), policy=policy or PolicyMemoryView(),
        brief=brief, wake_reason=wake_reason,
        brief_unavailable_reason=brief_unavailable_reason,
    )
```

- [ ] **Step 5: Render policy and accountability contract**

In `backend/app/brain/prompt.py`, update the JSON contract in `_SYSTEM`:

```python
{{"actions": [{{"type": "BUY"|"SELL"|"HOLD", "symbol": "<SYMBOL or null>",
  "usd_amount": "<USD to spend on BUY, or null>", "fraction": "<0-1 of position to SELL, or null>",
  "rationale": "<one short sentence>",
  "policy_refs": ["<P123>"],
  "policy_alignment": "follows"|"violates"|"unrelated",
  "override_reason": "<required when policy_alignment is violates, otherwise empty>"}}],
  "note": "<one-line thesis for this cycle>"}}
```

Add after the memory block in `render_trader_prompt`:

```python
    if ctx.policy.active:
        system = system + (
            "\n\nYour self-policy below is your own prior reflection. "
            "Account for it in each action using policy_refs, policy_alignment, and override_reason. "
            "These fields are disclosures for later reflection, not server-side strategic enforcement."
        )
        lines += ["", "Your self-policy:"]
        for p in ctx.policy.active:
            lines.append(f"  - {p.ref}: {p.content}")
```

- [ ] **Step 6: Load policy in runtime context**

In `backend/app/agents/runtime.py`, update `assemble_trader_context`:

```python
    memory = journal.compact_view(session, agent.id)
    policy = journal.policy_view(session, agent.id)
    brief = filter_brief_for(brief_row, symbols) if brief_row is not None else None
    return build_context(instructions=agent.instructions, cash_usd=agent.cash_usd,
                         holdings=holdings, recent_events=recent,
                         memory=memory, policy=policy, brief=brief,
                         wake_reason=wake_reason)
```

- [ ] **Step 7: Run tests to verify they pass**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_brain_schema.py backend/tests/test_brain_context.py backend/tests/test_brain_trader_prompt.py backend/tests/test_runtime.py::test_policy_violation_disclosure_does_not_block_valid_buy -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/brain/context.py backend/app/brain/schema.py backend/app/brain/prompt.py backend/app/agents/runtime.py backend/tests/test_brain_context.py backend/tests/test_brain_schema.py backend/tests/test_brain_trader_prompt.py backend/tests/test_runtime.py
git commit -m "feat: disclose policy alignment in trader output"
```

---

### Task 4: Market Brief Freshness

**Files:**
- Modify: `backend/app/brain/brief_store.py`
- Modify: `backend/app/brain/context.py`
- Modify: `backend/app/brain/prompt.py`
- Modify: `backend/app/agents/runtime.py`
- Modify: `backend/app/agents/preview.py`
- Test: `backend/tests/test_brief_store.py`
- Test: `backend/tests/test_brain_trader_prompt.py`
- Test: `backend/tests/test_analyst_orchestration.py`

**Interfaces:**
- Consumes: `settings.market_brief_max_age_minutes`
- Produces: `BriefLookup(row: MarketBrief | None, unavailable_reason: str | None, has_valid: bool)`
- Produces: `brief_lookup_for_prompt(session, now=None) -> BriefLookup`

- [ ] **Step 1: Write failing freshness tests**

Add to `backend/tests/test_brief_store.py`:

```python
def test_brief_lookup_returns_fresh_valid_brief(db_session):
    from datetime import datetime, timezone, timedelta
    from app.brain.brief_store import brief_lookup_for_prompt

    row = persist_brief(db_session, "fresh", _result(regime="fresh"))
    row.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db_session.commit()

    lookup = brief_lookup_for_prompt(db_session, now=datetime.now(timezone.utc))

    assert lookup.row == row
    assert lookup.unavailable_reason is None
    assert lookup.has_valid is True


def test_brief_lookup_treats_stale_valid_brief_as_unavailable(db_session):
    from datetime import datetime, timezone, timedelta
    from app.brain.brief_store import brief_lookup_for_prompt

    row = persist_brief(db_session, "stale", _result(regime="stale"))
    row.created_at = datetime.now(timezone.utc) - timedelta(minutes=124)
    db_session.commit()

    lookup = brief_lookup_for_prompt(db_session, now=datetime.now(timezone.utc))

    assert lookup.row is None
    assert lookup.has_valid is True
    assert "stale by 124m" in lookup.unavailable_reason


def test_brief_lookup_ignores_failed_rows_for_freshness(db_session):
    from datetime import datetime, timezone, timedelta
    from app.db.models import MarketBrief
    from app.brain.brief_store import brief_lookup_for_prompt

    db_session.add(MarketBrief(cycle_id="bad", parsed_brief=None,
                               system_prompt="s", user_prompt="u", raw_response=None,
                               parse_status="failed", model_provider="openrouter",
                               model_name="m", latency_ms=1,
                               created_at=datetime.now(timezone.utc)))
    db_session.commit()

    lookup = brief_lookup_for_prompt(db_session, now=datetime.now(timezone.utc))

    assert lookup.row is None
    assert lookup.has_valid is False
    assert lookup.unavailable_reason is None
```

Add to `backend/tests/test_brain_trader_prompt.py`:

```python
def test_trader_prompt_reports_stale_brief_reason():
    ctx = build_context(instructions="", cash_usd=Decimal("100"), holdings=[],
                        recent_events=[],
                        brief=None,
                        brief_unavailable_reason="latest valid brief is stale by 124m")

    _system, user = render_trader_prompt(ctx)

    assert "Market brief: unavailable this cycle; latest valid brief is stale by 124m" in user
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_brief_store.py::test_brief_lookup_returns_fresh_valid_brief backend/tests/test_brief_store.py::test_brief_lookup_treats_stale_valid_brief_as_unavailable backend/tests/test_brief_store.py::test_brief_lookup_ignores_failed_rows_for_freshness backend/tests/test_brain_trader_prompt.py::test_trader_prompt_reports_stale_brief_reason -q
```

Expected: FAIL because freshness helpers and prompt reason do not exist.

- [ ] **Step 3: Add brief lookup helper**

In `backend/app/brain/brief_store.py`, add imports:

```python
from dataclasses import dataclass
from datetime import datetime, timezone
```

Add:

```python
@dataclass
class BriefLookup:
    row: MarketBrief | None
    unavailable_reason: str | None
    has_valid: bool


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
        return BriefLookup(row=None,
                           unavailable_reason=f"latest valid brief is stale by {age}m",
                           has_valid=True)
    return BriefLookup(row=row, unavailable_reason=None, has_valid=True)
```

- [ ] **Step 4: Render unavailable reason**

In `backend/app/brain/prompt.py`, replace the missing-brief block:

```python
    else:
        reason = f"; {ctx.brief_unavailable_reason}" if ctx.brief_unavailable_reason else ""
        lines += ["", f"Market brief: unavailable this cycle{reason}"]
```

- [ ] **Step 5: Use lookup in runtime without refreshing stale briefs**

In `backend/app/agents/runtime.py`, import `BriefLookup` and `brief_lookup_for_prompt`:

```python
from app.brain.brief_store import persist_brief, filter_brief_for, brief_lookup_for_prompt, BriefLookup
```

Update `build_trader_context` and `assemble_trader_context`:

```python
async def build_trader_context(session, agent, market, symbols, *, wake_reason=None):
    brief_lookup = await get_or_bootstrap_brief(session, market)
    return await assemble_trader_context(session, agent, market, symbols, brief_lookup,
                                         wake_reason=wake_reason)


async def assemble_trader_context(session, agent, market, symbols, brief_lookup, *, wake_reason=None):
    holdings = []
    for pos in agent.positions:
        last = await market.get_price(pos.symbol)
        holdings.append((pos.symbol, pos.quantity, pos.avg_price, last))
    recent = [e.message for e in (
        session.query(Event).filter_by(agent_id=agent.id)
        .order_by(Event.timestamp.desc()).limit(10).all())]
    memory = journal.compact_view(session, agent.id)
    policy = journal.policy_view(session, agent.id)
    brief = filter_brief_for(brief_lookup.row, symbols) if brief_lookup.row is not None else None
    return build_context(instructions=agent.instructions, cash_usd=agent.cash_usd,
                         holdings=holdings, recent_events=recent,
                         memory=memory, policy=policy, brief=brief,
                         wake_reason=wake_reason,
                         brief_unavailable_reason=brief_lookup.unavailable_reason)
```

Update `get_or_bootstrap_brief`:

```python
async def get_or_bootstrap_brief(session, market, *, run_cycle=None, now=None) -> BriefLookup:
    lookup = brief_lookup_for_prompt(session, now=now)
    if lookup.row is not None or lookup.has_valid:
        return lookup
    if run_cycle is None:
        run_cycle = run_analyst_cycle
    await run_cycle(session, market)
    return brief_lookup_for_prompt(session, now=now)
```

Update tests that pass a raw `MarketBrief` to `assemble_trader_context` by wrapping it:

```python
BriefLookup(row=brief_row, unavailable_reason=None, has_valid=True)
```

Update `backend/app/agents/preview.py` to keep preview read-only and compatible:

```python
from app.brain.brief_store import brief_lookup_for_prompt

brief_lookup = brief_lookup_for_prompt(session)          # read-only: niente bootstrap → niente LLM
ctx = await assemble_trader_context(session, agent, market, symbols, brief_lookup, wake_reason=None)
```

- [ ] **Step 6: Run tests to verify they pass**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_brief_store.py backend/tests/test_brain_trader_prompt.py backend/tests/test_analyst_orchestration.py backend/tests/test_preview.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/brain/brief_store.py backend/app/brain/context.py backend/app/brain/prompt.py backend/app/agents/runtime.py backend/app/agents/preview.py backend/tests/test_brief_store.py backend/tests/test_brain_trader_prompt.py backend/tests/test_analyst_orchestration.py backend/tests/test_preview.py
git commit -m "feat: surface stale market briefs as unavailable"
```

---

### Task 5: Reflection Policy Edits

**Files:**
- Modify: `backend/app/brain/memory.py`
- Modify: `backend/app/brain/journal.py`
- Test: `backend/tests/test_brain_memory.py`
- Test: `backend/tests/test_journal.py`

**Interfaces:**
- Consumes: `PolicyMemoryView`
- Produces: `PolicyEdit(op, policy_ref, text, reason)`
- Produces: `MemoryUpdate.policy_edits: list[PolicyEdit]`
- Produces: `journal.apply_memory_update(session, agent_id, update, cycle_id=None) -> None`

- [ ] **Step 1: Write failing parser and journal tests**

Add to `backend/tests/test_brain_memory.py`:

```python
def test_parse_reflection_reads_policy_edits():
    raw = ('{"coin_theses": [], "trade_lessons": [], "strategy_notes": [], '
           '"policy_edits": [{"op": "add", "text": "Wait for fresh evidence.", "reason": "Churn hurt."}]}')

    update = parse_reflection(raw)

    assert update.policy_edits[0].op == "add"
    assert update.policy_edits[0].text == "Wait for fresh evidence."
    assert update.policy_edits[0].reason == "Churn hurt."


def test_build_reflection_prompt_shows_self_policy():
    from app.brain.context import PolicyLine, PolicyMemoryView

    mem = MemoryView(coin_theses="BTC: old view")
    policy = PolicyMemoryView(active=[PolicyLine("P3", "Avoid re-entry without fresh evidence.")])
    closed = [ClosedTrade("BTCUSDT", Decimal("1"), Decimal("120"), Decimal("100"), Decimal("20"))]

    system, user = build_reflection_prompt(mem, policy, closed, ["ETHUSDT"], "be bold")

    assert "policy_edits" in system
    assert "P3: Avoid re-entry without fresh evidence." in user
```

Add to `backend/tests/test_journal.py`:

```python
def test_apply_memory_update_adds_policy(db_session):
    from app.brain.memory import MemoryUpdate, PolicyEdit

    a = _agent(db_session)
    update = MemoryUpdate(policy_edits=[
        PolicyEdit(op="add", text="Wait for fresh evidence.", reason="Churn hurt.")
    ])

    journal.apply_memory_update(db_session, a.id, update, cycle_id="c1")
    db_session.commit()

    rows = journal.active_entries(db_session, a.id, "self_policy")
    assert [r.content for r in rows] == ["Wait for fresh evidence."]
    assert rows[0].cycle_id == "c1"


def test_apply_memory_update_retires_policy_without_deleting(db_session):
    from app.brain.memory import MemoryUpdate, PolicyEdit

    a = _agent(db_session)
    journal.append_entries(db_session, a.id, "self_policy", ["old policy"])
    db_session.commit()
    row = journal.active_entries(db_session, a.id, "self_policy")[0]

    update = MemoryUpdate(policy_edits=[
        PolicyEdit(op="retire", policy_ref=f"P{row.id}", reason="No longer useful.")
    ])
    journal.apply_memory_update(db_session, a.id, update, cycle_id="c2")
    db_session.commit()

    assert journal.active_entries(db_session, a.id, "self_policy") == []
    assert db_session.query(MemoryEntry).filter_by(id=row.id).one().active is False


def test_apply_memory_update_rejects_invalid_policy_ref_without_partial_memory(db_session):
    import pytest
    from app.brain.memory import MemoryUpdate, PolicyEdit

    a = _agent(db_session)
    update = MemoryUpdate(coin_theses=["BTC: new"], policy_edits=[
        PolicyEdit(op="retire", policy_ref="P999", reason="bad ref")
    ])

    with pytest.raises(ValueError):
        journal.apply_memory_update(db_session, a.id, update, cycle_id="c3")

    assert journal.active_entries(db_session, a.id, "coin_theses") == []
    assert journal.active_entries(db_session, a.id, "self_policy") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_brain_memory.py::test_parse_reflection_reads_policy_edits backend/tests/test_brain_memory.py::test_build_reflection_prompt_shows_self_policy backend/tests/test_journal.py::test_apply_memory_update_adds_policy backend/tests/test_journal.py::test_apply_memory_update_retires_policy_without_deleting backend/tests/test_journal.py::test_apply_memory_update_rejects_invalid_policy_ref_without_partial_memory -q
```

Expected: FAIL because policy edits and `apply_memory_update` do not exist.

- [ ] **Step 3: Extend reflection models and prompt**

In `backend/app/brain/memory.py`, add `Literal` import:

```python
from typing import Literal
```

Add:

```python
class PolicyEdit(BaseModel):
    op: Literal["add", "retire", "replace"]
    policy_ref: str | None = None
    text: str = ""
    reason: str = ""
```

Update `MemoryUpdate`:

```python
class MemoryUpdate(BaseModel):
    coin_theses: list[str] = []
    trade_lessons: list[str] = []
    strategy_notes: list[str] = []
    policy_edits: list[PolicyEdit] = []
```

Update `_REFLECT_SYSTEM` JSON shape to include:

```text
  "policy_edits": [{"op": "add"|"retire"|"replace", "policy_ref": "<P123 or null>", "text": "<new policy text or empty>", "reason": "<short factual reason>"}]
```

Change `build_reflection_prompt` signature and body:

```python
def build_reflection_prompt(memory: MemoryView, policy: PolicyMemoryView, closed: list[ClosedTrade],
                            held_symbols: list[str], instructions: str) -> tuple[str, str]:
    system = _REFLECT_SYSTEM.format(instructions=instructions or "(none provided)")
    lines = ["Closed trades this cycle:"]
    for t in closed:
        lines.append(f"  {t.symbol}: sold {t.qty} @ ${t.sell_price} "
                     f"(avg cost ${t.avg_cost}, realized {t.realized_pnl_pct:+.2f}%)")
    lines += ["", f"Currently held: {', '.join(held_symbols) or '(none)'}", "", "Current memory:"]
    for label, text in (("Coin theses", memory.coin_theses),
                        ("Trade lessons", memory.trade_lessons),
                        ("Strategy notes", memory.strategy_notes)):
        lines.append(f"{label}:")
        lines += [f"  - {l}" for l in text.splitlines() if l.strip()] or ["  (none)"]
    lines += ["", "Current self-policy:"]
    if policy.active:
        lines += [f"  - {p.ref}: {p.content}" for p in policy.active]
    else:
        lines += ["  (none)"]
    return system, "\n".join(lines)
```

Update `run_reflection_result` to accept policy:

```python
def run_reflection_result(memory: MemoryView, policy: PolicyMemoryView, closed: list[ClosedTrade],
                          held_symbols: list[str], instructions: str, adapter) -> ReflectionResult:
    system, user = build_reflection_prompt(memory, policy, closed, held_symbols, instructions)
```

Update existing `backend/tests/test_brain_memory.py` calls to pass an empty policy view:

```python
from app.brain.context import MemoryView, PolicyMemoryView

system, user = build_reflection_prompt(mem, PolicyMemoryView(), closed, ["ETHUSDT"], "be bold")
r = run_reflection_result(MemoryView(), PolicyMemoryView(), [], [], "x", FakeAdapter())
```

- [ ] **Step 4: Apply memory updates atomically in journal**

In `backend/app/brain/journal.py`, import under `TYPE_CHECKING` to avoid runtime cycles:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.brain.memory import MemoryUpdate, PolicyEdit
```

Add:

```python
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
            row.active = False
        elif edit.op == "replace":
            row = policy_row_for_ref(session, agent_id, edit.policy_ref or "")
            row.active = False
            append_entries(session, agent_id, "self_policy", [edit.text], cycle_id=cycle_id)


def apply_memory_update(session, agent_id: int, update: "MemoryUpdate",
                        cycle_id: str | None = None) -> None:
    _validate_policy_edits(session, agent_id, update.policy_edits)
    for section in NARRATIVE_SECTIONS:
        append_entries(session, agent_id, section, getattr(update, section), cycle_id=cycle_id)
    _apply_policy_edits(session, agent_id, update.policy_edits, cycle_id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_brain_memory.py backend/tests/test_journal.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/brain/memory.py backend/app/brain/journal.py backend/tests/test_brain_memory.py backend/tests/test_journal.py
git commit -m "feat: allow llm-authored policy edits"
```

---

### Task 6: Runtime Reflection Applies Memory and Policy Atomically

**Files:**
- Modify: `backend/app/agents/runtime.py`
- Modify: `backend/app/agents/preview.py`
- Test: `backend/tests/test_runtime.py`
- Test: `backend/tests/test_preview.py`

**Interfaces:**
- Consumes: `DecisionContext.policy`
- Consumes: `journal.apply_memory_update`
- Produces: reflection calls with signature `reflect(memory, policy, closed, held_symbols, instructions, adapter)`

- [ ] **Step 1: Update runtime tests for policy-aware reflection**

In `backend/tests/test_runtime.py`, update fake reflection functions that use explicit args from:

```python
def fake_reflect(memory, closed, held_symbols, instructions, adapter):
```

to:

```python
def fake_reflect(memory, policy, closed, held_symbols, instructions, adapter):
```

Add:

```python
async def test_reflection_can_add_self_policy_on_sell(db_session):
    agent = _llm_agent(db_session)
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("2"))]
    market = FakeMarketLLM(snap, Decimal("120"), (Decimal("120"), Decimal("121")))
    decision = Decision(actions=[Action(type="SELL", symbol="BTCUSDT", fraction=Decimal("1"))], note="exit")

    def fake_reflect(memory, policy, closed, held_symbols, instructions, adapter):
        from app.brain.memory import PolicyEdit
        return ReflectionResult(MemoryUpdate(policy_edits=[
            PolicyEdit(op="add", text="Wait for fresh evidence before re-entry.", reason="Churn hurt.")
        ]))

    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision),
                       reflect=fake_reflect)

    rows = journal.active_entries(db_session, agent.id, "self_policy")
    assert [r.content for r in rows] == ["Wait for fresh evidence before re-entry."]


async def test_invalid_policy_edit_leaves_reflection_memory_unchanged(db_session):
    agent = _llm_agent(db_session)
    journal.append_entries(db_session, agent.id, "coin_theses", ["BTC: keep"])
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.commit()
    snap = [CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("2"))]
    market = FakeMarketLLM(snap, Decimal("120"), (Decimal("120"), Decimal("121")))
    decision = Decision(actions=[Action(type="SELL", symbol="BTCUSDT", fraction=Decimal("1"))], note="exit")

    def fake_reflect(memory, policy, closed, held_symbols, instructions, adapter):
        from app.brain.memory import PolicyEdit
        return ReflectionResult(MemoryUpdate(coin_theses=["BTC: should not apply"],
                                             policy_edits=[PolicyEdit(op="retire", policy_ref="P999",
                                                                      reason="bad ref")]))

    await run_decision(db_session, agent, market, ["BTCUSDT"],
                       brain_decide=lambda ctx, adapter: DecisionResult(decision),
                       reflect=fake_reflect)

    assert [r.content for r in journal.active_entries(db_session, agent.id, "coin_theses")] == ["BTC: keep"]
    assert journal.active_entries(db_session, agent.id, "self_policy") == []
    ev = db_session.query(Event).filter_by(agent_id=agent.id, kind="reflection").order_by(Event.id.desc()).first()
    assert "errore" in ev.message.lower() or "invalid" in ev.message.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_runtime.py::test_reflection_can_add_self_policy_on_sell backend/tests/test_runtime.py::test_invalid_policy_edit_leaves_reflection_memory_unchanged -q
```

Expected: FAIL because runtime does not pass policy or apply policy edits.

- [ ] **Step 3: Update runtime reflection call**

In `backend/app/agents/runtime.py`, replace the reflection call and memory application block:

```python
            rr = reflect(ctx.memory, ctx.policy, closed_trades, held_symbols, agent.instructions, adapter)
            _record_llm_call(session, agent, cycle_id, "reflection", trigger,
                             system=rr.system, user=rr.user, raw=rr.raw,
                             parsed_output=(rr.entries.model_dump_json()
                                            if rr.parse_status == "ok" else None),
                             parse_status=rr.parse_status, latency_ms=rr.latency_ms)
            if rr.parse_status == "ok":
                journal.apply_memory_update(session, agent.id, rr.entries, cycle_id=cycle_id)
                session.add(Event(agent_id=agent.id, kind="reflection", cycle_id=cycle_id,
                                  message="memoria aggiornata dopo trade chiuso"))
                for section in journal.NARRATIVE_SECTIONS:
                    if journal.active_count(session, agent.id, section) > journal.SECTION_CAPS[section]:
```

Leave the existing distillation block on `journal.NARRATIVE_SECTIONS`.

- [ ] **Step 4: Update preview reflection prompt**

In `backend/app/agents/preview.py`, load policy and pass it:

```python
policy = journal.policy_view(session, agent.id)
r_system, r_user = build_reflection_prompt(ctx.memory, policy, closed, held_symbols, agent.instructions)
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_runtime.py backend/tests/test_preview.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/runtime.py backend/app/agents/preview.py backend/tests/test_runtime.py backend/tests/test_preview.py
git commit -m "feat: apply reflection policy edits in runtime"
```

---

### Task 7: Pure Outcome Reflection Prompt

**Files:**
- Create: `backend/app/brain/learning.py`
- Test: `backend/tests/test_brain_learning.py`

**Interfaces:**
- Consumes: `MemoryView`
- Consumes: `PolicyMemoryView`
- Produces: `ScoredActionEvidence`
- Produces: `OutcomeReflectionEvidence`
- Produces: `build_outcome_reflection_prompt(evidence, memory, policy, instructions) -> tuple[str, str]`
- Produces: `run_outcome_reflection_result(evidence, memory, policy, instructions, adapter) -> ReflectionResult`

- [ ] **Step 1: Write failing pure learning tests**

Create `backend/tests/test_brain_learning.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal
from app.brain.context import MemoryView, PolicyLine, PolicyMemoryView
from app.brain.learning import (
    OutcomeReflectionEvidence, ScoredActionEvidence,
    build_outcome_reflection_prompt, run_outcome_reflection_result,
)


def test_outcome_reflection_prompt_contains_raw_facts_not_judgment():
    evidence = OutcomeReflectionEvidence(agent_id=1, scores=[
        ScoredActionEvidence(
            decision_record_id=10,
            score_id=20,
            window="24h",
            created_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            n_actions=2,
            n_hits=1,
            avg_return_pct=Decimal("1.25"),
            actions=[{"type": "BUY", "symbol": "BTCUSDT",
                      "policy_refs": ["P3"], "policy_alignment": "violates",
                      "override_reason": "fresh catalyst", "rationale": "news"}],
        )
    ])
    policy = PolicyMemoryView(active=[PolicyLine("P3", "Avoid re-entry without fresh evidence.")])

    system, user = build_outcome_reflection_prompt(evidence, MemoryView(), policy, "be careful")

    assert "raw factual evidence" in system.lower()
    assert "do not blacklist" in system.lower()
    assert "BTCUSDT" in user
    assert "policy_alignment=violates" in user
    assert "avg_return_pct=1.25" in user
    assert "P3: Avoid re-entry without fresh evidence." in user


def test_run_outcome_reflection_result_parses_memory_update():
    evidence = OutcomeReflectionEvidence(agent_id=1, scores=[])

    class FakeAdapter:
        def complete_json(self, system, user):
            return '{"coin_theses":[],"trade_lessons":["Outcome review: wait."],"strategy_notes":[],"policy_edits":[]}'

    result = run_outcome_reflection_result(evidence, MemoryView(), PolicyMemoryView(), "x", FakeAdapter())

    assert result.parse_status == "ok"
    assert result.entries.trade_lessons == ["Outcome review: wait."]
    assert result.raw is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_brain_learning.py -q
```

Expected: FAIL because `backend/app/brain/learning.py` does not exist.

- [ ] **Step 3: Implement pure learning module**

Create `backend/app/brain/learning.py`:

```python
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from time import perf_counter
from app.brain.context import MemoryView, PolicyMemoryView
from app.brain.memory import MemoryUpdate, ReflectionResult, parse_reflection


@dataclass
class ScoredActionEvidence:
    decision_record_id: int
    score_id: int
    window: str
    created_at: datetime
    n_actions: int
    n_hits: int
    avg_return_pct: Decimal | None
    actions: list[dict]


@dataclass
class OutcomeReflectionEvidence:
    agent_id: int
    scores: list[ScoredActionEvidence]


_OUTCOME_REFLECT_SYSTEM = """You are the reflective memory of an autonomous paper-trading agent.
You are reviewing raw factual evidence from matured decision scores. These are facts, not judgments.
Decide what they mean, if anything, for your future behavior and self-policy.
Do not blacklist symbols. Do not create hard cooldown rules unless you explicitly choose them as your own self-policy.
Output ONLY a JSON object of this exact shape:
{{"coin_theses": ["<one-line new thesis>"],
  "trade_lessons": ["<one-line new lesson>"],
  "strategy_notes": ["<one-line behavior observation>"],
  "policy_edits": [{{"op": "add"|"retire"|"replace", "policy_ref": "<P123 or null>", "text": "<new policy text or empty>", "reason": "<short factual reason>"}}]}}
Output JSON only, no prose.

The agent's operator instructions:
{instructions}"""


def build_outcome_reflection_prompt(evidence: OutcomeReflectionEvidence, memory: MemoryView,
                                    policy: PolicyMemoryView, instructions: str) -> tuple[str, str]:
    system = _OUTCOME_REFLECT_SYSTEM.format(instructions=instructions or "(none provided)")
    lines = [f"Agent id: {evidence.agent_id}", "", "Matured decision-score facts:"]
    for score in evidence.scores:
        avg = "null" if score.avg_return_pct is None else str(score.avg_return_pct)
        lines.append(
            f"  score_id={score.score_id} decision_record_id={score.decision_record_id} "
            f"window={score.window} created_at={score.created_at.isoformat()} "
            f"n_actions={score.n_actions} n_hits={score.n_hits} avg_return_pct={avg}"
        )
        for action in score.actions:
            lines.append(
                "    action="
                + json.dumps(action, sort_keys=True, default=str)
            )
    lines += ["", "Current memory:"]
    for label, text in (("Coin theses", memory.coin_theses),
                        ("Trade lessons", memory.trade_lessons),
                        ("Strategy notes", memory.strategy_notes)):
        lines.append(f"{label}:")
        lines += [f"  - {l}" for l in text.splitlines() if l.strip()] or ["  (none)"]
    lines += ["", "Current self-policy:"]
    lines += [f"  - {p.ref}: {p.content}" for p in policy.active] or ["  (none)"]
    return system, "\n".join(lines)


def run_outcome_reflection_result(evidence: OutcomeReflectionEvidence, memory: MemoryView,
                                  policy: PolicyMemoryView, instructions: str, adapter) -> ReflectionResult:
    system, user = build_outcome_reflection_prompt(evidence, memory, policy, instructions)
    t0 = perf_counter()
    try:
        raw = adapter.complete_json(system, user)
    except Exception:
        return ReflectionResult(MemoryUpdate(), system, user, None, "failed",
                                int((perf_counter() - t0) * 1000))
    try:
        entries = parse_reflection(raw)
        return ReflectionResult(entries, system, user, raw, "ok",
                                int((perf_counter() - t0) * 1000))
    except Exception:
        return ReflectionResult(MemoryUpdate(), system, user, raw, "failed",
                                int((perf_counter() - t0) * 1000))
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_brain_learning.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/brain/learning.py backend/tests/test_brain_learning.py
git commit -m "feat: build outcome reflection prompt"
```

---

### Task 8: Post-Scoring Learning Tick

**Files:**
- Create: `backend/app/agents/learning.py`
- Modify: `backend/app/scheduler/jobs.py`
- Test: `backend/tests/test_learning_job.py`
- Test: `backend/tests/test_scheduler_jobs.py`

**Interfaces:**
- Consumes: `DecisionScore.reflected_at`
- Consumes: `run_outcome_reflection_result`
- Produces: `reflect_unlearned_scores(session, adapter_factory=make_adapter, now=None) -> int`
- Produces: scheduler `_learning_tick()`

- [ ] **Step 1: Write failing learning orchestration tests**

Create `backend/tests/test_learning_job.py`:

```python
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from app.agents.learning import reflect_unlearned_scores
from app.brain.memory import MemoryUpdate, ReflectionResult, PolicyEdit
from app.db.models import Agent, DecisionRecord, DecisionScore, MemoryEntry
from app.brain import journal


def _agent(session):
    a = Agent(name="L", duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("100"), model_name="m")
    session.add(a); session.commit()
    return a


def _scored_decision(session, agent_id):
    rec = DecisionRecord(agent_id=agent_id, cycle_id="c", kind="decision", trigger="schedule",
                         system_prompt="s", user_prompt="u", raw_response="r",
                         parsed_output=('{"actions":[{"type":"BUY","symbol":"BTCUSDT",'
                                        '"policy_refs":["P1"],"policy_alignment":"violates",'
                                        '"override_reason":"fresh catalyst","rationale":"news"}]}'),
                         parse_status="ok", model_provider="openrouter", model_name="m", latency_ms=1)
    rec.created_at = datetime.now(timezone.utc) - timedelta(days=2)
    session.add(rec); session.commit()
    score = DecisionScore(decision_record_id=rec.id, window="24h",
                          n_actions=1, n_hits=0, avg_return_pct=Decimal("-2.5"))
    session.add(score); session.commit()
    return rec, score


async def test_reflect_unlearned_scores_applies_memory_and_marks_scores(db_session):
    agent = _agent(db_session)
    _rec, score = _scored_decision(db_session, agent.id)
    calls = []

    def fake_run(evidence, memory, policy, instructions, adapter):
        calls.append(evidence)
        return ReflectionResult(MemoryUpdate(
            trade_lessons=["Outcome review: override failed."],
            policy_edits=[PolicyEdit(op="add", text="Require fresh evidence before overrides.",
                                     reason="A violating BUY scored poorly.")]
        ), system="SYS", user="USR", raw='{"trade_lessons":["Outcome review: override failed."],"policy_edits":[]}',
           parse_status="ok", latency_ms=3)

    n = await reflect_unlearned_scores(db_session, run=fake_run,
                                       adapter_factory=lambda provider, model: object())

    assert n == 1
    assert calls[0].scores[0].score_id == score.id
    assert db_session.query(DecisionScore).filter_by(id=score.id).one().reflected_at is not None
    assert [r.content for r in journal.active_entries(db_session, agent.id, "trade_lessons")] == [
        "Outcome review: override failed."
    ]
    assert [r.content for r in journal.active_entries(db_session, agent.id, "self_policy")] == [
        "Require fresh evidence before overrides."
    ]
    rr = db_session.query(DecisionRecord).filter_by(agent_id=agent.id, kind="reflection", trigger="scoring").one()
    assert rr.system_prompt == "SYS" and rr.user_prompt == "USR" and rr.latency_ms == 3


async def test_reflect_unlearned_scores_does_not_repeat_reflected_scores(db_session):
    agent = _agent(db_session)
    _rec, score = _scored_decision(db_session, agent.id)
    score.reflected_at = datetime.now(timezone.utc)
    db_session.commit()

    calls = []
    n = await reflect_unlearned_scores(db_session,
                                       run=lambda *a, **k: calls.append(1) or ReflectionResult(MemoryUpdate()),
                                       adapter_factory=lambda provider, model: object())

    assert n == 0
    assert calls == []


async def test_reflect_unlearned_scores_failure_leaves_score_unreflected(db_session):
    agent = _agent(db_session)
    _rec, score = _scored_decision(db_session, agent.id)

    def failed(*a, **k):
        return ReflectionResult(MemoryUpdate(), system="SYS", user="USR", raw="bad",
                                parse_status="failed", latency_ms=2)

    n = await reflect_unlearned_scores(db_session, run=failed,
                                       adapter_factory=lambda provider, model: object())

    assert n == 0
    assert db_session.query(DecisionScore).filter_by(id=score.id).one().reflected_at is None
    assert db_session.query(MemoryEntry).filter_by(agent_id=agent.id).count() == 0
    assert db_session.query(DecisionRecord).filter_by(agent_id=agent.id, kind="reflection",
                                                      trigger="scoring").one().parse_status == "failed"
```

Add to `backend/tests/test_scheduler_jobs.py`:

```python
async def test_learning_tick_reflects_after_scoring(db_session, monkeypatch):
    calls = []

    async def fake_reflect(session):
        calls.append(session)
        return 1

    monkeypatch.setattr(jobs, "get_session", lambda: _CtxSession(db_session))
    monkeypatch.setattr(jobs, "reflect_unlearned_scores", fake_reflect)

    await jobs._learning_tick()

    assert calls == [db_session]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_learning_job.py backend/tests/test_scheduler_jobs.py::test_learning_tick_reflects_after_scoring -q
```

Expected: FAIL because `app.agents.learning` and `_learning_tick` do not exist.

- [ ] **Step 3: Implement learning orchestrator**

Create `backend/app/agents/learning.py`:

```python
import json
from datetime import datetime, timezone
from uuid import uuid4
from app.brain import journal
from app.brain.learning import OutcomeReflectionEvidence, ScoredActionEvidence, run_outcome_reflection_result
from app.brain.providers import make_adapter
from app.db.models import Agent, DecisionRecord, DecisionScore


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _actions(parsed_output: str | None) -> list[dict]:
    try:
        return list(json.loads(parsed_output or "{}").get("actions", []))
    except Exception:
        return []


def _unreflected_scores(session) -> list[tuple[Agent, DecisionRecord, DecisionScore]]:
    rows = (session.query(Agent, DecisionRecord, DecisionScore)
            .join(DecisionRecord, DecisionRecord.agent_id == Agent.id)
            .join(DecisionScore, DecisionScore.decision_record_id == DecisionRecord.id)
            .filter(DecisionRecord.kind == "decision",
                    DecisionRecord.parse_status.in_(("ok", "repaired")),
                    DecisionScore.reflected_at.is_(None))
            .order_by(Agent.id.asc(), DecisionScore.scored_at.asc(), DecisionScore.id.asc())
            .all())
    return rows


async def reflect_unlearned_scores(session, *, run=run_outcome_reflection_result,
                                   adapter_factory=make_adapter, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    rows = _unreflected_scores(session)
    by_agent: dict[int, list[tuple[Agent, DecisionRecord, DecisionScore]]] = {}
    for agent, rec, score in rows:
        by_agent.setdefault(agent.id, []).append((agent, rec, score))

    reflected = 0
    for agent_id, grouped in by_agent.items():
        agent = grouped[0][0]
        evidence = OutcomeReflectionEvidence(agent_id=agent_id, scores=[
            ScoredActionEvidence(
                decision_record_id=rec.id,
                score_id=score.id,
                window=score.window,
                created_at=_as_utc(rec.created_at),
                n_actions=score.n_actions,
                n_hits=score.n_hits,
                avg_return_pct=score.avg_return_pct,
                actions=_actions(rec.parsed_output),
            )
            for _agent, rec, score in grouped
        ])
        cycle_id = uuid4().hex
        adapter = adapter_factory(agent.model_provider, agent.model_name)
        memory = journal.compact_view(session, agent_id)
        policy = journal.policy_view(session, agent_id)
        result = run(evidence, memory, policy, agent.instructions, adapter)
        session.add(DecisionRecord(
            agent_id=agent_id, cycle_id=cycle_id, kind="reflection", trigger="scoring",
            system_prompt=result.system, user_prompt=result.user, raw_response=result.raw,
            parsed_output=(result.entries.model_dump_json() if result.parse_status == "ok" else None),
            parse_status=result.parse_status,
            model_provider=agent.model_provider, model_name=agent.model_name,
            latency_ms=result.latency_ms))
        if result.parse_status != "ok":
            session.commit()
            continue
        try:
            journal.apply_memory_update(session, agent_id, result.entries, cycle_id=cycle_id)
        except Exception:
            session.rollback()
            session.add(DecisionRecord(
                agent_id=agent_id, cycle_id=cycle_id, kind="reflection", trigger="scoring",
                system_prompt=result.system, user_prompt=result.user, raw_response=result.raw,
                parsed_output=None, parse_status="failed",
                model_provider=agent.model_provider, model_name=agent.model_name,
                latency_ms=result.latency_ms))
            session.commit()
            continue
        for _agent, _rec, score in grouped:
            score.reflected_at = now
            reflected += 1
        session.commit()
    return reflected
```

- [ ] **Step 4: Add scheduler tick**

In `backend/app/scheduler/jobs.py`, import:

```python
from app.agents.learning import reflect_unlearned_scores
```

Add:

```python
async def _learning_tick():
    with get_session() as session:
        try:
            await reflect_unlearned_scores(session)
        except Exception as exc:
            logger.error("learning tick failed: %s", exc)
            session.rollback()
```

Update `start_scheduler`:

```python
    _scheduler.add_job(_learning_tick, "interval", seconds=settings.scoring_seconds)
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_learning_job.py backend/tests/test_scheduler_jobs.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/learning.py backend/app/scheduler/jobs.py backend/tests/test_learning_job.py backend/tests/test_scheduler_jobs.py
git commit -m "feat: reflect on matured decision scores"
```

---

### Task 9: API/Auth Visibility and Backward Compatibility

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api.py`
- Test: `backend/tests/test_auth.py`
- Test: `backend/tests/test_scoring_job.py`

**Interfaces:**
- Consumes: existing `/api/agents/{id}/memory/journal`
- Produces: no policy mutation endpoint

- [ ] **Step 1: Write compatibility tests**

Add to `backend/tests/test_api.py`:

```python
def test_memory_journal_includes_self_policy_entries(db_session):
    from datetime import datetime, timezone, timedelta
    from decimal import Decimal
    from app.brain import journal
    from app.db.models import Agent

    agent = Agent(name="Policy API", duration_start=datetime.now(timezone.utc),
                  duration_end=datetime.now(timezone.utc) + timedelta(days=1),
                  cash_usd=Decimal("100"))
    db_session.add(agent); db_session.commit()
    journal.append_entries(db_session, agent.id, "self_policy", ["Wait for evidence."])
    db_session.commit()
    client = _client(db_session)

    r = client.get(f"/api/agents/{agent.id}/memory/journal")

    assert r.status_code == 200
    body = r.json()
    assert body[0]["section"] == "self_policy"
    assert body[0]["content"] == "Wait for evidence."
```

Add to `backend/tests/test_auth.py`:

```python
def test_no_policy_mutation_endpoint_exists(client):
    assert client.post("/api/agents/1/memory/policy", json={}).status_code == 404
```

Add to `backend/tests/test_scoring_job.py`:

```python
async def test_scoring_ignores_policy_accountability_fields(db_session):
    agent = _agent(db_session)
    made = datetime.now(timezone.utc) - timedelta(days=8)
    rec = _decision(
        db_session, agent.id, made,
        actions_json=('{"actions":[{"type":"BUY","symbol":"BTCUSDT",'
                      '"policy_refs":["P1"],"policy_alignment":"violates",'
                      '"override_reason":"fresh catalyst"}]}')
    )

    n = await score_matured_decisions(db_session, FakePriceMarket({}, default=Decimal("100")),
                                      datetime.now(timezone.utc))

    assert n == 2
    assert db_session.query(DecisionScore).filter_by(decision_record_id=rec.id).count() == 2
```

- [ ] **Step 2: Run tests**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_api.py::test_memory_journal_includes_self_policy_entries backend/tests/test_auth.py::test_no_policy_mutation_endpoint_exists backend/tests/test_scoring_job.py::test_scoring_ignores_policy_accountability_fields -q
```

Expected: PASS. The existing journal endpoint already returns `MemoryEntry` rows, so no API code should be necessary.

- [ ] **Step 3: Commit tests**

```bash
git add backend/tests/test_api.py backend/tests/test_auth.py backend/tests/test_scoring_job.py
git commit -m "test: cover policy visibility and scoring compatibility"
```

---

### Task 10: Final Verification

**Files:**
- Review: all files changed by Tasks 1-9

**Interfaces:**
- Consumes: all previous task outputs
- Produces: verified branch ready for review

- [ ] **Step 1: Run backend tests**

Run:

```bash
backend/.venv/bin/pytest backend/tests -q
```

Expected: all backend tests pass.

- [ ] **Step 2: Run Alembic upgrade/downgrade smoke test**

Run the repo's existing migration smoke pattern if available. If there is no helper, run:

```bash
cd backend && DATABASE_URL=sqlite:////tmp/crypto_bot_learning_migration.db .venv/bin/alembic upgrade head
```

Expected: command exits 0 and creates the latest schema.

Then run:

```bash
cd backend && DATABASE_URL=sqlite:////tmp/crypto_bot_learning_migration.db .venv/bin/alembic downgrade c89a7674625e
```

Expected: command exits 0 and removes `decision_scores.reflected_at`.

- [ ] **Step 3: Inspect git diff for forbidden behavior**

Run:

```bash
rg "blacklist|cooldown|block.*policy|policy.*block|skip.*policy|salience|risk manager" backend/app backend/tests
```

Expected: no runtime enforcement code. Prompt/test text may mention "blacklist" or "cooldown" only as prohibited behavior.

- [ ] **Step 4: Commit final fixes if needed**

If verification required fixes:

```bash
git add backend/app backend/tests backend/alembic
git commit -m "fix: finalize behavioral learning loop"
```

If no fixes were needed, do not create an empty commit.

- [ ] **Step 5: Summarize implementation**

Prepare a concise summary with:

- Behavioral learning loop implemented through memory, policy, and outcome reflection.
- Runtime still enforces only physical trade validity.
- Stale briefs are unavailable with exact age.
- Test command results.
