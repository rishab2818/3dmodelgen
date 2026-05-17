"""Stage 3: Blender headless cleanup.

Invokes ``blender/scripts/cleanup.py`` via the shared ``blender_runner`` and produces
``cleanup/mesh.glb`` for the rest of the pipeline. Real, not mocked — this stage runs the
actual Blender even in M1, so we exercise the subprocess plumbing.
"""

from __future__ import annotations

from pathlib import Path

from m3d_backend.blender_runner import BlenderRunResult, run_blender_script
from m3d_backend.util.paths import stage_dir


async def run(
    *,
    blender_exe: Path,
    repo_root: Path,
    temp_dir: Path,
    job_id: str,
    iteration: int,
    input_mesh: Path,
) -> tuple[Path, BlenderRunResult]:
    out_dir = stage_dir(temp_dir, job_id, iteration, "blender_cleanup")
    out_dir.mkdir(parents=True, exist_ok=True)
    output_mesh = out_dir / "mesh.glb"

    script = repo_root / "blender" / "scripts" / "cleanup.py"
    result = await run_blender_script(
        blender_exe=blender_exe,
        script=script,
        args=[
            "--input", str(input_mesh),
            "--output", str(output_mesh),
            "--json-progress",
        ],
        timeout_s=300,
    )
    if not result.ok:
        raise RuntimeError(f"Blender cleanup failed: {result.error}")
    return output_mesh, result
