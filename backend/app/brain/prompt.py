from app.brain.context import DecisionContext

_SYSTEM = """You are an autonomous paper-trading agent managing a simulated crypto portfolio.
Real market prices are used; trades incur fees and bid/ask spread. You may only hold coins
listed in the universe. Server-side guardrails enforce limits, so impossible actions are dropped.

Your operator's instructions:
{instructions}

Decide what to do this cycle. Respond with ONLY a JSON object of this exact shape:
{{"actions": [{{"type": "BUY"|"SELL"|"HOLD", "symbol": "<SYMBOL or null>",
  "usd_amount": "<USD to spend on BUY, or null>", "fraction": "<0-1 of position to SELL, or null>",
  "rationale": "<one short sentence>"}}], "note": "<one-line thesis for this cycle>"}}
Use BUY with usd_amount to open/add, SELL with fraction (1 = all) to reduce/close, HOLD to do nothing.
Numbers must be JSON strings. Output JSON only, no prose."""


def render_trader_prompt(ctx: DecisionContext) -> tuple[str, str]:
    """v2 trader prompt: brief (già filtrato) + posizioni live + memoria + wake_reason. Nessuna
    tabella universo (l'analyst ha già sintetizzato il mercato). Stesso contratto Decision di sempre."""
    system = _SYSTEM.format(instructions=ctx.instructions or "(none provided)")

    lines = []
    if ctx.wake_reason:
        lines += [f"⚠ {ctx.wake_reason}", ""]
    lines += [f"Cash: ${ctx.cash_usd}", f"Equity: ${ctx.equity_usd}", "", "Open positions:"]
    if ctx.positions:
        for p in ctx.positions:
            lines.append(f"  {p.symbol}: qty {p.quantity} @ avg ${p.avg_price}, "
                         f"now ${p.last_price} ({p.unrealized_pnl_pct:+.2f}%)")
    else:
        lines.append("  (none)")

    b = ctx.brief
    if b is not None:
        when = f" (as of {b.as_of.strftime('%m-%d %H:%M')})" if b.as_of else ""
        lines += ["", f"Market brief{when}:", f"Regime: {b.regime or '(n/a)'}",
                  "", "Watchlist (your universe):"]
        if b.highlights:
            for h in b.highlights:
                lines.append(f"  {h.symbol} {h.snapshot} [{h.signal}] {h.note}")
        else:
            lines.append("  (nothing notable in your universe)")
        if b.key_news:
            lines += ["", "Market news:"] + [f"  - {n}" for n in b.key_news]
    else:
        lines += ["", "Market brief: (unavailable this cycle)"]

    # Blocco memoria: stesso formato usato altrove nel prompt. ~10 righe.
    mem = ctx.memory
    mem_lines = []
    for label, text in (("Coin theses", mem.coin_theses),
                        ("Trade lessons", mem.trade_lessons),
                        ("Strategy notes", mem.strategy_notes)):
        rows = [l for l in text.splitlines() if l.strip()]
        if rows:
            mem_lines.append(f"{label}:")
            mem_lines += [f"  - {l}" for l in rows]
    if mem_lines:
        system = system + "\n\nYour memory below is your own prior reflection on past trades — treat it as your evolving view."
        lines += ["", "Your memory (you wrote this; update your behaviour accordingly):"] + mem_lines

    return system, "\n".join(lines)


def retry_user_suffix(error: str) -> str:
    """Suffisso appeso al messaggio user quando la risposta non è JSON valido.
    Condiviso tra il ciclo di decisione (retry reale) e il monitor dei prompt (con errore d'esempio)."""
    return (f"\n\nYour previous reply was not valid JSON for the schema "
            f"({error}). Reply with ONLY the corrected JSON object.")
