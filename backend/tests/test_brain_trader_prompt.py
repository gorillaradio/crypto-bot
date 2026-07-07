from decimal import Decimal
from datetime import datetime, timezone
from app.brain.context import build_context, MarketBriefView, HighlightView
from app.brain.prompt import render_trader_prompt
from app.brain import evaluate_trader


class _Adapter:
    def __init__(self, outputs): self.outputs = list(outputs); self.calls = 0
    def complete_json(self, system, user):
        self.calls += 1
        return self.outputs.pop(0)


def _brief():
    return MarketBriefView(regime="risk-on, BTC leads",
                           highlights=[HighlightView("BTCUSDT", "$60000 (+2% 24h)", "bullish", "etf inflows")],
                           key_news=["Fed holds rates"],
                           as_of=datetime(2026, 7, 4, 14, 0, tzinfo=timezone.utc))


def _ctx(brief=None):
    return build_context(instructions="favor blue chips", cash_usd=Decimal("100"),
                         holdings=[], recent_events=[], brief=brief,
                         wake_reason=None)


def test_trader_prompt_uses_brief_not_universe_table():
    system, user = render_trader_prompt(_ctx(_brief()))
    assert "favor blue chips" in system and '"actions"' in system   # same Decision contract
    assert "Regime: risk-on, BTC leads" in user
    assert "BTCUSDT" in user and "[bullish]" in user and "Fed holds rates" in user
    assert "Market (universe):" not in user                         # NO raw universe table


def test_trader_prompt_handles_missing_brief():
    system, user = render_trader_prompt(_ctx(None))
    assert "unavailable" in user.lower()


def test_trader_prompt_reports_stale_brief_reason():
    ctx = build_context(instructions="", cash_usd=Decimal("100"), holdings=[],
                        recent_events=[],
                        brief=None,
                        brief_unavailable_reason="latest valid brief is stale by 124m")

    _system, user = render_trader_prompt(ctx)

    assert "Market brief: unavailable this cycle; latest valid brief is stale by 124m" in user


def test_trader_prompt_surfaces_wake_reason():
    ctx = build_context(instructions="", cash_usd=Decimal("100"), holdings=[],
                        recent_events=[], brief=_brief(),
                        wake_reason="SOLUSDT news: hack")
    _system, user = render_trader_prompt(ctx)
    assert "SOLUSDT news: hack" in user


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


def test_evaluate_trader_parses_decision():
    r = evaluate_trader(_ctx(_brief()),
                        _Adapter(['{"actions":[{"type":"HOLD","rationale":"wait"}],"note":"n"}']))
    assert r.parse_status == "ok" and r.decision.note == "n"
    assert "Regime:" in r.user            # the trader prompt was used
