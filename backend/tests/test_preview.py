from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.db.models import Agent, Position, AgentMemory
from app.brain.context import CoinSnapshot
from app.agents.preview import render_agent_prompts_preview


class FakeMarketPreview:
    def __init__(self, snapshot, price, symbols=None):
        self._snap, self._price, self._symbols = snapshot, price, symbols or ["BTCUSDT"]
    async def get_top_symbols(self, quote, n): return self._symbols
    async def get_universe_snapshot(self, symbols): return self._snap
    async def get_price(self, symbol): return self._price


def _agent(session, instructions=""):
    a = Agent(name="P", instructions=instructions,
              duration_start=datetime.now(timezone.utc),
              duration_end=datetime.now(timezone.utc) + timedelta(days=1),
              cash_usd=Decimal("100"), model_name="deepseek/deepseek-v4-flash")
    session.add(a); session.commit()
    return a


async def test_preview_returns_three_prompts_with_real_data(db_session):
    agent = _agent(db_session, instructions="compra basso vendi alto")
    db_session.add(Position(agent_id=agent.id, symbol="BTCUSDT",
                            quantity=Decimal("1"), avg_price=Decimal("100")))
    db_session.add(AgentMemory(agent_id=agent.id, section="trade_lessons", content="cut losers"))
    db_session.commit()
    market = FakeMarketPreview([CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("3"))], Decimal("120"))
    out = await render_agent_prompts_preview(db_session, agent, market)
    assert set(out) == {"decision", "reflection", "retry"}
    assert "compra basso vendi alto" in out["decision"]["system"]     # istruzioni operatore
    assert "BTCUSDT" in out["decision"]["user"]                        # universo/posizione
    assert "cut losers" in out["decision"]["user"]                     # memoria
    assert out["retry"]["user"].startswith(out["decision"]["user"])    # retry = decision user + suffisso
    assert "corrected JSON" in out["retry"]["user"]
    assert "BTCUSDT" in out["reflection"]["user"]                      # posizione come trade ipotetico


async def test_preview_no_positions_has_note(db_session):
    agent = _agent(db_session)
    market = FakeMarketPreview([CoinSnapshot("BTCUSDT", Decimal("120"), Decimal("3"))], Decimal("120"))
    out = await render_agent_prompts_preview(db_session, agent, market)
    assert "Nessuna posizione" in out["reflection"]["note"]
