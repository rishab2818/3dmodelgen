"""Job CRUD + pause / resume / cancel endpoints.

See docs/BACKEND_CONTRACT.md §1.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from m3d_backend.db import repo
from m3d_backend.db.models import Job
from m3d_backend.events.shapes import SseEvent
from m3d_backend.pipeline.graph import PipelineConfig, PipelineExecutor
from m3d_backend.util.ids import new_job_id

router = APIRouter(prefix="/jobs", tags=["jobs"])


class CreateJobRequest(BaseModel):
    input_images: list[Path]
    target_quality: float = Field(default=0.85, ge=0.0, le=1.0)
    max_iterations: int = Field(default=6, ge=1, le=12)
    seed: int = 42
    generator_pref: Literal["auto", "triposr", "hunyuan3d-2", "instantmesh"] = "auto"
    export_formats: list[Literal["glb", "obj", "ply"]] = Field(
        default_factory=lambda: ["glb", "obj", "ply"],
    )
    label: str | None = None
    budget_cap_s: int | None = Field(default=None, ge=10)

    @field_validator("input_images")
    @classmethod
    def _at_least_one_input(cls, v: list[Path]) -> list[Path]:
        if not v:
            raise ValueError("input_images must contain at least one path")
        return v


class CreateJobResponse(BaseModel):
    job_id: str


def _serialize_job(job: Job, *, budget: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": job.id,
        "label": job.label,
        "state": job.state,
        "paused_reason": job.paused_reason,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "current_iteration": job.current_iter_n,
        "best_iteration": job.best_iter_n,
        "inputs": json.loads(job.inputs_json),
        "budget": budget or {},
    }


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CreateJobResponse)
async def create_job(request: Request, body: CreateJobRequest) -> CreateJobResponse:
    state = request.app.state.app

    # Light validation: paths must exist.
    for p in body.input_images:
        if not p.exists():
            raise HTTPException(400, f"Input image not found: {p}")

    job_id = new_job_id()
    async with state.session_factory() as session:
        await repo.create_job(
            session,
            job_id=job_id,
            label=body.label,
            inputs=body.model_dump(mode="json"),
            budget_cap_s=body.budget_cap_s,
        )
        await session.commit()

    # Kick off execution as a background task; SSE clients see progress in real time.
    cfg = PipelineConfig(
        blender_exe=state.settings.blender_exe,
        repo_root=state.repo_root,
        temp_dir=state.settings.temp_dir,
        exports_dir=state.settings.exports_dir,
        fixtures_dir=state.settings.fixtures_dir,
        model=(
            "mock" if state.settings.gpu_backend == "mock"
            else (body.generator_pref if body.generator_pref != "auto" else "triposr")
        ),
        target_quality=body.target_quality,
        max_iterations=body.max_iterations,
        initial_seed=body.seed,
        export_formats=tuple(body.export_formats),
        # M2: preprocessing follows backend settings. Tests turn this off.
        bg_removal_enabled=state.settings.bg_removal_enabled,
        bg_removal_model=state.settings.bg_removal_model,
        preprocess_target_size=state.settings.preprocess_target_size,
    )
    executor = PipelineExecutor(
        bus=state.bus,
        backend=state.backend,
        session_factory=state.session_factory,
        config=cfg,
    )

    async def _runner() -> None:
        try:
            await executor.run(job_id, body.input_images)
        except Exception:  # noqa: BLE001
            # Already published as job_failed by the executor.
            pass

    request.app.state.tasks.add(asyncio.create_task(_runner()))
    return CreateJobResponse(job_id=job_id)


@router.get("")
async def list_jobs(request: Request, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    state = request.app.state.app
    async with state.session_factory() as session:
        jobs = await repo.list_jobs(session, limit=limit, offset=offset)
        return {"jobs": [_serialize_job(j) for j in jobs]}


@router.get("/{job_id}")
async def get_job(request: Request, job_id: str) -> dict[str, Any]:
    state = request.app.state.app
    async with state.session_factory() as session:
        job = await repo.get_job(session, job_id)
        if job is None:
            raise HTTPException(404, f"job {job_id} not found")
        budget = await repo.job_budget_summary(session, job_id)
        return _serialize_job(job, budget=budget)


@router.post("/{job_id}/cancel")
async def cancel_job(request: Request, job_id: str) -> dict[str, str]:
    state = request.app.state.app
    async with state.session_factory() as session:
        job = await repo.get_job(session, job_id)
        if job is None:
            raise HTTPException(404, f"job {job_id} not found")
        await repo.set_job_state(session, job, "cancelled")
        await session.commit()
    await state.bus.publish(job_id, SseEvent(
        event="job_failed",
        data={"error": {"code": "CANCELLED_BY_USER", "message": "Cancelled by user"}},
    ))
    return {"status": "cancelled"}


@router.post("/{job_id}/pause")
async def pause_job(request: Request, job_id: str) -> dict[str, str]:
    state = request.app.state.app
    async with state.session_factory() as session:
        job = await repo.get_job(session, job_id)
        if job is None:
            raise HTTPException(404, f"job {job_id} not found")
        await repo.set_job_state(session, job, "paused_by_user", paused_reason="by_user")
        await session.commit()
    await state.bus.publish(job_id, SseEvent(
        event="job_paused", data={"reason": "by_user"},
    ))
    return {"status": "paused_by_user"}


@router.post("/{job_id}/resume")
async def resume_job(request: Request, job_id: str) -> dict[str, str]:
    state = request.app.state.app
    async with state.session_factory() as session:
        job = await repo.get_job(session, job_id)
        if job is None:
            raise HTTPException(404, f"job {job_id} not found")
        if not job.state.startswith("paused_"):
            raise HTTPException(409, f"job {job_id} is not paused (state={job.state})")
        # M1: resume is not yet wired to re-enter the executor. The router would re-create
        # the executor here in M2 once the resumability test trio is implemented.
        await repo.set_job_state(session, job, "queued")
        await session.commit()
    await state.bus.publish(job_id, SseEvent(
        event="job_resumed", data={"resumed_at_stage": "(M2)"},
    ))
    return {"status": "queued"}
