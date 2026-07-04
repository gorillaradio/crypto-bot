from decimal import Decimal
from app.eval.scoring import aligned_return_pct, score_decision


def test_buy_win_when_price_rises():
    assert aligned_return_pct("BUY", Decimal("100"), Decimal("110")) == Decimal("10")


def test_sell_win_when_price_falls():
    # sold at 100, price fell to 90 → good exit → +10 aligned return
    assert aligned_return_pct("SELL", Decimal("100"), Decimal("90")) == Decimal("10")


def test_score_counts_hits_and_averages_only_priced_actions():
    actions = [
        {"type": "BUY", "symbol": "AAA"},      # 100 → 120, +20, hit
        {"type": "SELL", "symbol": "BBB"},     # 100 → 120, aligned -20, miss
        {"type": "BUY", "symbol": "CCC"},      # unpriced → ignored
        {"type": "HOLD", "symbol": None},      # not BUY/SELL → ignored
    ]
    p0 = {"AAA": Decimal("100"), "BBB": Decimal("100")}
    p1 = {"AAA": Decimal("120"), "BBB": Decimal("120")}
    n, hits, avg = score_decision(actions, p0, p1)
    assert n == 2 and hits == 1
    assert avg == Decimal("0")                 # (+20 + -20) / 2


def test_score_no_scorable_actions_returns_none_avg():
    n, hits, avg = score_decision([{"type": "BUY", "symbol": "ZZZ"}], {}, {})
    assert n == 0 and hits == 0 and avg is None
