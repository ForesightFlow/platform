from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database
    db_url: str = "postgresql+asyncpg://fflow:fflow@localhost:5432/fflow"

    # Polymarket REST
    gamma_api_url: str = "https://gamma-api.polymarket.com"
    clob_api_url: str = "https://clob.polymarket.com"

    # The Graph — Polymarket subgraph
    subgraph_url: str = (
        "https://gateway.thegraph.com/api/subgraphs/id/"
        "81Dm16JjuFSrqz813HysXoUPvzTwE7fsfPk2RTf66nyC"
    )
    thegraph_api_key: str | None = None

    # Polygonscan
    polygonscan_api_key: str | None = None
    polygonscan_url: str = "https://api.etherscan.io/v2/api"

    # Anthropic (Tier 3 LLM) — accepts FFLOW_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("FFLOW_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )

    # UMA / Polygon RPC
    polygon_rpc_url: str = "https://1rpc.io/matic"

    # HTTP tuning
    http_timeout_seconds: float = 30.0
    http_max_retries: int = 5
    http_backoff_base_seconds: float = 1.0

    # Logging
    log_level: str = "INFO"
    log_json: bool = False

    model_config = SettingsConfigDict(env_prefix="FFLOW_", env_file=".env", extra="ignore")


settings = Settings()
