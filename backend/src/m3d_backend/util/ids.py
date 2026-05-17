"""Identifier generation."""

from __future__ import annotations

import uuid


def new_job_id() -> str:
    """Return a fresh UUIDv4 job id as a string."""
    return str(uuid.uuid4())


def idempotency_key(job_id: str, iteration: int, stage: str, call_index: int = 0) -> str:
    """Return the deterministic idempotency key for a remote-GPU call.

    See docs/BACKEND_CONTRACT.md §2.6. Determinism is critical: a crashed-then-restarted
    backend must produce the same key so the remote can deduplicate.
    """
    return f"{job_id}:{iteration}:{stage}:{call_index}"
