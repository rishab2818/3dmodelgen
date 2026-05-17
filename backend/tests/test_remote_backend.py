"""Unit tests for RemoteGPUBackend HTTP client.

Uses httpx.MockTransport so we exercise the real serialization, header handling, and
error-mapping paths without needing a live server.
"""

from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path

import httpx
import pytest

from m3d_backend.gpu.base import GenerateRequest
from m3d_backend.gpu.remote import RemoteBackendError, RemoteConfig, RemoteGPUBackend


def _make_backend(handler) -> RemoteGPUBackend:  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(handler)
    cfg = RemoteConfig(
        base_url="http://test.local",
        token="secret",
        provider="colab",
        timeout_s=5.0,
    )
    backend = RemoteGPUBackend(cfg)
    # Pre-initialize the client so we can swap in our test transport.
    backend._client = httpx.AsyncClient(  # type: ignore[reportPrivateUsage]  # noqa: SLF001
        base_url=cfg.base_url,
        timeout=cfg.timeout_s,
        headers={
            "User-Agent": "m3d-orchestrator-test/0.1",
            "Authorization": f"Bearer {cfg.token}",
        },
        transport=transport,
    )
    return backend


@pytest.mark.asyncio
async def test_health_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(200, json={"status": "ok", "adapter": "mock"})

    backend = _make_backend(handler)
    try:
        data = await backend.health()
    finally:
        await backend.close()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_health_offline_maps_cleanly() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    backend = _make_backend(handler)
    with pytest.raises(RemoteBackendError) as exc:
        await backend.health()
    await backend.close()
    assert exc.value.code == "REMOTE_GPU_OFFLINE"


@pytest.mark.asyncio
async def test_health_bad_auth() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    backend = _make_backend(handler)
    with pytest.raises(RemoteBackendError) as exc:
        await backend.health()
    await backend.close()
    assert exc.value.code == "REMOTE_GPU_AUTH"


@pytest.mark.asyncio
async def test_generate_carries_idempotency_key_and_decodes_response(tmp_path: Path) -> None:
    # Prepare a fake input image (file contents only — server side decodes).
    image = tmp_path / "img.png"
    image.write_bytes(b"PNG-content-stub")

    # Server returns gzip+b64 of an OBJ.
    mesh_obj = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
    encoded = base64.b64encode(gzip.compress(mesh_obj)).decode("ascii")

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["idempotency_key"] = request.headers.get("idempotency-key")
        body = json.loads(request.content)
        captured["body"] = body
        return httpx.Response(
            200,
            json={
                "mesh_obj_b64": encoded,
                "albedo_png_b64": None,
                "meta": {
                    "model": "mock",
                    "revision": "rev-1",
                    "seed": 42,
                    "runtime_ms": 1234,
                    "vram_peak_mb": None,
                    "provider": "remote",
                    "tri_count": 1,
                    "cached": False,
                },
            },
        )

    backend = _make_backend(handler)
    req = GenerateRequest(
        job_id="abc",
        iteration=1,
        stage="generate",
        model="mock",
        image_paths=[image],
        seed=42,
        idempotency_key="abc:1:generate:0",
    )
    resp = await backend.generate(req)
    await backend.close()

    assert captured["path"] == "/generate"
    assert captured["idempotency_key"] == "abc:1:generate:0"
    assert isinstance(captured["body"], dict)
    assert captured["body"]["model"] == "mock"
    assert captured["body"]["seed"] == 42
    assert len(captured["body"]["images_b64"]) == 1
    # Round-trip: the response payload is gunzipped + base64-decoded.
    assert resp.mesh_obj_bytes == mesh_obj
    # Provider is overridden by orchestrator config (colab), not server response.
    assert resp.meta.provider == "colab"
    assert resp.meta.runtime_ms == 1234


@pytest.mark.asyncio
async def test_generate_oom_mapped_to_stable_code(tmp_path: Path) -> None:
    image = tmp_path / "img.png"
    image.write_bytes(b"x")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"detail": {"code": "CUDA_OOM", "message": "out of memory"}},
        )

    backend = _make_backend(handler)
    req = GenerateRequest(
        job_id="abc",
        iteration=1,
        stage="generate",
        model="mock",
        image_paths=[image],
        seed=42,
        idempotency_key="abc:1:generate:0",
    )
    with pytest.raises(RemoteBackendError) as exc:
        await backend.generate(req)
    await backend.close()
    assert exc.value.code == "GENERATOR_OOM"


@pytest.mark.asyncio
async def test_generate_retries_on_transient_then_succeeds(tmp_path: Path) -> None:
    """502 once, then 200. The retry must reuse the same idempotency key — that's the
    whole point of idempotency in our budget contract.
    """
    image = tmp_path / "img.png"
    image.write_bytes(b"x")
    mesh_obj = b"v 0 0 0\n"
    encoded = base64.b64encode(gzip.compress(mesh_obj)).decode("ascii")

    attempts: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.headers.get("idempotency-key"))
        if len(attempts) == 1:
            return httpx.Response(502, text="upstream busy")
        return httpx.Response(
            200,
            json={
                "mesh_obj_b64": encoded,
                "albedo_png_b64": None,
                "meta": {
                    "model": "mock",
                    "revision": "rev-1",
                    "seed": 42,
                    "runtime_ms": 100,
                    "vram_peak_mb": None,
                    "provider": "remote",
                    "tri_count": 1,
                    "cached": False,
                },
            },
        )

    backend = _make_backend(handler)
    req = GenerateRequest(
        job_id="job-A",
        iteration=2,
        stage="generate",
        model="mock",
        image_paths=[image],
        seed=42,
        idempotency_key="job-A:2:generate:0",
    )
    resp = await backend.generate(req)
    await backend.close()
    assert resp.mesh_obj_bytes == mesh_obj
    assert len(attempts) == 2
    # Both attempts MUST carry the same key — the entire point of idempotency.
    assert attempts[0] == attempts[1] == "job-A:2:generate:0"
