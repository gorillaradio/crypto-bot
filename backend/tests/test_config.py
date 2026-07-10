from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import pytest
from pydantic import ValidationError
from app.core.config import Settings, _parse_window, _require_config_toml, _CONFIG_TOML

_FULL_TOML = _CONFIG_TOML.read_text()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Il container inietta FEE_RATE, SCORING_WINDOW_LONG, ... da .env, e le env var
    battono il TOML. Senza questa pulizia i test misurano il .env, non il codice."""
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)


@pytest.fixture
def toml_file(tmp_path, monkeypatch):
    """Punta Settings a un config.toml usa-e-getta. Ritorna lo scrittore."""
    p = tmp_path / "config.toml"
    monkeypatch.setitem(Settings.model_config, "toml_file", p)

    def _write(body: str) -> Path:
        p.write_text(body)
        return p

    return _write


def _settings(**over):
    # _env_file=None: i test non devono dipendere da un eventuale .env locale
    return Settings(_env_file=None, **over)


# --- _parse_window (invariati) ---

def test_parse_window_units():
    assert _parse_window("15m") == timedelta(minutes=15)
    assert _parse_window("24h") == timedelta(hours=24)
    assert _parse_window("7d") == timedelta(days=7)


@pytest.mark.parametrize("bad", ["", "24", "h24", "1w", "0h", "-3d", "24H", "1.5h"])
def test_parse_window_rejects_bad_formats(bad):
    with pytest.raises(ValueError):
        _parse_window(bad)


# --- guardia sull'esistenza del file ---

def test_require_config_toml_raises_when_missing(tmp_path):
    with pytest.raises(RuntimeError, match="config.toml"):
        _require_config_toml(tmp_path / "nope.toml")


def test_require_config_toml_returns_path_when_present(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("fee_rate = 0.001\n")
    assert _require_config_toml(p) == p


def test_shipped_config_toml_exists():
    assert _CONFIG_TOML.is_file()


# --- niente defaulting silenzioso ---

def test_missing_key_in_toml_is_loud(toml_file):
    toml_file(_FULL_TOML.replace("fee_rate = 0.001", ""))
    with pytest.raises(ValidationError) as exc:
        _settings()
    assert ("fee_rate",) in [e["loc"] for e in exc.value.errors()]


def test_empty_toml_reports_every_missing_field(toml_file):
    toml_file("")
    with pytest.raises(ValidationError) as exc:
        _settings()
    locs = {e["loc"] for e in exc.value.errors()}
    assert ("fee_rate",) in locs and ("decision_seconds",) in locs


# --- precedenza ---

def test_toml_is_the_source_of_values(toml_file):
    toml_file(_FULL_TOML.replace("fee_rate = 0.001", "fee_rate = 0.007"))
    assert _settings().fee_rate == Decimal("0.007")


def test_env_var_overrides_toml(toml_file, monkeypatch):
    toml_file(_FULL_TOML)
    monkeypatch.setenv("DECISION_SECONDS", "999")
    assert _settings().decision_seconds == 999


def test_init_kwargs_override_everything(toml_file, monkeypatch):
    toml_file(_FULL_TOML)
    monkeypatch.setenv("DECISION_SECONDS", "999")
    assert _settings(decision_seconds=1).decision_seconds == 1


def test_database_url_keeps_its_code_default(toml_file):
    toml_file(_FULL_TOML)                       # il TOML non lo definisce
    assert "postgres:5432" in _settings().database_url


# --- i validator girano anche sui valori del TOML ---

def test_toml_values_pass_through_validators(toml_file):
    toml_file(_FULL_TOML.replace('scoring_window_short = "24h"',
                                 'scoring_window_short = "30d"'))   # short >= long
    with pytest.raises(ValueError):
        _settings()


def test_shipped_windows_parse():
    s = _settings()
    assert list(s.scoring_windows) == ["24h", "7d"]                 # short→long
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
    with pytest.raises(ValueError):                                 # uguali ⇒ stessa durata
        _settings(scoring_window_short="24h", scoring_window_long="24h")


def test_settings_reject_label_longer_than_db_column():
    with pytest.raises(ValueError):                                 # String(8) in DecisionScore
        _settings(scoring_window_long="10000000m")
