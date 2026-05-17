"""MockGPUBackend: returns canned fixtures with realistic delays.

The mock is what lets all of M1 work without a real GPU. It also drives integration tests
in CI. See docs/DECISIONS/ADR-0002 and ai_models/CLAUDE.md §5.

Score profiles (env M3D_MOCK_SCORE_PROFILE):
  - "instant_success" (default): first iteration scores 0.92, exits the loop.
  - "improving": 0.55 → 0.70 → 0.84 → 0.91 across iterations.
  - "stuck": always 0.72.
  - "oscillating": 0.7 ↔ 0.6 ↔ 0.75 ↔ 0.62.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from m3d_backend.gpu.base import (
    EvaluateRequest,
    EvaluateResponse,
    GenerateRequest,
    GenerateResponse,
    GenerationMeta,
)

MOCK_REVISION = "mock-fixture-v1"


class MockGPUBackend:
    name = "mock"

    def __init__(self, fixtures_dir: Path, delay_ms: int = 400) -> None:
        self._fixtures = fixtures_dir
        self._delay_s = delay_ms / 1000.0

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "models_loaded": ["mock"], "vram_free_mb": None}

    async def generate(self, req: GenerateRequest) -> GenerateResponse:
        # Simulate runtime.
        await asyncio.sleep(self._delay_s)
        cube_obj = self._fixtures / "cube.obj"
        if not cube_obj.exists():
            raise FileNotFoundError(
                f"Mock fixture missing: {cube_obj}. Run ai_models/fixtures/build_cube.py.",
            )
        data = cube_obj.read_bytes()
        # cheap heuristic: count vertex lines for tri_count (cube has 8 verts → 12 tris).
        tri_count = sum(1 for line in data.splitlines() if line.startswith(b"f "))
        meta = GenerationMeta(
            model=req.model,
            revision=MOCK_REVISION,
            seed=req.seed,
            runtime_ms=int(self._delay_s * 1000),
            vram_peak_mb=None,
            provider="mock",
            tri_count=tri_count,
        )
        return GenerateResponse(mesh_obj_bytes=data, albedo_png_bytes=None, meta=meta)

    async def evaluate(self, req: EvaluateRequest) -> EvaluateResponse:
        await asyncio.sleep(self._delay_s / 2)
        score = _scripted_score(req.iteration)
        report = {
            "overall_score": score,
            "silhouette_iou": min(1.0, score + 0.02),
            "clip_similarity": min(1.0, score),
            "dino_similarity": min(1.0, score),
            "color_emd": min(1.0, score),
            "lpips": min(1.0, score),
            "geometry": {
                "manifold": True,
                "watertight": True,
                "non_manifold_edge_pct": 0.0,
            },
            "diagnosis": [],
            "recommended_action": "stop" if score >= 0.85 else "regenerate_with_new_seed",
        }
        return EvaluateResponse(
            report=report,
            runtime_ms=int((self._delay_s / 2) * 1000),
            provider="mock",
        )


def _scripted_score(iteration: int) -> float:
    profile = os.environ.get("M3D_MOCK_SCORE_PROFILE", "instant_success")
    if profile == "improving":
        return [0.55, 0.70, 0.84, 0.91, 0.94][min(iteration - 1, 4)]
    if profile == "stuck":
        return 0.72
    if profile == "oscillating":
        return [0.70, 0.60, 0.75, 0.62][(iteration - 1) % 4]
    # instant_success: every iteration is great.
    return 0.92
