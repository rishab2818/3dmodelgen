"""FastAPI dependency providers + app-state holder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, AsyncSession

from m3d_backend.app.settings import Settings
from m3d_backend.events.bus import EventBus
from m3d_backend.gpu.base import GPUBackend
from m3d_backend.gpu.mock import MockGPUBackend
from m3d_backend.gpu.remote import RemoteConfig, RemoteGPUBackend


@dataclass
class AppState:
    settings: Settings
    repo_root: Path
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    bus: EventBus
    backend: GPUBackend


def make_gpu_backend(settings: Settings) -> GPUBackend:
    """Construct the GPU backend selected by env (mock / remote / local)."""
    if settings.gpu_backend == "mock":
        return MockGPUBackend(settings.fixtures_dir, delay_ms=settings.mock_delay_ms)
    if settings.gpu_backend == "remote":
        if not settings.gpu_backend_url:
            raise ValueError(
                "gpu_backend=remote requires M3D_GPU_BACKEND_URL to be set "
                "(e.g. an ngrok HTTPS URL from the Colab notebook)",
            )
        return RemoteGPUBackend(
            RemoteConfig(
                base_url=settings.gpu_backend_url,
                token=settings.gpu_backend_token,
                provider=settings.gpu_backend_provider,
                timeout_s=settings.gpu_backend_timeout_s,
            ),
        )
    if settings.gpu_backend == "local":
        raise NotImplementedError("LocalGPUBackend lands in M6")
    raise ValueError(f"Unknown gpu_backend: {settings.gpu_backend}")
