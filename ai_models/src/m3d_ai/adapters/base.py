"""Adapter protocols.

Every generator implements ``GeneratorAdapter``; every evaluator implements
``EvaluatorAdapter``. Adapters are pure Python; no HTTP, no business logic. The
HTTP wrapping lives in ``remote_server.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from PIL import Image


@dataclass(frozen=True)
class GenerationResult:
    mesh_obj: bytes
    albedo_png: bytes | None
    meta: dict[str, Any]


class GeneratorAdapter(Protocol):
    name: ClassVar[str]
    revision: ClassVar[str]
    min_vram_mb: ClassVar[int]

    def warm_up(self) -> None: ...
    def unload(self) -> None: ...

    def generate(
        self,
        images: list[Image.Image],
        seed: int,
        params: dict[str, Any],
    ) -> GenerationResult: ...


class EvaluatorAdapter(Protocol):
    """Composite evaluator (CLIP + DINOv2 + LPIPS + silhouette). Lands in M3."""

    name: ClassVar[str]

    def warm_up(self) -> None: ...

    def evaluate(
        self,
        original: Image.Image,
        renders: dict[str, Image.Image],
        weights: dict[str, float] | None,
    ) -> dict[str, Any]: ...
