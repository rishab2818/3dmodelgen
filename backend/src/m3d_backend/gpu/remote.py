"""RemoteGPUBackend — HTTP client for the ai_models remote_server.

Implements the GPUBackend protocol. Carries Idempotency-Key on every call so retries
never double-bill. Maps remote errors onto the orchestrator's stable error codes per
docs/BACKEND_CONTRACT.md §1.5.
"""

from __future__ import annotations

import base64
import gzip
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from m3d_backend.gpu.base import (
    EvaluateRequest,
    EvaluateResponse,
    GenerateRequest,
    GenerateResponse,
    GenerationMeta,
)

log = structlog.get_logger(__name__)


class RemoteBackendError(Exception):
    """Raised when the remote endpoint returns a non-2xx response."""

    def __init__(self, code: str, message: str, *, status_code: int | None = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class RemoteConfig:
    base_url: str          # e.g. "https://xyz.ngrok.app"
    token: str | None      # bearer
    provider: str          # "colab" | "modal" | "runpod" — recorded in gpu_call rows
    timeout_s: float = 180.0
    health_timeout_s: float = 5.0


_TRANSIENT_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.HTTPStatusError,  # filtered below — only 5xx is transient
)


class RemoteGPUBackend:
    """Synchronous-feeling async client. One connection pool, lazy-initialized.

    Retries are conservative: 3 attempts max, exponential backoff. Idempotency-Key means
    even retries that race the original request don't double-bill — the server returns
    the cached response.
    """

    def __init__(self, cfg: RemoteConfig) -> None:
        self.name = "remote"
        self._cfg = cfg
        self._client: httpx.AsyncClient | None = None

    def _client_or_init(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"User-Agent": "m3d-orchestrator/0.1"}
            if self._cfg.token:
                headers["Authorization"] = f"Bearer {self._cfg.token}"
            self._client = httpx.AsyncClient(
                base_url=self._cfg.base_url,
                timeout=self._cfg.timeout_s,
                headers=headers,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # --- GPUBackend protocol ----------------------------------------------

    async def health(self) -> dict[str, Any]:
        c = self._client_or_init()
        try:
            r = await c.get("/health", timeout=self._cfg.health_timeout_s)
        except Exception as e:  # noqa: BLE001
            raise RemoteBackendError("REMOTE_GPU_OFFLINE", str(e)) from e
        if r.status_code == 401:
            raise RemoteBackendError("REMOTE_GPU_AUTH", "bad bearer token", status_code=401)
        if not r.is_success:
            raise RemoteBackendError(
                "REMOTE_GPU_OFFLINE",
                f"health returned {r.status_code}: {r.text[:200]}",
                status_code=r.status_code,
            )
        return r.json()

    async def generate(self, req: GenerateRequest) -> GenerateResponse:
        body = {
            "model": req.model,
            "images_b64": [_encode_image(p) for p in req.image_paths],
            "seed": req.seed,
            "params": req.params,
        }
        headers = {"Idempotency-Key": req.idempotency_key}
        resp = await self._post_with_retry("/generate", body, headers=headers)

        mesh_bytes = _gunzip_b64(resp["mesh_obj_b64"])
        albedo_bytes: bytes | None = None
        if resp.get("albedo_png_b64"):
            albedo_bytes = base64.b64decode(resp["albedo_png_b64"])

        m = resp["meta"]
        meta = GenerationMeta(
            model=m["model"],
            revision=m["revision"],
            seed=m["seed"],
            runtime_ms=int(m["runtime_ms"]),
            vram_peak_mb=m.get("vram_peak_mb"),
            provider=self._cfg.provider,
            tri_count=int(m.get("tri_count", 0)),
            cached=bool(m.get("cached", False)),
        )
        return GenerateResponse(
            mesh_obj_bytes=mesh_bytes,
            albedo_png_bytes=albedo_bytes,
            meta=meta,
        )

    async def evaluate(self, req: EvaluateRequest) -> EvaluateResponse:
        # M3 wires the real evaluator. This stub keeps the protocol satisfied so
        # M2 doesn't crash when reaching the evaluate stage in remote mode.
        _ = req
        raise RemoteBackendError(
            "EVAL_FAILED",
            "remote evaluate is not implemented until M3 — set GPU_BACKEND=mock for eval",
        )

    # --- Internals --------------------------------------------------------

    @retry(
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _post_with_retry(
        self,
        path: str,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        c = self._client_or_init()
        try:
            r = await c.post(path, json=body, headers=headers)
        except (httpx.ConnectError, httpx.ReadTimeout) as e:
            log.warning("remote.transient_error", path=path, error=str(e))
            raise
        except Exception as e:  # noqa: BLE001
            raise RemoteBackendError("REMOTE_GPU_OFFLINE", str(e)) from e

        if r.status_code == 401:
            raise RemoteBackendError("REMOTE_GPU_AUTH", "bad bearer token", status_code=401)
        if r.status_code in (502, 503, 504):
            log.warning("remote.transient_status", status=r.status_code)
            raise httpx.RemoteProtocolError(f"transient {r.status_code}")
        if not r.is_success:
            code, message = _classify_error(r)
            raise RemoteBackendError(code, message, status_code=r.status_code)
        return r.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _encode_image(path: Path) -> str:
    data = path.read_bytes()
    return base64.b64encode(data).decode("ascii")


def _gunzip_b64(s: str) -> bytes:
    return gzip.decompress(base64.b64decode(s))


def _classify_error(r: httpx.Response) -> tuple[str, str]:
    """Map remote HTTP error to (orchestrator_code, message)."""
    body: Any
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = r.text
    if isinstance(body, dict):
        detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            code = str(detail["code"])
            # Translate a few known codes; pass through the rest.
            mapping = {
                "OOM": "GENERATOR_OOM",
                "CUDA_OOM": "GENERATOR_OOM",
                "GENERATOR_FAILED": "GENERATOR_FAILED",
            }
            return mapping.get(code, code), str(detail.get("message", ""))
    return ("GENERATOR_FAILED", f"HTTP {r.status_code}: {str(body)[:300]}")
