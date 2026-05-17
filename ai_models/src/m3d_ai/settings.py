"""Settings for the remote_server (env prefix M3D_AI_)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="M3D_AI_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    host: str = "0.0.0.0"  # noqa: S104  — server intentionally listens on all interfaces (Colab/Modal)
    port: int = 8000

    # Bearer auth token shared with the orchestrator. None = no auth (dev-only).
    auth_token: str | None = None

    # Idempotency LRU capacity + TTL (see BACKEND_CONTRACT §2.6).
    idempotency_capacity: int = 1024
    idempotency_ttl_s: int = 24 * 3600

    # Adapter selection. "mock" works without torch; everything else requires the torch extra.
    primary_generator: str = "mock"

    # Model cache dir on the host (HF_HOME).
    models_cache: str = "./models_cache"

    log_level: str = "INFO"
