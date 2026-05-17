"""Pydantic models for the SSE event wire shapes.

These ARE the contract. See docs/BACKEND_CONTRACT.md §1.4.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Job-state vocabulary (mirrored on the TS side as a zod literal union)
# ---------------------------------------------------------------------------

JobState = Literal[
    "queued",
    "running",
    "paused_by_user",
    "paused_remote_offline",
    "paused_crashed",
    "paused_budget",
    "succeeded",
    "failed",
    "cancelled",
]

StageStatus = Literal[
    "pending",
    "running",
    "complete",
    "failed",
    "cache_hit",
]


# ---------------------------------------------------------------------------
# Per-event payloads
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StageUpdate(BaseModel):
    iteration: int
    stage: str
    status: StageStatus
    progress: float = Field(ge=0.0, le=1.0)
    message: str = ""
    artifacts: list[str] = Field(default_factory=list)
    elapsed_ms: int = 0


class IterationComplete(BaseModel):
    iteration: int
    score: dict[str, Any] | None  # EvaluationReport when ready
    refinement_action: str | None


class JobComplete(BaseModel):
    state: Literal["succeeded"] = "succeeded"
    exports: dict[str, str]  # format → relative path


class JobFailed(BaseModel):
    error: dict[str, Any]


class JobPaused(BaseModel):
    reason: Literal["by_user", "remote_offline", "crashed", "budget"]


class JobResumed(BaseModel):
    resumed_at_stage: str


class BudgetUpdate(BaseModel):
    stage: str
    cached: bool
    runtime_ms: int
    provider: str
    job_total_runtime_ms: int


class RemoteStatus(BaseModel):
    at: str = Field(default_factory=_now_iso)


class Heartbeat(BaseModel):
    ts: str = Field(default_factory=_now_iso)


# ---------------------------------------------------------------------------
# Envelope used by the SSE route
# ---------------------------------------------------------------------------


class SseEvent(BaseModel):
    """Wire envelope: one of these is serialized to JSON per SSE message."""

    event: Literal[
        "snapshot",
        "stage_update",
        "iteration_complete",
        "job_complete",
        "job_failed",
        "job_paused",
        "job_resumed",
        "budget_update",
        "remote_offline",
        "remote_online",
        "heartbeat",
    ]
    data: dict[str, Any]
