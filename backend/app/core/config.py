from decimal import Decimal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://crypto:crypto@localhost:5432/crypto"
    initial_capital_usd: Decimal = Decimal("100")
    fee_rate: Decimal = Decimal("0.001")
    heartbeat_seconds: int = 300
    decision_seconds: int = 3600
    universe_default: str = "TOP_100"


settings = Settings()
