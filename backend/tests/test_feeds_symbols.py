from app.feeds.symbols import match_symbols


def test_matches_coin_name_and_safe_ticker():
    assert match_symbols("Bitcoin ETF sees record inflows") == ["BTC"]
    assert match_symbols("BTC breaks 100k") == ["BTC"]


def test_matches_multiple_and_sorts():
    assert match_symbols("Ethereum and Solana lead the rally") == ["ETH", "SOL"]


def test_market_wide_headline_matches_nothing():
    assert match_symbols("Crypto market sheds $200B after Fed holds rates") == []


def test_word_boundary_avoids_false_positive():
    # "solar" must not match SOL; "nearest" must not match NEAR
    assert match_symbols("New solar mining farm opens; nearest grid strained") == []


def test_case_insensitive_and_empty_text():
    assert match_symbols("ethereum upgrade") == ["ETH"]
    assert match_symbols("") == []


def test_polygon_resolves_to_single_symbol():
    # Polygon renamed MATIC→POL (Binance ticker is POL); name + legacy ticker resolve to POL, never both.
    assert match_symbols("Polygon upgrades its bridge") == ["POL"]
    assert match_symbols("MATIC holders migrate their tokens") == ["POL"]
