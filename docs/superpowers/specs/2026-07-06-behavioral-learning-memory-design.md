# Behavioral Learning Through Memory and Reflection - Design Spec

**Date:** 2026-07-06
**Status:** Draft, awaiting user review
**Type:** Feature design - agent learning loop

## Goal

Let an autonomous LLM trading agent improve its behavior over time by accumulating
experience in persistent memory and reflecting on factual outcomes.

This is not model training, fine-tuning, or an expert system. The system stores facts,
computes raw outcomes, retrieves evidence, and persists LLM-authored memory. The LLM
remains the trader, semantic evaluator, and owner of its self-policy.

## Assumptions

- The current memory implementation is the append-only `memory_entries` journal, not
  the older three-row `agent_memory` table.
- `DecisionRecord` already stores prompts, parsed decision JSON, model metadata, and
  reflection calls.
- `DecisionScore` already computes factual 24h/7d decision outcomes, but those facts
  do not currently feed the trader or reflection loop.
- Existing runtime guardrails continue to enforce only physical validity: cash, fee,
  min trade, universe membership, and held-position sells.
- The stale market brief issue is factual plumbing and can be fixed without adding
  strategic runtime rules.

## Boundary

System responsibilities:

- Persist prompts, parsed decisions, trades, memory entries, market briefs, and scores.
- Compute raw numeric facts: realized P&L, decision windows, hit counts, average returns,
  brief age, and whether the LLM referenced a policy ID in its own output.
- Retrieve bounded evidence for reflection.
- Apply explicit LLM-produced memory and policy edits.

LLM responsibilities:

- Choose trades.
- Decide whether an outcome was strategically meaningful.
- Decide whether it followed, violated, or intentionally overrode its own self-policy.
- Add, revise, or retire self-policy.
- Decide what memories matter.

The runtime must not:

- Block a strategically valid action because it conflicts with memory.
- Generate blacklists, cooldowns, avoid lists, or strategy rules.
- Increase policy salience automatically.
- Judge a policy as good or bad.
- Infer semantic inconsistency between a trade and memory.

## Success Criteria

- Trader prompts show narrative memory and active self-policy as separate blocks.
- Trader JSON can disclose per-action policy alignment without runtime enforcement.
- Reflection can consume factual evidence from closed trades and matured decision scores.
- LLM-produced policy edits are persisted and visible in later prompts.
- Old decisions without policy fields remain readable and scorable.
- Brief staleness is treated as unavailable with exact age, not silently hidden behind
  an old valid brief.
- The effect can be measured by equity vs benchmarks, policy-alignment telemetry, and
  inspection of policy changes after outcomes.

## Non-Goals

- No fine-tuning or training loop.
- No expert-system risk manager.
- No hardcoded "do not buy X" or "cooldown after loss" rule.
- No runtime scoring of semantic quality.
- No dashboard editing of self-policy in this slice.
- No full redesign of the trading prompt beyond the accountability fields.

## Current State

The live path is:

1. Analyst creates `market_briefs`.
2. Trader receives filtered brief, positions, cash/equity, events, and compact memory.
3. Trader returns `BUY`/`SELL`/`HOLD` actions with rationale.
4. Runtime enforces physical validity and executes trades.
5. Reflection runs only after executed SELLs.
6. Scoring later writes `decision_scores`, but those facts are not reflected into memory.

Observed problems:

- A stale but parse-valid `MarketBrief` can remain the latest valid brief while newer
  analyst calls fail.
- Memory can be present in the prompt but ignored by later decisions.
- Reflection currently sees closed trades, but not mature outcome windows, policy
  alignment, or whether prior self-policy helped or was overridden.

## Alternatives Considered

### Recommended: Minimal LLM-Owned Accountability

Extend the existing journal with a new `self_policy` section, extend trader actions
with optional accountability fields, and add an outcome-reflection path that feeds raw
facts from `DecisionScore` into the LLM.

Trade-off: small migration and prompt/schema changes, but no new strategic authority
in the runtime.

### Heavier: Dedicated Policy Table

Create a first-class `agent_self_policies` table with statuses, revisions, and explicit
relationships to decisions.

Trade-off: cleaner relational model, but more product surface than this slice needs.
It risks turning policy management into a system-owned subsystem too early.

### Rejected: Runtime Enforcement

Add blacklists, cooldowns, or blockers when a trade conflicts with remembered lessons.

Trade-off: superficially effective, but it violates the core experiment. The agent would
be babysat by rules instead of learning through reflection.

## Design

### 1. Self-Policy as a Fourth Journal Section

Use the existing `memory_entries` table and add one section key:

```text
self_policy
```

