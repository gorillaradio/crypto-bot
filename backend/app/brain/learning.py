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
  "policy_edits": [{{"op": "add"|"retire"|"replace", "policy_ref": "<P123 or null>",
                     "text": "<new policy text or empty>", "reason": "<short factual reason>"}}]}}
Output JSON only, no prose.

The agent's operator instructions:
{instructions}"""


def _format_action(action: dict) -> str:
    parts: list[str] = []
    for key, value in action.items():
        if isinstance(value, list):
            rendered = json.dumps(value)
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return " ".join(parts)


def build_outcome_reflection_prompt(
    evidence: OutcomeReflectionEvidence,
    memory: MemoryView,
    policy: PolicyMemoryView,
    instructions: str,
) -> tuple[str, str]:
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
            lines.append(f"    action { _format_action(action) }")
    lines += ["", "Current memory:"]
    for label, text in (
        ("Coin theses", memory.coin_theses),
        ("Trade lessons", memory.trade_lessons),
        ("Strategy notes", memory.strategy_notes),
    ):
        lines.append(f"{label}:")
        lines += [f"  - {line}" for line in text.splitlines() if line.strip()] or ["  (none)"]
    lines += ["", "Current self-policy:"]
    if policy.active:
        lines += [f"  - {entry.ref}: {entry.content}" for entry in policy.active]
    else:
        lines += ["  (none)"]
    return system, "\n".join(lines)


def run_outcome_reflection_result(
    evidence: OutcomeReflectionEvidence,
    memory: MemoryView,
    policy: PolicyMemoryView,
    instructions: str,
    adapter,
) -> ReflectionResult:
    system, user = build_outcome_reflection_prompt(evidence, memory, policy, instructions)
    t0 = perf_counter()
    try:
        raw = adapter.complete_json(system, user)
    except Exception:
        return ReflectionResult(
            MemoryUpdate(), system, user, None, "failed", int((perf_counter() - t0) * 1000)
        )
    try:
        entries = parse_reflection(raw)
        return ReflectionResult(
            entries, system, user, raw, "ok", int((perf_counter() - t0) * 1000)
        )
    except Exception:
        return ReflectionResult(
            MemoryUpdate(), system, user, raw, "failed", int((perf_counter() - t0) * 1000)
        )
