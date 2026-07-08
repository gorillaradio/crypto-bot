from datetime import timedelta
import pytest
from app.core.config import Settings, _parse_window


def test_parse_window_units():
    assert _parse_window("15m") == timedelta(minutes=15)
    assert _parse_window("24h") == timedelta(hours=24)
    assert _parse_window("7d") == timedelta(days=7)


@pytest.mark.parametrize("bad", ["", "24", "h24", "1w", "0h", "-3d", "24H", "1.5h"])
def test_parse_window_rejects_bad_formats(bad):
    with pytest.raises(ValueError):
        _parse_window(bad)


def _settings(**over):
    # _env_file=None: i test non devono dipendere da un eventuale .env locale
    return Settings(_env_file=None, **over)


def test_settings_default_windows_parse():
    s = _settings()
    assert list(s.scoring_windows) == ["24h", "7d"]                     # short→long
    assert s.scoring_windows["24h"] == timedelta(hours=24)
    assert s.scoring_windows["7d"] == timedelta(days=7)


def test_settings_accept_custom_windows():
    s = _settings(scoring_window_short="90m", scoring_window_long="12h")
    assert s.scoring_windows == {"90m": timedelta(minutes=90), "12h": timedelta(hours=12)}


def test_settings_reject_invalid_window_format():
    with pytest.raises(ValueError):
        _settings(scoring_window_short="fast")


def test_settings_reject_short_not_shorter_than_long():
    with pytest.raises(ValueError):
        _settings(scoring_window_short="7d", scoring_window_long="24h")
    with pytest.raises(ValueError):                                     # uguali ⇒ stessa durata
        _settings(scoring_window_short="24h", scoring_window_long="24h")


def test_settings_reject_label_longer_than_db_column():
    with pytest.raises(ValueError):                                     # String(8) in DecisionScore
        _settings(scoring_window_long="10000000m")
