import json
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from pydantic import BaseModel
from app.brain.context import MemoryView

CAP_COIN_THESES = 8
CAP_TRADE_LESSONS = 10
CAP_STRATEGY_NOTES = 5


@dataclass
class ClosedTrade:
    symbol: str
    qty: Decimal
    sell_price: Decimal
    avg_cost: Decimal
    realized_pnl_pct: Decimal


class MemoryUpdate(BaseModel):
    coin_theses: list[str] = []
    trade_lessons: list[str] = []
    strategy_notes: list[str] = []


_REFLECT_SYSTEM = """You are the reflective memory of an autonomous paper-trading agent.
The agent just closed one or more trades. Rewrite its long-term memory in light of the outcomes.
Output ONLY a JSON object of this exact shape:
{{"coin_theses": ["<SYMBOL: one-line current view>", ...],
  "trade_lessons": ["<one-line lesson from a closed trade>", ...],
  "strategy_notes": ["<one-line observation about the agent's own behaviour>", ...]}}
Rewrite each list fully (do NOT append). Keep at most {coin} coin_theses, {lessons} trade_lessons,
{notes} strategy_notes. One short line per item. Output JSON only, no prose.

The agent's operator instructions:
{instructions}"""


def build_reflection_prompt(memory: MemoryView, closed: list[ClosedTrade],
                            held_symbols: list[str], instructions: str) -> tuple[str, str]:
    system = _REFLECT_SYSTEM.format(
        coin=CAP_COIN_THESES, lessons=CAP_TRADE_LESSONS, notes=CAP_STRATEGY_NOTES,
        instructions=instructions or "(none provided)",
    )
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
    return system, "\n".join(lines)


def parse_reflection(raw: str) -> MemoryUpdate:
    return MemoryUpdate.model_validate(json.loads(raw))


def enforce_caps(update: MemoryUpdate) -> MemoryView:
    def cap(items: list[str], n: int) -> str:
        return "\n".join(s.strip() for s in items[:n] if s.strip())
    return MemoryView(
        coin_theses=cap(update.coin_theses, CAP_COIN_THESES),
        trade_lessons=cap(update.trade_lessons, CAP_TRADE_LESSONS),
        strategy_notes=cap(update.strategy_notes, CAP_STRATEGY_NOTES),
    )


def run_reflection(memory: MemoryView, closed: list[ClosedTrade],
                   held_symbols: list[str], instructions: str, adapter) -> MemoryView:
    system, user = build_reflection_prompt(memory, closed, held_symbols, instructions)
    raw = adapter.complete_json(system, user)
    return enforce_caps(parse_reflection(raw))


@dataclass
class ReflectionResult:
    memory: MemoryView
    system: str = ""
    user: str = ""
    raw: str | None = None
    parse_status: str = "ok"      # "ok" | "failed"
    latency_ms: int = 0


def run_reflection_result(memory: MemoryView, closed: list[ClosedTrade],
                          held_symbols: list[str], instructions: str, adapter) -> ReflectionResult:
    system, user = build_reflection_prompt(memory, closed, held_symbols, instructions)
    t0 = perf_counter()
    try:
        raw = adapter.complete_json(system, user)
    except Exception:                     # provider error — memory left unchanged
        return ReflectionResult(memory, system, user, None, "failed", int((perf_counter() - t0) * 1000))
    try:
        new_memory = enforce_caps(parse_reflection(raw))
        return ReflectionResult(new_memory, system, user, raw, "ok", int((perf_counter() - t0) * 1000))
    except Exception:                     # unparseable — keep old memory
        return ReflectionResult(memory, system, user, raw, "failed", int((perf_counter() - t0) * 1000))
