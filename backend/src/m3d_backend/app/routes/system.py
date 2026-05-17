"""System endpoints: /health, /config (GET + PUT), /models, /api/version."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from m3d_backend.app.deps import make_gpu_backend

router = APIRouter(tags=["system"])

API_VERSION = "1.0"


class ConfigUpdateRequest(BaseModel):
    """Runtime switch of GPU backend mode + remote URL. None = leave as-is."""

    gpu_backend: Literal["mock", "remote", "local"] | None = None
    gpu_backend_url: str | None = None
    gpu_backend_token: str | None = None
    gpu_backend_provider: str | None = Field(default=None, max_length=32)


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    state = request.app.state.app  # AppState
    try:
        gpu_status = await state.backend.health()
    except Exception as e:  # noqa: BLE001
        gpu_status = {"status": "error", "error": str(e)}
    return {
        "status": "ok",
        "api_version": API_VERSION,
        "gpu_backend": state.settings.gpu_backend,
        "gpu_status": gpu_status,
    }


@router.get("/config")
async def get_config(request: Request) -> dict[str, Any]:
    state = request.app.state.app
    s = state.settings
    return {
        "gpu_backend": s.gpu_backend,
        "gpu_backend_url": s.gpu_backend_url,
        "gpu_backend_provider": s.gpu_backend_provider,
        "blender_exe": str(s.blender_exe),
        "temp_dir": str(s.temp_dir),
        "exports_dir": str(s.exports_dir),
        "mock_delay_ms": s.mock_delay_ms,
        "bg_removal_enabled": s.bg_removal_enabled,
        "bg_removal_model": s.bg_removal_model,
    }


@router.put("/config")
async def update_config(request: Request, body: ConfigUpdateRequest) -> dict[str, Any]:
    """Runtime backend swap. The new GPU backend is constructed eagerly so we surface
    config errors (missing URL, bad auth) here instead of at job time.

    The previous backend is closed (if it has ``close()``) to release sockets.
    """
    state = request.app.state.app
    s = state.settings

    if body.gpu_backend is not None:
        s.gpu_backend = body.gpu_backend
    if body.gpu_backend_url is not None:
        s.gpu_backend_url = body.gpu_backend_url or None
    if body.gpu_backend_token is not None:
        s.gpu_backend_token = body.gpu_backend_token or None
    if body.gpu_backend_provider is not None:
        s.gpu_backend_provider = body.gpu_backend_provider

    try:
        new_backend = make_gpu_backend(s)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"config rejected: {e}") from e

    # Close prior backend if it owns resources.
    prior = state.backend
    state.backend = new_backend
    close = getattr(prior, "close", None)
    if callable(close):
        try:
            await close()
        except Exception:  # noqa: BLE001
            pass

    return await get_config(request)


@router.get("/models")
async def list_models(request: Request) -> dict[str, Any]:
    state = request.app.state.app
    # M1: only mock. M2+ pulls from ai_models/registry.yaml.
    if state.settings.gpu_backend == "mock":
        return {
            "generators": [
                {"name": "mock", "available": True, "min_vram_mb": 0},
            ],
        }
    return {"generators": []}
