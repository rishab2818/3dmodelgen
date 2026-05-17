"""MockAdapter — returns the canned cube fixture. Lets the server stand up without torch.

Used by:
  - Dev laptop running the remote_server for plumbing tests.
  - CI integration tests against the orchestrator.
"""

from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Any, ClassVar

from PIL import Image

from m3d_ai.adapters.base import GenerationResult


_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"


class MockAdapter:
    name: ClassVar[str] = "mock"
    revision: ClassVar[str] = "mock-fixture-v1"
    min_vram_mb: ClassVar[int] = 0

    def __init__(self, delay_ms: int = 300) -> None:
        self._delay_s = delay_ms / 1000.0
        self._fixture = _FIXTURES / "cube.obj"

    def warm_up(self) -> None:
        # Verify the fixture exists; cheap check.
        if not self._fixture.exists():
            raise FileNotFoundError(f"Mock fixture missing: {self._fixture}")

    def unload(self) -> None:
        pass

    def generate(
        self,
        images: list[Image.Image],
        seed: int,
        params: dict[str, Any],
    ) -> GenerationResult:
        if not images:
            raise ValueError("MockAdapter.generate: no input images")
        t0 = time.monotonic()
        time.sleep(self._delay_s)
        data = self._fixture.read_bytes()
        tri_count = sum(1 for line in data.splitlines() if line.startswith(b"f "))
        runtime_ms = int((time.monotonic() - t0) * 1000)
        meta = {
            "model": self.name,
            "revision": self.revision,
            "seed": seed,
            "runtime_ms": runtime_ms,
            "vram_peak_mb": None,
            "provider": "mock",
            "tri_count": tri_count,
            "params": params,
            "input_size": [images[0].size[0], images[0].size[1]],
        }
        # Encode a 32x32 black PNG as a "albedo" placeholder so downstream code paths
        # that expect albedo_png_bytes don't crash.
        buf = io.BytesIO()
        Image.new("RGBA", (32, 32), (0, 0, 0, 255)).save(buf, format="PNG")
        return GenerationResult(mesh_obj=data, albedo_png=buf.getvalue(), meta=meta)
