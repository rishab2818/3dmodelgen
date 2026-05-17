"""Smoke + idempotency tests for the m3d_ai remote_server with the mock adapter."""

from __future__ import annotations

import asyncio
import base64
import gzip
import io

import pytest
from httpx import AsyncClient
from PIL import Image


def _png_b64() -> str:
    buf = io.BytesIO()
    Image.new("RGBA", (16, 16), (50, 100, 200, 255)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


@pytest.mark.asyncio
async def test_health(server_client: AsyncClient) -> None:
    r = await server_client.get("/health")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ok"
    assert data["adapter"] == "mock"


@pytest.mark.asyncio
async def test_generate_round_trip(server_client: AsyncClient) -> None:
    body = {
        "model": "mock",
        "images_b64": [_png_b64()],
        "seed": 42,
        "params": {},
    }
    r = await server_client.post(
        "/generate",
        json=body,
        headers={"Idempotency-Key": "job-x:1:generate:0"},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    # Mesh round-trips through gzip+b64.
    mesh = gzip.decompress(base64.b64decode(payload["mesh_obj_b64"]))
    assert mesh.startswith(b"# cube.obj") or b"\nv " in mesh
    assert payload["meta"]["model"] == "mock"
    assert payload["meta"]["runtime_ms"] >= 0


@pytest.mark.asyncio
async def test_generate_requires_idempotency_key(server_client: AsyncClient) -> None:
    body = {"model": "mock", "images_b64": [_png_b64()], "seed": 42, "params": {}}
    r = await server_client.post("/generate", json=body)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_idempotency_dedupes_repeat_calls(server_client: AsyncClient) -> None:
    """Two POSTs with the same key produce ONE adapter invocation (timestamps identical
    because the cached response is byte-identical, including its runtime_ms).
    """
    body = {"model": "mock", "images_b64": [_png_b64()], "seed": 7, "params": {}}
    key = "job-y:1:generate:0"
    r1 = await server_client.post("/generate", json=body, headers={"Idempotency-Key": key})
    r2 = await server_client.post("/generate", json=body, headers={"Idempotency-Key": key})
    assert r1.status_code == 200 and r2.status_code == 200
    # Same response body — including the meta.runtime_ms — confirms the second call
    # was served from cache, not re-run.
    assert r1.json() == r2.json()


@pytest.mark.asyncio
async def test_idempotency_concurrent_requests_collapse_to_one(server_client: AsyncClient) -> None:
    """Two concurrent requests with the same key — the second blocks on the first and
    returns the same response without re-invoking the adapter.
    """
    body = {"model": "mock", "images_b64": [_png_b64()], "seed": 11, "params": {}}
    key = "job-z:1:generate:0"
    r1, r2 = await asyncio.gather(
        server_client.post("/generate", json=body, headers={"Idempotency-Key": key}),
        server_client.post("/generate", json=body, headers={"Idempotency-Key": key}),
    )
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json() == r2.json()


@pytest.mark.asyncio
async def test_different_keys_run_independently(server_client: AsyncClient) -> None:
    body = {"model": "mock", "images_b64": [_png_b64()], "seed": 1, "params": {}}
    r1 = await server_client.post(
        "/generate", json=body, headers={"Idempotency-Key": "job-a:1:generate:0"},
    )
    r2 = await server_client.post(
        "/generate", json=body, headers={"Idempotency-Key": "job-b:1:generate:0"},
    )
    assert r1.status_code == 200 and r2.status_code == 200
    # Different keys, different adapter invocations — runtime_ms varies. The constant
    # we can rely on is the decoded mesh bytes (cube fixture is deterministic).
    # gzip stamps a timestamp, so the encoded payload itself is NOT byte-identical.
    p1, p2 = r1.json(), r2.json()
    mesh1 = gzip.decompress(base64.b64decode(p1["mesh_obj_b64"]))
    mesh2 = gzip.decompress(base64.b64decode(p2["mesh_obj_b64"]))
    assert mesh1 == mesh2
