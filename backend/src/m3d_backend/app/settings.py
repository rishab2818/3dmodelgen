"""Application settings, loaded from environment with the M3D_ prefix."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Effective settings for the backend process.

    All values can be overridden via environment variables prefixed with ``M3D_``
    or via a ``.env`` file in the project root.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="M3D_",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # HTTP
    host: str = "127.0.0.1"
    port: int = 7878

    # GPU backend selection (see ADR-0002)
    gpu_backend: Literal["mock", "remote", "local"] = "mock"
    gpu_backend_url: str | None = None
    gpu_backend_token: str | None = None

    # External executables
    blender_exe: Path = Path(
        "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe",
    )

    # Storage
    db_url: str = "sqlite+aiosqlite:///./backend/state.db"
    temp_dir: Path = Path("./temp")
    exports_dir: Path = Path("./exports")
    models_cache: Path = Path("./models_cache")
    fixtures_dir: Path = Path("./ai_models/fixtures")

    # Pipeline knobs
    mock_delay_ms: int = Field(default=400, ge=0, le=60_000)
    stage_timeout_s: int = Field(default=300, ge=10, le=3_600)

    # Preprocessing knobs (see RESUMABILITY_AND_BUDGET.md — cache hits depend on
    # deterministic preprocessing output).
    bg_removal_enabled: bool = True
    bg_removal_model: str = "u2net"  # rembg model name: u2net | u2netp | silueta | isnet-general-use
    preprocess_target_size: int = 512  # generator-facing canvas, px

    # Remote backend (only used when gpu_backend == "remote")
    gpu_backend_provider: str = "colab"  # recorded in gpu_call rows for budget tracking
    gpu_backend_timeout_s: float = 180.0

    # Observability
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False  # human-readable in dev, JSON in prod

    def ensure_dirs(self) -> None:
        """Create runtime directories if they don't exist."""
        for d in (self.temp_dir, self.exports_dir, self.models_cache):
            d.mkdir(parents=True, exist_ok=True)
