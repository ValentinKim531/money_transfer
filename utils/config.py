from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, ValidationError
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # .../money_transfer/
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    db_url: str = Field(
        ..., description="DB URL, e.g. sqlite+aiosqlite:///data/app.sqlite3"
    )
    jwt_secret: str = Field(
        ..., min_length=16, description="Server signing key for JWT"
    )

    # Необязательные — с безопасными дефолтами
    jwt_alg: str = "HS256"
    jwt_expires_min: int = 300

    default_language: str = "en"
    supported_languages: str = "en,ru"

    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    jaeger_agent_host: str = "localhost"
    jaeger_agent_port: int = 6831

    use_mock_rates: bool = True
    rates_provider_url: str = "https://api.exchangerate.host/latest"

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        extra="ignore",
    )


settings = Settings()
