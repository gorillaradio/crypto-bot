from decimal import Decimal
from pydantic_settings import BaseSettings, SettingsConfigDict


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
