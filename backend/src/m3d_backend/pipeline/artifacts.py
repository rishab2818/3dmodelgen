"""Helpers for reading the per-stage artifact set written by each stage."""

from __future__ import annotations

from pathlib import Path

from m3d_backend.util.paths import stage_complete_marker, stage_dir


def stage_is_complete(temp_dir: Path, job_id: str, iteration: int, stage: str) -> bool:
    """True iff this stage's ``.complete`` marker exists.

    See docs/RESUMABILITY_AND_BUDGET.md §2.
    """
    return stage_complete_marker(temp_dir, job_id, iteration, stage).exists()


def list_stage_artifacts(
    temp_dir: Path,
    job_id: str,
    iteration: int,
    stage: str,
) -> list[Path]:
    d = stage_dir(temp_dir, job_id, iteration, stage)
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and not p.name.startswith("."))
