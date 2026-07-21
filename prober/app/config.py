from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    backend_url: str = "http://backend:8000"
    prober_api_token: str = "change-me-prober-token"

    prober_concurrency: int = 20
    prober_min_cycle_seconds: int = 30
    prober_target_refresh_seconds: int = 30
    prober_run_timeout_seconds: int = 60

    mtr_probe_count: int = 5
    mtr_probe_interval: int = 1
    mtr_timeout_seconds: int = 1
    mtr_max_hops: int = 30
    mtr_gracetime: int = 5

    # Strip this container's own default-route gateway (e.g. the Docker
    # bridge) from every trace's hops -- it's an artifact of running mtr
    # from inside a container's network namespace, not a real hop past
    # this host.
    filter_gateway_hop: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
