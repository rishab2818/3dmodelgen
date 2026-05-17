"""Stage 5: evaluate the rendered mesh against the original image.

In mock mode the backend returns scripted scores. In real mode (M3+) this calls the
remote evaluator (CLIP+DINOv2+LPIPS+silhouette).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from m3d_backend.gpu.base import EvaluateRequest, GPUBackend
from m3d_backend.util.paths import input_dir


async def run(
    *,
    backend: GPUBackend,
    temp_dir: Path,
    job_id: str,
    iteration: int,
    render_paths: dict[str, Path],
    idempotency_key: str,
) -> tuple[dict[str, Any], int, str]:
    """Returns ``(report, runtime_ms, provider)``."""
    in_dir = input_dir(temp_dir, job_id)
    original = in_dir / "original.png"
    req = EvaluateRequest(
        job_id=job_id,
        iteration=iteration,
        stage="evaluate",
        original_path=original,
        mask_path=None,
        render_paths=render_paths,
        idempotency_key=idempotency_key,
    )
    resp = await backend.evaluate(req)
    return resp.report, resp.runtime_ms, resp.provider
