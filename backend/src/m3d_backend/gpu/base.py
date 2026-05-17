"""GPU backend abstraction (mock / remote / local).

See docs/DECISIONS/ADR-0002-gpu-backend-abstraction.md. The three implementations of this
Protocol let us develop on any machine and ship to any user.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class GenerateRequest:
    job_id: str
    iteration: int
    stage: str
    model: str
    image_paths: list[Path]
    seed: int
    params: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""


@dataclass(frozen=True)
class GenerateResponse:
    mesh_obj_bytes: bytes
    albedo_png_bytes: bytes | None
    meta: GenerationMeta


@dataclass(frozen=True)
class GenerationMeta:
    model: str
    revision: str
    seed: int
    runtime_ms: int
    vram_peak_mb: int | None
    provider: str  # "mock" | "colab" | "modal" | "runpod" | "local"
    tri_count: int
    cached: bool = False


@dataclass(frozen=True)
class EvaluateRequest:
    job_id: str
    iteration: int
    stage: str
    original_path: Path
    mask_path: Path | None
    render_paths: dict[str, Path]
    weights: dict[str, float] | None = None
    idempotency_key: str = ""


@dataclass(frozen=True)
class EvaluateResponse:
    report: dict[str, Any]  # serialized EvaluationReport (see QUALITY_RUBRIC.md §3)
    runtime_ms: int
    provider: str


class GPUBackend(Protocol):
    """The single boundary between orchestrator and AI compute.

    Mock returns canned fixtures; Remote does HTTP; Local imports ai_models in-process.
    """

    name: str

    async def health(self) -> dict[str, Any]: ...

    async def generate(self, req: GenerateRequest) -> GenerateResponse: ...

    async def evaluate(self, req: EvaluateRequest) -> EvaluateResponse: ...
