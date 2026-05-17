"""Idempotency cache for the remote server.

See docs/BACKEND_CONTRACT.md §2.6. Repeats of a request with the same Idempotency-Key
return the cached response — they do NOT re-run the model. This is what makes "never pay
twice" hold across timeouts and retries.

Concurrent-request semantics: an in-flight request blocks subsequent requests with the
same key until the first one finishes, then returns that result. This handles the
classic "client retries before original response arrived" race.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


@dataclass
class _CacheEntry:
    expires_at: float
    response: Any | None = None
    error: BaseException | None = None
    done: asyncio.Event | None = None  # set when in-flight request completes


class IdempotencyCache:
    """LRU + TTL cache keyed on Idempotency-Key string."""

    def __init__(self, *, capacity: int = 1024, ttl_s: int = 24 * 3600) -> None:
        self._capacity = capacity
        self._ttl_s = ttl_s
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()

    async def execute(self, key: str, fn):  # type: ignore[no-untyped-def]
        """Run ``fn()`` for this key — but only once per key within the TTL.

        Semantics:
          - Cache hit (fresh + done): return cached response (or re-raise cached error).
          - Cache hit (in flight): wait for the original caller's result.
          - Cache miss / expired: register as in-flight, run fn(), store + signal waiters.
        """
        async with self._lock:
            entry = self._entries.get(key)
            now = time.time()
            if entry is None or entry.expires_at <= now:
                # Miss / expired — register in-flight entry.
                entry = _CacheEntry(
                    expires_at=now + self._ttl_s,
                    done=asyncio.Event(),
                )
                self._entries[key] = entry
                self._entries.move_to_end(key)
                if len(self._entries) > self._capacity:
                    self._entries.popitem(last=False)
                in_flight = True
            else:
                self._entries.move_to_end(key)
                in_flight = False

        if not in_flight:
            # Existing entry: either completed (return) or in-flight (wait).
            if entry.done is not None and not entry.done.is_set():
                await entry.done.wait()
            if entry.error is not None:
                raise entry.error
            return entry.response

        # We are the first caller for this key. Run fn() and signal others.
        try:
            entry.response = await fn()
            return entry.response
        except BaseException as e:
            entry.error = e
            raise
        finally:
            if entry.done is not None:
                entry.done.set()

    def size(self) -> int:
        return len(self._entries)
