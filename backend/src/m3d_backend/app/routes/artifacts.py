"""Static-file serving for per-job artifacts and final exports.

Both paths are sandboxed: requests cannot escape the configured directory via ``..``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter(tags=["artifacts"])


def _safe_join(root: Path, rel: str) -> Path:
    """Resolve ``rel`` under ``root``, rejecting any path that escapes ``root``."""
    candidate = (root / rel).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as e:
        raise HTTPException(400, "Path escapes sandbox") from e
    return candidate


@router.get("/jobs/{job_id}/artifacts/{path:path}")
async def get_artifact(request: Request, job_id: str, path: str) -> FileResponse:
    state = request.app.state.app
    job_root = state.settings.temp_dir / job_id
    file = _safe_join(job_root, path)
    if not file.exists() or not file.is_file():
        raise HTTPException(404, f"artifact not found: {path}")
    return FileResponse(file)


@router.get("/exports/{job_id}/{file:path}")
async def get_export(request: Request, job_id: str, file: str) -> FileResponse:
    state = request.app.state.app
    export_root = state.settings.exports_dir / job_id
    target = _safe_join(export_root, file)
    if not target.exists() or not target.is_file():
        raise HTTPException(404, f"export not found: {file}")
    return FileResponse(target)
