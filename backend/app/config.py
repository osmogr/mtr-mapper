from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+asyncpg://mtrmapper:mtrmapper@db:5432/mtrmapper"
    )

    admin_password: str = "change-me"
    admin_session_secret: str = "change-me-to-a-long-random-string"
    admin_session_ttl_seconds: int = 28800

    prober_api_token: str = "change-me-prober-token"

    trace_retention_hours: int = 48
    retention_sweep_interval_seconds: int = 900
    tree_recompute_interval_seconds: float = 2.0

    loss_warn_threshold: float = 2.0
    loss_critical_threshold: float = 20.0

    target_list_default_fetch_interval_seconds: int = 3600

    asn_lookup_enabled: bool = True
    asn_lookup_timeout_seconds: float = 2.0
    asn_cache_ttl_hours: int = 24

    hostname_lookup_enabled: bool = True
    hostname_lookup_timeout_seconds: float = 2.0
    hostname_cache_ttl_hours: int = 24

    path_fade_hours: float = 24.0

    cors_allowed_origins: str = "http://localhost:8080"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
