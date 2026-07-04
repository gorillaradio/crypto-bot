from time import perf_counter
from app.brain.schema import Decision, DecisionResult
from app.brain.context import DecisionContext
from app.brain.prompt import render_trader_prompt, retry_user_suffix


def _elapsed_ms(t0: float) -> int:
    return int((perf_counter() - t0) * 1000)


def _evaluate_with(ctx: DecisionContext, adapter, render) -> DecisionResult:
    system, user = render(ctx)
    t0 = perf_counter()
    try:
        raw = adapter.complete_json(system, user)
    except Exception as exc:  # network / provider error — no response received
        return DecisionResult(Decision(actions=[], note=f"brain error: {exc}"),
                              system, user, None, "failed", _elapsed_ms(t0))
    try:
        decision = Decision.model_validate_json(raw)
        return DecisionResult(decision, system, user, raw, "ok", _elapsed_ms(t0))
    except Exception as first_err:
        raw2 = None
        try:
            raw2 = adapter.complete_json(system, user + retry_user_suffix(str(first_err)))
            decision = Decision.model_validate_json(raw2)
            return DecisionResult(decision, system, user, raw2, "repaired", _elapsed_ms(t0))
        except Exception as second_err:
            return DecisionResult(
                Decision(actions=[], note=f"decision parse failed: {second_err}"),
                system, user, raw2 if raw2 is not None else raw, "failed", _elapsed_ms(t0))


def evaluate_trader(ctx: DecisionContext, adapter) -> DecisionResult:
    return _evaluate_with(ctx, adapter, render_trader_prompt)
