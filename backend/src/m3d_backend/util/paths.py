"""Path conventions for per-job, per-iteration, per-stage artifacts.

See docs/PIPELINE.md and docs/RESUMABILITY_AND_BUDGET.md.
"""

from __future__ import annotations

from pathlib import Path


def job_root(temp_dir: Path, job_id: str) -> Path:
    return temp_dir / job_id


def input_dir(temp_dir: Path, job_id: str) -> Path:
    return job_root(temp_dir, job_id) / "input"


def iter_dir(temp_dir: Path, job_id: str, iteration: int) -> Path:
    return job_root(temp_dir, job_id) / f"iter_{iteration:02d}"


def stage_dir(temp_dir: Path, job_id: str, iteration: int, stage: str) -> Path:
    return iter_dir(temp_dir, job_id, iteration) / stage


def stage_complete_marker(temp_dir: Path, job_id: str, iteration: int, stage: str) -> Path:
    """Marker file written as the LAST act of every stage. Its existence means the stage
    completed successfully and can be skipped on resume.

    See docs/RESUMABILITY_AND_BUDGET.md §2.
    """
    return stage_dir(temp_dir, job_id, iteration, stage) / ".complete"


def exports_dir_for(exports_dir: Path, job_id: str) -> Path:
    return exports_dir / job_id
