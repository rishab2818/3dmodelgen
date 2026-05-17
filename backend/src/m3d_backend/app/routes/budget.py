"""Budget endpoints. See docs/RESUMABILITY_AND_BUDGET.md §4 + BACKEND_CONTRACT.md §1.6."""

from __future__ import annotations

import shutil
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from m3d_backend.db import repo
from m3d_backend.db.models import GpuCall

router = APIRouter(tags=["budget"])


@router.get("/jobs/{job_id}/budget")
async def job_budget(request: Request, job_id: str) -> dict[str, Any]:
    state = request.app.state.app
    async with state.session_factory() as session:
        if await repo.get_job(session, job_id) is None:
            raise HTTPException(404, f"job {job_id} not found")
        return await repo.job_budget_summary(session, job_id)


@router.get("/budget")
async def total_budget(request: Request) -> dict[str, Any]:
    state = request.app.state.app
    async with state.session_factory() as session:
        result = await session.execute(select(GpuCall))
        calls = list(result.scalars().all())
        total = sum(c.runtime_ms for c in calls)
        by_provider: dict[str, int] = {}
        for c in calls:
            by_provider[c.provider] = by_provider.get(c.provider, 0) + c.runtime_ms
        return {
            "window": "lifetime",
            "total_runtime_ms": total,
            "call_count": len(calls),
            "cached_call_count": sum(1 for c in calls if c.cached),
            "by_provider": by_provider,
        }


@router.post("/cache/clear")
async def clear_cache(request: Request) -> dict[str, Any]:
    state = request.app.state.app
    cache_dir = state.settings.models_cache / "generation_cache"
    freed = 0
    if cache_dir.exists():
        for p in cache_dir.rglob("*"):
            if p.is_file():
                freed += p.stat().st_size
        shutil.rmtree(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
    return {"bytes_freed": freed}
