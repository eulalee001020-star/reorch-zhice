"""Application configuration via environment variables."""

from typing import Literal

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
    env: str = Field(
        default="development", description="development | staging | production"
    )
    log_level: str = "INFO"
    require_durable_persistence: bool = False

    # OpenTelemetry
    otel_service_name: str = "reorch-backend"
    otel_exporter_endpoint: str = "http://localhost:4317"

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    @property
    def durable_persistence_required(self) -> bool:
        return self.require_durable_persistence or self.env in {"staging", "production"}


class AuthSettings(BaseSettings):
    """Authentication settings.

    ``users`` format:
    username:password:user_id:role:api_key:display_name,username2:...

    This is intentionally simple for PoC deployments. Production deployments
    should replace it with an external IdP or a dedicated user table.
    """

    model_config = {"env_prefix": "AUTH_"}

    require_api_key: bool = False
    mode: Literal["api_key", "oidc", "hybrid"] = "api_key"
    writeback_permit_secret: str = ""
    recovery_approval_secret: str = ""
    writeback_permit_ttl_seconds: int = Field(default=300, ge=30, le=1800)
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_algorithms: str = "RS256"
    oidc_role_claim: str = "roles"
    oidc_tenant_claim: str = "tenant_id"
    oidc_role_mapping: str = (
        "planner=Planner,shop_floor_executor=Shop_Floor_Executor,"
        "management=Management,it_admin=IT_Admin"
    )

    users: str = (
        "planner:planner123:planner-1:Planner:planner-key-001:Planner,"
        "executor:executor123:executor-1:Shop_Floor_Executor:executor-key-001:Executor,"
        "manager:manager123:mgmt-1:Management:mgmt-key-001:Manager,"
        "admin:admin123:admin-1:IT_Admin:admin-key-001:Admin"
    )


class IntegrationSettings(BaseSettings):
    """Customer-system adapter settings.

    Empty base URLs keep adapters in local PoC mode. Set the relevant base URL
    and path/API key values to connect a customer ERP/MES/APS/IoT system.
    """

    model_config = {"env_prefix": "INTEGRATION_"}

    mes_base_url: str | None = None
    mes_api_key: str | None = None
    mes_writeback_path: str = "/api/schedule/writeback"
    mes_progress_path: str = "/api/execution/progress"
    mes_health_path: str = "/health"
    mes_format: str = "standard"
    writeback_mode: Literal["disabled", "sandbox"] = "disabled"
    mes_target_environment: Literal["local", "sandbox", "production"] = "local"
    require_certified_writeback_adapter: bool = False
    writeback_adapter_id: str = "mes-default"

    erp_aps_base_url: str | None = None
    erp_aps_api_key: str | None = None
    erp_aps_snapshot_path: str = "/api/schedule/snapshot"
    erp_aps_resources_path: str = "/api/resources"
    erp_aps_work_orders_path: str = "/api/work-orders"
    erp_aps_health_path: str = "/health"

    iot_base_url: str | None = None
    iot_api_key: str | None = None
    iot_events_path: str = "/api/events"
    iot_health_path: str = "/health"

    request_timeout_seconds: float = 10.0


class LLMSettings(BaseSettings):
    """Optional OpenAI-compatible LLM settings for low-risk Agent steps."""

    model_config = {"env_prefix": "LLM_"}

    enabled: bool = False
    provider: str = "openai_compatible"
    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = None
    model: str = "configured-small-agent-model"
    request_timeout_seconds: float = 12.0
    max_attempts: int = Field(default=2, ge=1, le=4)
    retry_backoff_seconds: float = Field(default=0.25, ge=0.0, le=5.0)
    circuit_failure_threshold: int = Field(default=3, ge=1, le=20)
    circuit_reset_seconds: float = Field(default=60.0, ge=1.0, le=3600.0)
    max_payload_bytes: int = Field(default=65_536, ge=1024, le=1_048_576)


class AgentRuntimeSettings(BaseSettings):
    """Timeouts for the controlled decision workflow."""

    model_config = {"env_prefix": "AGENT_"}

    impact_timeout_seconds: float = Field(default=15.0, gt=0.0, le=120.0)
    strategy_timeout_seconds: float = Field(default=15.0, gt=0.0, le=120.0)
    solver_timeout_seconds: float = Field(default=65.0, gt=0.0, le=600.0)
    evaluation_timeout_seconds: float = Field(default=15.0, gt=0.0, le=120.0)
    explanation_timeout_seconds: float = Field(default=12.0, gt=0.0, le=120.0)


class SolverRuntimeSettings(BaseSettings):
    """Process-local capacity limits for CPU-heavy solver calls."""

    model_config = {"env_prefix": "SOLVER_"}

    max_concurrent_jobs: int = Field(default=2, ge=1, le=16)
    queue_timeout_seconds: float = Field(default=2.0, ge=0.0, le=60.0)
    cp_sat_workers: int = Field(default=4, ge=1, le=32)
    max_model_operations: int = Field(default=2000, ge=10, le=100_000)
    heuristic_budget_ratio: float = Field(default=0.20, ge=0.01, le=0.50)
    heuristic_max_seconds: float = Field(default=2.0, ge=0.05, le=30.0)
    initial_cp_sat_budget_ratio: float = Field(default=0.65, ge=0.20, le=0.95)
    max_alns_iterations: int = Field(default=4, ge=0, le=20)


class OperationalRuntimeSettings(BaseSettings):
    """Durable state used by CDC, solve jobs, shadow, and evidence services."""

    model_config = {"env_prefix": "RUNTIME_"}

    database_url: str | None = None
    local_database_path: str = "output/reorch_runtime.db"
    default_max_queued_jobs: int = Field(default=20, ge=1, le=10000)
    default_max_running_jobs: int = Field(default=2, ge=1, le=100)
    default_max_operations_per_job: int = Field(default=10000, ge=1, le=1_000_000)
    solve_lease_seconds: int = Field(default=30, ge=3, le=3600)


class Settings(BaseSettings):
    """Aggregated settings — single entry point for all configuration."""

    db: DatabaseSettings = DatabaseSettings()
    redis: RedisSettings = RedisSettings()
    kafka: KafkaSettings = KafkaSettings()
    app: AppSettings = AppSettings()
    auth: AuthSettings = AuthSettings()
    integration: IntegrationSettings = IntegrationSettings()
    llm: LLMSettings = LLMSettings()
    agent: AgentRuntimeSettings = AgentRuntimeSettings()
    solver: SolverRuntimeSettings = SolverRuntimeSettings()
    runtime: OperationalRuntimeSettings = OperationalRuntimeSettings()


settings = Settings()
