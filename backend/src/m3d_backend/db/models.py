"""SQLAlchemy 2.x ORM models for state.db.

Schema lifted verbatim from docs/RESUMABILITY_AND_BUDGET.md §8. The point of these tables
is that every change to job state is persisted before being announced — there is no
in-memory state that isn't also on disk.

NOTE: For M1 we create tables via ``Base.metadata.create_all`` on first launch. Alembic
migrations come in M2 (when the first schema change lands).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "job"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str | None] = mapped_column(String(256))
    state: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
    paused_reason: Mapped[str | None] = mapped_column(String(64))

    # The original CreateJobRequest as canonical JSON. Used by resume to know what to do.
    inputs_json: Mapped[str] = mapped_column(Text)

    # Best iteration so far (export uses this, NOT current_iteration).
    best_iter_n: Mapped[int | None] = mapped_column()
    current_iter_n: Mapped[int] = mapped_column(default=0)

    # Per-job GPU-time cap in seconds. NULL = unlimited.
    budget_cap_s: Mapped[int | None] = mapped_column()

    iterations: Mapped[list[Iteration]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="Iteration.n",
    )
    stage_runs: Mapped[list[StageRun]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )
    gpu_calls: Mapped[list[GpuCall]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )


class Iteration(Base):
    __tablename__ = "iteration"

    job_id: Mapped[str] = mapped_column(
        ForeignKey("job.id", ondelete="CASCADE"), primary_key=True,
    )
    n: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column()
    score_json: Mapped[str | None] = mapped_column(Text)  # EvaluationReport
    refinement_action: Mapped[str | None] = mapped_column(String(64))

    job: Mapped[Job] = relationship(back_populates="iterations")


class StageRun(Base):
    __tablename__ = "stage_run"

    job_id: Mapped[str] = mapped_column(
        ForeignKey("job.id", ondelete="CASCADE"), primary_key=True,
    )
    iteration: Mapped[int] = mapped_column(primary_key=True)
    stage: Mapped[str] = mapped_column(String(64), primary_key=True)

    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    artifacts_json: Mapped[str | None] = mapped_column(Text)
    error_json: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(192))

    job: Mapped[Job] = relationship(back_populates="stage_runs")


class GpuCall(Base):
    """One row per remote-GPU call. Source of truth for budget tracking.

    See docs/RESUMABILITY_AND_BUDGET.md §4.
    """

    __tablename__ = "gpu_call"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("job.id", ondelete="CASCADE"), index=True,
    )
    iteration: Mapped[int] = mapped_column()
    stage: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64))
    revision: Mapped[str] = mapped_column(String(64))
    runtime_ms: Mapped[int] = mapped_column()
    vram_peak_mb: Mapped[int | None] = mapped_column()
    provider: Mapped[str] = mapped_column(String(32))
    est_credits: Mapped[float | None] = mapped_column()
    est_currency: Mapped[str | None] = mapped_column(String(16))
    cached: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)

    job: Mapped[Job] = relationship(back_populates="gpu_calls")
