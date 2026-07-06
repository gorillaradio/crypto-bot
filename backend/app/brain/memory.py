import json
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import Literal
from pydantic import BaseModel
from app.brain.context import MemoryView, PolicyMemoryView


@dataclass
class ClosedTrade:
    symbol: str
    qty: Decimal
    sell_price: Decimal
    avg_cost: Decimal
    realized_pnl_pct: Decimal


class PolicyEdit(BaseModel):
    op: Literal["add", "retire", "replace"]
    policy_ref: str | None = None
    text: str = ""
    reason: str = ""


class MemoryUpdate(BaseModel):
    coin_theses: list[str] = []
    trade_lessons: list[str] = []
    strategy_notes: list[str] = []
    policy_edits: list[PolicyEdit] = []


_REFLECT_SYSTEM = """You are the reflective memory of an autonomous paper-trading agent.
The agent just closed one or more trades. Add NEW journal entries capturing what you learned.
Output ONLY a JSON object of this exact shape:
{{"coin_theses": ["<SYMBOL: one-line updated view>", ...],
  "trade_lessons": ["<one-line lesson from a closed trade>", ...],
  "strategy_notes": ["<one-line observation about the agent's own behaviour>", ...],
  "policy_edits": [{{"op": "add"|"retire"|"replace", "policy_ref": "<P123 or null>",
                     "text": "<new policy text or empty>", "reason": "<short factual reason>"}}]}}
Output ONLY genuinely new entries prompted by these outcomes. Do NOT repeat entries already present
in the current memory shown below; return an empty list for a section that has nothing new.
One short line per item. Output JSON only, no prose.

The agent's operator instructions:
{instructions}"""


def build_reflection_prompt(memory: MemoryView, policy: PolicyMemoryView | list[ClosedTrade],
                            closed: list[ClosedTrade] | list[str],
                            held_symbols: list[str] | str,
                            instructions: str | None = None) -> tuple[str, str]:
    if isinstance(policy, list):
        instructions = str(held_symbols)
        held_symbols = closed
        closed = policy
        policy = PolicyMemoryView()
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


def parse_reflection(raw: str) -> MemoryUpdate:
    return MemoryUpdate.model_validate(json.loads(raw))


@dataclass
class ReflectionResult:
    entries: MemoryUpdate
    system: str = ""
    user: str = ""
    raw: str | None = None
    parse_status: str = "ok"      # "ok" | "failed"
    latency_ms: int = 0


def run_reflection_result(memory: MemoryView, policy: PolicyMemoryView | list[ClosedTrade],
                          closed: list[ClosedTrade] | list[str],
                          held_symbols: list[str] | str, instructions=None, adapter=None) -> ReflectionResult:
    if isinstance(policy, list):
        adapter = instructions
        instructions = held_symbols
        held_symbols = closed
        closed = policy
        policy = PolicyMemoryView()
    system, user = build_reflection_prompt(memory, policy, closed, held_symbols, instructions)
    t0 = perf_counter()
    try:
        raw = adapter.complete_json(system, user)
    except Exception:                     # provider error — nothing to append
        return ReflectionResult(MemoryUpdate(), system, user, None, "failed", int((perf_counter() - t0) * 1000))
    try:
        entries = parse_reflection(raw)
        return ReflectionResult(entries, system, user, raw, "ok", int((perf_counter() - t0) * 1000))
    except Exception:                     # unparseable — nothing to append
        return ReflectionResult(MemoryUpdate(), system, user, raw, "failed", int((perf_counter() - t0) * 1000))


_DISTILL_SYSTEM = """You compact one section of an autonomous paper-trading agent's long-term memory.
You are given the current entries of the "{section}" section (oldest first). Merge and condense them
into AT MOST {cap} one-line entries, preserving the most recent and most decision-relevant information
and dropping redundancy. Never invent facts. Output ONLY a JSON object of this exact shape:
{{"entries": ["<one short line>", ...]}}
Output JSON only, no prose.

The agent's operator instructions:
{instructions}"""


def build_distillation_prompt(section: str, entries: list[str], cap: int,
                              instructions: str) -> tuple[str, str]:
    system = _DISTILL_SYSTEM.format(section=section, cap=cap,
                                    instructions=instructions or "(none provided)")
    lines = [f"Current {section} entries (oldest first):"]
    lines += [f"  - {e}" for e in entries] or ["  (none)"]
    return system, "\n".join(lines)


def parse_distillation(raw: str) -> list[str]:
    data = json.loads(raw)
    return [str(x) for x in data.get("entries", [])]


@dataclass
class DistillationResult:
    entries: list[str]
    system: str = ""
    user: str = ""
    raw: str | None = None
    parse_status: str = "ok"      # "ok" | "failed"
    latency_ms: int = 0


def run_distillation_result(section: str, entries: list[str], cap: int,
                            instructions: str, adapter) -> DistillationResult:
    system, user = build_distillation_prompt(section, entries, cap, instructions)
    t0 = perf_counter()
    try:
        raw = adapter.complete_json(system, user)
    except Exception:                     # provider error — keep the originals, do not apply
        return DistillationResult(entries, system, user, None, "failed", int((perf_counter() - t0) * 1000))
    try:
        compacted = parse_distillation(raw)
        if not compacted:                 # never wipe a section to nothing
            return DistillationResult(entries, system, user, raw, "failed", int((perf_counter() - t0) * 1000))
        return DistillationResult(compacted[:cap], system, user, raw, "ok", int((perf_counter() - t0) * 1000))
    except Exception:                     # unparseable — keep the originals
        return DistillationResult(entries, system, user, raw, "failed", int((perf_counter() - t0) * 1000))
