"""TripoSRAdapter — single-image → untextured mesh in ~5–15 s on a T4.

This module imports torch + tsr lazily on construction so a dev machine without those
packages can still import ``m3d_ai``. Only the Colab/local-GPU host runs this.

Loading procedure:
  1. ``warm_up()`` downloads weights from the pinned revision into ``HF_HOME``.
  2. ``generate()`` resizes the input to 512x512 (alpha respected), runs the model,
     marches mesh, returns OBJ bytes + meta.

References:
  - https://github.com/VAST-AI-Research/TripoSR
  - https://huggingface.co/stabilityai/TripoSR
"""

from __future__ import annotations

import io
import time
from typing import Any, ClassVar

from PIL import Image

from m3d_ai.adapters.base import GenerationResult
from m3d_ai.registry import get as get_model_entry

_ENTRY = get_model_entry("triposr")


class TripoSRAdapter:
    name: ClassVar[str] = _ENTRY.name
    revision: ClassVar[str] = _ENTRY.revision
    min_vram_mb: ClassVar[int] = _ENTRY.min_vram_mb

    def __init__(self, device: str = "cuda", weights_path: str | None = None) -> None:
        self._device = device
        self._weights_path = weights_path
        self._model: Any = None  # set in warm_up()

    def warm_up(self) -> None:
        if self._model is not None:
            return
        # Lazy imports — torch/tsr are only needed on the GPU host.
        import torch  # type: ignore[import-not-found]
        from tsr.system import TSR  # type: ignore[import-not-found]

        if self._device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("TripoSRAdapter requested cuda but torch.cuda.is_available() is False")

        # Pinned revision — never "main".
        model = TSR.from_pretrained(
            self._weights_path or _ENTRY.repo,
            revision=_ENTRY.revision,
            config_name="config.yaml",
            weight_name="model.ckpt",
        )
        model.renderer.set_chunk_size(8192)
        model.to(self._device)
        self._model = model

    def unload(self) -> None:
        import torch  # type: ignore[import-not-found]
        self._model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def generate(
        self,
        images: list[Image.Image],
        seed: int,
        params: dict[str, Any],
    ) -> GenerationResult:
        if self._model is None:
            self.warm_up()
        assert self._model is not None  # noqa: S101  # mypy/pyright narrow

        import torch  # type: ignore[import-not-found]

        if not images:
            raise ValueError("TripoSRAdapter.generate: no input images")

        # TripoSR is a single-image model. If multiple images supplied, pick the first.
        img = images[0].convert("RGBA")

        # Resize to 512 on the longest side, preserving aspect; pad to 512x512 with
        # transparent background so silhouette geometry is consistent.
        target = 512
        ratio = target / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (target, target), (0, 0, 0, 0))
        canvas.paste(
            img,
            ((target - new_size[0]) // 2, (target - new_size[1]) // 2),
            img,
        )

        t0 = time.monotonic()
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
            torch.cuda.reset_peak_memory_stats()

        with torch.no_grad():
            scene_codes = self._model([canvas], device=self._device)
            meshes = self._model.extract_mesh(
                scene_codes,
                has_vertex_color=True,
                resolution=params.get("mc_resolution", 256),
            )
        mesh = meshes[0]
        runtime_ms = int((time.monotonic() - t0) * 1000)

        # Serialize to OBJ bytes via trimesh.
        obj_text = mesh.export(file_type="obj")
        obj_bytes = obj_text.encode("utf-8") if isinstance(obj_text, str) else bytes(obj_text)

        vram_peak_mb: int | None = None
        if torch.cuda.is_available():
            vram_peak_mb = int(torch.cuda.max_memory_allocated() / (1024 * 1024))

        meta = {
            "model": self.name,
            "revision": self.revision,
            "seed": seed,
            "runtime_ms": runtime_ms,
            "vram_peak_mb": vram_peak_mb,
            "provider": "triposr",
            "tri_count": int(len(mesh.faces)),
            "params": params,
        }
        return GenerationResult(mesh_obj=obj_bytes, albedo_png=None, meta=meta)
