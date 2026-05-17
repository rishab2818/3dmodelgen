"""End-to-end smoke test: POST /jobs against mock backend → real Blender cleanup → export.

Exercises every M1 contract:
  * REST: POST /jobs, GET /jobs/{id}, GET /jobs/{id}/budget
  * SSE: would be the same code path; here we wait via polling for simplicity
  * Mock GPU backend round-trip
  * REAL Blender subprocess (cleanup.py against the cube fixture)
  * Export step writes the .glb under exports/{job_id}/

This is the test that must stay green for the rest of the project's life. If you
broke it, you broke M1.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_full_mock_pipeline_produces_glb(
    client: AsyncClient,
    png_image: Path,
) -> None:
    # 1. /health
    r = await client.get("/health")
    assert r.status_code == 200, r.text
    health = r.json()
    assert health["status"] == "ok"
    assert health["gpu_backend"] == "mock"

    # 2. POST /jobs
    r = await client.post("/jobs", json={
        "input_images": [str(png_image)],
        "target_quality": 0.85,
        "max_iterations": 2,
        "export_formats": ["glb", "obj"],
        "label": "smoke-test",
    })
    assert r.status_code == 201, r.text
    job_id = r.json()["job_id"]
    assert job_id

    # 3. Poll for completion. Mock pipeline + real Blender = a few seconds.
    deadline = 90.0
    interval = 0.4
    elapsed = 0.0
    final = None
    while elapsed < deadline:
        r = await client.get(f"/jobs/{job_id}")
        assert r.status_code == 200, r.text
        snap = r.json()
        if snap["state"] in ("succeeded", "failed", "cancelled"):
            final = snap
            break
        await asyncio.sleep(interval)
        elapsed += interval

    assert final is not None, f"job did not finish in {deadline}s"
    assert final["state"] == "succeeded", f"job ended {final['state']}: {final}"

    # 4. Budget recorded.
    r = await client.get(f"/jobs/{job_id}/budget")
    assert r.status_code == 200
    budget = r.json()
    assert budget["call_count"] >= 1
    assert budget["by_provider"].get("mock", 0) > 0

    # 5. Export artifacts on disk.
    exports_root = Path(os.environ["M3D_EXPORTS_DIR"]) / job_id
    glb = exports_root / "model.glb"
    obj = exports_root / "model.obj"
    report = exports_root / "report.json"
    assert glb.exists(), f"missing {glb}"
    assert glb.stat().st_size > 0
    assert obj.exists()
    assert report.exists()

    # 6. .complete markers exist for every stage of the best iteration.
    temp_root = Path(os.environ["M3D_TEMP_DIR"]) / job_id
    best_iter = final["best_iteration"]
    assert best_iter is not None
    for stage in ("preprocess",):  # preprocess is iter-1 only
        marker = temp_root / "iter_01" / stage / ".complete"
        assert marker.exists(), f"missing .complete for iter01/{stage}"
    for stage in ("generate", "blender_cleanup", "render_multiview", "evaluate"):
        marker = temp_root / f"iter_{best_iter:02d}" / stage / ".complete"
        assert marker.exists(), f"missing .complete for iter{best_iter}/{stage}"


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["api_version"] == "1.0"
    assert body["gpu_backend"] == "mock"


@pytest.mark.asyncio
async def test_create_job_rejects_missing_image(client: AsyncClient) -> None:
    r = await client.post("/jobs", json={
        "input_images": ["/nonexistent/image.png"],
    })
    assert r.status_code == 400
