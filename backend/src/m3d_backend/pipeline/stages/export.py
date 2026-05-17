"""Stage 7: write final exports.

Copies the chosen iteration's cleanup mesh into ``exports/{job_id}/`` and produces a
``report.json`` summarizing the run.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from m3d_backend.util.paths import exports_dir_for, stage_dir


def run(
    *,
    exports_dir: Path,
    temp_dir: Path,
    job_id: str,
    best_iteration: int,
    formats: list[str],
    iteration_reports: list[dict[str, Any]],
) -> dict[str, str]:
    """Returns ``{format: relative_path}`` for each exported artifact."""
    dest = exports_dir_for(exports_dir, job_id)
    dest.mkdir(parents=True, exist_ok=True)

    cleanup_dir = stage_dir(temp_dir, job_id, best_iteration, "blender_cleanup")
    glb = cleanup_dir / "mesh.glb"
    if not glb.exists():
        raise FileNotFoundError(f"No cleanup mesh for iteration {best_iteration}: {glb}")

    out: dict[str, str] = {}

    if "glb" in formats:
        target = dest / "model.glb"
        shutil.copy2(glb, target)
        out["glb"] = str(target.relative_to(exports_dir.parent))

    if "obj" in formats:
        # The original .obj from the generate stage is the closest source. In M2+ we will
        # round-trip through Blender to emit a properly textured .obj.
        gen_obj = stage_dir(temp_dir, job_id, best_iteration, "generate") / "mesh.obj"
        if gen_obj.exists():
            target_obj = dest / "model.obj"
            shutil.copy2(gen_obj, target_obj)
            out["obj"] = str(target_obj.relative_to(exports_dir.parent))

    if "ply" in formats:
        # M1 placeholder: skip until Blender export_final.py lands (v1.1 stage).
        pass

    report_path = dest / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "job_id": job_id,
                "best_iteration": best_iteration,
                "iterations": iteration_reports,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    out["report"] = str(report_path.relative_to(exports_dir.parent))
    return out
