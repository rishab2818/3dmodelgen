"""In-process pub/sub for per-job SSE streams.

The bus is a tiny dict from job_id to a set of asyncio.Queue subscribers. Publishers fan
out one message to every live subscriber for that job. There is no broker; the bus dies
with the process. That's fine for a single-user desktop app — durability lives in SQLite,
not in the bus.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from m3d_backend.events.shapes import SseEvent


class EventBus:
    """Per-job fan-out queue.

    Thread-safe via asyncio (single-threaded event loop assumed). Subscribers receive
    events via async iteration; backpressure is bounded by ``maxsize`` on each queue.
    """

    def __init__(self, maxsize: int = 256) -> None:
        self._subs: dict[str, set[asyncio.Queue[SseEvent]]] = {}
        self._maxsize = maxsize

    async def publish(self, job_id: str, event: SseEvent) -> None:
        """Deliver an event to every live subscriber for this job.

        A slow subscriber blocks only itself — we use ``put_nowait`` and drop on a full
        queue. (Dropping is acceptable: SSE clients reconnect with a `snapshot` event,
        which is authoritative.)
        """
        subs = self._subs.get(job_id, set())
        for q in list(subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop. Subscriber will re-sync on reconnect via the snapshot event.
                pass

    @asynccontextmanager
    async def subscribe(self, job_id: str) -> AsyncIterator[asyncio.Queue[SseEvent]]:
        """Context-managed subscription. Removes the queue on exit."""
        q: asyncio.Queue[SseEvent] = asyncio.Queue(maxsize=self._maxsize)
        self._subs.setdefault(job_id, set()).add(q)
        try:
            yield q
        finally:
            self._subs.get(job_id, set()).discard(q)
            if not self._subs.get(job_id):
                self._subs.pop(job_id, None)
