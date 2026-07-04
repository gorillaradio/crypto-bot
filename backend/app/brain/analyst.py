from dataclasses import dataclass
from time import perf_counter
from app.brain.analyst_schema import MarketBriefSchema, AnalystResult
from app.brain.context import CoinSnapshot, ObservationView
from app.brain.prompt import retry_user_suffix
from app.core.config import settings


@dataclass
class AnalystContext:
    universe: list[CoinSnapshot]
    observations: list[ObservationView]


_SYSTEM = """You are a crypto market analyst. Synthesize the market data and recent news into a
compact, structured brief that downstream trading agents will read. Surface only what matters now —
market regime plus the coins worth attention (movers, news-driven, opportunities/risks) — not a line
for every coin. Use the exact symbol shown (e.g. BTCUSDT). Respond with ONLY a JSON object of this
exact shape:
{{"regime": "<2-3 sentences: overall direction, BTC/ETH lead, risk sentiment, dominant theme>",
  "highlights": [{{"symbol": "<SYMBOL>", "snapshot": "<price and 24h move>",
    "signal": "bullish"|"bearish"|"neutral", "note": "<one sentence: momentum + any news + why it matters>"}}],
  "key_news": ["<market-wide item not tied to a single coin>"]}}
At most {max_highlights} highlights, most important first. Output JSON only, no prose."""


def render_analyst_prompt(ctx: AnalystContext) -> tuple[str, str]:
    system = _SYSTEM.format(max_highlights=settings.brief_max_highlights)
    lines = ["Market (top by market cap):"]
    for c in sorted(ctx.universe, key=lambda c: c.symbol):
        lines.append(f"  {c.symbol}: ${c.price} ({c.pct_24h:+.2f}% 24h)")
    lines += ["", "Recent crypto news (headlines):"]
    if ctx.observations:
        for o in ctx.observations:
            when = o.published_at.strftime("%m-%d %H:%M")
            tag = f"[{', '.join(o.symbols)}]" if o.symbols else "[market]"
            lines.append(f"  - {when} {o.source}: {o.title} {tag}")
    else:
        lines.append("  (none)")
    return system, "\n".join(lines)


def run_analyst(ctx: AnalystContext, adapter) -> AnalystResult:
    system, user = render_analyst_prompt(ctx)
    t0 = perf_counter()
    try:
        raw = adapter.complete_json(system, user)
    except Exception:                         # provider error — no response received
        return AnalystResult(MarketBriefSchema(), system, user, None, "failed",
                             int((perf_counter() - t0) * 1000))
    try:
        brief = MarketBriefSchema.model_validate_json(raw)
        return AnalystResult(brief, system, user, raw, "ok", int((perf_counter() - t0) * 1000))
    except Exception as first_err:
        raw2 = None
        try:
            raw2 = adapter.complete_json(system, user + retry_user_suffix(str(first_err)))
            brief = MarketBriefSchema.model_validate_json(raw2)
            return AnalystResult(brief, system, user, raw2, "repaired",
                                 int((perf_counter() - t0) * 1000))
        except Exception:
            return AnalystResult(MarketBriefSchema(), system, user,
                                 raw2 if raw2 is not None else raw, "failed",
                                 int((perf_counter() - t0) * 1000))
