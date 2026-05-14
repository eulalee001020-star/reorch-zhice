"""Application configuration via environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings


class DatabaseSettings(BaseSettings):
    """PostgreSQL + pgvector connection settings."""

    model_config = {"env_prefix": "DB_"}

    host: str = "localhost"
    port: int = 5432
    user: str = "reorch"
    password: str = "reorch"
    name: str = "reorch"
    echo: bool = False
    pool_size: int = 10
    max_overflow: int = 20

    @property
    def async_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )

    @property
    def sync_url(self) -> str:
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


class RedisSettings(BaseSettings):
    """Redis connection settings."""

    model_config = {"env_prefix": "REDIS_"}

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = None
    max_connections: int = 20

    @property
    def url(self) -> str:
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class KafkaSettings(BaseSettings):
    """Kafka / Redpanda connection settings."""

    model_config = {"env_prefix": "KAFKA_"}

    bootstrap_servers: str = "localhost:9092"
    group_id: str = "reorch"
    auto_offset_reset: str = "earliest"
    enable_auto_commit: bool = False

    # Topic names
    topic_incidents_created: str = "incidents.created"
    topic_impact_completed: str = "impact.completed"
    topic_strategy_selected: str = "strategy.selected"
    topic_plans_generated: str = "plans.generated"
    topic_plans_confirmed: str = "plans.confirmed"
    topic_writeback_status: str = "writeback.status"


class AppSettings(BaseSettings):
    """Top-level application settings."""

    model_config = {"env_prefix": "APP_"}

    name: str = "ReOrch 智策"
    version: str = "0.1.0"
    debug: bool = False
    env: str = Field(default="development", description="development | staging | production")
    log_level: str = "INFO"

    # OpenTelemetry
    otel_service_name: str = "reorch-backend"
    otel_exporter_endpoint: str = "http://localhost:4317"

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]


class Settings(BaseSettings):
    """Aggregated settings — single entry point for all configuration."""

    db: DatabaseSettings = DatabaseSettings()
    redis: RedisSettings = RedisSettings()
    kafka: KafkaSettings = KafkaSettings()
    app: AppSettings = AppSettings()


settings = Settings()
