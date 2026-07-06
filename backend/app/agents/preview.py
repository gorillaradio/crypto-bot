from app.agents.runtime import assemble_trader_context, universe_size
from app.brain.prompt import render_trader_prompt, retry_user_suffix
from app.brain.memory import build_reflection_prompt, ClosedTrade
from app.brain.brief_store import brief_lookup_for_prompt

_RETRY_EXAMPLE_ERROR = ("1 validation error for Decision: actions.0.type — "
                        "input should be 'BUY', 'SELL' or 'HOLD'")


async def render_agent_prompts_preview(session, agent, market) -> dict:
    """Ricostruisce i prompt (decision/reflection/retry) che la pipeline invierebbe ORA per
    questo agente, con dati reali. Nessuna chiamata LLM, nessuna persistenza: usa l'ultimo brief
    valido senza bootstrap (se non c'è, il prompt trader mostra 'brief non disponibile')."""
    symbols = await market.get_top_symbols("USDT", universe_size(agent))
    brief_lookup = brief_lookup_for_prompt(session)  # read-only: niente bootstrap → niente LLM
    ctx = await assemble_trader_context(session, agent, market, symbols, brief_lookup, wake_reason=None)
    d_system, d_user = render_trader_prompt(ctx)

    retry_user = d_user + retry_user_suffix(_RETRY_EXAMPLE_ERROR)

    closed = [ClosedTrade(symbol=p.symbol, qty=p.quantity, sell_price=p.last_price,
                          avg_cost=p.avg_price, realized_pnl_pct=p.unrealized_pnl_pct)
              for p in ctx.positions]
    held_symbols = [p.symbol for p in ctx.positions]
    r_system, r_user = build_reflection_prompt(ctx.memory, closed, held_symbols, agent.instructions)
    refl_note = ("Anteprima: le posizioni attuali come se chiuse ora." if closed
                 else "Nessuna posizione aperta: mostrato a scopo strutturale "
                      "(la reflection scatta alla chiusura di un trade).")

    return {
        "decision":   {"system": d_system, "user": d_user, "note": None},
        "reflection": {"system": r_system, "user": r_user, "note": refl_note},
        "retry":      {"system": d_system, "user": retry_user,
                       "note": "Suffisso di retry mostrato con un errore d'esempio."},
    }
