import re
from datetime import timedelta
from decimal import Decimal
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_WINDOW_RE = re.compile(r"([1-9]\d*)([mhd])")
_WINDOW_UNITS = {"m": timedelta(minutes=1), "h": timedelta(hours=1), "d": timedelta(days=1)}


def _parse_window(s: str) -> timedelta:
    """'15m' | '24h' | '7d' → timedelta. La durata è l'unica fonte di verità;
    la stringa stessa fa da label persistita (DecisionScore.window) e mostrata in dashboard."""
    m = _WINDOW_RE.fullmatch(s)
    if m is None:
        raise ValueError(f"finestra di scoring non valida: {s!r} (atteso <numero><m|h|d>, es. '24h')")
    return int(m.group(1)) * _WINDOW_UNITS[m.group(2)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://crypto:crypto@postgres:5432/crypto"
    initial_capital_usd: Decimal = Decimal("100")
    fee_rate: Decimal = Decimal("0.001")
    heartbeat_seconds: int = 300
    decision_seconds: int = 3600
    scoring_seconds: int = 900       # re-score matured decisions every 15 min
    news_poll_seconds: int = 900     # poll crypto news feeds every 15 min
    universe_default: str = "TOP_100"

    # --- scoring windows: la durata è configurabile, il label è la stringa stessa ---
    scoring_window_short: str = "24h"
    scoring_window_long: str = "7d"

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

    # --- trigger engine (Fase 5) ---
    wake_budget_per_hour: int = 2          # max news+movement wakes/hour per agent
    movement_threshold: Decimal = Decimal("0.05")   # |~1h move| >= this fraction => movement wake
    movement_window_hours: int = 1

    # --- auth ---
    admin_password: str = ""
    secret_key: str = ""
    session_https_only: bool = True
    session_max_age_seconds: int = 1209600  # 14 days

    # --- brain v1 ---
    min_trade_usd: Decimal = Decimal("5")

    # --- brain v2 (Fase 6) ---
    analyst_model: str = "deepseek/deepseek-v4-pro"   # OpenRouter slug — verify at wiring/deploy
    brief_max_highlights: int = 15
    market_brief_max_age_minutes: int = 120
    analyst_news_limit: int = 30

    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    glm_api_key: str = ""
    glm_base_url: str = "https://api.z.ai/api/paas/v4"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

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
