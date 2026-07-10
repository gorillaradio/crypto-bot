import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from pydantic import model_validator
from pydantic_settings import (BaseSettings, PydanticBaseSettingsSource,
                               SettingsConfigDict, TomlConfigSettingsSource)

_WINDOW_RE = re.compile(r"([1-9]\d*)([mhd])")
_WINDOW_UNITS = {"m": timedelta(minutes=1), "h": timedelta(hours=1), "d": timedelta(days=1)}


def _parse_window(s: str) -> timedelta:
    """'15m' | '24h' | '7d' → timedelta. La durata è l'unica fonte di verità;
    la stringa stessa fa da label persistita (DecisionScore.window) e mostrata in dashboard."""
    m = _WINDOW_RE.fullmatch(s)
    if m is None:
        raise ValueError(f"finestra di scoring non valida: {s!r} (atteso <numero><m|h|d>, es. '24h')")
    return int(m.group(1)) * _WINDOW_UNITS[m.group(2)]


def _require_config_toml(path: Path) -> Path:
    """Un config.toml mancante non solleverebbe niente da solo: pydantic-settings
    ignora la sorgente. I campi obbligatori lo farebbero fallire comunque, ma con
    venti 'field required' invece di una causa. Meglio dirla."""
    if not path.is_file():
        raise RuntimeError(
            f"config.toml non trovato in {path}. È la fonte dei parametri di progetto "
            "(capitale, fee, intervalli, finestre di scoring)."
        )
    return path


_CONFIG_TOML = _require_config_toml(Path(__file__).resolve().parents[3] / "config.toml")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore",
                                      toml_file=_CONFIG_TOML)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """init kwargs > env var > .env > config.toml."""
        return (init_settings, env_settings, dotenv_settings,
                TomlConfigSettingsSource(settings_cls), file_secret_settings)

    # --- da config.toml: nessun default, un TOML incompleto deve fallire ---
    initial_capital_usd: Decimal          # seed del cash di ogni nuovo agente
    fee_rate: Decimal
    min_trade_usd: Decimal
    heartbeat_seconds: int
    decision_seconds: int
    scoring_seconds: int
    news_poll_seconds: int
    universe_default: str
    scoring_window_short: str             # la durata è la fonte di verità, il label è la stringa
    scoring_window_long: str
    wake_budget_per_hour: int             # max news+movement wakes/hour per agent
    movement_threshold: Decimal           # |~1h move| >= this fraction => movement wake
    movement_window_hours: int
    analyst_model: str                    # OpenRouter slug
    brief_max_highlights: int
    market_brief_max_age_minutes: int
    analyst_news_limit: int
    session_max_age_seconds: int
    deepseek_base_url: str
    glm_base_url: str
    openrouter_base_url: str

    # --- specifici della macchina: il default nel codice è il valore giusto ---
    database_url: str = "postgresql+psycopg://crypto:crypto@postgres:5432/crypto"
    session_https_only: bool = True

    # --- segreti: main.py:15 rifiuta di partire senza secret_key ---
    secret_key: str = ""
    admin_password: str = ""
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    glm_api_key: str = ""
    openrouter_api_key: str = ""

    @model_validator(mode="after")
    def _check_scoring_windows(self):
        for label in (self.scoring_window_short, self.scoring_window_long):
            if len(label) > 8:                       # DecisionScore.window è String(8)
                raise ValueError(f"label della finestra di scoring troppo lungo (max 8): {label!r}")
        if _parse_window(self.scoring_window_short) >= _parse_window(self.scoring_window_long):
            raise ValueError("scoring_window_short deve essere più corta di scoring_window_long")
        return self

    @property
    def scoring_windows(self) -> dict[str, timedelta]:
        """Label → durata, in ordine short→long (l'ordine guida scoring, API e dashboard)."""
        return {self.scoring_window_short: _parse_window(self.scoring_window_short),
                self.scoring_window_long: _parse_window(self.scoring_window_long)}

    @property
    def decision_buy_default_usd(self) -> Decimal:
        return self.initial_capital_usd / Decimal("10")

    def provider_api_key(self, provider: str) -> str:
        return {"anthropic": self.anthropic_api_key,
                "deepseek": self.deepseek_api_key,
                "glm": self.glm_api_key,
                "openrouter": self.openrouter_api_key}[provider]

    def provider_base_url(self, provider: str) -> str:
        return {"deepseek": self.deepseek_base_url,
                "glm": self.glm_base_url,
                "openrouter": self.openrouter_base_url}.get(provider, "")


settings = Settings()