An active self-policy entry is a short LLM-authored line. The database row ID becomes
the stable policy reference rendered in prompts:

```text
P123: Do not re-enter recent losers unless fresh external evidence changes the setup.
```

Why this representation:

- It reuses the append-only journal and `active` flag.
- Retired or replaced policies remain auditable as inactive rows.
- Historical decisions that referenced `P123` still point to a durable row.
- The system does not need to understand the strategic meaning of the text.

`journal.SECTIONS` gains `self_policy`, with a cap of 8 active policies. Keep
narrative memory and self-policy separate in code:

```python
@dataclass
class PolicyLine:
    ref: str        # "P123"
    content: str

@dataclass
class PolicyMemoryView:
    active: list[PolicyLine]
```

`journal.compact_view` continues to return narrative memory. Add a companion
`journal.policy_view(session, agent_id)` that returns active policy rows as `P<row.id>`
references. This avoids overloading the existing newline-only `MemoryView`.

### 2. Prompt Separation

The trader prompt renders two distinct blocks:

```text
Your memory:
Coin theses:
  - ...
Trade lessons:
  - ...
Strategy notes:
  - ...

Your self-policy:
  - P123: ...
  - P124: ...
```

The system prompt tells the trader to account for self-policy, but not that the server
will enforce it.

The stale brief fix treats a too-old brief as unavailable and reports the exact age:

```text
Market brief: unavailable this cycle; latest valid brief is stale by 124m.
```

This is factual plumbing. It is not a strategy rule.

### 3. Trader Output Accountability

Extend each `Action` with optional fields:

```python
policy_refs: list[str] = []
policy_alignment: Literal["follows", "violates", "unrelated"] = "unrelated"
override_reason: str = ""
```

Prompt contract:

- `policy_refs` names active policy IDs shown in the prompt, such as `P123`.
- `policy_alignment` is the LLM's own disclosure.
- `override_reason` is required by prompt instruction when alignment is `violates`.

Runtime behavior:

- Persist these fields in `DecisionRecord.parsed_output`.
- Do not block, skip, resize, or modify actions based on these fields.
- Optionally log invalid policy refs as factual telemetry, but do not reinterpret the
  action.

Backward compatibility:

- Defaults make old records parseable.
- Scoring continues to read only `type` and `symbol`.

### 4. Reflection Output Becomes Memory Plus Policy Edits

Current reflection returns new journal entries:

```json
{
  "coin_theses": [],
  "trade_lessons": [],
  "strategy_notes": []
}
```

Extend it to include LLM-authored policy edits:

```json
{
  "coin_theses": [],
  "trade_lessons": [],
  "strategy_notes": [],
  "policy_edits": [
    {
      "op": "add",
      "text": "Do not re-enter recent losers unless fresh external evidence changes the setup.",
      "reason": "Repeated re-entry after losing exits hurt equity."
    },
    {
      "op": "retire",
      "policy_ref": "P123",
      "reason": "Recent scored outcomes no longer support this policy."
    },
    {
      "op": "replace",
      "policy_ref": "P124",
      "text": "Only override a loss-avoidance policy when the prompt contains fresh external evidence.",
      "reason": "The prior version was too broad."
    }
  ]
}
```

The system only validates shape and ownership:

- `add`: append a new active `self_policy` entry.
- `retire`: mark that agent's referenced row inactive.
- `replace`: mark old row inactive and append a new active row.
- Invalid refs or malformed edits make the reflection invalid for this slice. Memory
  stays unchanged and the failure is logged as reflection telemetry.

The system must not decide whether the edit is wise.

### 5. Outcome Reflection Path

Add a factual evidence builder that gathers bounded, already-computed facts for an
agent:

- Recent closed trades and realized P&L.
- Mature `DecisionScore` rows not yet used in a learning reflection.
- Original decision actions, rationale, `policy_refs`, `policy_alignment`, and
  `override_reason`.
- The active self-policy shown now.
- If available from audit prompts, the policy/memory block that was shown at decision
  time. If this is too brittle to parse, include only the current active policy refs
  plus the decision's own declared refs.

Add a separate learning tick that runs after scoring and reflects on newly mature
scores. Keeping this outside the scoring function preserves the scoring job as a
numeric fact writer, not a semantic evaluator.

Minimal storage:

- Add `DecisionScore.reflected_at nullable datetime`, or an equivalent marker, so the
  same score evidence is not reflected repeatedly.
- Record the LLM call as `DecisionRecord(kind="reflection", trigger="scoring")`.

Reflection prompt rule:

