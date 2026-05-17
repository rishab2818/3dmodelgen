"""Typed repository layer.

All SQL access goes through here. Routes never write raw queries.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from m3d_backend.db.models import GpuCall, Iteration, Job, StageRun


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


async def create_job(
    session: AsyncSession,
    *,
    job_id: str,
    label: str | None,
    inputs: dict[str, Any],
    budget_cap_s: int | None,
) -> Job:
    job = Job(
        id=job_id,
        label=label,
        state="queued",
        inputs_json=json.dumps(inputs, default=str, sort_keys=True),
        budget_cap_s=budget_cap_s,
    )
    session.add(job)
    await session.flush()
    return job


async def get_job(session: AsyncSession, job_id: str) -> Job | None:
    return await session.get(Job, job_id)


async def list_jobs(session: AsyncSession, limit: int = 50, offset: int = 0) -> list[Job]:
    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit).offset(offset)
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def set_job_state(
    session: AsyncSession,
    job: Job,
    state: str,
    *,
    paused_reason: str | None = None,
) -> None:
    job.state = state
    job.paused_reason = paused_reason
    job.updated_at = _utcnow()


async def set_best_iter(session: AsyncSession, job: Job, n: int) -> None:
    job.best_iter_n = n
    job.updated_at = _utcnow()


# ---------------------------------------------------------------------------
# Iterations
# ---------------------------------------------------------------------------


async def upsert_iteration(
    session: AsyncSession,
    *,
    job_id: str,
    n: int,
) -> Iteration:
    existing = await session.get(Iteration, (job_id, n))
    if existing is not None:
        return existing
    it = Iteration(job_id=job_id, n=n)
    session.add(it)
    await session.flush()
    return it


async def finish_iteration(
    session: AsyncSession,
    *,
    job_id: str,
    n: int,
    score: dict[str, Any] | None,
    refinement_action: str | None,
) -> None:
    it = await session.get(Iteration, (job_id, n))
    if it is None:
        raise LookupError(f"Iteration {job_id}/{n} not found")
    it.finished_at = _utcnow()
    it.score_json = json.dumps(score, default=str, sort_keys=True) if score else None
    it.refinement_action = refinement_action


# ---------------------------------------------------------------------------
# Stage runs
# ---------------------------------------------------------------------------


async def upsert_stage_run(
    session: AsyncSession,
    *,
    job_id: str,
    iteration: int,
    stage: str,
    status: str,
    idempotency_key: str | None,
) -> StageRun:
    sr = await session.get(StageRun, (job_id, iteration, stage))
    if sr is None:
        sr = StageRun(
            job_id=job_id,
            iteration=iteration,
            stage=stage,
            status=status,
            idempotency_key=idempotency_key,
            started_at=_utcnow(),
        )
        session.add(sr)
    else:
        sr.status = status
        if idempotency_key is not None:
            sr.idempotency_key = idempotency_key
        if sr.started_at is None:
            sr.started_at = _utcnow()
    await session.flush()
    return sr


async def complete_stage_run(
    session: AsyncSession,
    *,
    job_id: str,
    iteration: int,
    stage: str,
    artifacts: list[str],
    cached: bool = False,
) -> None:
    sr = await session.get(StageRun, (job_id, iteration, stage))
    if sr is None:
        raise LookupError(f"StageRun {job_id}/{iteration}/{stage} not found")
    sr.status = "cache_hit" if cached else "complete"
    sr.finished_at = _utcnow()
    sr.artifacts_json = json.dumps(artifacts)


async def fail_stage_run(
    session: AsyncSession,
    *,
    job_id: str,
    iteration: int,
    stage: str,
    error: dict[str, Any],
) -> None:
    sr = await session.get(StageRun, (job_id, iteration, stage))
    if sr is None:
        raise LookupError(f"StageRun {job_id}/{iteration}/{stage} not found")
    sr.status = "failed"
    sr.finished_at = _utcnow()
    sr.error_json = json.dumps(error, default=str)


async def get_stage_run(
    session: AsyncSession,
    *,
    job_id: str,
    iteration: int,
    stage: str,
) -> StageRun | None:
    return await session.get(StageRun, (job_id, iteration, stage))


# ---------------------------------------------------------------------------
# GPU calls (budget ledger)
# ---------------------------------------------------------------------------


async def record_gpu_call(
    session: AsyncSession,
    *,
    job_id: str,
    iteration: int,
    stage: str,
    model: str,
    revision: str,
    runtime_ms: int,
    provider: str,
    vram_peak_mb: int | None = None,
    cached: bool = False,
) -> GpuCall:
    call = GpuCall(
        job_id=job_id,
        iteration=iteration,
        stage=stage,
        model=model,
        revision=revision,
        runtime_ms=runtime_ms,
        vram_peak_mb=vram_peak_mb,
        provider=provider,
        cached=cached,
    )
    session.add(call)
    await session.flush()
    return call


async def job_budget_summary(session: AsyncSession, job_id: str) -> dict[str, Any]:
    stmt = select(GpuCall).where(GpuCall.job_id == job_id)
    res = await session.execute(stmt)
    calls = list(res.scalars().all())
    total = sum(c.runtime_ms for c in calls)
    cached = sum(1 for c in calls if c.cached)
    by_provider: dict[str, int] = {}
    for c in calls:
        by_provider[c.provider] = by_provider.get(c.provider, 0) + c.runtime_ms
    job = await session.get(Job, job_id)
    cap = job.budget_cap_s if job else None
    cap_remaining = None
    if cap is not None:
        cap_remaining = max(0, cap - total // 1000)
    return {
        "total_runtime_ms": total,
        "call_count": len(calls),
        "cached_call_count": cached,
        "cache_hit_rate": (cached / len(calls)) if calls else 0.0,
        "by_provider": by_provider,
        "cap_seconds": cap,
        "cap_remaining_seconds": cap_remaining,
    }
