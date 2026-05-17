"""FastAPI server exposing /generate, /evaluate, /health.

This is the wire side of the RemoteGPUBackend abstraction. Same adapter code runs here
(remote) and in-process (local). The orchestrator never knows which.

Contract: docs/BACKEND_CONTRACT.md §2. In particular:
  * Bearer token in Authorization header (env M3D_AI_AUTH_TOKEN; None = no auth in dev).
  * Idempotency-Key required on /generate and /evaluate. Deduped via IdempotencyCache.
  * Response includes ``meta`` with runtime_ms + vram_peak_mb so the orchestrator can
    record a gpu_call row.

The adapter chosen by env M3D_AI_PRIMARY_GENERATOR:
  * "mock"     — no torch needed; uses cube fixture. Default.
  * "triposr"  — requires torch extra installed + CUDA.
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import io
import logging
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Literal

import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from PIL import Image
from pydantic import BaseModel, Field

from m3d_ai.adapters.base import GenerationResult
from m3d_ai.adapters.mock import MockAdapter
from m3d_ai.idempotency import IdempotencyCache
from m3d_ai.settings import Settings


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=level, stream=sys.stderr, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO),
        ),
        cache_logger_on_first_use=True,
    )


# ---------------------------------------------------------------------------
# Wire schemas
# ---------------------------------------------------------------------------


class GenerateRequest(BaseModel):
    model: Literal["mock", "triposr", "hunyuan3d-2", "instantmesh"]
    images_b64: list[str] = Field(..., min_length=1)
    seed: int = 42
    params: dict[str, Any] = Field(default_factory=dict)


class GenerationMetaWire(BaseModel):
    model: str
    revision: str
    seed: int
    runtime_ms: int
    vram_peak_mb: int | None = None
    provider: str
    tri_count: int
    cached: bool = False


class GenerateResponse(BaseModel):
    # gzip+b64 of OBJ bytes — keeps payloads small over ngrok.
    mesh_obj_b64: str
    albedo_png_b64: str | None = None
    meta: GenerationMetaWire


# ---------------------------------------------------------------------------
# Lifespan + adapter factory
# ---------------------------------------------------------------------------


def _make_adapter(name: str):  # type: ignore[no-untyped-def]
    if name == "mock":
        return MockAdapter()
    if name == "triposr":
        from m3d_ai.adapters.triposr import TripoSRAdapter  # lazy: requires torch extra
        return TripoSRAdapter(device="cuda")
    raise ValueError(f"Unknown adapter: {name}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    _configure_logging(settings.log_level)
    log = structlog.get_logger("m3d_ai")

    adapter = _make_adapter(settings.primary_generator)
    # Warm up off the main loop so health works immediately.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, adapter.warm_up)

    cache = IdempotencyCache(
        capacity=settings.idempotency_capacity,
        ttl_s=settings.idempotency_ttl_s,
    )

    app.state.settings = settings
    app.state.adapter = adapter
    app.state.cache = cache

    log.info(
        "remote_server.start",
        adapter=adapter.name,
        revision=adapter.revision,
        host=settings.host,
        port=settings.port,
        auth=bool(settings.auth_token),
    )
    try:
        yield
    finally:
        adapter.unload()
        log.info("remote_server.stop")


# ---------------------------------------------------------------------------
# Auth dep
# ---------------------------------------------------------------------------


async def require_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    expected = request.app.state.settings.auth_token
    if expected is None:
        return  # auth disabled (dev)
    if authorization != f"Bearer {expected}":
        raise HTTPException(401, "missing or invalid bearer token")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(title="m3d_ai remote server", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:  # type: ignore[unused-function]
        adapter = request.app.state.adapter
        # Best-effort VRAM stats (only meaningful with torch on cuda).
        vram_free_mb: int | None = None
        try:
            import torch  # type: ignore[import-not-found]
            if torch.cuda.is_available():
                free, _total = torch.cuda.mem_get_info()
                vram_free_mb = int(free / (1024 * 1024))
        except Exception:  # noqa: BLE001
            pass
        return {
            "status": "ok",
            "adapter": adapter.name,
            "revision": adapter.revision,
            "vram_free_mb": vram_free_mb,
            "idempotency_cache_size": request.app.state.cache.size(),
        }

    @app.post("/generate", response_model=GenerateResponse, dependencies=[Depends(require_token)])
    async def generate(
        request: Request,
        body: GenerateRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> GenerateResponse:
        if not idempotency_key:
            raise HTTPException(400, "Idempotency-Key header is required")
        adapter = request.app.state.adapter
        cache: IdempotencyCache = request.app.state.cache

        async def run() -> GenerateResponse:
            images = [_decode_image(b) for b in body.images_b64]
            loop = asyncio.get_running_loop()
            result: GenerationResult = await loop.run_in_executor(
                None, adapter.generate, images, body.seed, body.params,
            )
            return GenerateResponse(
                mesh_obj_b64=_gzip_b64(result.mesh_obj),
                albedo_png_b64=_b64(result.albedo_png) if result.albedo_png else None,
                meta=GenerationMetaWire(**result.meta),
            )

        try:
            return await cache.execute(idempotency_key, run)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "GENERATOR_FAILED", "message": str(e)},
            ) from e

    @app.post("/evaluate", dependencies=[Depends(require_token)])
    async def evaluate(
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        # M3 implements this. We stub it now so the route exists in the contract.
        _ = request, idempotency_key
        raise HTTPException(501, "evaluate lands in M3")

    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decode_image(b64: str) -> Image.Image:
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"invalid base64 image: {e}") from e
    try:
        return Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"image decode failed: {e}") from e


def _gzip_b64(data: bytes) -> str:
    return base64.b64encode(gzip.compress(data, compresslevel=6)).decode("ascii")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


app = create_app()