- The evidence is raw facts.
- The LLM decides what those facts mean.
- The LLM may update narrative memory and self-policy.
- The LLM must not be told to blacklist symbols or enforce cooldowns.

Closed-trade reflection can remain, but the richer outcome reflection is the learning
loop that connects scoring back into future behavior.

### 6. Brief Freshness P0

Fix brief freshness before or alongside this slice.

Chosen behavior:

- Define a factual freshness threshold, for example `market_brief_max_age_minutes`
  defaulting to about two decision intervals.
- Compute age from `MarketBrief.created_at`.
- Trader prompt treats a too-old brief as unavailable while reporting the stale age.
- Analyst failures remain isolated and audited.

Do not add a rule like "never buy on stale brief". The LLM receives the factual
freshness state and decides how much confidence to place in the rest of the context.

## Data Flow

### Decision

1. Runtime loads narrative memory and active self-policy.
2. Prompt renders memory and self-policy separately, including policy refs.
3. Trader returns actions with optional policy-accountability fields.
4. Runtime executes only physically valid actions.
5. Runtime records the decision JSON as returned.

### Trade Reflection

1. SELL executes.
2. Runtime computes realized P&L from pre-sell average cost.
3. Reflection sees closed-trade facts plus current memory/policy.
4. LLM returns new memory entries and optional policy edits.
5. Runtime applies the edits exactly as authored, subject to shape/ownership checks.

### Outcome Reflection

1. Scoring job writes new mature `DecisionScore` facts.
2. A separate learning tick gathers unreflected scores for each affected agent.
3. LLM receives score facts, original action accountability, and current policy.
4. LLM updates memory/self-policy if it chooses.
5. Included scores are marked reflected.

## Error Handling

- Provider failure: record failed reflection call when possible, leave memory unchanged.
- Malformed reflection JSON: leave memory unchanged. This slice uses all-or-nothing
  reflection parsing.
- Invalid policy ref: reject the reflection and log telemetry.
- Over-cap self-policy: reject add edits that would exceed 8 active policies unless
  the same LLM response also retires or replaces enough existing policies. Do not pick
  "best" policies in system code.
- Stale/absent brief: render factual state; do not crash trader path.

## Testing

Validation tests:

- `Action` accepts old JSON without policy fields.
- `Action` rejects invalid `policy_alignment`.
- Reflection parser rejects malformed `policy_edits`.
- Invalid policy refs cannot modify another agent's policy.
- Over-cap self-policy is handled deterministically without system-authored strategy.

Business-rule tests:

- A BUY that declares `policy_alignment="violates"` still executes if physically valid.
- Runtime records `policy_refs` and `override_reason` unchanged.
- Outcome reflection receives factual scores, not interpreted judgments.
- The system applies only explicit LLM policy edits.

Reflection tests:

- SELL reflection can add self-policy.
- Outcome reflection marks included scores as reflected.
- Re-running the scoring reflection does not reflect the same score twice.
- Reflection provider failure leaves memory and policy unchanged.

Brief freshness tests:

- Fresh brief renders normally.
- Stale brief is treated as unavailable with exact age.
- Analyst failed rows are not considered valid fresh briefs.

Destructive-safeguard tests:

- Retiring a self-policy marks it inactive rather than deleting it.
- Replacing a self-policy preserves the old row inactive and creates a new active row.
- Invalid retire/replace operations leave existing policies untouched.

Authorization tests:

- If `self_policy` is exposed through existing memory endpoints, it follows the same
  viewer/admin protections as the current memory journal.
- There is no user-facing mutation endpoint for policy in this slice.

## Measurement

Track before/after over comparable windows:

- Agent equity vs HODL BTC, equal-weight, and random benchmark bands.
- Decision hit rate and average aligned return by window.
- Count of actions declaring `follows`, `violates`, and `unrelated`.
- Violations with and without override reasons, as self-declared by the LLM.
- Number and content of policy adds/retires/replacements after outcome reflection.
- Frequency of stale-brief decisions and later outcomes.

These metrics are observational. They are not runtime rules.

## Rollout

1. Implement brief freshness first or as the first task of this slice.
2. Add self-policy rendering with no behavior change.
3. Add optional action accountability fields with backward-compatible defaults.
4. Add policy edits to reflection.
5. Add outcome reflection from unreflected `DecisionScore` facts.
6. Observe metrics before deciding whether to expose policy/alignment in the dashboard.

## Review Questions

These choices are made in the spec, but are worth explicit review before
implementation:

- Stale briefs are treated as unavailable after the freshness threshold, with exact age
  shown to the LLM.
- Outcome reflection runs in a separate learning tick after scoring.
- Reflection parsing is all-or-nothing for this slice.
