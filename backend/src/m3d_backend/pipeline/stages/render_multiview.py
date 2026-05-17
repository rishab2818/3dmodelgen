"""Stage 4: multi-view rendering.

M1 implementation: skipped in mock mode (returns no renders). The real ``render_views.py``
Blender script lands in M3 when the evaluator needs renders.
"""

from __future__ import annotations

from pathlib import Path

from m3d_backend.util.paths import stage_dir


async def run(
    *,
    temp_dir: Path,
    job_id: str,
    iteration: int,
    mock: bool,
) -> dict[str, Path]:
    out_dir = stage_dir(temp_dir, job_id, iteration, "render_multiview")
    out_dir.mkdir(parents=True, exist_ok=True)
    if mock:
        # Mock: produce empty placeholder PNG paths so the evaluator's contract is satisfied.
        return {}
    # Real path (M3): invoke blender/scripts/render_views.py.
    raise NotImplementedError("render_multiview real path lands in M3")
