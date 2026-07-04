from datetime import datetime, timezone
from decimal import Decimal
from app.brain.analyst import AnalystContext, render_analyst_prompt, run_analyst
from app.brain.context import CoinSnapshot, ObservationView


class _Adapter:
    def __init__(self, outputs): self.outputs = list(outputs); self.calls = 0
    def complete_json(self, system, user):
        self.calls += 1
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def _ctx():
    return AnalystContext(
        universe=[CoinSnapshot("BTCUSDT", Decimal("60000"), Decimal("2")),
                  CoinSnapshot("ETHUSDT", Decimal("3000"), Decimal("-1"))],
        observations=[ObservationView("CoinDesk", "Bitcoin ETF inflows",
                                      datetime(2026, 7, 4, 10, 0, tzinfo=timezone.utc), ["BTC"]),
                      ObservationView("Cointelegraph", "Fed holds rates",
                                      datetime(2026, 7, 4, 9, 0, tzinfo=timezone.utc), [])])


_OK = ('{"regime":"risk-on","highlights":[{"symbol":"BTCUSDT","snapshot":"$60000 (+2% 24h)",'
       '"signal":"bullish","note":"etf"}],"key_news":["Fed holds"]}')


def test_render_includes_universe_news_and_schema():
    system, user = render_analyst_prompt(_ctx())
    assert "JSON" in system and "highlights" in system and "15" in system   # cap surfaced
    assert "BTCUSDT" in user and "Bitcoin ETF inflows" in user
    assert "[market]" in user                                   # empty-symbol obs labelled
    assert user.index("BTCUSDT") < user.index("ETHUSDT")        # sorted by symbol


def test_run_analyst_ok_captures_raw_status_latency():
    r = run_analyst(_ctx(), _Adapter([_OK]))
    assert r.parse_status == "ok" and r.brief.regime == "risk-on"
    assert r.brief.highlights[0].symbol == "BTCUSDT"
    assert r.raw == _OK and r.system and r.user and r.latency_ms >= 0


def test_run_analyst_repairs_then_succeeds():
    a = _Adapter(["not json", _OK])
    r = run_analyst(_ctx(), a)
    assert r.parse_status == "repaired" and r.brief.regime == "risk-on" and a.calls == 2


def test_run_analyst_failed_keeps_empty_brief_and_last_raw():
    r = run_analyst(_ctx(), _Adapter(["bad", "still bad"]))
    assert r.parse_status == "failed" and r.brief.highlights == [] and r.raw == "still bad"


def test_run_analyst_provider_error_is_failed_null_raw():
    r = run_analyst(_ctx(), _Adapter([RuntimeError("boom")]))
    assert r.parse_status == "failed" and r.raw is None
