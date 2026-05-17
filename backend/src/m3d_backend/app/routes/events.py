"""SSE event stream per job. See docs/BACKEND_CONTRACT.md §1.4."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from m3d_backend.db import repo
from m3d_backend.events.shapes import SseEvent

router = APIRouter(tags=["events"])

HEARTBEAT_S = 15.0


@router.get("/jobs/{job_id}/events")
async def stream_events(request: Request, job_id: str) -> EventSourceResponse:
    state = request.app.state.app

    async with state.session_factory() as session:
        job = await repo.get_job(session, job_id)
        if job is None:
            raise HTTPException(404, f"job {job_id} not found")
        budget = await repo.job_budget_summary(session, job_id)
        snapshot = {
            "job": {
                "id": job.id,
                "state": job.state,
                "current_iteration": job.current_iter_n,
                "best_iteration": job.best_iter_n,
                "budget": budget,
            },
        }

    async def _gen() -> AsyncIterator[dict[str, str]]:
        # First event is always 'snapshot' — authoritative state for clients reconnecting.
        yield {"event": "snapshot", "data": json.dumps(snapshot, default=str)}

        async with state.bus.subscribe(job_id) as queue:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event: SseEvent = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
                    continue
                yield {"event": event.event, "data": json.dumps(event.data, default=str)}

    return EventSourceResponse(_gen())
