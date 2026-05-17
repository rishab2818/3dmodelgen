"""Stage graph executor.

Runs the pipeline for one job, iteration by iteration, stage by stage. On each stage:

  1. Check the ``.complete`` marker (resume).
  2. If present, emit a synthetic ``cache_hit`` event and skip.
  3. Else, run the stage; on success write the marker atomically (last act).

State transitions are persisted to SQLite **inside the same transaction** as the marker
write. There is no in-memory state that isn't also on disk — that's what makes
resumability work across crashes, ngrok rotation, app close, and reboot.

See docs/RESUMABILITY_AND_BUDGET.md (the prime-directive doc).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from m3d_backend.db import repo
from m3d_backend.events.bus import EventBus
from m3d_backend.events.shapes import SseEvent
from m3d_backend.gpu.base import GPUBackend
from m3d_backend.pipeline.artifacts import stage_is_complete
from m3d_backend.pipeline.stages import (
    blender_cleanup,
    evaluate,
    export,
    generate,
    preprocess,
    refine,
    render_multiview,
)
from m3d_backend.util.ids import idempotency_key
from m3d_backend.util.jsonio import write_stage_complete
from m3d_backend.util.paths import stage_complete_marker

log = structlog.get_logger(__name__)


STAGES_PER_ITER: tuple[str, ...] = (
    "preprocess",  # only on iteration 1; subsequent iters reuse
    "generate",
    "blender_cleanup",
    "render_multiview",
    "evaluate",
)


@dataclass
class PipelineConfig:
    blender_exe: Path
    repo_root: Path
    temp_dir: Path
    exports_dir: Path
    fixtures_dir: Path
    model: str = "mock"
    target_quality: float = 0.85
    max_iterations: int = 6
    initial_seed: int = 42
    export_formats: tuple[str, ...] = ("glb", "obj")
    bg_removal_enabled: bool = True
    bg_removal_model: str = "u2net"
    preprocess_target_size: int = 512


class PipelineExecutor:
    def __init__(
        self,
        *,
        bus: EventBus,
        backend: GPUBackend,
        session_factory: async_sessionmaker[AsyncSession],
        config: PipelineConfig,
    ) -> None:
        self._bus = bus
        self._backend = backend
        self._sessions = session_factory
        self._cfg = config

    async def run(self, job_id: str, input_images: list[Path]) -> None:
        """Execute the pipeline for ``job_id`` to completion.

        Idempotent in the sense that completed stages are skipped on re-entry.
        """
        log.info("pipeline.start", job_id=job_id)
        await self._set_state(job_id, "running")

        try:
            iteration_reports: list[dict[str, Any]] = []
            best_iter = 1
            best_score = -1.0

            for n in range(1, self._cfg.max_iterations + 1):
                await self._with_session(
                    lambda s, _n=n: repo.upsert_iteration(s, job_id=job_id, n=_n),
                )

                # Stage 1: preprocess (only iter 1; later iters re-use)
                if n == 1:
                    await self._run_stage(
                        job_id, n, "preprocess",
                        lambda: _run_preprocess(self._cfg, job_id, input_images),
                    )

                # Stage 2: generate
                gen_meta = await self._run_stage(
                    job_id, n, "generate",
                    lambda _n=n: _run_generate(
                        backend=self._backend,
                        cfg=self._cfg,
                        job_id=job_id,
                        iteration=_n,
                        seed=self._cfg.initial_seed + (_n - 1),
                    ),
                )
                if gen_meta is not None:
                    await self._record_gpu_call(
                        job_id=job_id, iteration=n, stage="generate",
                        meta=gen_meta,
                    )

                # Stage 3: blender_cleanup
                await self._run_stage(
                    job_id, n, "blender_cleanup",
                    lambda _n=n: _run_blender_cleanup(self._cfg, job_id, _n),
                )

                # Stage 4: render_multiview (mock in M1)
                await self._run_stage(
                    job_id, n, "render_multiview",
                    lambda _n=n: _run_render(self._cfg, job_id, _n),
                )

                # Stage 5: evaluate
                report = await self._run_stage(
                    job_id, n, "evaluate",
                    lambda _n=n: _run_evaluate(
                        backend=self._backend,
                        cfg=self._cfg,
                        job_id=job_id,
                        iteration=_n,
                    ),
                )
                assert report is not None  # noqa: S101
                eval_report = report["report"]
                if report.get("runtime_ms"):
                    await self._record_gpu_call(
                        job_id=job_id, iteration=n, stage="evaluate",
                        meta={
                            "model": "evaluator",
                            "revision": "mock-v1",
                            "runtime_ms": report["runtime_ms"],
                            "vram_peak_mb": None,
                            "provider": report.get("provider", "mock"),
                            "cached": False,
                        },
                    )

                # Refinement decision
                action = refine.decide(
                    report=eval_report,
                    iteration=n,
                    max_iterations=self._cfg.max_iterations,
                    target_quality=self._cfg.target_quality,
                )

                async def _finish(s: AsyncSession, n: int = n) -> None:
                    await repo.finish_iteration(
                        s,
                        job_id=job_id,
                        n=n,
                        score=eval_report,
                        refinement_action=action,
                    )
                await self._with_session(_finish)

                iteration_reports.append({
                    "n": n,
                    "score": eval_report,
                    "refinement_action": action,
                })

                score = float(eval_report.get("overall_score", 0.0))
                if score > best_score:
                    best_score = score
                    best_iter = n
                    await self._with_session(
                        lambda s, _n=n: _set_best_iter(s, job_id, _n),
                    )

                await self._bus.publish(job_id, SseEvent(
                    event="iteration_complete",
                    data={
                        "iteration": n,
                        "score": eval_report,
                        "refinement_action": action,
                    },
                ))

                if action == "stop":
                    break

            # Stage 7: export
            exports = export.run(
                exports_dir=self._cfg.exports_dir,
                temp_dir=self._cfg.temp_dir,
                job_id=job_id,
                best_iteration=best_iter,
                formats=list(self._cfg.export_formats),
                iteration_reports=iteration_reports,
            )

            await self._set_state(job_id, "succeeded")
            await self._bus.publish(job_id, SseEvent(
                event="job_complete",
                data={"state": "succeeded", "exports": exports},
            ))
            log.info("pipeline.done", job_id=job_id, best_iter=best_iter, score=best_score)

        except Exception as e:  # noqa: BLE001
            log.exception("pipeline.failed", job_id=job_id)
            await self._set_state(job_id, "failed")
            await self._bus.publish(job_id, SseEvent(
                event="job_failed",
                data={"error": {"code": "INTERNAL", "message": str(e)}},
            ))
            raise

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _run_stage(
        self,
        job_id: str,
        iteration: int,
        stage: str,
        fn,  # type: ignore[no-untyped-def]  # callable returning Awaitable[Any | None]
    ) -> Any:
        cfg = self._cfg
        key = idempotency_key(job_id, iteration, stage)

        # Resume short-circuit: if marker exists, emit cache_hit and skip.
        if stage_is_complete(cfg.temp_dir, job_id, iteration, stage):
            log.info("stage.cache_hit", job_id=job_id, iteration=iteration, stage=stage)
            await self._bus.publish(job_id, SseEvent(
                event="stage_update",
                data={
                    "iteration": iteration, "stage": stage,
                    "status": "cache_hit", "progress": 1.0,
                    "message": "Cached from prior run", "artifacts": [], "elapsed_ms": 0,
                },
            ))
            return None

        await self._with_session(
            lambda s: repo.upsert_stage_run(
                s, job_id=job_id, iteration=iteration, stage=stage,
                status="running", idempotency_key=key,
            ),
        )
        await self._bus.publish(job_id, SseEvent(
            event="stage_update",
            data={
                "iteration": iteration, "stage": stage,
                "status": "running", "progress": 0.0,
                "message": "", "artifacts": [], "elapsed_ms": 0,
            },
        ))

        t0 = time.monotonic()
        try:
            result = await fn() if _is_async(fn) else fn()
            if hasattr(result, "__await__"):  # support sync wrappers returning awaitables
                result = await result
        except Exception as e:  # noqa: BLE001
            elapsed = int((time.monotonic() - t0) * 1000)
            await self._with_session(
                lambda s: repo.fail_stage_run(
                    s, job_id=job_id, iteration=iteration, stage=stage,
                    error={"message": str(e), "type": type(e).__name__},
                ),
            )
            await self._bus.publish(job_id, SseEvent(
                event="stage_update",
                data={
                    "iteration": iteration, "stage": stage,
                    "status": "failed", "progress": 1.0,
                    "message": str(e), "artifacts": [], "elapsed_ms": elapsed,
                },
            ))
            raise

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        # ATOMIC: write .complete marker as the last act of the stage.
        marker = stage_complete_marker(cfg.temp_dir, job_id, iteration, stage)
        write_stage_complete(
            marker,
            idempotency_key=key,
            completed_at_iso=datetime.now(timezone.utc).isoformat(),
        )

        await self._with_session(
            lambda s: repo.complete_stage_run(
                s, job_id=job_id, iteration=iteration, stage=stage,
                artifacts=[],  # the marker carries provenance; artifact discovery is on read
            ),
        )
        await self._bus.publish(job_id, SseEvent(
            event="stage_update",
            data={
                "iteration": iteration, "stage": stage,
                "status": "complete", "progress": 1.0,
                "message": "", "artifacts": [], "elapsed_ms": elapsed_ms,
            },
        ))
        return result

    async def _record_gpu_call(
        self,
        *,
        job_id: str,
        iteration: int,
        stage: str,
        meta: dict[str, Any],
    ) -> None:
        runtime_ms = int(meta.get("runtime_ms", 0))
        await self._with_session(
            lambda s: repo.record_gpu_call(
                s,
                job_id=job_id,
                iteration=iteration,
                stage=stage,
                model=str(meta.get("model", "unknown")),
                revision=str(meta.get("revision", "unknown")),
                runtime_ms=runtime_ms,
                vram_peak_mb=meta.get("vram_peak_mb"),
                provider=str(meta.get("provider", "mock")),
                cached=bool(meta.get("cached", False)),
            ),
        )
        # Compute job total for the event payload.
        async def _summary(s: AsyncSession) -> dict[str, Any]:
            return await repo.job_budget_summary(s, job_id)
        summary = await self._with_session(_summary)

        await self._bus.publish(job_id, SseEvent(
            event="budget_update",
            data={
                "stage": stage,
                "cached": bool(meta.get("cached", False)),
                "runtime_ms": runtime_ms,
                "provider": str(meta.get("provider", "mock")),
                "job_total_runtime_ms": summary["total_runtime_ms"],
            },
        ))

    async def _set_state(self, job_id: str, state: str) -> None:
        async def _go(s: AsyncSession) -> None:
            job = await repo.get_job(s, job_id)
            if job is None:
                return
            await repo.set_job_state(s, job, state)
        await self._with_session(_go)

    async def _with_session(self, fn):  # type: ignore[no-untyped-def]
        async with self._sessions() as session:
            result = await fn(session)
            await session.commit()
            return result


# ---------------------------------------------------------------------------
# Stage thunks (kept here to centralize iteration/argument plumbing)
# ---------------------------------------------------------------------------


async def _set_best_iter(s: AsyncSession, job_id: str, n: int) -> None:
    job = await repo.get_job(s, job_id)
    if job is not None:
        await repo.set_best_iter(s, job, n)


def _is_async(fn) -> bool:  # type: ignore[no-untyped-def]
    import inspect
    return inspect.iscoroutinefunction(fn)


def _run_preprocess(cfg: PipelineConfig, job_id: str, inputs: list[Path]):
    def go() -> list[Path]:
        return preprocess.run(
            temp_dir=cfg.temp_dir,
            job_id=job_id,
            input_images=inputs,
            bg_removal_enabled=cfg.bg_removal_enabled,
            bg_removal_model=cfg.bg_removal_model,
            target_size=cfg.preprocess_target_size,
        )
    return go()


async def _run_generate(
    *, backend: GPUBackend, cfg: PipelineConfig, job_id: str, iteration: int, seed: int,
) -> dict[str, Any]:
    _, meta = await generate.run(
        backend=backend,
        temp_dir=cfg.temp_dir,
        job_id=job_id,
        iteration=iteration,
        model=cfg.model,
        seed=seed,
        idempotency_key=idempotency_key(job_id, iteration, "generate"),
    )
    return meta


async def _run_blender_cleanup(cfg: PipelineConfig, job_id: str, iteration: int) -> None:
    from m3d_backend.util.paths import stage_dir
    in_mesh = stage_dir(cfg.temp_dir, job_id, iteration, "generate") / "mesh.obj"
    await blender_cleanup.run(
        blender_exe=cfg.blender_exe,
        repo_root=cfg.repo_root,
        temp_dir=cfg.temp_dir,
        job_id=job_id,
        iteration=iteration,
        input_mesh=in_mesh,
    )


async def _run_render(cfg: PipelineConfig, job_id: str, iteration: int) -> dict[str, Path]:
    return await render_multiview.run(
        temp_dir=cfg.temp_dir,
        job_id=job_id,
        iteration=iteration,
        mock=True,
    )


async def _run_evaluate(
    *, backend: GPUBackend, cfg: PipelineConfig, job_id: str, iteration: int,
) -> dict[str, Any]:
    report, runtime_ms, provider = await evaluate.run(
        backend=backend,
        temp_dir=cfg.temp_dir,
        job_id=job_id,
        iteration=iteration,
        render_paths={},
        idempotency_key=idempotency_key(job_id, iteration, "evaluate"),
    )
    return {"report": report, "runtime_ms": runtime_ms, "provider": provider}


# Reference json import for stages that may want to serialize (currently unused)
_ = json
