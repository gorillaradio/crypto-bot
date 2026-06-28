from app.brain.schema import Decision
from app.brain.context import DecisionContext
from app.brain.prompt import render_prompt


def decide(ctx: DecisionContext, adapter) -> Decision:
    system, user = render_prompt(ctx)
    try:
        raw = adapter.complete_json(system, user)
    except Exception as exc:  # network / provider error
        return Decision(actions=[], note=f"brain error: {exc}")

    try:
        return Decision.model_validate_json(raw)
    except Exception as first_err:
        try:
            raw2 = adapter.complete_json(
                system, user + f"\n\nYour previous reply was not valid JSON for the schema "
                               f"({first_err}). Reply with ONLY the corrected JSON object.")
            return Decision.model_validate_json(raw2)
        except Exception as second_err:
            return Decision(actions=[], note=f"decision parse failed: {second_err}")
